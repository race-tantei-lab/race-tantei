#!/usr/bin/env python3
"""Research only: temporal cross-market cash momentum with held-out settlements.
No official T-15 odds; never deploy from this experiment."""
import json
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
START=[0,10,55,100,190,310,1030]
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(np.float64)
  rank=z['rankMin'].astype(np.int32)
  odds=z['oddsGeom'].astype(np.int32)
  gap=z['rankGap'].astype(np.int32)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  train=np.flatnonzero((years>=2015)&(years<year))
  test=np.flatnonzero(years==year)
  if not len(test):continue
  # Distinct hypothesis: value is recent cash momentum MINUS older-regime
  # cash expectation, conditional on popularity/price. A candidate must
  # exhibit improving cash performance, not just high pooled ROI.
  scores=np.empty((len(test),6)); picks=np.empty((len(test),6),dtype=int)
  for m in range(6):
   lo,hi=START[m:m+2]
   code=(rank[:,lo:hi]*8+odds[:,lo:hi]).astype(int)
   nbin=80
   def estimate(indices,prior):
    x=code[indices].ravel(); y=paid[indices,lo:hi].ravel()
    # Cap training-only payouts for stable cash estimates.
    cap=np.quantile(y,.995)
    y=np.minimum(y,cap)
    n=np.bincount(x,minlength=nbin)
    s=np.bincount(x,weights=y,minlength=nbin)
    return (s+prior*np.mean(y))/(n+prior),n
   recent=train[years[train]>=year-3]
   older=train[years[train]<year-3]
   if not len(older):older=train
   r,rn=estimate(recent,120)
   o,on=estimate(older,120)
   # Momentum is estimated from strictly prior years. The second term
   # penalizes transient low-support regime changes in yen.
   delta=(r-o)*np.sqrt(rn/(rn+200))
   # Lower historical base expectation avoids chasing expensive markets.
   value=0.75*r+0.25*o+0.6*delta-100
   testscore=value[code[test]]
   # Stable tie-breaking via gap, not realized outcomes.
   testscore=testscore-0.00001*gap[test,lo:hi]
   ix=np.argmax(testscore,axis=1)
   picks[:,m]=lo+ix
   scores[:,m]=testscore[np.arange(len(test)),ix]
  groups=defaultdict(list)
  for j,i in enumerate(test):
   # Joint choice is a constrained 2-market maximum with an explicit
   # preference for different popularity structures (complementarity).
   options=[]
   for a in range(6):
    for b in range(a+1,6):
     ra=rank[i,picks[j,a]];rb=rank[i,picks[j,b]]
     complement=5*abs(int(ra)-int(rb))
     options.append((scores[j,a]+scores[j,b]+complement,a,b))
   score,a,b=max(options)
   r=races[int(i)]
   key=(r.get('venue',r['id'][0:2]),r.get('day',r['id'][:10]))
   groups[key].append((score,int(i),a,b,int(picks[j,a]),int(picks[j,b])))
  selected=[]
  for rows in groups.values():
   rows.sort(key=lambda t:(-t[0],races[t[1]]['id']))
   selected+=rows[:5]
  settlements=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in selected],dtype=np.int64)
  stake=2000*len(selected);gross=int(settlements.sum())
  results[str(year)]={'races':len(selected),'bets':2*len(selected),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,3) if stake else None,'minusMaxRaceRoiPct':round(100*(gross-int(settlements.max()))/stake,3) if stake else None,'pairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in selected)),'previouslyInspected':year>=2025}
  print('REGIME_MOMENTUM_CASH',year,json.dumps(results[str(year)],ensure_ascii=False),flush=True)
 out=ROOT/'analysis-results/nov2026-regime-momentum-cash.json'
 out.parent.mkdir(exist_ok=True)
 out.write_text(json.dumps({'hypothesis':'recent-versus-old historical settled cash regime momentum plus complementary popularity pairing','officialT15':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':main()
