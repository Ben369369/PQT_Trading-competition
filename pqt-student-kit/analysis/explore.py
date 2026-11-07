"""Phase 2 analysis of the 24 historical sessions.

Run:  .venv\\Scripts\\python.exe analysis\\explore.py

Proxy for the hidden true value V: the mid 60 s (120 batches) later.  Prices are cents.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
SYMS = ["HPPO", "BNKY", "CRRT", "BRRY"]
H = 120  # 60 s markout horizon in batches


def load(name):
    top = pd.read_csv(DATA / f"{name}.top.csv")
    tr = pd.read_csv(DATA / f"{name}.trades.csv")
    top["mid"] = (top.bid_px + top.ask_px) / 2
    top["spread"] = top.ask_px - top.bid_px
    tot = top.bid_qty + top.ask_qty
    top["micro"] = (top.bid_px * top.ask_qty + top.ask_px * top.bid_qty) / tot
    return top, tr


rows, gaps, mk, pred, jumps, lead = [], [], [], [], [], []
for name in [f"s{i:02d}" for i in range(1, 25)]:
    top, tr = load(name)
    wide = {s: top[top.symbol == s].set_index("batch").sort_index() for s in SYMS}
    for s in SYMS:
        d = wide[s]
        mid = d.mid.ffill()
        fut = mid.shift(-H)
        t = tr[tr.symbol == s]
        rows.append(dict(sess=name, sym=s, spread=d.spread.median(), bidq=d.bid_qty.median(),
                         askq=d.ask_qty.median(), halted=(d.status != "TRADING").mean(),
                         trades=len(t), vol=t.qty.sum(), px=mid.median(),
                         sd60=(fut - mid).std()))
        # markout of the PASSIVE side of each public trade, at several horizons
        for h in (2, 20, 60, 120):
            f = mid.shift(-h)
            fm = f.reindex(t.batch).values
            sign = np.where(t.aggressor == "SELL", 1, -1)  # passive buyer if aggressor sold
            m = sign * (fm - t.price.values)
            for q, v in zip(t.qty.values, m):
                if not np.isnan(v):
                    mk.append((s, h, q, v))
        # does microprice predict the future mid?
        x = (d.micro - d.mid).values
        y = (fut - mid).values
        ok = ~np.isnan(x) & ~np.isnan(y)
        pred.append((s, np.corrcoef(x[ok], y[ok])[0, 1]))
        dm = mid.diff().abs()
        big = dm[dm > 6 * dm[dm > 0].median()]
        jumps.append((name, s, len(big), big.max()))
    b = wide["BNKY"].mid + 2 * wide["BRRY"].mid
    g = (wide["HPPO"].mid - b).dropna()
    rich = wide["HPPO"].bid_px - (wide["BNKY"].ask_px + 2 * wide["BRRY"].ask_px)
    cheap = (wide["BNKY"].bid_px + 2 * wide["BRRY"].bid_px) - wide["HPPO"].ask_px
    gaps.append(dict(sess=name, gap_mean=g.mean(), gap_sd=g.std(),
                     arb_gt3_6=((rich > 3.6) | (cheap > 3.6)).mean(),
                     arb_gt5=((rich > 5) | (cheap > 5)).mean()))
    # lead/lag: does the gap predict which side moves next 10 s?
    dh = wide["HPPO"].mid.shift(-20) - wide["HPPO"].mid
    db = b.shift(-20) - b
    ok = g.index.intersection(dh.dropna().index).intersection(db.dropna().index)
    lead.append((name, np.corrcoef(g[ok], dh[ok])[0, 1], np.corrcoef(g[ok], db[ok])[0, 1]))

pd.set_option("display.width", 200)
R = pd.DataFrame(rows)
print("=== per symbol (median over sessions) ===")
print(R.groupby("sym")[["px", "spread", "bidq", "askq", "trades", "vol", "sd60", "halted"]]
      .median().round(2))
print("\n=== spread range across sessions ===")
print(R.pivot(index="sess", columns="sym", values="spread").describe().round(1))

M = pd.DataFrame(mk, columns=["sym", "h", "qty", "m"])
print("\n=== passive-side markout (cents/share, qty-weighted) by horizon: >0 = market making paid ===")
M["mq"] = M.m * M.qty
print((M.groupby(["sym", "h"]).mq.sum() / M.groupby(["sym", "h"]).qty.sum()).unstack().round(2))
print("\n=== 60s passive markout by aggressor trade size bucket ===")
M120 = M[M.h == 120].copy()
M120["bucket"] = pd.qcut(M120.qty, 4, duplicates="drop")
print((M120.groupby(["sym", "bucket"], observed=True).mq.sum()
       / M120.groupby(["sym", "bucket"], observed=True).qty.sum()).unstack().round(2))

print("\n=== corr(microprice - mid, mid change over 60s) ===")
print(pd.DataFrame(pred, columns=["sym", "corr"]).groupby("sym")["corr"].mean().round(3))

G = pd.DataFrame(gaps)
print("\n=== HPPO - (BNKY + 2 BRRY), cents ===")
print(G.describe().round(3))
L = pd.DataFrame(lead, columns=["sess", "gap_vs_dHPPO", "gap_vs_dBasket"])
print("\n=== gap predicts next-10s move (corr; negative on HPPO = HPPO does the correcting) ===")
print(L[["gap_vs_dHPPO", "gap_vs_dBasket"]].mean().round(3))

J = pd.DataFrame(jumps, columns=["sess", "sym", "n_jumps", "max_jump"])
print("\n=== big 1-batch mid jumps (>6x median move) ===")
print(J.groupby("sym")[["n_jumps", "max_jump"]].median())
