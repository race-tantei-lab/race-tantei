#!/usr/bin/env python3
"""Research-only conditional cash-neighbor pair generator. Final odds are NOT official T-15."""
import json
from collections import defaultdict, Counter
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
def run():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  paid=z['payout'].astype(float); rank=z['rankMin'].astype(float)
  odds=z['oddsGeom'].astype(float); gap=z['rankGap'].astype(float)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  tr=np.where((years>=2015)&(years<year))[0]; te=np.where(years==year)[0]
  if not len(tr) or not len(te):continue
  # Unlike previous additive score models, this jointly estimates the CASH
  # distribution of two bets conditional on race-level popularity structure.
  # A neighbor race is selected using only pre-race rank/odds/gap features.
  # Each candidate is evaluated on matching ticket coordinates in neighbors.
  chosen=defaultdict(list)
  for i in te:
   # Same race-level feature geometry for every market; no settlement leakage.
   anchors=np.array([np.nanmin(rank[i,CUT[m]:CUT[m+1]]) for m in range(6)])
   dist=np.abs(np.array([[np.nanmin(rank[t,CUT[m]:CUT[m+1]]) for m in range(6)] for t in tr])-anchors).mean(axis=1)
   nearest=tr[np.argsort(dist,kind='stable')[:min(240,len(tr))]]
   picks=[]
   for m in range(6):
    lo,hi=CUT[m:m+1][0],CUT[m+1]
    # Rank candidate tickets by a local, shrinkage-adjusted monetary payout,
    # not by horse win probabilities or hit-rate.
    scores=[]
    for k in range(lo,hi):
     delta=(np.abs(rank[nearest,k]-rank[i,k])+
            .3*np.abs(odds[nearest,k]-odds[i,k])+
            .5*np.abs(gap[nearest,k]-gap[i,k]))
     weights=np.exp(-np.minimum(delta,60)/5)
     y=np.minimum(paid[nearest,k],np.quantile(paid[nearest,k],.995))
     mu=(np.sum(weights*y)+30*np.mean(y))/(np.sum(weights)+30)
     scores.append((float(mu),k))
    picks.append(sorted(scores,reverse=True)[:2])
   best=None
   for a in range(6):
    for b in range(a+1,6):
     for _,ka in picks[a]:
      for _,kb in picks[b]:
       da=np.abs(rank[nearest,ka]-rank[i,ka])+.3*np.abs(odds[nearest,ka]-odds[i,ka])
       db=np.abs(rank[nearest,kb]-rank[i,kb])+.3*np.abs(odds[nearest,kb]-odds[i,kb])
       w=np.exp(-np.minimum(da+db,80)/7)
       # Joint cash outcome directly, with downside-tail lower partial moment.
       pair=paid[nearest,ka]+paid[nearest,kb]
       cap=np.quantile(pair,.995); pair=np.minimum(pair,cap)
       expected=(np.sum(w*pair)+50*np.mean(pair))/(np.sum(w)+50)
       downside=np.sum(w*np.maximum(200-pair,0))/(np.sum(w)+1e-12)
       utility=float(expected-.2*downside-200)
       candidate=(utility,-a,-b,-ka,-kb,a,b,ka,kb)
       if best is None or candidate>best:best=candidate
   u,_,_,_,_,a,b,ka,kb=best
   r=races[int(i)]
   chosen[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append((u,int(i),a,b,ka,kb))
  selected=[]
  for group in chosen.values():
   selected.extend(sorted(group,key=lambda x:(-x[0],races[x[1]]['id']))[:5])
  amounts=np.array([10*(paid[i,ka]+paid[i,kb]) for _,i,a,b,ka,kb in selected])
  stake=2000*len(selected); gross=float(amounts.sum())
  result={'trainStart':2015,'trainEnd':year-1,'evaluationYear':year,'eligibleRaces':len(te),
          'selectedRaces':len(selected),'tickets':2*len(selected),
          'marketPairs':dict(Counter(f'{a}-{b}' for _,i,a,b,ka,kb in selected)),
          'stakeYen':stake,'paidYen':round(gross),
          'roiPct':round(100*gross/stake,3) if stake else None,
          'minusMaxRaceRoiPct':round(100*(gross-float(amounts.max()))/stake,3) if stake else None,
          'previouslyInspected':year>=2025}
  results[str(year)]=result
  print('JOINT_NEIGHBOR_CASH',json.dumps(result),flush=True)
 out=ROOT/'analysis-results/nov2026-pair-cash-quantile-neighbors.json'
 out.parent.mkdir(exist_ok=True)
 out.write_text(json.dumps({'hypothesis':'race-conditional neighbor joint cash distribution with lower partial moment','officialT15':False,'adopted':False,'results':results},indent=2)+'\n')
if __name__=='__main__':run()
