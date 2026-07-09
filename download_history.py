"""Baixa candles históricos da Deriv (índices sintéticos) e salva em CSV.

Uso: python3 download_history.py [SYMBOL] [DIAS]
Ex.:  python3 download_history.py R_100 30
Não precisa de token — dados de mercado são públicos.
"""
import asyncio
import csv
import json
import sys
import time

import websockets

APP_ID = 1089  # app_id público de teste; troque pelo seu ao registrar em api.deriv.com
URI = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
GRANULARITY = 60  # candles de 1 minuto
BATCH = 5000      # máximo por requisição


async def fetch(symbol: str, days: int) -> list[dict]:
    total = days * 24 * 60
    candles: list[dict] = []
    end: int | str = "latest"
    async with websockets.connect(URI) as ws:
        while len(candles) < total:
            req = {
                "ticks_history": symbol,
                "style": "candles",
                "granularity": GRANULARITY,
                "count": min(BATCH, total - len(candles)),
                "end": end,
            }
            await ws.send(json.dumps(req))
            resp = json.loads(await ws.recv())
            if "error" in resp:
                raise RuntimeError(resp["error"]["message"])
            batch = resp.get("candles", [])
            if not batch:
                break
            candles = batch + candles
            end = batch[0]["epoch"] - GRANULARITY  # pagina para trás
            await asyncio.sleep(0.3)  # respeita rate limit
    # dedup + ordena
    seen, out = set(), []
    for c in sorted(candles, key=lambda c: c["epoch"]):
        if c["epoch"] not in seen:
            seen.add(c["epoch"])
            out.append(c)
    return out


async def payout_probe(symbol: str) -> float | None:
    """Consulta o payout real de um contrato Rise/Fall de 1 min (sem auth)."""
    try:
        async with websockets.connect(URI) as ws:
            await ws.send(json.dumps({
                "proposal": 1, "amount": 100, "basis": "stake",
                "contract_type": "CALL", "currency": "USD",
                "duration": 1, "duration_unit": "m", "symbol": symbol,
            }))
            resp = json.loads(await ws.recv())
            if "proposal" in resp:
                p = resp["proposal"]
                return (p["payout"] - 100) / 100  # retorno líquido por acerto
    except Exception:
        pass
    return None


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "R_100"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    t0 = time.time()
    candles = asyncio.run(fetch(symbol, days))
    fname = f"{symbol}_1m.csv"
    with open(fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["epoch", "open", "high", "low", "close"])
        w.writeheader()
        w.writerows(candles)
    payout = asyncio.run(payout_probe(symbol))
    print(f"{symbol}: {len(candles)} candles -> {fname} ({time.time()-t0:.0f}s)")
    print(f"payout liquido Rise/Fall 1m: {payout if payout is not None else 'n/d'}")


if __name__ == "__main__":
    main()
