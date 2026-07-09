"""Bot spike-fade para conta DEMO da Deriv — Nova Options API (2026).

Fluxo de autenticacao (developers.deriv.com):
  1. REST GET  /trading/v1/options/accounts        -> acha a conta DEMO (DOT...)
  2. REST POST /trading/v1/options/accounts/{id}/otp -> URL do WebSocket com OTP
  3. Conecta no WebSocket /ws/demo e opera

Config via variaveis de ambiente:
  DERIV_TOKEN   (obrigatorio - Personal Access Token do dashboard developers.deriv.com)
  DERIV_APP_ID  (obrigatorio - App ID do mesmo dashboard)
  SYMBOL        (padrao R_100)
  Z_THRESHOLD   (padrao 3.5)
  EXPIRY_MIN    (padrao 1)
  STAKE         (padrao 1.0 USD)
  STOP_LOSS_DAY (padrao 20.0)   STOP_WIN_DAY (padrao 50.0)

SEGURANCA: o bot so usa a conta account_type == "demo" e aborta se a URL
do WebSocket nao for a do endpoint /ws/demo. Nao opera conta real.
"""
import asyncio
import json
import math
import os
import sqlite3
import time
import urllib.request
from collections import deque
from datetime import date

import websockets

TOKEN = (os.environ.get("DERIV_TOKEN") or "").strip().strip('"').strip("'")
APP_ID = (os.environ.get("DERIV_APP_ID") or "").strip().strip('"').strip("'")
SYMBOL = os.environ.get("SYMBOL", "R_100")
Z_TH = float(os.environ.get("Z_THRESHOLD", "3.5"))
EXPIRY = int(os.environ.get("EXPIRY_MIN", "1"))
STAKE = float(os.environ.get("STAKE", "1.0"))
STOP_LOSS_DAY = float(os.environ.get("STOP_LOSS_DAY", "20.0"))
STOP_WIN_DAY = float(os.environ.get("STOP_WIN_DAY", "50.0"))
WINDOW = 30
REST = "https://api.derivws.com"

DB = sqlite3.connect(os.environ.get("DB_PATH", "trades.sqlite"))
DB.execute("""CREATE TABLE IF NOT EXISTS trades(
    ts INTEGER, symbol TEXT, direction TEXT, z REAL, stake REAL,
    contract_id INTEGER, payout REAL, profit REAL, status TEXT)""")
DB.commit()


def log_trade(**kw):
    DB.execute("INSERT INTO trades VALUES(:ts,:symbol,:direction,:z,:stake,"
               ":contract_id,:payout,:profit,:status)", kw)
    DB.commit()


def rest(method: str, path: str):
    req = urllib.request.Request(
        REST + path, method=method,
        headers={"Deriv-App-ID": APP_ID, "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_demo_account() -> dict:
    resp = rest("GET", "/trading/v1/options/accounts")
    accounts = resp.get("data", [])
    demo = next((a for a in accounts
                 if a.get("account_type") == "demo" and a.get("status") == "active"), None)
    if not demo:
        raise SystemExit(f"Nenhuma conta DEMO ativa encontrada. Contas: "
                         f"{[(a.get('account_id'), a.get('account_type')) for a in accounts]}")
    return demo


def get_ws_url(account_id: str) -> str:
    resp = rest("POST", f"/trading/v1/options/accounts/{account_id}/otp")
    url = resp.get("data", {}).get("url", "")
    if "/ws/demo" not in url:
        raise SystemExit(f"URL do WebSocket nao e do endpoint demo. Abortando. ({url[:60]})")
    return url


class SpikeBot:
    def __init__(self):
        self.rets: deque = deque(maxlen=WINDOW)
        self.last_close = None
        self.pnl_today = 0.0
        self.day = date.today()
        self.busy = False

    def daily_guard(self) -> bool:
        if date.today() != self.day:
            self.day, self.pnl_today = date.today(), 0.0
        if self.pnl_today <= -STOP_LOSS_DAY:
            print(f"[guard] stop-loss diario ({self.pnl_today:+.2f}). Pausado ate amanha.")
            return False
        if self.pnl_today >= STOP_WIN_DAY:
            print(f"[guard] meta diaria ({self.pnl_today:+.2f}). Pausado ate amanha.")
            return False
        return True

    def signal(self, close: float):
        if self.last_close is not None:
            self.rets.append((close - self.last_close) / self.last_close)
        self.last_close = close
        if len(self.rets) < WINDOW:
            return None, 0.0
        w = list(self.rets)[:-1]
        mu = sum(w) / len(w)
        var = sum((r - mu) ** 2 for r in w) / (len(w) - 1)
        sd = math.sqrt(var) if var > 0 else 1e-12
        z = (self.rets[-1] - mu) / sd
        if z >= Z_TH:
            return "PUT", z    # parede pra cima -> aposta que cai
        if z <= -Z_TH:
            return "CALL", z   # parede pra baixo -> aposta que sobe
        return None, z


async def buy(ws, direction: str, currency: str):
    await ws.send(json.dumps({
        "buy": "1", "price": STAKE,
        "parameters": {
            "amount": STAKE, "basis": "stake", "contract_type": direction,
            "currency": currency, "duration": EXPIRY, "duration_unit": "m",
            "underlying_symbol": SYMBOL,
        },
    }))


async def run() -> None:
    if not TOKEN or not APP_ID:
        raise SystemExit("Defina DERIV_TOKEN (PAT) e DERIV_APP_ID (dashboard developers.deriv.com).")
    acct = get_demo_account()
    currency = acct.get("currency", "USD")
    print(f"Conta demo: {acct['account_id']} saldo {acct['balance']} {currency}")
    url = get_ws_url(acct["account_id"])
    bot = SpikeBot()
    pending_z = 0.0
    async with websockets.connect(url) as ws:
        print("Conectado ao WebSocket demo.")
        await ws.send(json.dumps({
            "ticks_history": SYMBOL, "style": "candles", "granularity": 60,
            "count": WINDOW + 2, "end": "latest", "subscribe": 1,
        }))
        await ws.send(json.dumps({"proposal_open_contract": 1, "subscribe": 1}))
        last_epoch = 0
        async for raw in ws:
            msg = json.loads(raw)
            mt = msg.get("msg_type")
            if mt == "candles":
                for c in msg["candles"][:-1]:
                    bot.signal(float(c["close"]))
                last_epoch = msg["candles"][-1]["epoch"]
            elif mt == "ohlc":
                o = msg["ohlc"]
                epoch = int(o["open_time"])
                if epoch != last_epoch and last_epoch:
                    sig, z = bot.signal(float(o["open"]))
                    if sig and not bot.busy and bot.daily_guard():
                        bot.busy = True
                        pending_z = z
                        print(f"[{time.strftime('%H:%M:%S')}] z={z:+.2f} sinal {sig} "
                              f"-> comprando {STAKE} {currency}, exp {EXPIRY}m")
                        await buy(ws, sig, currency)
                last_epoch = epoch
            elif mt == "buy":
                if "error" in msg:
                    print(f"[erro compra] {msg['error'].get('message', msg['error'])}")
                    bot.busy = False
                else:
                    b = msg["buy"]
                    print(f"  contrato {b.get('contract_id')} comprado por {b.get('buy_price')}")
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
                print(f"[erro] {msg['error'].get('message', msg['error'])}")


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run())
            print("[conexao encerrada; novo OTP em 5s]")
        except SystemExit:
            raise
        except Exception as e:
            print(f"[reconectando em 5s] {type(e).__name__}: {e}")
        time.sleep(5)
