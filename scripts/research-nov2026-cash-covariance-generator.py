#!/usr/bin/env python3
"""Research-only cash utility ticket generator: hierarchical rank-bin cash + downside covariance.
Historical final odds are NOT official T-15 quotes. No production deployment.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-cash-covariance-generator.json'
MARKET_ENDS=(10,55,100,190,310,1030)
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(np.int64)
  rank=z['rankMin'].astype(np.int16)
  odd=z['oddsGeom'].astype(np.int16)
  fav=z['favOdds'].astype(np.int16)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 # Pre-register four time-forward periods. No period is a truly untouched external holdout.
 results={}
 for target in (2023,2024,2025,2026):
  train=(years>=2015)&(years<target)
  test=np.flatnonzero(years==target)
  # Rank x final-odds bin: historical CASH per 100 yen, with hierarchical shrinkage.
  scores=np.zeros((len(test),paid.shape[1]),dtype=np.float32)
  pair_risk=np.zeros((6,6),dtype=float)
  for m in range(6):
   lo=0 if m==0 else MARKET_ENDS[m-1];hi=MARKET_ENDS[m]
   y=paid[train,lo:hi].reshape(-1).astype(float)
   mean=(y.sum()+100*5000)/(len(y)+5000)
   # robust cash utility: trim top 0.1% to reduce single jackpot influence in ranking.
   cap=np.quantile(y,0.999)
   yclip=np.minimum(y,cap)
   r=rank[train,lo:hi].reshape(-1);o=odd[train,lo:hi].reshape(-1)
   f=fav[train,lo:hi].reshape(-1)
   code=(r*8+o)*5+f
   n=np.bincount(code,minlength=400)
   cash=np.bincount(code,weights=yclip,minlength=400)
   posterior=(cash+500*mean)/(n+500)
   evidence=np.sqrt(n/(n+500))
   ct=(rank[test,lo:hi]*8+odd[test,lo:hi])*5+fav[test,lo:hi]
   scores[:,lo:hi]=((posterior[ct]-100)*evidence[ct]).astype(np.float32)
  # Historical downside co-occurrence, measured per race from best pre-specified rank slot.
  # This is NOT a target-race payout-derived selection.
  market_losses=[]
  for m in range(6):
   lo=0 if m==0 else MARKET_ENDS[m-1]
   # use fixed first template slot for a stable historical market downside proxy
   market_losses.append((paid[train,lo]<100).astype(float))
  losses=np.array(market_losses)
  for a in range(6):
   for b in range(a+1,6):
    pair_risk[a,b]=float(np.mean(losses[a]*losses[b]))
  byday=defaultdict(list)
  for j,i in enumerate(test):
   offers=[]
   for m in range(6):
    lo=0 if m==0 else MARKET_ENDS[m-1];hi=MARKET_ENDS[m]
    k=lo+int(np.argmax(scores[j,lo:hi]))
    offers.append((float(scores[j,k]),k,m))
   best=None
   for a in range(6):
    for b in range(a+1,6):
     x,y=offers[a],offers[b]
     if min(x[0],y[0])<=0:continue
     # Different from previous additive uplift: risk-adjusted portfolio score.
     # Penalize joint downside, favor balanced cash opportunities.
     value=min(x[0],y[0])+0.35*max(x[0],y[0])-40*pair_risk[a,b]
     if best is None or value>best[0]:best=(value,x[1],y[1],a,b)
   if best:
    r=races[i]
    byday[(r['id'][:8],r['id'][4:6])].append((best,i))
  picks=[]
  for key,items in byday.items():
   items.sort(key=lambda x:(-x[0][0],races[x[1]]['id']))
   picks.extend(items[:5])
  investment=len(picks)*2000
  cash=np.array([10*(paid[i,b[1]]+paid[i,b[2]]) for b,i in picks],dtype=np.int64)
  gross=int(cash.sum());big=int(cash.max()) if len(cash) else 0
  results[str(target)]={'races':len(picks),'stakeYen':investment,'paidYen':gross,
   'roiPct':round(100*gross/investment,4) if investment else None,
   'minusMaxRaceRoiPct':round(100*(gross-big)/investment,4) if investment else None,
   'marketPairs':dict(Counter(str(b[3])+'-'+str(b[4]) for b,i in picks)),
   'previouslyInspected':target in (2025,2026)}
  print('CASH_COVARIANCE_YEAR',json.dumps({target:results[str(target)]}),flush=True)
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps({'algorithm':'winsorized rank-odds-favorite hierarchical cash posterior with historical joint-loss penalty','T15OfficialSixMarketOdds':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':run()
