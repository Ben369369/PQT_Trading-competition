"""Backtest a strategy on all 24 sessions and print a proxy of the OFFICIAL score.

    .venv\\Scripts\\python.exe analysis\\bt_all.py [strategies/team59.py] [param=value ...]

Proxy score per fill = qty * (mid 60 s later - price) - fee   (true value is hidden; mid is a
stand-in).  The official score uses the true value, so treat these as a guide, not a forecast.
"""
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from pqt_client.backtest_v2 import load_manifest, load_session
from pqt_client.v2 import Strategy, backtest_strategy

path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".py") else "strategies/team59.py"
overrides = dict(a.split("=") for a in sys.argv[1:] if "=" in a)
spec = importlib.util.spec_from_file_location("strat", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cls = next(v for v in vars(mod).values()
           if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy)
if overrides:  # change parameter defaults for this run
    cls.MODEL_PARAMS = tuple(
        type(ps)(ps.name, ps.kind, float(overrides[ps.name]), ps.min, ps.max)
        if ps.name in overrides else ps for ps in cls.MODEL_PARAMS)

man = load_manifest("data")
rows, by_sym = [], defaultdict(float)
for name in man.sessions:
    top = pd.read_csv(f"data/{name}.top.csv")
    top["mid"] = (top.bid_px + top.ask_px) / 2
    mid = top.pivot(index="batch", columns="symbol", values="mid").ffill()
    strat = cls()
    res = backtest_strategy(load_session("data", name, man), strat)
    score = 0.0
    last = mid.index.max()
    for b, s, q, px, fee in strat.fills_log:
        v = mid.at[min(b + 120, last), s]
        x = q * (v - px) / 100 - fee / 1000  # dollars
        score += x
        by_sym[s] += x
    rows.append(dict(sess=name, proxy_score=round(score, 2), est_pnl=res.pnl_est_mills / 1000,
                     fills=res.fills, shares=res.shares_traded,
                     rejects=sum(res.rejects.values()), fees=res.fees_mills / 1000))
df = pd.DataFrame(rows)
print(df.to_string(index=False))
print(f"\nTOTAL proxy score ${df.proxy_score.sum():,.0f}   mean/session ${df.proxy_score.mean():,.0f}"
      f"   worst ${df.proxy_score.min():,.0f}   sessions>0: {(df.proxy_score > 0).sum()}/24")
print(f"TOTAL est. raw PnL ${df.est_pnl.sum():,.0f}   sd/session ${df.est_pnl.std():,.0f}")
print("by symbol:", {k: round(v) for k, v in by_sym.items()})
