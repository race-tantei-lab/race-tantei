#!/usr/bin/env python3
"""Research only: conditional cash-tail ticket allocator. Not official T-15 odds."""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
def run():
    with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as raw:
        paid=raw['payout'].astype(float)
        rank=raw['rankMin'].astype(int)
        gap=raw['rankGap'].astype(int)
        odds=raw['oddsGeom'].astype(int)
        fav=raw['favOdds'].astype(int)
    races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
    years=np.array([int(r['month'][:4]) for r in races])
    output={}
    for year in (2023,2024,2025,2026):
        tr=np.where((years>=2015)&(years<year))[0]
        te=np.where(years==year)[0]
        if not len(tr) or not len(te):continue
        scores=np.zeros((len(te),6)); ticket=np.zeros((len(te),6),dtype=int)
        for m in range(6):
            lo,hi=CUT[m:m+2]
            y=paid[tr,lo:hi]
            # NEW: estimate expected money as frequency of positive cash times
            # conditional mean positive cash, with separate shrinkage of both.
            # Unlike mean-cash ANOVA or pairwise ranking, rare tail size and
            # hit frequency are learned separately and recombined in yen units.
            cap=np.quantile(y,.995)
            clipped=np.minimum(y,cap)
            positive=(y>0).astype(float)
            # Two complementary cells; combine via learned incremental cash
            # instead of requiring every historical high-ROI condition.
            keys=[
                (rank[tr,lo:hi]*100+odds[tr,lo:hi],
                 rank[te,lo:hi]*100+odds[te,lo:hi]),
                (gap[tr,lo:hi]*100+fav[tr,lo:hi],
                 gap[te,lo:hi]*100+fav[te,lo:hi])]
            prior_hit=float(positive.mean())
            prior_size=float(clipped.sum()/max(1,positive.sum()))
            market_cash=prior_hit*prior_size
            combined=np.zeros((len(te),hi-lo))
            for kt,ke in keys:
                ids,inv=np.unique(kt.ravel(),return_inverse=True)
                n=np.bincount(inv)
                hits=np.bincount(inv,weights=positive.ravel())
                cash=np.bincount(inv,weights=clipped.ravel())
                # Independent beta-style shrinkage for hit probability and
                # gamma-style shrinkage for conditional positive cash.
                p=(hits+120*prior_hit)/(n+120)
                size=(cash+40*prior_size)/(hits+40)
                value=p*size
                ix=np.searchsorted(ids,ke)
                valid=ix<len(ids)
                valid[valid]=ids[ix[valid]]==ke[valid]
                effect=np.zeros(ke.shape)
                effect[valid]=value[ix[valid]]-market_cash
                combined+=effect/2
            s=market_cash+combined
            j=np.argmax(s,axis=1)
            scores[:,m]=s[np.arange(len(te)),j]
            ticket[:,m]=lo+j
        groups=defaultdict(list)
        for j,i in enumerate(te):
            a,b=sorted(range(6),key=lambda m:(-scores[j,m],m))[:2]
            r=races[int(i)]
            groups[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append(
                (float(scores[j,a]+scores[j,b]),int(i),a,b,int(ticket[j,a]),int(ticket[j,b])))
        chosen=[]
        for rows in groups.values():
            chosen.extend(sorted(rows,key=lambda v:(-v[0],races[v[1]]['id']))[:5])
        payouts=np.array([paid[i,x]+paid[i,y] for _,i,a,b,x,y in chosen])
        # Historical cache payout unit is not independently audited. Never
        # fabricate yen ROI by treating unknown raw units as yen.
        output[str(year)]={'trainYears':[int(years[tr].min()),int(years[tr].max())],
            'evaluationYear':year,'candidateRaces':len(te),'selectedRaces':len(chosen),
            'ticketTypes':dict(Counter(str(m) for _,i,a,b,x,y in chosen for m in (a,b))),
            'stakeYen':200*len(chosen),'rawPayoutUnits':float(payouts.sum()),
            'maxRaceRawPayoutUnits':float(payouts.max()) if len(payouts) else 0,
            'payoutYen':None,'cashRoiPct':None,'minusMaxPayoutRoiPct':None,
            'payoutUnitAuditRequired':True,'officialT15':False,
            'previouslyInspected':year>=2025}
        print('CASH_TAIL_HURDLE',json.dumps(output[str(year)]),flush=True)
    path=ROOT/'analysis-results/nov2026-cash-tail-hurdle.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'hypothesis':'separate conditional cash frequency and positive cash magnitude with two-cell monetary uplift','adopted':False,'results':output},indent=2)+'\n')
if __name__=='__main__':run()
