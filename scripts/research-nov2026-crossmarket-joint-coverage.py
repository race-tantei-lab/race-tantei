#!/usr/bin/env python3
"""Joint market-pair cash search with race-day coverage and chronological holdout.
Research only: historical payout mirror, no verified JRA T-15 six-market odds.
"""
import sys,json,gzip,csv,importlib.util
from pathlib import Path
from collections import defaultdict
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-crossmarket-joint-coverage.json"
BETS=ROOT/"analysis-results/nov2026-crossmarket-joint-bets.csv.gz"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
def load():
 p=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
 s=importlib.util.spec_from_file_location("cash_source",p)
 m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
 return m.obtain_rows()
def metrics(rows):
 s=200*len(rows);p=sum(x["paidYen"] for x in rows);mx=max((x["paidYen"] for x in rows),default=0)
 return dict(races=len(rows),stakeYen=s,paidYen=p,roiPct=round(100*p/s,3) if s else None,
  minusMaxRaceRoiPct=round(100*(p-mx)/s,3) if s else None,
  hitRaces=sum(x["paidYen"]>0 for x in rows))
def main():
 races,cash,cat,widths,types,rid,year,quarter,joint=load()
 n=len(races);assert len(cash)==336*n and np.all(cash>=0)
 money=np.asarray(cash).reshape(n,336)
 venues=[r["venue"] for r in races]
 fields=cat["fieldSize"].reshape(n,336)[:,0].astype(int)
 # Prior-year only; train actual PAIRS, not separately best market tickets.
 # Pool venue/quarter/field regime, with global fallback on sparse cells.
 keys=[(venues[i],int(quarter[i]),int(fields[i])) for i in range(n)]
 records=[];diagnostics={}
 for target in (2023,2024,2025,2026):
  train=np.flatnonzero((year>=2017)&(year<target))
  test=np.flatnonzero(year==target)
  groups=defaultdict(list)
  for i in train:groups[keys[int(i)]].append(int(i))
  def rank_pair(indices):
   values=money[np.asarray(indices,dtype=int)]
   # A finite predeclared candidate grid: top-3 historical hit positions
   # and top-3 historical trimmed cash positions within each of six markets.
   hits=np.count_nonzero(values>0,axis=0)
   paid=values.sum(axis=0)
   peak=values.max(axis=0)
   positions=[]
   for lo,hi in BOUNDS:
    ix=np.arange(lo,hi)
    a=ix[np.lexsort((ix,-hits[lo:hi]))][:3]
    b=ix[np.lexsort((ix,-(paid[lo:hi]-peak[lo:hi])))][:3]
    positions.append(sorted(set(map(int,np.r_[a,b]))))
   candidates=[]
   for a in range(6):
    for b in range(a+1,6):
     for x in positions[a]:
      for z in positions[b]:
       pair=values[:,x]+values[:,z]
       total=int(pair.sum());mx=int(pair.max())
       robust=(total-mx)/(200*len(indices))
       # Joint cash objective with explicit hit support; no separate
       # per-condition ROI hurdle and no use of test-year payouts.
       hit=int(np.count_nonzero(pair))
       candidates.append((robust,hit/len(indices),total,x,z))
   candidates.sort(reverse=True)
   return [(x,z,robust,hit) for robust,hit,total,x,z in candidates[:12]]
  global_rank=rank_pair(train)
  cache={k:rank_pair(v) for k,v in groups.items() if len(v)>=50}
  candidates=[]
  for i in test:
   i=int(i); options=cache.get(keys[i],global_rank)
   # Fixed first pair, selected entirely from historical money.
   x,z,robust,hit=options[0]
   r=races[i]
   candidates.append(dict(raceId=r["id"],day=r["day"],venue=venues[i],
     year=target,quarter=int(quarter[i]),stakeYen=200,
     paidYen=int(money[i,x]+money[i,z]),ticketA=x,ticketB=z,
     marketA=next(MARKETS[j] for j,(lo,hi) in enumerate(BOUNDS) if lo<=x<hi),
     marketB=next(MARKETS[j] for j,(lo,hi) in enumerate(BOUNDS) if lo<=z<hi),
     priorJointRobustRoi=round(100*robust,3),priorHitFraction=round(hit,5)))
  days=defaultdict(list)
  for r in candidates:days[(r["day"],r["venue"])].append(r)
  chosen=[]
  for k,rows in days.items():
   rows.sort(key=lambda r:(-r["priorJointRobustRoi"],-r["priorHitFraction"],str(r["raceId"])))
   chosen+=rows[:5]
  assert all(r["marketA"]!=r["marketB"] for r in chosen)
  diagnostics[str(target)]=dict(trainRaces=len(train),testRaces=len(test),
    venueDays=len(days),daysAtLeast3=sum(len(v)>=3 for v in days.values()),
    daysAtLeast5=sum(len(v)>=5 for v in days.values()),
    regimeCount=len(cache),selected=metrics(chosen))
  records+=chosen
 report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,
  officialPayoutReconciled=False,known2025And2026ResearchExposure=True,
  candidateRaces=n,candidateTickets=len(cash),annual=diagnostics,
  combined=metrics(records),policy="joint_pair_trimmed_cash_regime_top12")
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(records[0]) if records else ["raceId"])
  w.writeheader();w.writerows(records)
 print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
