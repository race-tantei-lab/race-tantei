#!/usr/bin/env python3
"""Research only: paired-ticket empirical downside-hedge cash selector.
Payout cache units are unverified; never call its ratios audited yen ROI.
Final win odds are not T-15 snapshots. No deployment.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CUT=(0,10,55,100,190,310,1030)
MARKETS=('win','wide','quinella','exacta','trio','trifecta')

def main():
    with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
        cash=z['payout'].astype(float)
        rank=z['rankMin'].astype(float)
        gap=z['rankGap'].astype(float)
        odds=z['oddsGeom'].astype(float)
        fav=z['favOdds'].astype(float)
    races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
    years=np.array([int(r['month'][:4]) for r in races])
    # Different hypothesis: pair selection optimizes joint observed downside
    # across historical analogue races, rather than adding ticket expected cash.
    # Race regime is defined by available favourite odds and rank dispersion;
    # candidate-specific nearest historical contexts are searched per market.
    results={}
    for yr in (2023,2024,2025,2026):
        train=np.where((years>=2015)&(years<yr))[0]
        test=np.where(years==yr)[0]
        if len(train)<100 or not len(test):continue
        chosen=[]
        for i in test:
            candidates=[]
            for m in range(6):
                lo,hi=CUT[m:m+2]
                for k in range(lo,hi):
                    # Nearest-neighbour monetary samples for a specific ticket
                    # profile, strictly from earlier years. Avoid outcome leakage.
                    dist=(rank[train,k]-rank[i,k])**2
                    dist+=0.35*(gap[train,k]-gap[i,k])**2
                    dist+=0.20*(odds[train,k]-odds[i,k])**2
                    dist+=0.20*(fav[train,k]-fav[i,k])**2
                    near=train[np.argpartition(dist,min(79,len(dist)-1))[:min(80,len(dist))]]
                    v=cash[near,k]
                    # Empirical monetary value with shrinkage to market-wide
                    # historic baseline. One largest historical hit is clipped.
                    baseline=float(np.mean(cash[train,lo:hi]))
                    cap=float(np.quantile(v,.98))
                    expected=(np.minimum(v,cap).sum()+60*baseline)/(len(v)+60)
                    candidates.append((expected,m,k,near))
            # Search best per market, then explicitly evaluate pair downside
            # in shared historical race indices. This changes joint selection.
            best={}
            for item in candidates:
                if item[1] not in best or item[0]>best[item[1]][0]:best[item[1]]=item
            pairs=[]
            for a in range(6):
                for b in range(a+1,6):
                    x,y=best[a],best[b]
                    # Both payouts sampled on the same historical races:
                    # preserves cross-market hit dependence and asymmetric loss.
                    hist=np.intersect1d(x[3],y[3])
                    if len(hist)<8:
                        hist=np.union1d(x[3],y[3])
                    joint=(cash[hist,x[2]]+cash[hist,y[2]])/2
                    mean=(x[0]+y[0])/2
                    downside=float(np.mean(np.sort(joint)[:max(1,len(joint)//4)]))
                    score=.65*mean+.35*downside
                    pairs.append((score,a,b,x[2],y[2]))
            score,a,b,x,y=max(pairs,key=lambda v:(v[0],-v[1],-v[2]))
            r=races[int(i)]
            venue=r.get('venue',r['id'][4:6])
            day=r.get('day',r['id'][:8])
            chosen.append((venue,day,float(score),int(i),a,b,x,y))
        groups=defaultdict(list)
        for row in chosen:groups[(row[0],row[1])].append(row)
        selected=[]
        for rows in groups.values():
            selected.extend(sorted(rows,key=lambda r:(-r[2],races[r[3]]['id']))[:5])
        payouts=[(float(cash[i,x]),float(cash[i,y])) for _,_,_,i,a,b,x,y in selected]
        flat=[v for pair in payouts for v in pair]
        total=sum(flat)
        largest=max(flat,default=0)
        count=len(selected)
        results[str(yr)]={
            'trainYears':[int(years[train].min()),int(years[train].max())],
            'evaluationYear':yr,'candidateRaces':len(test),'selectedRaces':count,
            'marketTicketCounts':dict(Counter(MARKETS[m] for row in selected for m in row[4:6])),
            'stakeYen':200*count,'rawPayoutUnits':total,
            'maxTicketRawPayoutUnits':largest,
            'payoutYen':None,'cashRoiPct':None,'minusMaxTicketRoiPct':None,
            'payoutUnitAuditRequired':True,'officialT15':False,
            'previouslyInspected':yr>=2025}
        print('QUANTILE_HEDGE',json.dumps(results[str(yr)]),flush=True)
    path=ROOT/'analysis-results/nov2026-cash-quantile-hedge.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'algorithm':'nearest-context empirical monetary mean plus shared-race lower-quartile joint cash','adopted':False,'results':results},indent=2)+'\n')

if __name__=='__main__':main()
