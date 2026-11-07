"""Held-out (s17-s24, model fit on s01-s16): profit of TAKING a stale quote when fair beats it by > thr.
Realism: we see the book after batch b, our IOC is processed at end of b+1; we only count a fill if
the quote is still there (ask[b+1] <= ask[b]) and score it vs mid 60s after b+1, minus 0.4c fee."""
import json, numpy as np, pandas as pd
from pathlib import Path
C=json.load(open("analysis/coefs_train16.json")); D=Path("data")
CLIP={"HPPO":60,"BNKY":200,"CRRT":200,"BRRY":40}
res=[]
for i in range(17,25):
    t=pd.read_csv(D/f"s{i:02d}.top.csv"); t["mid"]=(t.bid_px+t.ask_px)/2
    q=t.bid_qty+t.ask_qty; t["imb"]=(t.bid_qty-t.ask_qty)/q; t["sp"]=t.ask_px-t.bid_px
    P=lambda c: t.pivot(index="batch",columns="symbol",values=c)
    m=P("mid").ffill(); im=P("imb").fillna(0); sp=P("sp").ffill()
    A,B,AQ,BQ=P("ask_px"),P("bid_px"),P("ask_qty"),P("bid_qty")
    gap=m.HPPO-(m.BNKY+2*m.BRRY)
    for s in C:
        f={"imb_sp":im[s]*sp[s]/2,"gap":gap}
        for k in (10,40,120): f[f"dH{k}"]=m.HPPO.diff(k).fillna(0); f[f"dS{k}"]=m[s].diff(k).fillna(0)
        fair=m[s]+sum(c*f[n] for n,c in C[s].items())
        fut=m[s].shift(-121)
        for thr in (0.5,1,1.5,2,3,4,6):
            buy=(fair-A[s]>thr+0.4)&(A[s].shift(-1)<=A[s])
            sell=(B[s]-fair>thr+0.4)&(B[s].shift(-1)>=B[s])
            qb=np.minimum(AQ[s],CLIP[s])[buy]; qs=np.minimum(BQ[s],CLIP[s])[sell]
            pb=(fut-A[s]-0.4)[buy]; ps=(B[s]-fut-0.4)[sell]
            ok_b=pb.notna(); ok_s=ps.notna()
            dollars=((pb*qb)[ok_b].sum()+(ps*qs)[ok_s].sum())/100
            n=ok_b.sum()+ok_s.sum()
            res.append(dict(sym=s,thr=thr,trades=n,dollars=dollars,
                c_per_sh=((pb*qb)[ok_b].sum()+(ps*qs)[ok_s].sum())/max(1,(qb[ok_b].sum()+qs[ok_s].sum()))))
R=pd.DataFrame(res).groupby(["thr","sym"]).agg(trades=("trades","sum"),usd=("dollars","sum"),c_sh=("c_per_sh","mean"))
R["usd_per_session"]=R.usd/8; R["trades_per_session"]=R.trades/8
pd.set_option("display.width",250)
for c in ["trades_per_session","c_sh","usd_per_session"]:
    print("\n==",c); print(R[c].round(2).unstack("sym"))
