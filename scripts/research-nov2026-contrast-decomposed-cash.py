#!/usr/bin/env python3
"""Research only: cross-market conditional cash lift via historical within-race ticket contrasts.
Final odds are not official T-15 prices. No deployment or adoption."""
import json
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
START=[0,10,55,100,190,310,1030]
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(np.float64)
  rank=z['rankMin'].astype(np.int16)
  odds=z['oddsGeom'].astype(np.int16)
  gap=z['rankGap'].astype(np.int16)
  fav=z['favOdds'].astype(np.int16)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 output={}
 for year in (2023,2024,2025,2026):
  train=np.flatnonzero((years>=2015)&(years<year))
  test=np.flatnonzero(years==year)
  if not len(test):continue
  # Distinct cash generator: learn per-ticket uplift against SAME-RACE market
  # average, using only prior years. Estimate a low-dimensional additive
  # interaction between popularity, spread and favorite-price regime.
  scores=np.zeros((len(test),6));picks=np.zeros((len(test),6),dtype=int)
  for m in range(6):
   lo,hi=START[m:m+2]
   raw=paid[train,lo:hi]
   # In-race comparison cancels payout-rich race environments, but unlike
   # earlier mean-contrast approaches, reward is clipped per race using
   # its own historical 95th percentile and interactions are decomposed.
   caps=np.quantile(raw,.95,axis=1)
   clipped=np.minimum(raw,caps[:,None])
   uplift=clipped-clipped.mean(axis=1,keepdims=True)
   # Three independently regularized cash contrasts; not a single
   # conjunctive ROI filter. Only historical features enter the score.
   features=((rank[:,lo:hi]*8+odds[:,lo:hi],80),
             (gap[:,lo:hi]*5+fav[:,lo:hi],50),
             (rank[:,lo:hi]*10+gap[:,lo:hi],100))
   values=np.zeros((len(test),hi-lo))
   for f,(code,bins) in enumerate(features):
    x=code[train].ravel().astype(int)
    y=uplift.ravel()
    n=np.bincount(x,minlength=bins)
    sums=np.bincount(x,weights=y,minlength=bins)
    shrink=(sums/(n+np.array([200,300,400])[f]))
    values+=np.array([.5,.3,.2])[f]*shrink[code[test]]
   ix=np.argmax(values,axis=1)
   picks[:,m]=lo+ix
   scores[:,m]=values[np.arange(len(test)),ix]
  days=defaultdict(list)
  for j,i in enumerate(test):
   options=[]
   for a in range(6):
    for b in range(a+1,6):
     # Pair objective is the sum of estimated relative CASH uplift, minus
     # duplicated popularity exposure. No win-probability optimization.
     overlap=max(0,3-abs(int(rank[i,picks[j,a]])-int(rank[i,picks[j,b]])))
     s=scores[j,a]+scores[j,b]-2*overlap
     options.append((s,a,b))
   s,a,b=max(options)
   r=races[int(i)]
   days[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append((s,int(i),a,b,int(picks[j,a]),int(picks[j,b])))
  chosen=[]
  for entries in days.values():
   entries.sort(key=lambda x:(-x[0],races[x[1]]['id']))
   chosen.extend(entries[:5])
  payouts=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in chosen],dtype=np.int64)
  invested=2000*len(chosen);gross=int(payouts.sum())
  output[str(year)]={'races':len(chosen),'bets':2*len(chosen),'stakeYen':invested,'paidYen':gross,'roiPct':round(100*gross/invested,3) if invested else None,'minusMaxRaceRoiPct':round(100*(gross-int(payouts.max()))/invested,3) if invested else None,'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in chosen)),'previouslyInspected':year>=2025}
  print('CONTRAST_DECOMPOSED_CASH',year,json.dumps(output[str(year)],ensure_ascii=False),flush=True)
 out=ROOT/'analysis-results/nov2026-contrast-decomposed-cash.json'
 out.parent.mkdir(exist_ok=True)
 out.write_text(json.dumps({'algorithm':'per-race winsorized cash-uplift with additive three-interaction shrinkage and cross-market exposure selection','officialT15':False,'adopted':False,'results':output},indent=2)+'\n')
if __name__=='__main__':run()
