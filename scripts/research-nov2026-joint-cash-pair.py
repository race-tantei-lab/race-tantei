#!/usr/bin/env python3
"""Research-only: cross-market *joint cash utility* generator. Final odds != T-15."""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
START=[0,10,55,100,190,310,1030]
FEATURES=('rankMin','rankGap','oddsGeom','favOdds')
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(np.float64)
  feat={k:z[k].astype(np.int32) for k in FEATURES}
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 output={}
 for year in (2023,2024,2025,2026):
  tr=np.flatnonzero((years>=2015)&(years<year))
  te=np.flatnonzero(years==year)
  if not len(te):continue
  # New hypothesis: choose two markets by their jointly observed historical
  # cash uplift, not two independently top-scored tickets or a fixed pair.
  # Four low-cardinality cash-conditioned strata; no realized test outcomes.
  market_scores=np.zeros((len(te),6))
  choices=np.zeros((len(te),6),dtype=np.int32)
  cohort=np.zeros((len(te),6),dtype=np.int32)
  for m in range(6):
   lo,hi=START[m:m+2]
   y=paid[tr,lo:hi]
   # The training target is yen returned per 100-yen ticket, not hit labels.
   # Winsorize only the TRAIN payouts to avoid one jackpot dominance.
   cap=np.quantile(y,.995)
   y=np.minimum(y,cap)
   a=feat['rankMin'][tr,lo:hi]
   b=feat['rankGap'][tr,lo:hi]
   c=feat['oddsGeom'][tr,lo:hi]
   d=feat['favOdds'][tr,lo:hi]
   # Marginal + two-way residual cash interaction, with shrinkage.
   codes=(a*5+c).astype(int)
   nbin=50
   count=np.bincount(codes.ravel(),minlength=nbin)
   sums=np.bincount(codes.ravel(),weights=y.ravel(),minlength=nbin)
   base=float(y.mean())
   means=(sums+200*base)/(count+200)
   interaction=(b*5+d).astype(int)
   ic=np.bincount(interaction.ravel(),minlength=50)
   residual=y-means[codes]
   isums=np.bincount(interaction.ravel(),weights=residual.ravel(),minlength=50)
   adj=isums/(ic+300)
   testcode=(feat['rankMin'][te,lo:hi]*5+feat['oddsGeom'][te,lo:hi]).astype(int)
   testint=(feat['rankGap'][te,lo:hi]*5+feat['favOdds'][te,lo:hi]).astype(int)
   predicted=means[testcode]+adj[testint]-100
   ix=np.argmax(predicted,axis=1)
   choices[:,m]=lo+ix
   market_scores[:,m]=predicted[np.arange(len(te)),ix]
   cohort[:,m]=testcode[np.arange(len(te)),ix]
  # Learn a PAIR interaction in real historical money using the same
  # pre-race candidate generator. Refit per training year with no lookahead.
  historical=np.zeros((len(tr),6),dtype=np.int32)
  for m in range(6):
   lo,hi=START[m:m+2]
   code=(feat['rankMin'][tr,lo:hi]*5+feat['oddsGeom'][tr,lo:hi]).astype(int)
   ix=np.argmax(code*-0.00001+paid[tr,lo:hi]*0,axis=1)
   # Predeclared rank-based reference candidate; never pick using payouts.
   historical[:,m]=lo+ix
  # Pair covariance uses settled historical reference tickets, not test cash.
  hist_returns=np.column_stack([paid[tr,historical[:,m]] for m in range(6)])
  hist_returns=np.minimum(hist_returns,np.quantile(hist_returns,.995,axis=0))
  cov=np.cov(hist_returns,rowvar=False)
  sd=np.sqrt(np.maximum(np.diag(cov),1))
  corr=cov/np.outer(sd,sd)
  groups=defaultdict(list)
  for j,i in enumerate(te):
   pairs=[]
   for a in range(6):
    for b in range(a+1,6):
     # Downside co-movement reduces cash utility; explicitly joint pair score.
     score=market_scores[j,a]+market_scores[j,b]-0.15*max(0,corr[a,b])*max(sd[a],sd[b])
     pairs.append((score,a,b))
   score,a,b=max(pairs)
   rid=races[int(i)]['id']
   # Venue/day key from canonical race metadata when available.
   key=races[int(i)].get('day',rid[:10])
   groups[key].append((score,int(i),a,b,int(choices[j,a]),int(choices[j,b])))
  selected=[]
  for rows in groups.values():
   rows.sort(key=lambda r:(-r[0],races[r[1]]['id']))
   selected.extend(rows[:5])
  cash=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in selected],dtype=np.int64)
  stake=2000*len(selected);gross=int(cash.sum())
  result={'races':len(selected),'bets':2*len(selected),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,4) if stake else None,'minusMaxRaceRoiPct':round(100*(gross-int(cash.max()))/stake,4) if stake else None,'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in selected)),'previouslyInspected':year>=2025}
  output[str(year)]=result
  print('JOINT_CASH_PAIR',json.dumps({str(year):result}),flush=True)
 target=ROOT/'analysis-results/nov2026-joint-cash-pair.json'
 target.parent.mkdir(exist_ok=True)
 target.write_text(json.dumps({'algorithm':'marginal cash shrinkage plus monetary residual interactions and cross-market pair covariance','officialT15':False,'adopted':False,'results':output},indent=2)+'\n')
if __name__=='__main__':main()
