#!/usr/bin/env python3
"""Research-only: joint two-market cash pair selection with pre-race regime switches.
Never uses target-year payouts for selection. Archived payouts are third-party,
not independently JRA-verified; official T-15 odds unavailable. Not deployable.
"""
from __future__ import annotations
import csv,gzip,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
OUT=ROOT/"analysis-results/nov2026-joint-pair-regime-cash.json"
BETS=ROOT/"analysis-results/nov2026-joint-pair-regime-bets.csv.gz"
def summary(rows):
    stake=200*len(rows);paid=sum(r["paidYen"] for r in rows)
    maximum=max((r["paidYen"] for r in rows),default=0)
    return dict(races=len(rows),tickets=2*len(rows),stakeYen=stake,
        paidYen=paid,profitYen=paid-stake,maxRacePaidYen=maximum,
        roiPct=round(100*paid/stake,4) if stake else None,
        minusMaxRaceRoiPct=round(100*(paid-maximum)/stake,4) if stake else None,
        hitRaces=sum(r["paidYen"]>0 for r in rows))
def main():
    if "--self-test" in sys.argv:
        assert summary([{"paidYen":500},{"paidYen":100}])["minusMaxRaceRoiPct"]==25
        print("JOINT_PAIR_SELF_TEST_OK");return
    path=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("seasonal_joint_source",path)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    races,cash,cat,widths,types,rid,years,quarters,joint=mod.obtain_rows()
    n=len(races)
    if len(cash)!=n*336 or np.any(cash<0):raise RuntimeError("INVALID_CASH_MATRIX")
    cash=cash.reshape(n,336).astype(np.int64)
    field=cat["fieldSize"].reshape(n,336)[:,0].astype(int)
    venues=[r["venue"] for r in races]
    # Regime uses only venue, quarter and known field size.
    keys=[(venues[i],int(quarters[i]),int(field[i])) for i in range(n)]
    decisions=[];diagnostics={}
    for target in (2023,2024,2025,2026):
        train=np.flatnonzero((years>=2017)&(years<target))
        test=np.flatnonzero(years==target)
        if not len(train) or not len(test):continue
        groups=defaultdict(list)
        for i in train:groups[keys[int(i)]].append(int(i))
        # Exact pair candidates, one representative per market and regime,
        # jointly ranked on 100-JPY cash paid, not independent ROI.
        # Two market positions chosen using train-only payout ranks.
        cache={}
        def fit(indices):
            ix=np.asarray(indices,dtype=int)
            sample=cash[ix]
            if not len(ix):raise RuntimeError("EMPTY_TRAIN")
            # Robust per-position selection: subtract largest single-race payout.
            robust=sample.sum(axis=0)-sample.max(axis=0)
            positions=[int(lo+np.argmax(robust[lo:hi])) for lo,hi in BOUNDS]
            candidates=[]
            for a in range(6):
                for b in range(a+1,6):
                    p,q=positions[a],positions[b]
                    per_race=sample[:,p]+sample[:,q]
                    total=int(per_race.sum())
                    minus=int(total-per_race.max())
                    # Direct joint cash objective; smooth against sparse hits.
                    hits=int(np.count_nonzero(per_race))
                    score=(minus/(200*len(ix)),hits/len(ix),total)
                    candidates.append((score,a,b,p,q))
            candidates.sort(reverse=True)
            _,a,b,p,q=candidates[0]
            return (a,b,p,q,len(ix),float(candidates[0][0][0]))
        global_fit=fit(train)
        for key,ix in groups.items():
            if len(ix)>=50:cache[key]=fit(ix)
        candidates=[]
        for i in test:
            i=int(i);a,b,p,q,support,robust=cache.get(keys[i],global_fit)
            candidates.append(dict(raceId=str(races[i]["id"]),day=str(races[i]["day"]),
                venue=str(venues[i]),year=target,quarter=int(quarters[i]),
                marketA=MARKETS[a],marketB=MARKETS[b],ticketA=p,ticketB=q,
                stakeYen=200,paidYen=int(cash[i,p]+cash[i,q]),
                trainSupport=support,preRacePriority=robust))
        byday=defaultdict(list)
        for x in candidates:byday[(x["day"],x["venue"])].append(x)
        for rows in byday.values():
            rows.sort(key=lambda r:(-r["preRacePriority"],r["raceId"]))
            decisions.extend(rows[:5])
        diagnostics[str(target)]=dict(trainRaces=len(train),testRaces=len(test),
            venueDays=len(byday),daysWithAtLeast3=sum(len(v)>=3 for v in byday.values()),
            daysWithAtLeast5=sum(len(v)>=5 for v in byday.values()),
            selectedDaysWith5=sum(min(len(v),5)==5 for v in byday.values()),
            regimeCount=len(cache),fallbackRaces=sum(keys[int(i)] not in cache for i in test))
    if any(x["marketA"]==x["marketB"] for x in decisions):raise RuntimeError("SAME_MARKET")
    yearly={str(y):summary([r for r in decisions if r["year"]==y]) for y in (2023,2024,2025,2026)}
    quarterly={str(y):{str(q):summary([r for r in decisions if r["year"]==y and r["quarter"]==q]) for q in (1,2,3,4)} for y in (2023,2024,2025,2026)}
    result=dict(researchOnly=True,adoptable=False,officialT15Verified=False,
        officialJraPayoutReconciled=False,knownPriorResearchExposure2025And2026=True,
        trainingUsesEarlierYearsOnly=True,selectionMethod="joint market pair robust cash",
        candidateRaces=n,candidateTickets=n*336,combined=summary(decisions),
        years=yearly,quarters=quarterly,coverage=diagnostics)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(decisions[0]) if decisions else ["raceId"])
        w.writeheader();w.writerows(decisions)
    print("JOINT_PAIR_CASH_RESULT",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
