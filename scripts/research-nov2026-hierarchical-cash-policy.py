#!/usr/bin/env python3
"""Research-only: hierarchical pre-race cash-condition ensemble and paired-ticket slate.
No horse classification accuracy, no fabricated odds or ROI.
Selection of the recipe uses ONLY the 2021/2022 pre-2023 chronological validation.
Evaluation years NEVER participate in recipe selection; no live JRA or D1 access.
The third-party payout archive and final win odds are not official T-15 evidence.
"""
from __future__ import annotations
import csv, gzip, importlib.util, json, sys
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-hierarchical-cash-policy.json"
BETS=ROOT/"analysis-results/nov2026-hierarchical-cash-policy-bets.csv.gz"
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
# Unlike fixed regime-pair search, every candidate ticket combines multiple
# overlapping historical cash cohorts. No individual condition must clear 200%.
SCHEMAS=(
 ("rankMin","oddsGeom","horseWinAvg"),
 ("rankMax","favOdds","recentSpeedAvg"),
 ("rankMin","fieldSize","jockeyWinAvg"),
 ("rankGap","venue","horseTop3Avg"),
 ("rankMax","quarter","rankFormMismatch"),
 ("oddsGeom","horseAge","trainerWinAvg"),
 ("rankMin","draw","surfaceWinAvg"),
 ("rankMax","fieldSize","recentFinishAvg"),
 ("oddsGeom","quarter","speedRelativeField"),
 ("rankMin","venue","distanceFamiliarAvg"),
)
PRIOR=(100,500,1500)
MAX_REMOVAL=(0.5,1.0)
HIT_BONUS=(0.0,2.0,6.0)
PAIR_MODE=("all","base-overlay")
RACE_LIMIT=5
YEAR_CHECK=(2023,2024,2025,2026)

def metrics(rows):
    s=sum(x["stakeYen"] for x in rows)
    p=sum(x["paidYen"] for x in rows)
    m=max((x["paidYen"] for x in rows),default=0)
    h=sum(x["paidYen"]>0 for x in rows)
    return {"races":len(rows),"tickets":2*len(rows),"stakeYen":s,
      "paidYen":p,"roiPct":round(100*p/s,5) if s else None,
      "minusMaxRaceRoiPct":round(100*(p-m)/s,5) if s else None,
      "hitRacePct":round(100*h/len(rows),5) if rows else None,
      "maxRacePaidYen":m}

def load():
    spec=importlib.util.spec_from_file_location(
      "seas_cash_hierarchical",ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py")
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod.obtain_rows()

def make_codes(n,types,cat,widths):
    code={}
    for fields in SCHEMAS:
        a=types.reshape(n,336).astype(np.int32).copy()
        nb=6
        for f in fields:
            w=int(widths[f]); v=cat[f].reshape(n,336)
            if np.any(v>=w):raise RuntimeError("INVALID_CONTEXT_"+f)
            a=a*w+v.astype(np.int32);nb*=w
        if nb>500000:raise RuntimeError("EXCESSIVE_FINANCIAL_GROUPS")
        code[fields]=(a,nb)
    return code

def train_cohorts(cash,types,code,train_idx):
    output={}
    values=cash[train_idx,:].ravel()
    mark=types.reshape(-1,336)[train_idx,:].ravel()
    # The market backoff is empirical REAL cash from prior years, not
    # predicted horse finish positions or log loss.
    market_n=np.bincount(mark,minlength=6)
    market_paid=np.bincount(mark,weights=values,minlength=6)
    market_hits=np.bincount(mark[values>0],minlength=6)
    baseline=np.divide(market_paid,100*np.maximum(market_n,1))
    hbase=np.divide(market_hits,np.maximum(market_n,1))
    for fields,(coded,nb) in code.items():
        codes=coded[train_idx,:].ravel()
        n=np.bincount(codes,minlength=nb)
        paid=np.bincount(codes,weights=values,minlength=nb)
        hits=np.bincount(codes[values>0],minlength=nb)
        largest=np.zeros(nb,dtype=np.int32)
        ix=values>0
        np.maximum.at(largest,codes[ix],values[ix])
        block=nb//6
        market=np.minimum(np.arange(nb)//block,5)
        output[fields]=(n,paid,hits,largest,market)
    return output,baseline,hbase

def scores_for(train_obj,code,types,test_idx,prior,removal,bonus):
    groups,baseline,hbase=train_obj
    ntest=len(test_idx)
    signal=np.zeros((ntest,336),dtype=np.float32)
    for fields,(coded,nb) in code.items():
        n,p,h,m,market=groups[fields]
        # Largest single ticket removed from cohort prior cash; retain stake.
        # Add direct money backoff for sparse groups to avoid jackpot memorizing.
        safe=np.maximum(0.0,p-removal*m)
        mean=(safe+100*prior*baseline[market])/(100*(n+prior))
        prob=(h+prior*hbase[market])/(n+prior)
        signal+=(mean+bonus*prob)[coded[test_idx,:]].astype(np.float32)
    return signal/len(SCHEMAS)

def pick(races,cash,year,quarter,index,signal,mode):
    days=defaultdict(list)
    for k,i in enumerate(index):
        i=int(i);scores=signal[k]
        by_market=[]
        for market,(lo,hi) in enumerate(BOUNDS):
            j=lo+int(np.argmax(scores[lo:hi]))
            by_market.append((float(scores[j]),market,j))
        if mode=="base-overlay":
            # A money-backed base from higher-hit markets and an independent
            # overlay from a different JRA market; choose both BEFORE payouts.
            first=max(by_market[:2],key=lambda z:(z[0],-z[1]))
            second=max((b for b in by_market if b[1]!=first[1]),
                       key=lambda z:(z[0],-z[1]))
        else:
            first,second=sorted(by_market,key=lambda z:(-z[0],z[1]))[:2]
        if first[1]==second[1]:raise RuntimeError("SAME_MARKET")
        x={"raceId":str(races[i]["id"]),"day":str(races[i]["day"]),
          "venue":str(races[i]["venue"]),"year":int(year[i]),"quarter":int(quarter[i]),
          "marketA":first[1],"ticketA":first[2],
          "marketB":second[1],"ticketB":second[2],
          "stakeYen":200,"paidYen":int(cash[i,first[2]]+cash[i,second[2]]),
          "preRaceCashScore":round(first[0]+second[0],8)}
        days[(x["day"],x["venue"])].append(x)
    ledger=[]
    count=Counter()
    for group in days.values():
        chosen=sorted(group,key=lambda x:(-x["preRaceCashScore"],x["raceId"]))[:RACE_LIMIT]
        count[len(chosen)]+=1
        ledger.extend(chosen)
    coverage={"observedVenueDays":len(days),
              "selected3to5VenueDays":sum(n for k,n in count.items() if k>=3),
              "selected5VenueDays":count[5],
              "under3VenueDays":sum(n for k,n in count.items() if k<3)}
    if len({r["raceId"] for r in ledger})!=len(ledger):
        raise RuntimeError("DUPLICATE_RACES")
    return ledger,coverage

def main():
    if "--self-test" in sys.argv:
        assert metrics([{"stakeYen":200,"paidYen":500},
                        {"stakeYen":200,"paidYen":100}])["minusMaxRaceRoiPct"]==25.
        assert len(SCHEMAS)==10 and len(BOUNDS)==6
        assert all(BOUNDS[i][1]==BOUNDS[i+1][0] for i in range(5))
        print("HIERARCHICAL_DIRECT_CASH_SELFTEST_OK",flush=True);return
    races,paid,cat,widths,types,rid,year,quarter,_=load()
    n=len(races)
    if n<16000 or len(paid)!=n*336 or np.any(paid<0):
        raise RuntimeError("INVALID_CASH_UNIVERSE")
    cash=paid.reshape(n,336)
    codes=make_codes(n,types,cat,widths)
    trials=[(p,m,b,mode) for p in PRIOR for m in MAX_REMOVAL
            for b in HIT_BONUS for mode in PAIR_MODE]
    # Nested, forward-only recipe selection. Neither 2023 nor any later
    # settlement selects the candidate recipe.
    validation={}
    for target in (2021,2022):
        train=np.flatnonzero((year>=2017)&(year<target))
        check=np.flatnonzero(year==target)
        if not len(train) or not len(check):raise RuntimeError("MISSING_VALIDATION_YEAR")
        obj=train_cohorts(cash,types,codes,train)
        ledger={}
        for p,m,b,mode in trials:
            key=(p,m,b,mode)
            score=scores_for(obj,codes,types,check,p,m,b)
            bets,cov=pick(races,cash,year,quarter,check,score,mode)
            ledger[str(key)]=(metrics(bets),cov)
        validation[target]=ledger
        print("HIERARCHICAL_TRAIN_ONLY_VALIDATION",target,flush=True)
    def quality(trial):
        key=str(trial)
        a=validation[2021][key][0];b=validation[2022][key][0]
        if a["races"]<100 or b["races"]<100:return (-1e6,-1e6)
        # Primary = actual yen returns after deleting the largest payout
        # in EACH pre-2023 validation year, with stakes retained.
        w=min(a["minusMaxRaceRoiPct"],b["minusMaxRaceRoiPct"])
        combined=(a["paidYen"]-a["maxRacePaidYen"]+
                  b["paidYen"]-b["maxRacePaidYen"])*100/(a["stakeYen"]+b["stakeYen"])
        return (w,combined)
    selected=max(trials,key=lambda t:(quality(t),-trials.index(t)))
    print("HIERARCHICAL_PRE2023_RECIPE_SELECTED",selected,quality(selected),flush=True)
    byyear={}
    venue_coverage={}
    all_bets=[]
    for target in YEAR_CHECK:
        train=np.flatnonzero((year>=2017)&(year<target))
        check=np.flatnonzero(year==target)
        if not len(train) or not len(check):raise RuntimeError("NO_EVALUATION_YEAR")
        obj=train_cohorts(cash,types,codes,train)
        p,m,b,mode=selected
        signal=scores_for(obj,codes,types,check,p,m,b)
        bets,coverage=pick(races,cash,year,quarter,check,signal,mode)
        byyear[str(target)]=metrics(bets)
        venue_coverage[str(target)]=coverage
        all_bets.extend(bets)
        print("HIERARCHICAL_CASH_EVALUATION",target,byyear[str(target)],flush=True)
    total=metrics(all_bets)
    # The word "model" is reserved for fully verified qualifying systems.
    cash_gate=(total["minusMaxRaceRoiPct"] is not None and
        total["minusMaxRaceRoiPct"]>=200.0 and
        total["hitRacePct"] is not None and total["hitRacePct"]>=20.0 and
        all(byyear[str(y)]["minusMaxRaceRoiPct"] is not None and
            byyear[str(y)]["minusMaxRaceRoiPct"]>=200.0 for y in YEAR_CHECK) and
        all(c["under3VenueDays"]==0 for c in venue_coverage.values()))
    report={"researchOnly":True,"qualifyingCashPatternFound":bool(cash_gate),
      "adoptable":False,"reasonAdoptableFalse":
       "JRA official T-15 odds and independent JRA settlement reconciliation not available",
      "pre2023SelectedRecipe":{"priorTickets":selected[0],
         "largestCashDiscount":selected[1],"cashHitBonus":selected[2],
         "pairMethod":selected[3]},
      "trainingOnlyValidation":{str(y):validation[y][str(selected)] for y in (2021,2022)},
      "searchedRecipesUsingOnlyPre2023Money":len(trials),
      "cashCriteria":{"combinedMin":200,"eachYearMin":200,"minusMaxPaidRace":True,
         "minHitRacePct":20,"requiredRacesPerObservedVenueDay":3,
         "ticketMarketsPerRace":2},
      "yearly":byyear,"combined":total,"coverage":venue_coverage,
      "source":"unreconciled third-party settled 100-JPY payout CSVs",
      "finalWinOddsNotT15":True,"knownRetrospectiveExposure2025And2026":True,
      "officialVenueDayCoverageVerified":False,"productionUntouched":True,
      "candidateRaces":n,"candidateTickets":len(paid)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(all_bets[0]));w.writeheader();w.writerows(all_bets)
    print("HIERARCHICAL_DIRECT_CASH_FINAL",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
