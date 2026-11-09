#!/usr/bin/env python3
"""Cross-market empirical-Bayes CASH ranking. Research only; final odds are NOT T-15."""
import json, numpy as np
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz'
RACES=ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json'
OUT=ROOT/'analysis-results/nov2026-bayes-crossmarket-cash.json'
# No hindsight ticket choices: ranks use prior years' observed yen per 100-yen ticket.
# Sparse 2-way conditional cash effects shrink toward single-feature cash means.
SCHEMAS=(('market','rankMin','oddsGeom'),('market','rankMax','favOdds'),
         ('market','rankGap','fieldSize'),('market','rankFirst','raceBand'))
def run():
 with np.load(CACHE) as z:
  paid=z['payout'].astype(np.int64)
  features={k:z[k] for k in ('market','rankMin','rankMax','oddsGeom','favOdds','rankGap','fieldSize','rankFirst','raceBand')}
 races=json.loads(RACES.read_text())['races']
 years=np.array([int(x['month'][:4]) for x in races])
 venue=np.array([int(x['id'][4:6]) for x in races])
 day=np.array([x['id'][:8]+'-'+x['id'][4:6] for x in races])
 market=features['market'][0]
 results={}
 for target in (2023,2024,2025,2026):
  train=(years>=2015)&(years<target)
  test=years==target
  # Learn cash means using only historical payouts, never a target-year return.
  base=[]
  for m in range(6):
   y=paid[train][:,market==m].ravel()
   base.append(float(y.sum()+100*2000)/(len(y)+2000))
  scores=np.zeros((int(test.sum()),paid.shape[1]),dtype=np.float32)
  for schema in SCHEMAS:
   keys=[features[k] for k in schema]
   # Unique row-local mixed-radix codes, calculated without future outcomes.
   sizes=[int(features[k].max())+1 for k in schema]
   code=np.zeros_like(keys[0],dtype=np.int64)
   for arr,sz in zip(keys,sizes):code=code*sz+arr
   ncode=int(np.prod(sizes))
   if ncode>2000000:raise RuntimeError('excessive categories')
   counts=np.bincount(code[train].ravel(),minlength=ncode)
   cash=np.bincount(code[train].ravel(),weights=paid[train].ravel(),minlength=ncode)
   # Market baseline shrinkage; 250 pseudo-tickets to suppress rare jackpots.
   baseline=np.zeros(ncode,dtype=np.float64)
   for m in range(6):
    baseline[m*int(np.prod(sizes[1:])):(m+1)*int(np.prod(sizes[1:]))]=base[m]
   posterior=(cash+250*baseline)/(counts+250)
   uplift=posterior[code[test]]-baseline[code[test]]
   # Evidence-weighted net yen uplift, not win probability.
   confidence=np.sqrt(counts[code[test]]/(counts[code[test]]+250))
   scores+=np.maximum(0,uplift*confidence).astype(np.float32)
  indices=np.flatnonzero(test)
  byday=defaultdict(list)
  for j,r in enumerate(indices):
   offers=[]
   for m in range(6):
    ids=np.flatnonzero(market==m)
    k=int(ids[np.argmax(scores[j,ids])])
    offers.append((float(scores[j,k]),k,m))
   # Cross-market pair: optimize joint predicted cash uplift, penalize shared-favorite exposure.
   best=None
   for a in range(6):
    for b in range(a+1,6):
     x,y=offers[a],offers[b]
     if min(x[0],y[0])<=0:continue
     score=x[0]+y[0]-0.15*abs(x[0]-y[0])
     if best is None or score>best[0]:best=(score,x[1],y[1],a,b)
   if best:byday[day[r]].append((best,r))
  picks=[]
  for key,items in byday.items():
   items.sort(key=lambda q:(-q[0][0],q[1]))
   picks.extend(items[:5])
  invested=2000*len(picks)
  returns=np.array([10*(paid[r,b[1]]+paid[r,b[2]]) for b,r in picks],dtype=np.int64)
  gross=int(returns.sum())
  maxrace=int(returns.max()) if len(returns) else 0
  results[str(target)]={'races':len(picks),'stakeYen':invested,'paidYen':gross,
   'roiPct':round(100*gross/invested,4) if invested else None,
   'minusMaxRaceRoiPct':round(100*(gross-maxrace)/invested,4) if invested else None,
   'marketPairs':dict(__import__('collections').Counter(f'{b[3]}-{b[4]}' for b,r in picks)),
   'researchPreviouslyInspected':target in (2025,2026)}
  print('BAYES_CASH_YEAR',json.dumps({str(target):results[str(target)]}),flush=True)
 OUT.parent.mkdir(exist_ok=True)
 OUT.write_text(json.dumps({'algorithm':'4 independent shrinkage cash interaction schemas, pair-level score, equal 1000-yen stakes','officialT15Available':False,'adopted':False,'results':results},indent=2))
if __name__=='__main__':run()
