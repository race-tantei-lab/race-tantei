#!/usr/bin/env python3
"""Independent-year 2026 validation: 2024+2025 actual JRA payout learning.

2025 research winner (only the best within that year, NOT proof): grouped
horse LambdaRank + 2-part P(ticket wins)*E(payout|win), 2025 97.48% ROI.

NEW: refit payout head on *both* 2024 and 2025 genuine JRA settlements,
using out-of-year horse scores in each period, and test 2026 Jan-Aug09.
2024 horse rankings learned strictly through 2023; 2025 learned through
2024; 2026 learned through 2025. 2026 payout used ONLY for scoring.
No model parameters tuned using 2026, and no 2026 labels in fitting.

Also benchmark 2024-only payout head frozen into 2026 (not used to
select the winner after seeing 2026 outcomes).

All identical complete venue-days use 5 races per venue-day, distinct
2 JRA ticket types per race, 2,000 yen total, same cohort for hits+ROI.
Official odds final or synthetic odds never enter this study. However
archived runners exact 15m provenance is not established. No wagers
placed. 2025 and 2026 have been inspected in other studies: retrospective
validation, not pristine heldout or real-money profitability proof.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from pathlib import Path
import datetime as dt
import json,sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/2024-2025-payout-hurdle-2026-JRA-real.json"
MODEL_OUT=ROOT/"analysis-results/research-frozen-2026-pooled-lambdarank-hurdle.joblib"
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
UNORDERED={"ワイド","馬連","3連複"}
YEAR_MONTHS={2024:list(range(5,13)),2025:list(range(1,13)),2026:list(range(1,9))}
PRIMARY="ranker_only_2024plus2025_payout_head"

def load(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_SOURCE "+path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m

def official_paid_payouts(helper):
    payouts=defaultdict(dict);coverage={}
    for year,months in YEAR_MONTHS.items():
        for month in months:
            low=f"{year}-{month:02d}-"
            upper=(dt.date(year,month,1)+dt.timedelta(days=35)).replace(day=1).strftime("%Y-%m-")
            data=helper.read_d1("""SELECT race_id raceId,bet_type betType,combination,
                     payout_yen payoutYen FROM rt_payouts WHERE race_id>=? AND race_id<?
                     ORDER BY race_id,bet_type,combination LIMIT 4800""",[low,upper])
            if len(data)>=4800:raise RuntimeError("PAYOUT_MONTH_POSSIBLY_TRUNCATED:"+low)
            for row in data:
                typ=row["betType"]
                if typ not in TYPES:continue
                combo=tuple(map(int,str(row["combination"]).split("-")))
                if len(combo)!=(1 if typ=="単勝" else 3 if typ in {"3連複","3連単"} else 2):
                    raise ValueError("INVALID_JRA_TICKET_COMBINATION")
                if len(set(combo))!=len(combo):raise ValueError("DUPLICATE_JRA_TICKET_HORSES")
                if typ in UNORDERED:combo=tuple(sorted(combo))
                key=(typ,combo);rid=row["raceId"];amount=int(row["payoutYen"])
                if amount<0:raise AssertionError("NEGATIVE_JRA_PAYOUT")
                if key in payouts[rid] and payouts[rid][key]!=amount:
                    raise AssertionError("JRA_PAYOUT_DUPLICATE_CONFLICT")
                payouts[rid][key]=amount
            coverage[low]={"payoutRows":len(data),
              "racesWithPayout":len({r["raceId"] for r in data})}
            print("TWO_YEAR_PAYOUT_MONTH",low,coverage[low],flush=True)
    return payouts,coverage

def metrics_same_cohort(a,b):
    if a["races"]!=b["races"] or a["stakeYen"]!=b["stakeYen"]:
        raise RuntimeError("SAME_COHORT_REFERENCE_MISMATCH")
    return True

def selftest():
    assert len(YEAR_MONTHS[2024])==8 and len(YEAR_MONTHS[2025])==12
    assert len(YEAR_MONTHS[2026])==8
    assert PRIMARY.endswith("2024plus2025_payout_head")
    assert metrics_same_cohort({"races":5,"stakeYen":10000},{"races":5,"stakeYen":10000})
    try:
        metrics_same_cohort({"races":5,"stakeYen":10000},{"races":4,"stakeYen":8000})
        raise AssertionError("COHORT_GUARD_FAILED")
    except RuntimeError:pass
    print("TWO_YEAR_PAYOUT_HEAD_FROZEN_2026_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","pool_history")
    helper=load("scripts/research-extra-trees-2024-2025-paired-jra.py","pool_actual_jra")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","pool_struct")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","pool_tickets")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=structural.top3_targets(archive)
    meta=helper.eligible_metadata(archive)
    assert len(meta)==len(counts) and len(X)==len(y)==len(t3)
    if str(dates[-1])>"2026-08-09":raise RuntimeError("ARCHIVE_END_CHANGED_CHECK_PROVENANCE")
    payouts,coverage=official_paid_payouts(helper)
    years={};yearProvenance={};excluded={}
    for year in (2024,2025,2026):
        horse,training=structural.fit_horse_models(X,y,t3,counts,offsets,dates,year)
        eligible,bad,raw=structural.year_groups(
            year,X,counts,dates,offsets,meta,horse,payouts)
        years[year]=eligible
        yearProvenance[str(year)]={"trainHorse":training,
            "eligibleFullVenueDays":len(eligible),"targetRawRaces":raw}
        excluded[str(year)]=bad
        print("TWO_YEAR_HORSE_MODEL_YEAR",json.dumps({
            "year":year,**yearProvenance[str(year)],"excluded":bad},ensure_ascii=False),flush=True)
        if year==2026:
            # Keep BOTH actually fitted first-stage models for reproducible
            # offline inference of future pre-result runner feature vectors.
            ranker2026,top3model2026=horse
        else:
            del horse
    # Each candidate market is trained with out-of-year horse scores only.
    x24,pay24,hit24,_=structural.build_rows(years[2024],tickets,"ranker_only")
    x25,pay25,hit25,_=structural.build_rows(years[2025],tickets,"ranker_only")
    x26,_,_,meta26=structural.build_rows(years[2026],tickets,"ranker_only")
    if x24.shape[1]!=x25.shape[1] or x24.shape[1]!=x26.shape[1]:
        raise RuntimeError("TICKET_FEATURE_DIMENSIONS_CHANGED")
    print("TWO_YEAR_JRA_PAYOUT_MODEL_ROWS",json.dumps({
        "train2024":len(x24),"train2025":len(x25),"score2026":len(x26),
        "featureCount":x24.shape[1]},ensure_ascii=False),flush=True)
    models={}
    # Only 2024+2025 pooled is the primary hypothesis; 2024-only reference
    # is logged for understanding, not for hindsight selection.
    for name,xx,pay,hit in (
      ("ranker_only_2024_payout_head",x24,pay24,hit24),
      (PRIMARY,np.concatenate((x24,x25),axis=0),
       np.concatenate((pay24,pay25)),np.concatenate((hit24,hit25))),
    ):
        p,positive,priors=structural.fit_hurdle(xx,pay,hit)
        scores=structural.score_rows(x26,meta26,(p,positive),priors)
        output=structural.selected_portfolio(years[2026],scores,tickets)
        if name==PRIMARY:
            import joblib
            MODEL_OUT.parent.mkdir(parents=True,exist_ok=True)
            joblib.dump({
                "researchOnly":True,
                "notProvenProfitablyForward":True,
                "cannotRunInCloudflareWorkersWithoutPort":True,
                "horsePredictionFittedThrough":"2025-12-28",
                "ticketPayoutLabelsFittedThrough":"2025-12-28",
                "horseFeatureCount":56,
                "ticketFeatureCount":int(xx.shape[1]),
                "probabilityNormalization":"within_race_LambdaRank_softmax_temp_1.4",
                "horseRanker":ranker2026,
                "horseTop3":top3model2026,
                "ticketHits":p,
                "ticketConditionalPaidMultiplier":positive,
                "typeBaseRatePriors":priors,
                "fixedRaceBudgetYen":2000,
                "researchHistoricalFinalOddsUsed":False,
                "t15InputProven":False,
                "2026OutcomesUsedToTrain":False,
            },MODEL_OUT,compress=3)
            print("FROZEN_POOLED_2026_MODEL_WEIGHTS_SAVED",
                json.dumps({"path":str(MODEL_OUT.relative_to(ROOT)),
                 "bytes":MODEL_OUT.stat().st_size,
                 "runnerFeatures":56,"ticketFeatures":int(xx.shape[1]),
                 "notProductionPromotable":True}),flush=True)
        models[name]={
          "sameEligibleVenueDayPoolAsOtherModel":True,
          "selectedRaceIdsMayDifferBetweenModels":True,
          "trainedTicketRows":len(xx),"features":xx.shape[1],
          "monthlyActualJraPayout":output["byMonth"],
          "metrics":output["metrics"],"eligibleVenueDays":output["validVenueDays"],
          "notBet":True}
        print("TWO_YEAR_FROZEN_2026_REAL_JRA_PAIRED",json.dumps({
           "model":name,"metrics":output["metrics"],
           "eligibleVenueDays":output["validVenueDays"]},ensure_ascii=False),flush=True)
        del p,positive
    a=models[PRIMARY]["metrics"]
    b=models["ranker_only_2024_payout_head"]["metrics"]
    # Race selectors can differ per model, so do NOT wrongly claim that
    # the selected race IDs are common: both share the same full venue-day
    # evaluation pool and tickets/return within each policy are paired.
    if not a["races"] or not b["races"]:raise RuntimeError("INVALID_TARGET_COHORT")
    report={"classification":"RESEARCH_CHRONOLOGICAL_REAL_2026_JRA_NOT_T15",
       "initialUserCriterion":"hitRate>=20, actual JRA payout ROI>100, robust if largest outlier removed",
       "primaryFrozenFrom2025Research":PRIMARY,
       "2026OutcomesNeverUsedAsTrainingLabelsOrModelChoice":True,
       "2025PreviousResearchLookaheadWarning":True,
       "2026DataPreviouslyInspectedByOtherResearch":True,
       "runnerInputT15Proven":False,
       "betPricesKnownBeforeT15":False,
       "noHistoricalOddsUsed":True,
       "settlementSource":"2026 actual official JRA D1 6-type payout values per 100yen",
       "readOnlyD1":True,"realCashBetsPlaced":False,
       "promotionEligible":False,
       "years":yearProvenance,"cohortExclusions":excluded,
       "monthlyActualPayoutSourceCoverage":coverage,"comparedModels":models}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("TWO_YEAR_PAYOUT_HURDLE_FINAL",json.dumps({
      "primary":a,"2024OnlyBenchmark":b,
      "2026HitFloor":a["hitRacePct"]>=20,
      "2026HistoricalRoiPositive":a["roiPct"]>100,
      "largestPayoutRemovedRoiPositive":a["roiMinusLargestPayoutPct"]>100,
      "promotionEligible":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
