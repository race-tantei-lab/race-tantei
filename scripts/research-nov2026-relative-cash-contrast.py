#!/usr/bin/env python3
"""Research-only cash-contrast generator. Retrospective final odds are NOT T-15."""
import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
ENDS=[0,10,55,100,190,310,1030]
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout']; rank=z['rankMin']; spread=z['oddsSpread']; fav=z['favOdds']; field=z['fieldSize']
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  train=np.flatnonzero((years>=2015)&(years<year))
  test=np.flatnonzero(years==year)
  if not len(test): continue
  choices=np.zeros((len(test),6),int);scores=np.zeros((len(test),6))
  for m in range(6):
   lo,hi=ENDS[m:m+2]
   # New hypothesis: rank a ticket by the difference between its conditional
   # cash return and its same-race, same-market popularity-cohort alternatives.
   # This removes race-wide payout shocks before estimating monetary value.
   y=paid[train,lo:hi].astype(float)
   rk=rank[train,lo:hi].astype(int)
   cohort=np.empty_like(y)
   for b in range(3):
    mask=(rk//4==b)
    mean=np.divide((y*mask).sum(axis=1),mask.sum(axis=1),out=np.zeros(len(train)),where=mask.sum(axis=1)>0)
    cohort=np.where(mask,mean[:,None],cohort) if b else np.where(mask,mean[:,None],0.)
   contrast=y-cohort
   # A clipped residual prevents a single longshot from defining the score.
   cap=np.quantile(np.abs(contrast),.99)
   contrast=np.clip(contrast,-cap,cap)
   code=(((rk*5+spread[train,lo:hi].astype(int))*5+fav[train,lo:hi].astype(int))*4+field[train,lo:hi].astype(int))
   nbin=10*5*5*4
   sums=np.bincount(code.ravel(),weights=contrast.ravel(),minlength=nbin)
   counts=np.bincount(code.ravel(),minlength=nbin)
   # Partial pooling to the market-wide monetary contrast baseline.
   global_mean=float(contrast.mean())
   estimate=(sums+300*global_mean)/(counts+300)
   code_test=(((rank[test,lo:hi].astype(int)*5+spread[test,lo:hi].astype(int))*5+fav[test,lo:hi].astype(int))*4+field[test,lo:hi].astype(int))
   value=estimate[code_test]
   ix=value.argmax(axis=1)
   choices[:,m]=lo+ix;scores[:,m]=value[np.arange(len(test)),ix]
  groups=defaultdict(list)
  for j,i in enumerate(test):
   # Joint pair score rewards monetary complementarity across market types,
   # rather than taking the two highest individual scores unconditionally.
   pairs=[(min(scores[j,a],scores[j,b])+.5*(scores[j,a]+scores[j,b]),a,b) for a in range(6) for b in range(a+1,6)]
   score,a,b=max(pairs)
   if score<=0:continue
   rid=races[i]['id'];key=(rid[:4]+rid[6:10],rid[4:6])
   groups[key].append((float(score),int(i),a,b,int(choices[j,a]),int(choices[j,b])))
  selected=[]
  for rows in groups.values():
   rows.sort(key=lambda v:(-v[0],races[v[1]]['id']))
   selected+=rows[:5]
  cash=[10*(int(paid[i,x])+int(paid[i,y])) for _,i,a,b,x,y in selected]
  stake=2000*len(selected);gross=sum(cash)
  results[str(year)]={'races':len(selected),'bets':2*len(selected),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,3) if stake else None,'minusMaxRaceRoiPct':round(100*(gross-max(cash,default=0))/stake,3) if stake else None,'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in selected)),'previouslyInspected':year in (2025,2026)}
  print('RELATIVE_CASH_CONTRAST',json.dumps({year:results[str(year)]}),flush=True)
 out=ROOT/'analysis-results/nov2026-relative-cash-contrast.json'
 out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps({'model':'within-race popularity-cohort monetary contrast with partial pooling','training':'2015 to previous year','officialT15':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':main()
