#!/usr/bin/env python3
"""Research-only: cross-market downside-aware cash portfolio ticket generator.
Uses prior-year settled cash only; final win odds are NOT official T-15 quotes.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
ENDS=[0,10,55,100,190,310,1030]
OUT=ROOT/'analysis-results/nov2026-downside-pair-cash.json'
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(np.int32)
  rank=z['rankMin'].astype(np.int16)
  odds=z['oddsGeom'].astype(np.int16)
  fav=z['favOdds'].astype(np.int16)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for target in (2023,2024,2025,2026):
  tr=np.flatnonzero((years>=2015)&(years<target));te=np.flatnonzero(years==target)
  if not len(tr) or not len(te):continue
  # Each ticket is a 100 yen unit; shrink cash means towards the no-edge 100 yen.
  # Historical market-pair co-loss risk is estimated from prior races only.
  best=np.zeros((len(te),6),dtype=np.int32);value=np.zeros((len(te),6))
  train_market=np.zeros((len(tr),6),dtype=np.float64)
  for m in range(6):
   lo,hi=ENDS[m:m+2]
   p=paid[tr,lo:hi].astype(np.float64)
   cap=np.quantile(p,0.999)
   p=np.minimum(p,cap)
   # A separate market-specific feature interaction: popularity x odds x favourite price.
   code=((rank[tr,lo:hi].astype(np.int32)*8+odds[tr,lo:hi])*5+fav[tr,lo:hi]).ravel()
   yy=p.ravel();n=np.bincount(code,minlength=400)
   cash=np.bincount(code,weights=yy,minlength=400)
   market_prior=(yy.sum()+100*5000)/(len(yy)+5000)
   posterior=(cash+250*market_prior)/(n+250)
   c=((rank[te,lo:hi].astype(np.int32)*8+odds[te,lo:hi])*5+fav[te,lo:hi])
   # Monetary expected surplus; penalize uncertainty without fitting wins.
   scores=(posterior[c]-100)*np.sqrt(n[c]/(n[c]+250))
   ix=np.argmax(scores,axis=1)
   best[:,m]=lo+ix;value[:,m]=scores[np.arange(len(te)),ix]
   # Historical representative ticket chosen by past-only cell score.
   old_score=posterior[code.reshape(p.shape)]
   old_idx=np.argmax(old_score,axis=1)
   train_market[:,m]=paid[tr,lo:hi][np.arange(len(tr)),old_idx]
  # Empirical downside covariance of representative ticket returns, bounded to avoid jackpots.
  losses=np.minimum(train_market,200)-100
  cov=np.cov(losses,rowvar=False)
  std=np.sqrt(np.maximum(np.diag(cov),1))
  corr=np.clip(cov/np.outer(std,std),-1,1)
  grouped=defaultdict(list)
  for j,i in enumerate(te):
   pair=None
   for a in range(6):
    for b in range(a+1,6):
     # Distinct markets, joint cash surplus and downside co-movement penalty.
     score=value[j,a]+value[j,b]-20*max(0,float(corr[a,b]))
     if pair is None or score>pair[0]:pair=(score,a,b)
   if pair is None or pair[0]<=0:continue
   _,a,b=pair
   r=races[i];rid=r['id'];key=(rid[:4]+rid[6:10],rid[4:6])
   grouped[key].append((float(pair[0]),int(i),int(best[j,a]),int(best[j,b]),a,b))
  chosen=[]
  for items in grouped.values():
   items.sort(key=lambda x:(-x[0],races[x[1]]['id']))
   chosen+=items[:5]
  cash=np.array([10*(int(paid[i,x])+int(paid[i,y])) for _,i,x,y,_,_ in chosen],dtype=np.int64)
  stake=2000*len(chosen);gross=int(cash.sum());big=int(cash.max()) if len(cash) else 0
  result=dict(races=len(chosen),bets=2*len(chosen),stakeYen=stake,paidYen=gross,
   roiPct=round(100*gross/stake,3) if stake else None,
   minusMaxRaceRoiPct=round(100*(gross-big)/stake,3) if stake else None,
   markets=dict(Counter(f'{a}-{b}' for _,_,_,_,a,b in chosen)),
   previouslyInspected=target in (2025,2026))
  results[str(target)]=result
  print('DOWNSIDE_PAIR_CASH',json.dumps({target:result}),flush=True)
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(dict(model='past-only cash shrinkage plus cross-market downside correlation pair selection',
  training='2015 to year before evaluation',officialT15=False,adopted=False,results=results),indent=2)+'\n')
if __name__=='__main__':main()
