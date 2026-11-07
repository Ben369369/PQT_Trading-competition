"""Does the forecast help on REAL trades? For each public trade, the passive side's 60s markout,
split by whether our forecast agreed with that side (pred>0 favours passive buyers)."""
import json, numpy as np, pandas as pd
from pathlib import Path
C=json.load(open("analysis/coefs_train16.json")); D=Path("data"); out=[]
for i in range(17,25):
    t=pd.read_csv(D/f"s{i:02d}.top.csv"); t["mid"]=(t.bid_px+t.ask_px)/2
    q=t.bid_qty+t.ask_qty; t["imb"]=(t.bid_qty-t.ask_qty)/q; t["sp"]=t.ask_px-t.bid_px
    m=t.pivot(index="batch",columns="symbol",values="mid").ffill()
    im=t.pivot(index="batch",columns="symbol",values="imb").fillna(0)
    sp=t.pivot(index="batch",columns="symbol",values="sp").ffill()
    gap=m.HPPO-(m.BNKY+2*m.BRRY); tr=pd.read_csv(D/f"s{i:02d}.trades.csv")
    for s in C:
        f={"imb_sp":im[s]*sp[s]/2,"gap":gap}
        for k in (10,40,120): f[f"dH{k}"]=m.HPPO.diff(k).fillna(0); f[f"dS{k}"]=m[s].diff(k).fillna(0)
        pred=sum(c*f[n] for n,c in C[s].items()).shift(1)   # info known BEFORE the trade's batch
        fut=m[s].shift(-120)
        x=tr[tr.symbol==s]; pb=np.where(x.aggressor=="SELL",1,-1)   # +1 passive buyer
        mk=pb*(fut.reindex(x.batch).values-x.price.values); pr=pb*pred.reindex(x.batch).values
        out.append(pd.DataFrame(dict(sym=s,q=x.qty.values,mk=mk,agree=pr)))
d=pd.concat(out).dropna()
d["bucket"]=pd.cut(d.agree,[-99,-2,-0.5,0.5,2,99])
g=d.groupby(["sym","bucket"],observed=True)
print("HELD-OUT s17-s24, model fit on s01-s16 only. passive markout c/share by forecast agreement (agree>0 = forecast favoured the passive side)")
print((g.apply(lambda z:(z.mk*z.q).sum()/z.q.sum(),include_groups=False)).unstack().round(2))
print(g.q.sum().unstack())
