#!/usr/bin/env python3
"""Chronological adaptive cash-cohort allocation over ALL 18 JRA entrants.

For evaluation year Y, every cohort, market pair, stake and racing-day priority
uses only finished races dated <Y. Select one policy recipe on the 2021/2022
forward-cash ledgers, then freeze this recipe for 2023-26 while refreshing its
prior-year financial condition pool each year. NO future payoff selection.
Uses every legal ticket for all six markets, every subset of eight categorical
pre-race axes, ticket-level actual monetary settlement, max-race payout removal.
JRA T-15 official odds and official payout reconciliation remain unavailable.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict,Counter
import csv,gzip,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-rolling-allrunner-cash.json"
BETS=ROOT/"analysis-results/nov2026-rolling-allrunner-bets.csv.gz"
KEEP=(35,100,200,400,750)
HIT_WEIGHT=(0.,.5,2.,6.)
POOLS=((0,1,2,3,4,5),(1,2,3,4,5),(2,3,4,5))
RACE_LIMIT=(3,4,5)
OVERLAY_STAKE=(100,400,1500,6400)

def parent():
    p=ROOT/"scripts/research-nov2026-allrunner-cash.py"
    spec=importlib.util.spec_from_file_location("rolling_allrunner_parent",p)
    v=importlib.util.module_from_spec(spec);sys.modules[spec.name]=v;spec.loader.exec_module(v)
    return v

def main():
    a=parent()
    if "--self-test" in sys.argv:
        assert len(KEEP)*len(HIT_WEIGHT)*len(POOLS)*len(RACE_LIMIT)*len(OVERLAY_STAKE)==720
        assert a.metrics([dict(stakeYen=200,paidYen=400),
            dict(stakeYen=200,paidYen=200)])["minusMaxRaceRoiPct"]==50.
        assert len(a.tickets(18)[5][0])==4896
        print("ROLLING_ALLRUNNER_CASH_SELFTEST_OK",flush=True);return
    started=time.monotonic()
    src,parser=a.source()
    races=src.read_all_races(parser.parse_payments)
    yr=np.asarray([int(x["month"][:4]) for x in races],dtype=np.int16)
    if len(races)<25000:raise RuntimeError("MISSING_WIDE_JRA_HISTORY")
    templates={n:a.tickets(n) for n in range(10,19)}
    # Each calendar year has a separate immutable retrospective cash histogram.
    # Later years are NOT accessed until evaluating a following year.
    dim=int(np.prod(a.DIMS))
    years=range(2015,2026)
    byyear={y:{
        "count":np.zeros(dim,dtype=np.int32),
        "raw":np.zeros(dim,dtype=np.int64),
        "capped":np.zeros(dim,dtype=np.int64),
        "hits":np.zeros(dim,dtype=np.int32)}
        for y in years}
    bundles={}
    for i,r in enumerate(races):
        y=int(yr[i])
        cs,ps=a.features(r,templates[len(r["horses"])])
        if 2021<=y<=2026:bundles[i]=(cs,ps)
        if y in byyear:
            h=byyear[y]
            for code,pay in zip(cs,ps):
                np.add.at(h["count"],code,1)
                positive=pay>0
                if np.any(positive):
                    np.add.at(h["raw"],code[positive],pay[positive])
                    np.add.at(h["capped"],code[positive],np.minimum(pay[positive],30000))
                    np.add.at(h["hits"],code[positive],1)
        if (i+1)%5000==0:print("ROLLING_ALLRUNNER_HISTOGRAM",i+1,len(races),flush=True)
    summaries={};receipts={};candidateRecipes=[]
    frozen=None
    cache={}
    for target in (2021,2022,2023,2024,2025,2026):
        train_years=[v for v in years if v<=target-3]
        validation_years=[v for v in years if target-2<=v<=target-1]
        if len(train_years)<4 or not validation_years:raise RuntimeError("ROLLING_TRAIN_EMPTY")
        def sumhist(field,keys):
            return np.sum([byyear[v][field] for v in keys],axis=0,
                     dtype=np.int64)
        hist=(
          (sumhist("count",train_years),sumhist("count",validation_years)),
          (sumhist("raw",train_years),sumhist("raw",validation_years)),
          (sumhist("capped",train_years),sumhist("capped",validation_years)),
          (sumhist("hits",train_years),sumhist("hits",validation_years))
        )
        # Mine all 255 pre-race condition schemas using preceding years only.
        rules,audit=a.mine(hist)
        if len(rules)<100:raise RuntimeError("TOO_FEW_PREVIOUS_YEAR_ROI_RULES")
        ix=np.flatnonzero(yr==target)
        if not len(ix):raise RuntimeError("EVALUATION_YEAR_MISSING")
        votes={k:a.lookup_rules(rules,k) for k in KEEP if frozen is None or k==frozen[0]}
        if frozen is None:
            yearpolicies={}
            for k,(cash,hit) in votes.items():
                for blend in HIT_WEIGHT:
                    for pool in POOLS:
                        days=a.pick(races,bundles,ix,cash,hit,blend,pool)
                        for count in RACE_LIMIT:
                            for second in OVERLAY_STAKE:
                                recipe=(k,blend,pool,count,second)
                                bets=a.settle(days,count,second)
                                m=a.metrics(bets)
                                yearpolicies[str(recipe)]=m
            cache[target]=yearpolicies
            # Freeze recipe only after BOTH 2021 and 2022 cash evaluations.
            if target==2022:
                for k in KEEP:
                    for blend in HIT_WEIGHT:
                        for pool in POOLS:
                            for count in RACE_LIMIT:
                                for second in OVERLAY_STAKE:
                                    cfg=(k,blend,pool,count,second)
                                    x=cache[2021][str(cfg)]
                                    z=cache[2022][str(cfg)]
                                    if min(x["races"],z["races"])<400:continue
                                    worst=min(x["minusMaxRaceRoiPct"],z["minusMaxRaceRoiPct"])
                                    if min(x["hitRacePct"],z["hitRacePct"])<20:worst-=100
                                    combined=(x["paidYen"]-x["biggestPaidRaceYen"]+
                                      z["paidYen"]-z["biggestPaidRaceYen"])*100/(
                                        x["stakeYen"]+z["stakeYen"])
                                    candidateRecipes.append(((worst,combined),cfg))
                if not candidateRecipes:raise RuntimeError("NO_ROLLING_FINANCIAL_RECIPE")
                frozen=max(candidateRecipes,key=lambda x:x[0])[1]
                print("ROLLING_PRE2023_CASH_RECIPE_FROZEN",json.dumps({
                    "recipe":frozen,"2021":cache[2021][str(frozen)],
                    "2022":cache[2022][str(frozen)],
                    "recipesEvaluated":len(candidateRecipes)},ensure_ascii=False),flush=True)
        else:
            k,blend,pool,count,second=frozen
            cash,hit=votes[k]
            days=a.pick(races,bundles,ix,cash,hit,blend,pool)
            bets=a.settle(days,count,second)
            receipts[target]=bets
            m=a.metrics(bets)
            summaries[str(target)]=m
            print("ROLLING_ALLRUNNER_CASH_SETTLEMENT",target,json.dumps(m,ensure_ascii=False),flush=True)
        print("ROLLING_FINANCIAL_COHORT_AUDIT",json.dumps({
            "target":target,"priorTrainLastYear":max(train_years),
            "cohortValidationYears":validation_years,
            "conditions":audit["supportedCells"],"retained":len(rules)},flush=True)
    ledger=[x for y in (2023,2024,2025,2026) for x in receipts[y]]
    total=a.metrics(ledger)
    selected=Counter((r["day"],r["venue"]) for r in ledger)
    observed={(races[i]["day"],str(races[i]["venue"])) for i,r in enumerate(races)
              if int(r["month"][:4])>=2023}
    coverage={"observedVenueDays":len(observed),
        "venueDaysWith3to5R":sum(3<=selected[d]<=5 for d in observed),
        "venueDaysWith5R":sum(selected[d]==5 for d in observed),
        "venueDaysUnder3R":sum(selected[d]<3 for d in observed)}
    passed=bool(total["minusMaxRaceRoiPct"] is not None and
        total["minusMaxRaceRoiPct"]>=200 and
        total["hitRacePct"] is not None and total["hitRacePct"]>=20 and
        all(summaries[str(y)]["minusMaxRaceRoiPct"] is not None and
            summaries[str(y)]["minusMaxRaceRoiPct"]>=200 for y in
            (2023,2024,2025,2026)) and coverage["venueDaysUnder3R"]==0)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    report=dict(researchOnly=True,adoptable=False,cashGate=passed,
       officialJraT15Verified=False,independentOfficialPayoutVerified=False,
       noFutureYearSettlementForTraining=True,only2026JanAprAvailable=True,
       years2025And2026AlreadyResearchedBeforeThisRun=True,
       modelDefinitionRequiresCashRoi200=True,
       selectedPre2023Recipe=dict(k=frozen[0],blend=frozen[1],
          allowedOverlayMarkets=list(frozen[2]),racesPerDay=frozen[3],
          overlayStake=frozen[4]),
       preceding2021Cash=cache[2021][str(frozen)],
       preceding2022Cash=cache[2022][str(frozen)],
       evaluatedRecipes=len(candidateRecipes),
       refreshedByCalendarYear=list(range(2021,2027)),
       historicalRaces=len(races),combined=total,yearly=summaries,
       coverage=coverage,productionUntouched=True,
       seconds=round(time.monotonic()-started,1))
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    with gzip.open(BETS,"wt",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(ledger[0]) if ledger else ["raceId"])
        w.writeheader();w.writerows(ledger)
    print("ROLLING_ALLRUNNER_FINANCIAL_FINAL",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
