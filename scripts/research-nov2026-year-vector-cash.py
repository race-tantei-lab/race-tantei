#!/usr/bin/env python3
"""Research-only: historical-year cash-vector portfolio generator; final odds != T-15."""
import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(float); rank=z['rankMin'].astype(int); odds=z['oddsGeom'].astype(int); gap=z['rankGap'].astype(int)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  train=np.where((years>=2015)&(years<year))[0]; test=np.where(years==year)[0]
  if not len(test) or not len(train):continue
  # Unlike pooled cash lifts, each ticket receives a vector of year-specific
  # realized payout estimates. Pair selection maximizes worst-year cash return
  # while penalizing positive year-to-year co-movement of losses.
  historical=sorted(set(years[train])); vectors=[]; choices=[]
  for market in range(6):
   lo,hi=CUT[market:market+2]
   code=(rank[:,lo:hi]*8+odds[:,lo:hi]).astype(int)
   nbin=max(80,int(code.max())+1)
   byyear=[]
   for yy in historical:
    ix=train[years[train]==yy]
    x=code[ix].ravel(); y=paid[ix,lo:hi].ravel()
    cap=np.quantile(y,.995); y=np.minimum(y,cap)
    n=np.bincount(x,minlength=nbin); s=np.bincount(x,weights=y,minlength=nbin)
    byyear.append((s+80*np.mean(y))/(n+80))
   mat=np.stack(byyear)
   # Cash units are per 100-yen ticket; pessimistic lower quartile across
   # prior years is the new ranking target, not horse win probability.
   score=np.quantile(mat,.25,axis=0)-100
   j=np.argmax(score[code[test]],axis=1)
   choices.append(lo+j)
   vectors.append(mat[:,code[test][np.arange(len(test)),j]].T)
  choices=np.stack(choices,axis=1); vectors=np.stack(vectors,axis=1)
  grouped=defaultdict(list)
  for j,i in enumerate(test):
   best=None
   for a in range(6):
    for b in range(a+1,6):
     va=vectors[j,a];vb=vectors[j,b]
     joint=va+vb-200
     # Penalize joint downside concentration across historical years.
     downside=np.maximum(0,100-va)*np.maximum(0,100-vb)
     utility=float(np.quantile(joint,.25)-0.005*np.mean(downside))
     candidate=(utility,-a,-b,a,b)
     if best is None or candidate>best:best=candidate
   utility,_,_,a,b=best
   r=races[int(i)]
   grouped[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append((utility,int(i),a,b,int(choices[j,a]),int(choices[j,b])))
  selected=[]
  for group in grouped.values():
   group.sort(key=lambda v:(-v[0],races[v[1]]['id']))
   selected.extend(group[:5])
  amounts=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in selected],dtype=float)
  stake=2000*len(selected); gross=int(amounts.sum())
  result={'trainYears':historical,'evaluationYear':year,'races':len(selected),'tickets':2*len(selected),'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in selected)),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,3) if stake else None,'minusMaxRaceRoiPct':round(100*(gross-int(amounts.max()))/stake,3) if stake else None,'previouslyInspected':year>=2025}
  results[str(year)]=result
  print('YEAR_VECTOR_CASH',json.dumps(result,ensure_ascii=False),flush=True)
 path=ROOT/'analysis-results/nov2026-year-vector-cash.json';path.parent.mkdir(exist_ok=True)
 path.write_text(json.dumps({'hypothesis':'yearwise cash-vector lower-quartile and paired downside overlap','officialT15':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':run()
