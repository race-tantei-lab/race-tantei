#!/usr/bin/env python3
"""Research only: cross-market conditional cash uplift with within-race rank-exposure diversification.
Historical final win odds are NOT official T-15 market quotes. Never deploy.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
ENDS=[0,10,55,100,190,310,1030]
OUT=ROOT/'analysis-results/nov2026-rank-exposure-cash.json'
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout']; rank=z['rankMin']; odds=z['oddsGeom']; fav=z['favOdds']; gap=z['rankGap']
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  tr=np.flatnonzero((years>=2015)&(years<year))
  te=np.flatnonzero(years==year)
  if not len(te):continue
  # Cash-only hierarchical marginal uplift: market x rank/odds vs market x favourite/spacing.
  # Distinct from past full-cell posterior: additive cash residuals and overlap-aware pairing.
  selections=np.zeros((len(te),6),dtype=np.int32)
  values=np.zeros((len(te),6),dtype=np.float64)
  for m in range(6):
   lo,hi=ENDS[m:m+2]
   y=paid[tr,lo:hi].astype(np.float64)
   # Training-only winsorisation avoids a single jackpot setting all future picks.
   cap=np.quantile(y,0.999)
   y=np.minimum(y,cap)
   a=(rank[tr,lo:hi].astype(np.int32)*8+odds[tr,lo:hi]).ravel()
   b=(fav[tr,lo:hi].astype(np.int32)*10+gap[tr,lo:hi]).ravel()
   yy=y.ravel()
   prior=(yy.sum()+100*3000)/(len(yy)+3000)
   def effect(code,size):
    n=np.bincount(code,minlength=size)
    cash=np.bincount(code,weights=yy,minlength=size)
    return (cash-prior*n)/(n+500)
   ea=effect(a,128);eb=effect(b,100)
   ca=rank[te,lo:hi].astype(np.int32)*8+odds[te,lo:hi]
   cb=fav[te,lo:hi].astype(np.int32)*10+gap[te,lo:hi]
   score=prior-100+ea[ca]+eb[cb]
   ix=np.argmax(score,axis=1)
   selections[:,m]=lo+ix
   values[:,m]=score[np.arange(len(te)),ix]
  grouped=defaultdict(list)
  for j,i in enumerate(te):
   top=None
   for a in range(6):
    for b in range(a+1,6):
     x,y=int(selections[j,a]),int(selections[j,b])
     # Overlap penalty is a direct diversification term, not a support/ROI gate.
     overlap=max(0,3-abs(int(rank[i,x])-int(rank[i,y])))
     s=values[j,a]+values[j,b]-12*overlap
     candidate=(float(s),a,b,x,y)
     if top is None or candidate[0]>top[0]:top=candidate
   if top is None or top[0]<=0:continue
   r=races[i];rid=r['id']
   key=(rid[:4]+rid[6:10],rid[4:6])
   grouped[key].append((top[0],int(i),*top[1:]))
  chosen=[]
  for entries in grouped.values():
   entries.sort(key=lambda t:(-t[0],races[t[1]]['id']))
   chosen.extend(entries[:5])
  gross=0;big=0;counts=Counter()
  for _,i,a,b,x,y in chosen:
   p=10*(int(paid[i,x])+int(paid[i,y]))
   gross+=p;big=max(big,p);counts[f'{a}-{b}']+=1
  stake=2000*len(chosen)
  result=dict(races=len(chosen),bets=2*len(chosen),stakeYen=stake,paidYen=gross,
   roiPct=round(100*gross/stake,3) if stake else None,
   minusMaxRaceRoiPct=round(100*(gross-big)/stake,3) if stake else None,
   marketPairs=dict(counts),previouslyInspected=year in (2025,2026))
  results[str(year)]=result
  print('RANK_EXPOSURE_CASH',json.dumps({year:result}),flush=True)
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(dict(model='additive hierarchical cash residual plus rank-exposure diversified market pairing',
  training='2015 through prior year only',officialT15=False,adopted=False,results=results),indent=2)+'\n')
if __name__=='__main__':main()
