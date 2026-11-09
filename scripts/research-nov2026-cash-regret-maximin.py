#!/usr/bin/env python3
"""Research-only: cross-market cash regret portfolio with leave-one-year-out shrinkage.
Final odds are retrospective proxies, never official T-15 quotes.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
ENDS=[0,10,55,100,190,310,1030]
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout']; rank=z['rankMin']; odds=z['oddsGeom']; fav=z['favOdds']; gap=z['rankGap']
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  tr=np.flatnonzero((years>=2015)&(years<year));te=np.flatnonzero(years==year)
  if not len(te):continue
  choices=np.zeros((len(te),6),dtype=int);scores=np.zeros((len(te),6))
  # Novel model: conditional expected cash minus a race-level opportunity-cost baseline.
  # Unlike earlier additive residuals, compare each ticket to the mean payout of
  # competing tickets IN ITS OWN MARKET/RACE; cross-market value uses this regret.
  for m in range(6):
   lo,hi=ENDS[m:m+2]
   raw=paid[tr,lo:hi].astype(float)
   race_base=raw.mean(axis=1,keepdims=True)
   # winsorise per race, not globally; retain cross-race monetary variation
   cap=np.quantile(raw,0.995)
   excess=np.minimum(raw,cap)-np.minimum(race_base,cap)
   key=(rank[tr,lo:hi].astype(int)*8+odds[tr,lo:hi].astype(int))*50+fav[tr,lo:hi].astype(int)*10+gap[tr,lo:hi].astype(int)
   # Equal-weight historical years so one prolific season cannot dominate.
   totals=np.zeros(10000);counts=np.zeros(10000)
   for yr in np.unique(years[tr]):
    rows=years[tr]==yr
    code=key[rows].ravel();y=excess[rows].ravel()
    cnt=np.bincount(code,minlength=10000);sm=np.bincount(code,weights=y,minlength=10000)
    totals+=np.divide(sm,cnt,out=np.zeros_like(sm),where=cnt>0)*(cnt>0)
    counts+=(cnt>0)
   effect=totals/(counts+3) # 3 pseudo-years, zero-regret prior
   testkey=(rank[te,lo:hi].astype(int)*8+odds[te,lo:hi].astype(int))*50+fav[te,lo:hi].astype(int)*10+gap[te,lo:hi].astype(int)
   val=effect[testkey]
   ix=np.argmax(val,axis=1);choices[:,m]=lo+ix;scores[:,m]=val[np.arange(len(te)),ix]
  grouped=defaultdict(list)
  for j,i in enumerate(te):
   pairs=[]
   for a in range(6):
    for b in range(a+1,6):
     x,y=choices[j,a],choices[j,b]
     # Distinct cross-market selection: maximize weaker conditional regret,
     # then combined cash advantage (lexicographic maximin).
     s=min(scores[j,a],scores[j,b])+0.25*(scores[j,a]+scores[j,b])
     pairs.append((s,a,b,x,y))
   s,a,b,x,y=max(pairs)
   if s<=0:continue
   r=races[i];rid=r['id'];key=(rid[:4]+rid[6:10],rid[4:6])
   grouped[key].append((float(s),int(i),a,b,int(x),int(y)))
  selected=[]
  for v in grouped.values():
   v.sort(key=lambda x:(-x[0],races[x[1]]['id']))
   selected.extend(v[:5])
  cash=[10*(int(paid[i,x])+int(paid[i,y])) for _,i,a,b,x,y in selected]
  stake=2000*len(selected);gross=sum(cash);maxcash=max(cash,default=0)
  results[str(year)]={'races':len(selected),'bets':2*len(selected),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,3) if stake else None,'minusMaxRaceRoiPct':round(100*(gross-maxcash)/stake,3) if stake else None,'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in selected)),'previouslyInspected':year in (2025,2026)}
  print('CASH_REGRET_MAXIMIN',json.dumps({year:results[str(year)]}),flush=True)
 out=ROOT/'analysis-results/nov2026-cash-regret-maximin.json';out.parent.mkdir(exist_ok=True,parents=True)
 out.write_text(json.dumps({'model':'year-balanced conditional cash regret with maximin market-pair selection','training':'2015 to prior year','officialT15':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':main()
