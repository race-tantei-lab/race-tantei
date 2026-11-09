#!/usr/bin/env python3
"""Research only: sequential cash-residual ticket generation, never official T-15."""
import json
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
START=[0,10,55,100,190,310,1030]
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(float);rank=z['rankMin'].astype(int);odds=z['oddsGeom'].astype(int);gap=z['rankGap'].astype(int);fav=z['favOdds'].astype(int)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races]);out={}
 for year in (2023,2024,2025,2026):
  train=np.flatnonzero((years>=2015)&(years<year));test=np.flatnonzero(years==year)
  if not len(train) or not len(test):continue
  # Candidate payoff distributions estimated with only preceding races.
  # First ticket: shrinkage conditional cash expectation. Second ticket:
  # marginal cash payoff conditional on FIRST ticket losing in historical
  # analogous races, rather than two independently profitable tickets.
  allpick=np.zeros((len(test),6),int);first=np.zeros((len(test),6))
  second=np.zeros((len(test),6));lossbonus=np.zeros((len(test),6))
  for m in range(6):
   lo,hi=START[m:m+2];code=(rank[:,lo:hi]*8+odds[:,lo:hi]).astype(int)
   nbin=max(120,int(code.max())+1)
   x=code[train].ravel();y=paid[train,lo:hi].ravel()
   # Historical payout tail remains in settlement; estimation winsorizes only
   # the conditional means to prevent a single payout setting all picks.
   cap=np.quantile(y,.995);yc=np.minimum(y,cap)
   cnt=np.bincount(x,minlength=nbin);sm=np.bincount(x,weights=yc,minlength=nbin)
   globalmean=float(yc.mean());mean=(sm+150*globalmean)/(cnt+150)
   j=np.argmax(mean[code[test]],axis=1);allpick[:,m]=lo+j
   first[:,m]=mean[code[test][np.arange(len(test)),j]]
   # Stage two uses separate conditioning on historical first-ticket failures
   # (favorite regime, rank-gap) to estimate independent payout opportunity.
   key=(gap[:,lo:hi]*8+fav[:,lo:hi]).astype(int);nb=max(120,int(key.max())+1)
   xx=key[train].ravel();nn=np.bincount(xx,minlength=nb)
   ss=np.bincount(xx,weights=yc,minlength=nb)
   conditional=(ss+250*globalmean)/(nn+250)
   second[:,m]=conditional[key[test][np.arange(len(test)),j]]
  groups=defaultdict(list)
  for j,i in enumerate(test):
   # Reconstruct conditional joint payout under prior-year regime analogues.
   # For each first-market choice, identify historical loss cases using a
   # precommitted rank/odds cell and then score second-market candidates.
   best=None
   for a in range(6):
    xa=allpick[j,a];cell=(rank[i,xa],odds[i,xa],fav[i,xa])
    ix=train[(fav[train,xa]==cell[2])]
    if len(ix)<30:ix=train
    # A loss for a historical comparable ticket is its realized zero payout.
    # Cross-market conditional payout means are evaluated from the same
    # historical race cohort, not from future test-year outcomes.
    mask=(rank[ix,xa]==cell[0])&(odds[ix,xa]==cell[1])&(paid[ix,xa]==0)
    loss_ix=ix[mask]
    if len(loss_ix)<20:loss_ix=ix[paid[ix,xa]==0]
    for b in range(6):
     if b==a:continue
     xb=allpick[j,b]
     conditional=float(np.minimum(paid[loss_ix,xb],np.quantile(paid[train,xb],.995)).mean()) if len(loss_ix) else 0.
     # Reward conditional cash when first leg fails, with smoothing to the
     # independently estimated second-market cash expectation.
     marginal=(len(loss_ix)*conditional+100*second[j,b])/(len(loss_ix)+100)
     score=first[j,a]+marginal
     candidate=(score,-a,-b,a,b,xa,xb)
     if best is None or candidate>best:best=candidate
   score,_,_,a,b,xa,xb=best;r=races[int(i)]
   groups[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append((score,int(i),a,b,xa,xb))
  chosen=[]
  for entries in groups.values():
   entries.sort(key=lambda e:(-e[0],races[e[1]]['id']))
   chosen.extend(entries[:5])
  amounts=np.array([10*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in chosen])
  stake=2000*len(chosen);gross=int(amounts.sum())
  result={'trainYears':[int(years[train].min()),int(years[train].max())],'evaluationYear':year,'candidateRaces':len(test),'selectedRaces':len(chosen),'tickets':2*len(chosen),'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in chosen)),'stakeYen':stake,'paidYen':gross,'roiPct':round(100*gross/stake,3) if stake else None,'minusMaxPayoutRoiPct':round(100*(gross-int(amounts.max()))/stake,3) if stake else None,'previouslyInspected':year>=2025}
  out[str(year)]=result;print('SEQUENTIAL_RESIDUAL_CASH',json.dumps(result),flush=True)
 p=ROOT/'analysis-results/nov2026-sequential-residual-cash.json';p.parent.mkdir(exist_ok=True)
 p.write_text(json.dumps({'hypothesis':'second-market conditional cash on first-market loss; stagewise non-independent ticket generation','officialT15':False,'adopted':False,'results':out},indent=2)+'\n')
if __name__=='__main__':run()
