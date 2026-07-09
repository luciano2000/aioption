"""Backtest da estrategia spike-fade (aposta contraria a picos extremos).

Regra: mercado de lado -> "parede" gigante (outlier) -> aposta na direcao
contraria (reversao a media), contrato binario Rise/Fall de E minutos.

Uso: python3 backtest.py R_100_1m.csv [payout_liquido]
"""
import csv
import math
import sys
from dataclasses import dataclass


@dataclass
class Result:
    z: float
    expiry: int
    calm: bool
    trades: int
    wins: int
    pnl: float
    max_dd: float

    @property
    def winrate(self):
        return self.wins / self.trades if self.trades else 0.0


def load(path):
    with open(path) as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def _stats(ps, ps2, a, b):
    """media e desvio amostral de rets[a:b] via somas de prefixo, O(1)."""
    n = b - a
    s = ps[b] - ps[a]
    s2 = ps2[b] - ps2[a]
    mu = s / n
    var = (s2 - n * mu * mu) / (n - 1) if n > 1 else 0.0
    return mu, math.sqrt(var) if var > 0 else 1e-12


def run(candles, z_th, expiry, payout, window=30, calm_filter=False, stake=1.0):
    closes = [c["close"] for c in candles]
    rets = [0.0] + [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    n = len(closes)
    ps = [0.0] * (n + 1)
    ps2 = [0.0] * (n + 1)
    for i, r in enumerate(rets):
        ps[i+1] = ps[i] + r
        ps2[i+1] = ps2[i] + r * r
    trades = wins = 0
    pnl = peak = max_dd = 0.0
    i = window + 1
    while i < n - expiry:
        mu, sd = _stats(ps, ps2, i - window, i)
        z = (rets[i] - mu) / sd
        if calm_filter:
            _, sd_prev = _stats(ps, ps2, i - window, i - 5)
            pass_calm = sd_prev <= sd * 0.8
        else:
            pass_calm = True
        if abs(z) >= z_th and pass_calm:
            entry = closes[i]
            exit_ = closes[i + expiry]
            win = exit_ < entry if z > 0 else exit_ > entry
            trades += 1
            if win:
                wins += 1
                pnl += stake * payout
            else:
                pnl -= stake
            peak = max(peak, pnl)
            max_dd = max(max_dd, peak - pnl)
            i += expiry
        else:
            i += 1
    return Result(z_th, expiry, calm_filter, trades, wins, pnl, max_dd)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "R_100_1m.csv"
    payout = float(sys.argv[2]) if len(sys.argv) > 2 else 0.92
    candles = load(path)
    days = (candles[-1]["epoch"] - candles[0]["epoch"]) / 86400
    be = 1 / (1 + payout)
    print(f"{path}: {len(candles)} candles ({days:.1f} dias) | payout liquido {payout:.2f} | break-even: {be:.1%}\n")
    header = f"{'z':>4} {'exp':>4} {'calmo':>6} {'trades':>7} {'winrate':>8} {'P&L($1/op)':>11} {'maxDD':>8}"
    print(header)
    print("-" * len(header))
    for calm in (False, True):
        for z in (2.5, 3.0, 3.5, 4.0, 5.0):
            for expiry in (1, 3, 5, 10):
                r = run(candles, z, expiry, payout, calm_filter=calm)
                if r.trades == 0:
                    continue
                print(f"{r.z:>4.1f} {r.expiry:>3}m {str(r.calm):>6} {r.trades:>7} {r.winrate:>7.1%} {r.pnl:>+11.2f} {r.max_dd:>8.2f}")
    print("\nLeitura: P&L = lucro/prejuizo total apostando $1 por operacao.")
    print(f"Para lucrar, o win rate precisa ficar acima de {be:.1%} de forma estavel.")


if __name__ == "__main__":
    main()
