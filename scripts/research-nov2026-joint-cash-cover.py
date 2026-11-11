#!/usr/bin/env python3
"""Research-only joint cash optimization of two distinct markets, full venue-day coverage.
Prior-year settled payout only. Not official T-15 odds or independently JRA reconciled.
"""
import sys,json,gzip,csv
from pathlib import Path
from collections import defaultdict
import numpy as np
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("broad",ROOT/"scripts/research-nov2026-broad-base-overlay-walkforward.py")
broad=importlib.util.module_from_spec(spec);sys.modules[spec.name]=broad;spec.loader.exec_module(broad)
OUT=ROOT/"analysis-results/nov2026-joint-cash-cover.json"
BETS=ROOT/"analysis-results/nov2026-joint-cash-cover-bets.csv.gz"
def robust(payout,stake):
    if stake<=0:return -1.
    return (float(payout.sum())-float(payout.max(initial=0)))/stake
def select(cash,races,years,quarters,cat):
    n=len(races); payouts=np.asarray(cash,dtype=np.int64).reshape(n,336)
    field=cat["fieldSize"].reshape(n,336)[:,0]
    venue=[r["venue"] for r in races]
    keys=[(venue[i],int(quarters[i]),int(field[i])//4) for i in range(n)]
    # 15 pairs of markets, enumerating all 336 genuine ticket positions.
    market=np.empty(336,dtype=np.int8)
    for j,(lo,hi) in enumerate(broad.BOUNDS):market[lo:hi]=j
    decisions=[];diagnostics={}
    for target in (2023,2024,2025,2026):
        train=np.flatnonzero((years>=2017)&(years<target))
        test=np.flatnonzero(years==target)
        if not len(test):continue
        groups=defaultdict(list)
        for i in train:groups[keys[int(i)]].append(int(i))
        cache={}
        # Evaluate actual two-ticket combined cash rather than individually high ROI cells.
        def train_pairs(idx):
            v=payouts[np.asarray(idx,dtype=int)]
            if not len(v):raise ValueError("empty training")
            # Screen each market to 3 positions by historical cash after its max win;
            # joint pair is then scored on full per-race cash, excluding largest race.
            positions=[]
            for lo,hi in broad.BOUNDS:
                totals=v[:,lo:hi].sum(axis=0)-v[:,lo:hi].max(axis=0)
                positions.extend((lo+int(k)) for k in np.argsort(-totals,kind="stable")[:3])
            options=[]
            for a in positions:
                for c in positions:
                    if market[a]>=market[c]:continue
                    paid=v[:,a]+v[:,c]
                    options.append((robust(paid,200*len(idx)),int(paid.sum()),a,c))
            options.sort(key=lambda z:(-z[0],-z[1],z[2],z[3]))
            return options[:8]
        global_pairs=train_pairs(train)
        for key,idx in groups.items():
            if len(idx)>=60:cache[key]=train_pairs(idx)
        byday=defaultdict(list);fallback=0
        for i in test:
            i=int(i)
            if keys[i] not in cache:fallback+=1
            options=cache.get(keys[i],global_pairs)
            # Pre-race deterministic choice; never inspect test payout for ranking.
            _,_,a,c=options[0]
            row=dict(raceId=races[i]["id"],day=races[i]["day"],venue=venue[i],
                year=target,quarter=int(quarters[i]),stakeYen=200,
                paidYen=int(payouts[i,a]+payouts[i,c]),ticketA=a,ticketB=c,
                marketA=broad.MARKETS[int(market[a])],marketB=broad.MARKETS[int(market[c])],
                trainingRegimeSupport=len(groups.get(keys[i],[])))
            byday[(row["day"],row["venue"])].append(row)
        for day,rows in byday.items():
            # Coverage first: up to 5 races per venue day, fixed race-id tie break.
            rows.sort(key=lambda x:str(x["raceId"]))
            decisions.extend(rows[:5])
        diagnostics[str(target)]=dict(trainRaces=len(train),testRaces=len(test),
            venueDays=len(byday),daysAtLeast3=sum(len(v)>=3 for v in byday.values()),
            daysAtLeast5=sum(len(v)>=5 for v in byday.values()),
            fallbackRaces=fallback,trainingRegimes=len(cache))
    return decisions,diagnostics
def main():
    m=broad.source()
    races,cash,cat,widths,types,rid,year,quarter,joint=m.obtain_rows()
    if len(cash)!=len(races)*336:raise RuntimeError("CASH_DIMENSION")
    if np.any(np.asarray(cash)<0):raise RuntimeError("NEGATIVE_PAYOUT")
    decisions,coverage=select(cash,races,year,quarter,cat)
    yearly={str(y):broad.summary([x for x in decisions if x["year"]==y]) for y in (2023,2024,2025,2026)}
    combined=broad.summary(decisions)
    report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,
        officialJraPayoutReconciled=False,knownPriorResearchExposure2025And2026=True,
        method="prior-year two-market joint cash, largest-race excluded; venue-quarter-field regime",
        year=yearly,combined=combined,coverage=coverage,
        inputRaces=len(races),inputTickets=len(cash))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(decisions[0]) if decisions else ["raceId"])
        w.writeheader();w.writerows(decisions)
    print("JOINT_CASH_COVER_RESULT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
