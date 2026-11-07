"""Is there predictable drift beyond 60s? Past move over L minutes vs future move from t+1min to T (or t+H)."""
import numpy as np, pandas as pd
from pathlib import Path
D=Path("data"); rows=[]
for i in range(1,25):
    t=pd.read_csv(D/f"s{i:02d}.top.csv"); t["mid"]=(t.bid_px+t.ask_px)/2
    m=t.pivot(index="batch",columns="symbol",values="mid").ffill()
    mm=m.iloc[::120]  # one point per minute (46 points)
    for s in m.columns:
        x=mm[s].values
        for L in (2,5,10):
            for H in (5,10,"end"):
                for k in range(L,len(x)-2):
                    past=x[k]-x[k-L]
                    end=len(x)-1 if H=="end" else min(k+1+H,len(x)-1)
                    fut=x[end]-x[k+1]   # from t+1min (after the 60s window) onward
                    rows.append((s,L,str(H),i,past,fut,x[k]))
d=pd.DataFrame(rows,columns=["sym","L","H","sess","past","fut","px"])
def stats(g):
    c=np.corrcoef(g.past,g.fut)[0,1]
    # profit of holding sign(past) x 100 shares from t+1min to horizon, cents per decision
    pnl=(np.sign(g.past)*g.fut).mean()
    # split-half stability: sessions 1-12 vs 13-24
    a=g[g.sess<=12]; b=g[g.sess>12]
    return pd.Series(dict(corr=c,trend_pnl_c=pnl,corr_s1_12=np.corrcoef(a.past,a.fut)[0,1],corr_s13_24=np.corrcoef(b.past,b.fut)[0,1]))
pd.set_option("display.width",200)
print(d.groupby(["sym","L","H"]).apply(stats,include_groups=False).round(3))
# whole-session drift: first-15-min move vs remaining move
print("\nfirst 15 min move vs rest-of-session move (corr across 24 sessions):")
for s in ["HPPO","BNKY","CRRT","BRRY"]:
    e=d[(d.sym==s)&(d.L==10)&(d.H=="end")]
