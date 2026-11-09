#!/usr/bin/env python3
"""Research only: time-decayed conditional cash interaction generator.
Uses settled payouts solely for prior-year fitting and forward cash audit.
Final win odds proxy != official six-market T-15 snapshots.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
ENDS=[0,10,55,100,190,310,1030]
OUT=ROOT/'analysis-results/nov2026-temporal-interaction-cash.json'
def audit(rows,payout):
    if not rows:return dict(races=0,stakeYen=0,paidYen=0,roiPct=None,minusMaxRaceRoiPct=None)
    cash=np.array([10*(int(payout[i,a])+int(payout[i,b])) for i,a,b,_,_ in rows],dtype=np.int64)
    stake=len(rows)*2000
    return dict(races=len(rows),stakeYen=stake,paidYen=int(cash.sum()),
        roiPct=round(100*cash.sum()/stake,3),
        minusMaxRaceRoiPct=round(100*(cash.sum()-cash.max())/stake,3),
        markets=dict(Counter(f'{a}-{b}' for _,_,_,a,b in rows)))
def main():
    with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
        payout=z['payout'].astype(np.int32)
        rank=z['rankMin'].astype(np.int16)
        odd=z['oddsGeom'].astype(np.int16)
        fav=z['favOdds'].astype(np.int16)
    races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
    years=np.array([int(r['month'][:4]) for r in races])
    report={}
    for target in (2023,2024,2025,2026):
        tr=np.flatnonzero((years>=2015)&(years<target))
        te=np.flatnonzero(years==target)
        if len(tr)==0 or len(te)==0:continue
        # Only past payouts; half-life of 3 years. Conditional interaction
        # lift = joint mean - two marginal means + market mean.
        weights=np.exp2(-(target-years[tr]-1)/3.0)
        choices=np.full((len(te),6),-1,dtype=np.int32)
        scores=np.full((len(te),6),-1e9,dtype=np.float64)
        for m in range(6):
            lo,hi=ENDS[m:m+2]
            y=payout[tr,lo:hi].astype(np.float64)
            # robust training target caps a jackpot at 99.9th percentile
            cap=np.quantile(y,0.999)
            y=np.minimum(y,cap)
            w=np.broadcast_to(weights[:,None],y.shape).ravel()
            yy=y.ravel()
            baseline=(w@yy+100*2000)/(w.sum()+2000)
            a=rank[tr,lo:hi].ravel().astype(int)
            b=odd[tr,lo:hi].ravel().astype(int)
            c=fav[tr,lo:hi].ravel().astype(int)
            def post(code,size,prior,alpha):
                n=np.bincount(code,weights=w,minlength=size)
                v=np.bincount(code,weights=w*yy,minlength=size)
                return (v+alpha*prior)/(n+alpha),n
            pa,na=post(a,10,baseline,500)
            pb,nb=post(b,8,baseline,500)
            # Conditional residual on odds and favorite structure.
            joint=(a*8+b)*5+c
            pj,nj=post(joint,400,baseline,300)
            ta=rank[te,lo:hi].astype(int)
            tb=odd[te,lo:hi].astype(int)
            tc=fav[te,lo:hi].astype(int)
            tj=(ta*8+tb)*5+tc
            # Marginal effects + shrunk interaction (avoids double-counting).
            interaction=pj[tj]-0.5*(pa[ta]+pb[tb])
            score=0.5*(pa[ta]+pb[tb])+interaction*np.sqrt(nj[tj]/(nj[tj]+300))-100
            score*=np.sqrt(nj[tj]/(nj[tj]+100))
            k=np.argmax(score,axis=1)
            choices[:,m]=lo+k
            scores[:,m]=score[np.arange(len(te)),k]
        grouped=defaultdict(list)
        for j,i in enumerate(te):
            # Pick two different markets by combined expected monetary surplus.
            order=np.argsort(-scores[j])
            a,b=int(order[0]),int(order[1])
            if scores[j,a]<=0 or scores[j,b]<=0:continue
            r=races[i]
            # cache 'day' is month+race identifier, use race ID date/venue prefix.
            venue=r['id'][4:6]
            day=r['id'][:4]+r['id'][6:10]
            grouped[(day,venue)].append((float(scores[j,a]+scores[j,b]),int(i),
                                              int(choices[j,a]),int(choices[j,b]),a,b))
        rows=[]
        for key,items in grouped.items():
            items.sort(key=lambda t:(-t[0],races[t[1]]['id']))
            rows.extend((i,x,y,a,b) for _,i,x,y,a,b in items[:5])
        report[str(target)]=audit(rows,payout)
        report[str(target)]['previouslyInspected']=target in (2025,2026)
        print('TEMPORAL_INTERACTION_CASH',json.dumps({target:report[str(target)]}),flush=True)
    OUT.parent.mkdir(exist_ok=True,parents=True)
    OUT.write_text(json.dumps(dict(model='time-decayed cash marginal plus interaction shrinkage',
        training='2015 to prior year only',officialT15=False,adopted=False,
        results=report),indent=2)+'\n')
if __name__=='__main__':main()
