#!/usr/bin/env python3
"""Research only: rolling, shrinkage-backed joint ticket portfolio. No official T-15 claim."""
from __future__ import annotations
import csv,gzip,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
OUT=ROOT/"analysis-results/nov2026-regime-shrinkage-portfolio.json"
BETS=ROOT/"analysis-results/nov2026-regime-shrinkage-portfolio-bets.csv.gz"
def summarize(rows):
    stake=sum(x["stakeYen"] for x in rows); paid=sum(x["paidYen"] for x in rows)
    worst=max((x["paidYen"] for x in rows),default=0)
    return dict(races=len(rows),stakeYen=stake,paidYen=paid,profitYen=paid-stake,
        roiPct=round(100*paid/stake,4) if stake else None,
        minusMaxRaceRoiPct=round(100*(paid-worst)/stake,4) if stake else None,
        hitRaces=sum(x["paidYen"]>0 for x in rows))
def pairs():
    return [(p,q) for a,(lo,hi) in enumerate(BOUNDS)
            for blo,bhi in BOUNDS[a+1:] for p in range(lo,hi) for q in range(blo,bhi)]
def fit(cash,indices,prior,top=12):
    ix=np.asarray(indices,dtype=int)
    if not len(ix): return prior
    sample=cash[ix]
    hits=np.count_nonzero(sample,axis=0)
    robust=sample.sum(axis=0,dtype=np.int64)-sample.max(axis=0)
    options=[]
    for lo,hi in BOUNDS:
        frequent=sorted(range(lo,hi),key=lambda p:(hits[p],robust[p]),reverse=True)[:4]
        payout=sorted(range(lo,hi),key=lambda p:(robust[p],hits[p]),reverse=True)[:5]
        options.append(list(dict.fromkeys(frequent+payout)))
    choices=[]
    for a in range(6):
        for b in range(a+1,6):
            for p in options[a]:
                for q in options[b]:
                    per=sample[:,p]+sample[:,q]
                    total=int(per.sum()); maxpaid=int(per.max())
                    # shrink short regimes toward global, penalize jackpot concentration
                    robustcash=(total-maxpaid)/(200*len(ix))
                    hitrate=float(np.count_nonzero(per))/len(ix)
                    choices.append((robustcash+0.2*hitrate,p,q))
    choices.sort(reverse=True)
    return [(p,q) for _,p,q in choices[:top]]
def evaluate(cash,ix,pairs_):
    # Aggregate across actual training purchases, not per-cell ROI.
    if not len(ix):return -1e9
    sample=cash[np.asarray(ix,dtype=int)]
    vals=[]
    for p,q in pairs_:
        vals.append(sample[:,p]+sample[:,q])
    payouts=np.stack(vals)
    # One pair per race; rank by train-only robust historical performance.
    totals=payouts.sum(axis=1)
    worst=payouts.max(axis=1)
    return (totals-worst)/(200*len(ix)) + 0.15*np.count_nonzero(payouts,axis=1).mean()/len(ix)
def main():
    if "--self-test" in sys.argv:
        assert summarize([dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)])["minusMaxRaceRoiPct"]==25
        print("REGIME_SHRINKAGE_SELF_TEST_OK");return
    src=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("cash_source",src)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    races,cash,cat,widths,types,rid,years,quarters,joint=mod.obtain_rows()
    n=len(races)
    if cash.size!=n*336 or np.any(cash<0):raise RuntimeError("INVALID_CASH_MATRIX")
    cash=cash.reshape(n,336).astype(np.int64)
    fields=cat["fieldSize"].reshape(n,336)[:,0].astype(int)
    venue=[str(r["venue"]) for r in races]
    # Pre-race only: venue, quarter, field-size band. No outcome-derived regimes.
    regime=[(venue[i],int(quarters[i]),0 if fields[i]<=9 else 1 if fields[i]<=13 else 2) for i in range(n)]
    selected=[]; diagnostics={}
    for year in (2023,2024,2025,2026):
        train=np.flatnonzero((years>=2017)&(years<year)&(years>=year-5))
        test=np.flatnonzero(years==year)
        if not len(train) or not len(test):continue
        global_pairs=fit(cash,train,[])
        byregime=defaultdict(list)
        for i in train:byregime[regime[int(i)]].append(int(i))
        fitted={}
        for key,idx in byregime.items():
            # Pool low-support cells with parent venue/quarter and global candidates.
            parent=[int(i) for i in train if venue[int(i)]==key[0] and int(quarters[int(i)])==key[1]]
            source=idx if len(idx)>=80 else parent if len(parent)>=80 else train.tolist()
            local=fit(cash,source,global_pairs)
            # Jointly compare candidates; never require each candidate ROI>=200.
            pool=list(dict.fromkeys(local+global_pairs))
            score=lambda pq:evaluate(cash,source,[pq])
            fitted[key]=max(pool,key=score)
        byday=defaultdict(list)
        for i in test:
            i=int(i)
            p,q=fitted.get(regime[i],global_pairs[0])
            row=dict(raceId=str(races[i]["id"]),day=str(races[i]["day"]),venue=venue[i],
                     year=year,quarter=int(quarters[i]),marketA=MARKETS[next(a for a,(lo,hi) in enumerate(BOUNDS) if lo<=p<hi)],
                     marketB=MARKETS[next(a for a,(lo,hi) in enumerate(BOUNDS) if lo<=q<hi)],
                     ticketA=p,ticketB=q,stakeYen=200,paidYen=int(cash[i,p]+cash[i,q]))
            byday[(row["day"],row["venue"])].append(row)
        for rows in byday.values():
            # No outcome ranking: race order is pre-race available.
            rows.sort(key=lambda r:r["raceId"])
            selected.extend(rows[:5])
        diagnostics[str(year)]=dict(trainRaces=len(train),candidateRaces=len(test),
            venueDays=len(byday),daysWithAtLeast3=sum(len(v)>=3 for v in byday.values()),
            daysWith5=sum(len(v)>=5 for v in byday.values()),
            selectedDaysWith5=sum(len(v)>=5 for v in byday.values()),regimes=len(fitted))
    if any(r["marketA"]==r["marketB"] for r in selected):raise RuntimeError("DUPLICATE_MARKET")
    result=dict(researchOnly=True,adoptable=False,officialT15Verified=False,
        officialJraPayoutReconciled=False,knownPriorResearchExposure2025And2026=True,
        combined=summarize(selected),
        years={str(y):summarize([r for r in selected if r["year"]==y]) for y in (2023,2024,2025,2026)},
        quarters={str(y):{str(q):summarize([r for r in selected if r["year"]==y and r["quarter"]==q]) for q in (1,2,3,4)} for y in (2023,2024,2025,2026)},
        coverage=diagnostics,missingDataHandling="upstream obtain_rows only; verify source coverage separately")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(selected[0]) if selected else ["raceId"])
        w.writeheader();w.writerows(selected)
    print("REGIME_SHRINKAGE_RESULT",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
