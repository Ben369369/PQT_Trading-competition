"""Fit linear fair-value models: predict mid(t+60s)-mid(t) per symbol. Train s01-s16, test s17-s24."""
import numpy as np, pandas as pd, json
from pathlib import Path
D=Path("data"); S=["HPPO","BNKY","CRRT","BRRY"]; H=120
def feats(i):
    t=pd.read_csv(D/f"s{i:02d}.top.csv"); t["mid"]=(t.bid_px+t.ask_px)/2
    q=t.bid_qty+t.ask_qty; t["imb"]=(t.bid_qty-t.ask_qty)/q
    t["sp"]=t.ask_px-t.bid_px
    m=t.pivot(index="batch",columns="symbol",values="mid").ffill()
    im=t.pivot(index="batch",columns="symbol",values="imb").fillna(0)
    sp=t.pivot(index="batch",columns="symbol",values="sp").ffill()
    F={}
    gap=m.HPPO-(m.BNKY+2*m.BRRY)
    for s in S:
        X=pd.DataFrame(index=m.index)
        X["imb_sp"]=im[s]*sp[s]/2            # microprice - mid, cents
        X["gap"]=gap                          # ETF minus basket
        for k in (10,40,120):
            X[f"dH{k}"]=m.HPPO.diff(k).fillna(0)
            X[f"dS{k}"]=m[s].diff(k).fillna(0)
        X["y"]=m[s].shift(-H)-m[s]
        F[s]=X
    return F
data=[feats(i) for i in range(1,25)]
coefs={}
for s in S:
    tr=pd.concat([d[s] for d in data[:16]]).dropna(); te=pd.concat([d[s] for d in data[16:]]).dropna()
    cols=[c for c in tr.columns if c!="y"]
    A=tr[cols].values; b,*_=np.linalg.lstsq(A,tr.y.values,rcond=None)
    def r2(df): p=df[cols].values@b; return 1-((df.y-p)**2).sum()/((df.y-df.y.mean())**2).sum()
    # refit on all for deployment
    al=pd.concat([d[s] for d in data[:16]]).dropna(); bb,*_=np.linalg.lstsq(al[cols].values,al.y.values,rcond=None)
    coefs[s]=dict(zip(cols,[round(float(x),4) for x in bb]))
    print(f"{s}: R2 train {r2(tr):.3f} test {r2(te):.3f}  sd(y) {te.y.std():.1f}c  sd(pred) {(te[cols].values@b).std():.2f}c")
    print("   ",coefs[s])

json.dump(coefs,open("analysis/coefs_train16.json","w"),indent=1)
