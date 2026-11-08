#!/usr/bin/env python3
"""Chronological broad-search for high-ROI actual JRA portfolios.

Strict chronology:
  horse 2024 scored with <=2023-trained ranking/place heads
  horse 2025 scored with <=2024-trained heads
  horse 2026 scored with <=2025-trained heads
  payout 2024 fitted -> policies discovered on actual JRA 2025 only
  payout <=2025 refitted -> identical policies evaluated on JRA 2026
NO 2026 payouts influence 2025 policy search, ticket model training or tuning.
Out-of-year evaluation is historical and 2026 outcomes were inspected by prior
studies; it is NOT blind forward validation or T-15 proven. NEVER promote on it.

Requires historical actual JRA payout query from Cloudflare D1, which is
BLOCKED until after 22:00 JST daily to protect the race-day free quota.
The offline --self-test uses no D1, no real money, and no actual results.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys


ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"analysis-results/nov2026-open-policy-search-2025-selected-2026-jra.json"

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_RESEARCH_HELPER "+path)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def guard_historical_payouts():
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    if now.hour<22:
        raise RuntimeError("REAL_JRA_D1_HEAVY_PAYOUT_REPLAY_DISABLED_UNTIL_22_JST")
    needed=("CLOUDFLARE_API_TOKEN","CLOUDFLARE_D1_DATABASE_ID","CLOUDFLARE_ACCOUNT_ID")
    missing=[key for key in needed if not os.getenv(key)]
    if missing:raise RuntimeError("EXPLICIT_HISTORICAL_READ_ONLY_CREDENTIALS_MISSING:"+",".join(missing))

def sample_top_policies(engine,groups25,scored25,candidates,howmany:int):
    scores=[]
    n=len(groups25)
    for ix,policy in enumerate(candidates):
        if ix%500==0:
            print("2025_POLICY_SEARCH",ix,"/",len(candidates),flush=True)
        rows,missing=engine.select(groups25,scored25,policy)
        metrics=engine.summarize(rows,n)
        if metrics["races"]>=howmany:
            scores.append((policy,metrics))
    scores.sort(key=lambda z:(
        int(engine.robust_numeric_gate(z[1],howmany)),
        z[1]["trimLargestRaceRoiPct"],
        z[1]["trimLargestTicketRoiPct"],
        z[1]["hitRacePct"]>=20,
        z[1]["venueDayCoveragePct"] or 0),reverse=True)
    return scores

def train_and_score(base,v2,which,Xtrain,paidtrain,hittrain,Xtest,metatest):
    if which=="global_hgb_logpayout_p95":
        m=base.fit_payout(Xtrain,paidtrain,hittrain)
        return base.estimate_payout(Xtest,metatest,m)
    if which=="six_market_lgb_logpayout_p90":
        base.fit_payout_v1=base.fit_payout
        m=v2.fit_payout_v2(base,Xtrain,paidtrain,hittrain)
        return v2.score_payout_v2(Xtest,metatest,m)
    raise ValueError("UNKNOWN_ACTUAL_FITTED_PAYOUT_MODEL")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--actual-jra-2025-2026",action="store_true")
    parser.add_argument("--policies",type=int,default=4000)
    parser.add_argument("--minimum-races",type=int,default=100)
    args=parser.parse_args()
    engine=load("scripts/research-flexible-portfolio-search.py","unrestricted_portfolio")
    if args.self_test:
        engine.self_test()
        assert not args.actual_jra_2025_2026
        print("UNCONSTRAINED_CHRONOLOGICAL_RESEARCH_ENTRY_NO_D1_OK")
        return
    if not args.actual_jra_2025_2026:raise RuntimeError("MUST_EXPLICITLY_REQUEST_ACTUAL_JRA")
    guard_historical_payouts()
    import numpy as np
    if not 100<=args.policies<=20000:raise ValueError("INVALID_NUMBER_OF_PREDECLARED_POLICIES")
    if not 50<=args.minimum_races<=1500:raise ValueError("INVALID_MINIMUM_RESEARCH_RACES")
    base=load("scripts/research-nov2026-fresh-robust200.py","unrestricted_base")
    v2=load("scripts/research-nov2026-sixmarket-hurdle-v2.py","unrestricted_sixmarket")
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","unrestricted_hist")
    payouts_mod=load("scripts/research-payout-hurdle-pooled-2026.py","unrestricted_payouts")
    helper=load("scripts/research-extra-trees-2024-2025-paired-jra.py","unrestricted_official")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","unrestricted_struct")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","unrestricted_ticket")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=structural.top3_targets(archive)
    meta=helper.eligible_metadata(archive)
    if len(meta)!=len(counts) or len(X)!=len(y) or len(y)!=len(t3):
        raise ValueError("ARCHIVE_56_FEATURE_ALIGNMENT_FAILED")
    # Each historical month queried once, no synthetic odds and no D1 mutation.
    payouts,source_coverage=payouts_mod.official_paid_payouts(helper)
    years={}
    training={}
    for year in (2024,2025,2026):
        horse,info=base.fit_horse(X,y,t3,counts,offsets,dates,year)
        groups,omitted,raw=structural.year_groups(year,X,counts,dates,offsets,meta,horse,payouts)
        if not groups:raise RuntimeError("NO_COMPLETE_OFFICIAL_JRA_COHORT:"+str(year))
        years[year]=groups
        training[year]={"horse":info,"eligibleVenueDays":len(groups),
                        "excluded":omitted,"rawRaces":raw}
        print("FLEXIBLE_HORSE_FAMILY_OUT_OF_YEAR",year,training[year],flush=True)
    x24,p24,h24,_=structural.build_rows(years[2024],tickets,"ranker_only")
    x25,p25,h25,meta25=structural.build_rows(years[2025],tickets,"ranker_only")
    x26,p26,h26,meta26=structural.build_rows(years[2026],tickets,"ranker_only")
    assert x24.shape[1]==x25.shape[1]==x26.shape[1]==40
    assert len(h24)==len(p24)==len(x24)
    assert len(h25)==len(p25)==len(x25)
    assert len(h26)==len(p26)==len(x26)
    policies=engine.all_policies(args.policies)
    print("FLEXIBLE_POLICIES_PREDECLARED",len(policies),
          "search_seed",engine.SEED,flush=True)
    results={}
    for model_name in ("global_hgb_logpayout_p95","six_market_lgb_logpayout_p90"):
        # 2025 policy selection sees only genuine 2025 JRA returns.
        # The underlying candidate model was trained on 2024 JRA outcomes.
        print("START_2025_MODEL_FOR_POLICY_SEARCH",model_name,flush=True)
        scored25=train_and_score(base,v2,model_name,x24,p24,h24,x25,meta25)
        engine.clear_rank_cache()
        ranking25=sample_top_policies(engine,years[2025],scored25,policies,args.minimum_races)
        if not ranking25:
            results[model_name]={"status":"NO_2025_POLICY_WITH_ENOUGH_RACES"}
            continue
        finalists=ranking25[:8]
        # Freeze the TOP-8 entirely by 2025 only. No 2026 outcomes can
        # influence candidates or their order.
        testX=np.concatenate((x24,x25),axis=0)
        testP=np.concatenate((p24,p25))
        testH=np.concatenate((h24,h25))
        print("START_2026_FROZEN_POLICY_TEST",model_name,flush=True)
        scored26=train_and_score(base,v2,model_name,testX,testP,testH,x26,meta26)
        engine.clear_rank_cache()
        scored=[]
        for policy,validation in finalists:
            selected,missing=engine.select(years[2026],scored26,policy)
            test=engine.summarize(selected,len(years[2026]))
            test["passesHistoricalNumericGate"]=engine.robust_numeric_gate(test,args.minimum_races)
            scored.append({
              "policyFrozenOn2025":vars(policy),
              "2025DiscoveryValidation":validation,
              "2026HistoricalJraTest":test,
              "2026UnselectedVenueDays":missing
            })
        candidate=scored[0]
        results[model_name]={
          "policyCountTestedOn2025":len(policies),
          "2025PoliciesWithAdequateRaces":len(ranking25),
          "2025HistoricalGatePassingCandidateCount":sum(
            engine.robust_numeric_gate(m,args.minimum_races) for _,m in ranking25),
          "2025FrozenSelectionRule":"max robust largest-race trimmed ROI; outcomes examined ONLY in 2025",
          "2026NeverReoptimized":True,
          "frozen2025Top8EvaluatedOn2026In2025RankOrder":scored,
          "2026TopOf2025RankingPassedGate":candidate["2026HistoricalJraTest"]["passesHistoricalNumericGate"],
          "promotionAllowed":False
        }
        print("FLEXIBLE_2025_FROZEN_2026_ACTUAL_JRA",model_name,json.dumps({
          "policy":candidate["policyFrozenOn2025"],
          "2025":candidate["2025DiscoveryValidation"],
          "2026":candidate["2026HistoricalJraTest"]
        },ensure_ascii=False)[:6000],flush=True)
    report={
      "researchVersion":"nov2026-all-markets-races-tickets-stakes-policy-grid",
      "trainingHorseYears":[2024,2025,2026],
      "trainPayout2024":True,
      "2025SelectPoliciesAndTune":True,
      "payoutRefitThrough2025For2026":True,
      "2026OutcomesNeverUsedToTrainOrSelectPolicy":True,
      "2026AlreadySeenPreviously":True,
      "preT15FeatureAndOfficialOddsAvailabilityVerified":False,
      "2026ReturnsAreActualJraPayoutsNoSyntheticOdds":True,
      "modelFamiliesTested":list(results),
      "predeclaredSeed":engine.SEED,
      "sampledHypothesisCount":len(policies),
      "searchDimensions":{
        "horseModel":"LambdaRank + independent ExtraTrees winner + HGB place",
        "ticketModels":["shared HGB two-stage","six independent market LightGBM pairs"],
        "racesPerVenueDay":[0,1,2,3,4,5,7,9,12],
        "betCountPerRace":list(engine.TICKET_COUNTS),
        "betMarketSubsets":63,
        "maxTicketsPerMarket":list(engine.MARKET_CAPS),
        "stakesYen":list(engine.BET_BUDGETS),
        "stakeAllocation":list(engine.STAKES),
        "raceExpectedValueThreshold":list(engine.EV_THRESHOLDS),
        "ticketScoring":list(engine.RANK_MODES)},
      "minimumActualHitRatePct":20,
      "minimumActualRoiPct":200,
      "minimumActualRoiAfterLargestTicketRemovedPct":200,
      "minimumActualRoiAfterLargestRaceRemovedPct":200,
      "originalFullStakeRetainedInAllDenominators":True,
      "minimumDistinctRaceSampleForTest":args.minimum_races,
      "actualJraPayoutMonthlySourceCoverage":source_coverage,
      "trainingRecords":training,
      "results":results,
      "modelIsProductionAuthorized":False,
      "reasonNotAuthorized":"2026 already inspected + historical runner T15 provenance unverified"}
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FLEXIBLE_ROI200_JRA_SEARCH_DONE",json.dumps({
      "year2026Highest2025FrozenTest":{
        m:(z["frozen2025Top8EvaluatedOn2026In2025RankOrder"][0]["2026HistoricalJraTest"]
        if "frozen2025Top8EvaluatedOn2026In2025RankOrder" in z else None)
        for m,z in results.items()},
      "productionPromotable":False
    },ensure_ascii=False),flush=True)

if __name__=="__main__":main()
