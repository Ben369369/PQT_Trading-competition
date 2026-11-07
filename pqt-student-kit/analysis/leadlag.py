import numpy as np, pandas as pd, sys
from pathlib import Path
D=Path("data"); out=[]
for i in range(1,25):
    t=pd.read_csv(D/f"s{i:02d}.top.csv"); t["mid"]=(t.bid_px+t.ask_px)/2
    q=t.bid_qty+t.ask_qty; t["micro"]=(t.bid_px*t.ask_qty+t.ask_px*t.bid_qty)/q
    m=t.pivot(index="batch",columns="symbol",values="mid").ffill()
    mc=t.pivot(index="batch",columns="symbol",values="micro").ffill()
    for h in (20,120):
        f=m.shift(-h)-m
        impBR=(m.HPPO-m.BNKY)/2-m.BRRY      # implied BRRY minus BRRY mid
        impBN=(m.HPPO-2*m.BRRY)-m.BNKY
        impH=(m.BNKY+2*m.BRRY)-m.HPPO
        def c(a,b):
            ok=a.notna()&b.notna(); return np.corrcoef(a[ok],b[ok])[0,1]
        def beta(a,b):
            ok=a.notna()&b.notna(); return np.polyfit(a[ok],b[ok],1)[0]
        out.append(dict(h=h,BRRY_c=c(impBR,f.BRRY),BRRY_b=beta(impBR,f.BRRY),
            BNKY_c=c(impBN,f.BNKY),BNKY_b=beta(impBN,f.BNKY),
            HPPO_c=c(impH,f.HPPO),HPPO_b=beta(impH,f.HPPO),
            BRRY_micro_c=c(mc.BRRY-m.BRRY,f.BRRY), CRRT_vs_others=c(m.HPPO.diff(20),f.CRRT)))
print(pd.DataFrame(out).groupby("h").mean().round(3).T)
