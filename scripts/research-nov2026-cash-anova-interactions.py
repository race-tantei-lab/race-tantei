#!/usr/bin/env python3
"""Research-only cash ANOVA interaction generator; final odds are NOT official T-15."""
import json
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
FEATURES=('rankMin','oddsGeom','favOdds','rankGap','fieldSize')
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(float)
  feat={k:z[k].astype(np.int32) for k in FEATURES}
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 output={}
 for year in (2023,2024,2025,2026):
  tr=np.flatnonzero((years>=2015)&(years<year));te=np.flatnonzero(years==year)
  if not len(tr) or not len(te):continue
  picks=[];scores=[]
  for m in range(6):
   lo,hi=CUT[m:m+2]
   raw=paid[tr,lo:hi];cap=np.quantile(raw,.997)
   y=np.minimum(raw,cap).ravel()
   base=float(y.mean())
   # Two-way *monetary* ANOVA residuals, not independently profitable
   # subgroup gates. Interactions estimate cash left unexplained by
   # either main effect, with empirical-Bayes shrinkage.
   predicted=np.full((len(te),hi-lo),base)
   mains={}; main_train=np.full_like(raw,base,dtype=float)
   for name in FEATURES:
    x=feat[name][tr,lo:hi].ravel()
    nbin=max(int(x.max())+1,int(feat[name][:,lo:hi].max())+1)
    n=np.bincount(x,minlength=nbin)
    s=np.bincount(x,weights=y-base,minlength=nbin)
    effect=s/(n+350)
    mains[name]=effect
    main_train+=effect[feat[name][tr,lo:hi]]
    predicted+=effect[feat[name][te,lo:hi]]
   residual=y-(main_train.ravel())
   for a,b in (('rankMin','oddsGeom'),('favOdds','rankGap'),('oddsGeom','fieldSize')):
    xa=feat[a][tr,lo:hi].ravel();xb=feat[b][tr,lo:hi].ravel()
    width=int(max(feat[b][:,lo:hi].max(),xb.max()))+1
    idx=xa*width+xb
    size=(int(max(feat[a][:,lo:hi].max(),xa.max()))+1)*width
    n=np.bincount(idx,minlength=size)
    s=np.bincount(idx,weights=residual,minlength=size)
    interaction=s/(n+600)
    predicted+=interaction[(feat[a][te,lo:hi]*width+feat[b][te,lo:hi])]
   j=np.argmax(predicted,axis=1)
   picks.append(lo+j);scores.append(predicted[np.arange(len(te)),j])
  picks=np.stack(picks,axis=1);scores=np.stack(scores,axis=1)
  groups=defaultdict(list)
  for j,i in enumerate(te):
   # Select a two-market portfolio by direct *cash* advantage.
   # Second ticket gets no credit for the same market.
   a,b=max(((a,b) for a in range(6) for b in range(a+1,6)),
           key=lambda ab:(scores[j,ab[0]]+scores[j,ab[1]],-ab[0],-ab[1]))
   utility=float(scores[j,a]+scores[j,b]-200)
   r=races[int(i)]
   groups[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append((utility,int(i),a,b,int(picks[j,a]),int(picks[j,b])))
  chosen=[]
  for g in groups.values():
   g.sort(key=lambda x:(-x[0],races[x[1]]['id']))
   chosen.extend(g[:5])
  payouts=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in chosen],dtype=float)
  stake=2000*len(chosen);gross=int(payouts.sum())
  res={'trainStart':int(years[tr].min()),'trainEnd':int(years[tr].max()),
       'evaluationYear':year,'candidateRaces':len(te),'selectedRaces':len(chosen),
       'tickets':len(chosen)*2,'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in chosen)),
       'stakeYen':stake,'paidYen':gross,
       'roiPct':round(100*gross/stake,3) if stake else None,
       'minusMaxPayoutRoiPct':round(100*(gross-int(payouts.max()))/stake,3) if stake else None,
       'previouslyInspected':year>=2025}
  output[str(year)]=res
  print('CASH_ANOVA',json.dumps(res,ensure_ascii=False),flush=True)
 dest=ROOT/'analysis-results/nov2026-cash-anova-interactions.json'
 dest.parent.mkdir(exist_ok=True)
 dest.write_text(json.dumps({'hypothesis':'cash ANOVA two-way interaction residuals rank tickets across all markets; shrink residual monetary interactions, not subgroup ROI thresholds','officialT15':False,'adopted':False,'results':output},indent=2)+'\n')
if __name__=='__main__':run()
