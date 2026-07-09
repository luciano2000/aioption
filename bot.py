"""Bot spike-fade para conta DEMO da Deriv.

⚠️ USE APENAS EM CONTA VIRTUAL (demo). Crie o token em:
   app.deriv.com > Configurações > Token de API (escopos: read, trade)
   com a conta VIRTUAL selecionada. Token de demo começa a operar com
   $10.000 fictícios.

Config via variáveis de ambiente:
   DERIV_TOKEN   (obrigatório)
   DERIV_APP_ID  (padrão 1089 — registre o seu em api.deriv.com)
   SYMBOL        (padrão R_100)
   Z_THRESHOLD   (padrão 3.5)
   EXPIRY_MIN    (padrão 5)
   STAKE         (padrão 1.0, em USD)
   STOP_LOSS_DAY (padrão 20.0 — para o bot no dia após perder isso)
   STOP_WIN_DAY  (padrão 50.0)

Roda: DERIV_TOKEN=xxx python3 bot.py
Logs em trades.sqlite (tabela trades) + stdout.
"""
import asyncio
import json
import math
import os
import sqlite3
import time
from collections import deque
from datetime import date

import websockets

TOKEN = (os.environ.get("DERIV_TOKEN") or "").strip().strip('"').strip("'")
APP_ID = os.environ.get("DERIV_APP_ID", "1089")
SYMBOL = os.environ.get("SYMBOL", "R_100")
Z_TH = float(os.environ.get("Z_THRESHOLD", "3.5"))
EXPIRY = int(os.environ.get("EXPIRY_MIN", "5"))
STAKE = float(os.environ.get("STAKE", "1.0"))
STOP_LOSS_DAY = float(os.environ.get("STOP_LOSS_DAY", "20.0"))
STOP_WIN_DAY = float(os.environ.get("STOP_WIN_DAY", "50.0"))
WINDOW = 30
URI = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

DB = sqlite3.connect(os.environ.get("DB_PATH", "trades.sqlite"))
DB.execute("""CREATE TABLE IF NOT EXISTS trades(
    ts INTEGER, symbol TEXT, direction TEXT, z REAL, stake REAL,
    contract_id INTEGER, payout REAL, profit REAL, status TEXT)""")
DB.commit()


def log_trade(**kw) -> None:
    DB.execute(
        "INSERT INTO trades VALUES(:ts,:symbol,:direction,:z,:stake,"
        ":contract_id,:payout,:profit,:status)", kw)
    DB.commit()


class SpikeBot:
    def __init__(self) -> None:
        self.rets: deque[float] = deque(maxlen=WINDOW)
        self.last_close: float | None = None
        self.pnl_today = 0.0
        self.day = date.today()
        self.busy = False

    def daily_guard(self) -> bool:
        if date.today() != self.day:
            self.day, self.pnl_today = date.today(), 0.0
        if self.pnl_today <= -STOP_LOSS_DAY:
            print(f"[guard] stop-loss diário atingido ({self.pnl_today:+.2f}). Pausado até amanhã.")
            return False
        if self.pnl_today >= STOP_WIN_DAY:
            print(f"[guard] meta diária atingida ({self.pnl_today:+.2f}). Pausado até amanhã.")
            return False
        return True

    def signal(self, close: float) -> str | None:
        """Alimenta com o close de cada vela de 1min; retorna PUT/CALL/None."""
        if self.last_close is not None:
            self.rets.append((close - self.last_close) / self.last_close)
        self.last_close = close
        if len(self.rets) < WINDOW:
            return None
        w = list(self.rets)[:-1]
        mu = sum(w) / len(w)
        var = sum((r - mu) ** 2 for r in w) / (len(w) - 1)
        sd = math.sqrt(var) if var > 0 else 1e-12
        z = (self.rets[-1] - mu) / sd
        if z >= Z_TH:
            return "PUT"    # parede pra cima -> aposta que volta (cai)
        if z <= -Z_TH:
            return "CALL"   # parede pra baixo -> aposta que sobe
        return None


async def buy(ws, direction: str, z: float) -> None:
    await ws.send(json.dumps({
        "buy": 1, "price": STAKE,
        "parameters": {
            "amount": STAKE, "basis": "stake", "contract_type": direction,
            "currency": "USD", "duration": EXPIRY, "duration_unit": "m",
            "symbol": SYMBOL,
        },
    }))


async def main() -> None:
    if not TOKEN:
        raise SystemExit("Defina DERIV_TOKEN (token de API da conta VIRTUAL).")
    bot = SpikeBot()
    async with websockets.connect(URI) as ws:
        # autentica
        await ws.send(json.dumps({"authorize": TOKEN}))
        auth = json.loads(await ws.recv())
        if "error" in auth:
            raise SystemExit(f"Auth falhou: {auth['error']['message']}")
        acct = auth["authorize"]
        if not acct.get("is_virtual"):
            # token de usuario: procura a conta VIRTUAL (VRTC) e troca pra ela
            virt = next((a for a in acct.get("account_list", [])
                         if a.get("is_virtual")), None)
            if not virt:
                raise SystemExit("⛔ Nenhuma conta VIRTUAL encontrada no seu usuario Deriv.")
            print(f"Token autorizou {acct['loginid']} (real); trocando para {virt['loginid']} (virtual)...")
            await ws.send(json.dumps({"authorize": TOKEN, "loginid": virt["loginid"]}))
            auth = json.loads(await ws.recv())
            if "error" in auth:
                raise SystemExit(f"Falha ao trocar p/ conta virtual: {auth['error']['message']}")
            acct = auth["authorize"]
            if not acct.get("is_virtual"):
                raise SystemExit("⛔ Nao consegui autorizar a conta VIRTUAL. Abortando por seguranca.")
        print(f"Conectado: {acct['loginid']} (virtual) saldo {acct['balance']} {acct['currency']}")

        # assina candles de 1min e atualizações de contratos
        await ws.send(json.dumps({
            "ticks_history": SYMBOL, "style": "candles", "granularity": 60,
            "count": WINDOW + 2, "end": "latest", "subscribe": 1,
        }))
        await ws.send(json.dumps({"proposal_open_contract": 1, "subscribe": 1}))

        last_epoch = 0
        pending_z = 0.0
        async for raw in ws:
            msg = json.loads(raw)
            mt = msg.get("msg_type")

            if mt == "candles":  # carga inicial
                for c in msg["candles"][:-1]:
                    bot.signal(float(c["close"]))
                last_epoch = msg["candles"][-1]["epoch"]

            elif mt == "ohlc":
                o = msg["ohlc"]
                epoch = int(o["open_time"])
                if epoch != last_epoch and last_epoch:
                    # vela anterior fechou -> avalia sinal
                    sig = bot.signal(float(o["open"]))
                    if sig and not bot.busy and bot.daily_guard():
                        bot.busy = True
                        pending_z = 0.0
                        print(f"[{time.strftime('%H:%M:%S')}] sinal {sig} -> comprando {STAKE} USD, exp {EXPIRY}m")
                        await buy(ws, sig, pending_z)
                last_epoch = epoch

            elif mt == "buy":
                if "error" in msg:
                    print(f"[erro compra] {msg['error']['message']}")
                    bot.busy = False
                else:
                    b = msg["buy"]
                    print(f"  contrato {b['contract_id']} comprado por {b['buy_price']}")

            elif mt == "proposal_open_contract":
                c = msg.get("proposal_open_contract", {})
                if c.get("is_sold"):
                    profit = float(c.get("profit", 0))
                    bot.pnl_today += profit
                    bot.busy = False
                    status = "WIN" if profit > 0 else "LOSS"
                    print(f"  {status} {profit:+.2f} | P&L hoje: {bot.pnl_today:+.2f}")
                    log_trade(ts=int(time.time()), symbol=SYMBOL,
                              direction=c.get("contract_type", "?"), z=pending_z,
                              stake=STAKE, contract_id=c.get("contract_id", 0),
                              payout=float(c.get("payout", 0)), profit=profit,
                              status=status)

            elif "error" in msg:
                print(f"[erro] {msg['error']['message']}")


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[reconectando em 5s] {e}")
            time.sleep(5)
