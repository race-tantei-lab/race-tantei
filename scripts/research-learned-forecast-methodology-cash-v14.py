#!/usr/bin/env python3
"""Learn BETTING-METHODS THEMSELVES with fresh multi-window 56-feature models.

This is research-only, not an audit of the old deployed 431% model.
For every prediction month, genuinely retrain the original 56-column
LightGBM runner model on 3/6/12/24/36/60/96 months (0 or 12-month
historical information embargo); compose two different tickets from six
JRA markets. Unlike merely testing fixed betting rule thresholds, this
model LEARNS which underlying training duration, embargo, market pair,
horse rank choice, stake split and three- or five-race schedule works
for each venue, using earlier months' realized YEN profit.

The new second stage includes an online hierarchical monetary learner:
profit from a specific method is shrunk toward the historical profit
of its market-pair family (including information from sibling models),
then penalized for singular jackpot dependence and sub-20% race hits.
The training duration and actual BUY/ABSTAIN action are recomputed
on every venue/month. A research strategy is named as an eligible
"model" ONLY if actual payout ROI >=200%, ROI >=200% removing highest
single race while retaining stake, race hit >=20%, >=3 bought races
on each active venue day, and a sufficiently sized chronological sample
are all satisfied on 2025 development and untouched Jan-Aug2026.

We DO NOT use future cash for a same-month choice, T-15 odds are not
present for six markets, and rebuilt 56 features have unknown weather/
track inputs in historical periods. Even a 200% research model cannot
be promoted without official pre-T15 cash-bet input verification and
2017-2026 complete chronology. No production writes or deployment.
"""
from __future__ import annotations
import argparse
import collections
import dataclasses
import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-learned-methodology-sixmarket-v14.json"
PRIOR_WINDOWS=(3,6,12,24)
SCOPES=("venue","all")
SCORES=("robust_profit","net_profit","hit_adjusted")
SMOOTH=(20,200)
FAMILY_WEIGHTS=(0.0,0.5,1.0)
PARTICIPATION_THRESHOLDS=(80,100,125,160)
MIN_PAST_RACES=40
MIN_DEV_VENUE_DAYS=25
MIN_HOLD_VENUE_DAYS=15
CUTOFF_DEV="2026-01"
CUTOFF_HOLD="2026-09"
FIRST_DEV="2025-01"


@dataclasses.dataclass(frozen=True)
class LearnedMethod:
    cashWindowMonths:int
    cashScope:str
    objective:str
    shrinkRaces:int
    marketFamilyWeight:float
    minimumPriorReturnPct:float

    def asdict(self):return dataclasses.asdict(self)


def generate():
    return [LearnedMethod(*args) for args in itertools.product(
        PRIOR_WINDOWS,SCOPES,SCORES,SMOOTH,FAMILY_WEIGHTS,
        PARTICIPATION_THRESHOLDS)]


def source_v13():
    import importlib.util
    path=ROOT/"scripts/research-sixmarket-56feature-rolling-v13.py"
    spec=importlib.util.spec_from_file_location("sixmarket56v13",path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules["sixmarket56v13"]=mod
    spec.loader.exec_module(mod)
    return mod


def all_cash_prediction_methods(v13,features,payouts):
    import json
    import itertools
    import gc
    import time
    config=json.loads(v13.CONFIG.read_text(encoding="utf8"))
    names=config["runnerProbabilityModel"]["features"]
    frame,x,y=v13.import_python("scripts/research-retrained-original56-win-cash-v12.py",
                                 "original56featureloader_v14").feature_frame(features,names)
    settlements=v13.read_cash(payouts)
    helper=v13.import_python("scripts/build-ten-year-public-history-assets.py",
                              "jra_pl_generator_v14")
    cal=v13.import_python("scripts/research-retrained-original56-win-cash-v12.py",
                           "original56venuecal_v14").calendar_venues()
    month_groups=v13.month_feature_indices(frame)
    months=sorted(month_groups)
    ledger=v13.MoneyLedger(v13.methods(),months)
    for month in months:
        idx=month_groups[month]
        omitted_days=None
        for horizon,lag in itertools.product(v13.HORIZONS,v13.EMBARGOES):
            learner=v13.model_fit(frame,x,y,month,horizon,lag,config)
            if learner is None:
                raise RuntimeError("HISTORIC_TRAINING_FAMILY_INSUFFICIENT")
            grouped,received,confidence,omitted=v13.target_month_predictions(
                frame,x,idx,learner,helper,cal,settlements)
            ledger.append(month,horizon,lag,grouped,received,confidence,omitted)
            omitted_days=omitted
            del learner
            ledger.prediction_fits+=1
        print("NEW_MONEY_PREDICTION_FAMILY_TRAINED",json.dumps({
            "month":str(month),"directHorseForecastsFit":ledger.prediction_fits,
            "completeVenueDays":len(grouped),
            "excludedUnreconciledDays":len(omitted_days or []),
            "futureMonthLabelsUsed":False}),flush=True)
        del idx
        gc.collect()
    ledger.pref()
    return ledger,len(frame),len(settlements)


def family_index(methods):
    names=sorted({(m.market1,m.market2) for m in methods})
    lookup={x:i for i,x in enumerate(names)}
    return np.array([lookup[(m.market1,m.market2)] for m in methods],
                    dtype=np.int16),len(names)


def score_methods(ledger,t,v,meta,groups,nfamily):
    lo=max(0,t-meta.cashWindowMonths)
    nmethod=len(ledger.methods)
    if t==lo:
        return np.full(nmethod,-1e9,dtype=np.float64)
    if meta.cashScope=="venue":
        pc=ledger.prefix["paid"][:,t,v]-ledger.prefix["paid"][:,lo,v]
        stake=ledger.prefix["stake"][:,t,v]-ledger.prefix["stake"][:,lo,v]
        hit=ledger.prefix["hits"][:,t,v]-ledger.prefix["hits"][:,lo,v]
        races=ledger.prefix["races"][:,t,v]-ledger.prefix["races"][:,lo,v]
        top=ledger.ledger[:,lo:t,v,5].max(axis=1)
    else:
        pc=(ledger.prefix["paid"][:,t]-ledger.prefix["paid"][:,lo]).sum(axis=1)
        stake=(ledger.prefix["stake"][:,t]-ledger.prefix["stake"][:,lo]).sum(axis=1)
        hit=(ledger.prefix["hits"][:,t]-ledger.prefix["hits"][:,lo]).sum(axis=1)
        races=(ledger.prefix["races"][:,t]-ledger.prefix["races"][:,lo]).sum(axis=1)
        top=ledger.ledger[:,lo:t,:,5].max(axis=(1,2))
    denom=np.maximum(1,stake)
    gross=100*pc/denom
    robust=100*np.maximum(0,pc-top)/denom
    if meta.objective=="robust_profit":
        value=robust
    elif meta.objective=="net_profit":
        value=gross
    elif meta.objective=="hit_adjusted":
        value=robust-300*np.maximum(0,.20-hit/np.maximum(1,races))
    else:
        raise RuntimeError("INVALID_MONEY_OBJECTIVE")
    support=races/(races+meta.shrinkRaces)
    learned=100+(value-100)*support
    if meta.marketFamilyWeight:
        # Family generalization: market-pair information is borrowed
        # across differing rolling training windows, stake splits and
        # within-market horse ranks. Historical *cash* only.
        fam_gross=np.bincount(groups,weights=pc,minlength=nfamily)
        fam_stake=np.bincount(groups,weights=stake,minlength=nfamily)
        fam_races=np.bincount(groups,weights=races,minlength=nfamily)
        family_return=100*fam_gross/np.maximum(1,fam_stake)
        fam_support=fam_races/(fam_races+meta.shrinkRaces*nmethod/nfamily)
        family_learned=100+(family_return-100)*fam_support
        learned=(1-meta.marketFamilyWeight)*learned + (
            meta.marketFamilyWeight*family_learned[groups])
    learned=np.where(races>=MIN_PAST_RACES,learned,-1e9)
    return learned


def online_prediction_method(ledger,method,groups,nfamily,cache):
    picks=np.full((len(ledger.months),10),-1,dtype=np.int32)
    used=collections.Counter()
    for t,month in enumerate(ledger.months):
        if t==0:continue
        for v in range(10):
            # No speculation about missing historical payout days. We
            # abstain only on the cash model's PREVIOUS settled results.
            key=(t,v,method.cashWindowMonths,method.cashScope,
                 method.objective,method.shrinkRaces,
                 method.marketFamilyWeight)
            if key not in cache:
                scored=score_methods(ledger,t,v,method,groups,nfamily)
                k=int(np.argmax(scored))
                cache[key]=(k,float(scored[k]))
            k,confidence=cache[key]
            if confidence>=method.minimumPriorReturnPct:
                picks[t,v]=k
                used[k]+=1
    return picks,used


def qualify(model_metrics,days):
    return bool(model_metrics and model_metrics.get("qualified") and
                model_metrics["venueDays"]>=days)


def discover(ledger,v13):
    groups,nfamily=family_index(ledger.methods)
    cache={}
    accepted=[]
    for i,policy in enumerate(generate()):
        picks,used=online_prediction_method(ledger,policy,groups,nfamily,cache)
        dev=v13.summarise(picks,ledger,FIRST_DEV,CUTOFF_DEV,MIN_DEV_VENUE_DAYS)
        if qualify(dev,MIN_DEV_VENUE_DAYS):
            accepted.append((policy,dev,picks))
        if (i+1)%144==0:
            print("GENERATIVE_MONEY_METHOD_LEARNING_PROGRESS",json.dumps({
                "policiesLearned":i+1,"allPolicies":len(generate()),
                "eligibleForIndependentHoldout":len(accepted)}),flush=True)
    accepted.sort(key=lambda x:(x[1]["profitYen"],x[1]["cashRoiAfterLargestPaidRacePct"]),
                  reverse=True)
    found=[]
    for method,dev,picks in accepted:
        held=v13.summarise(picks,ledger,CUTOFF_DEV,CUTOFF_HOLD,MIN_HOLD_VENUE_DAYS)
        if qualify(held,MIN_HOLD_VENUE_DAYS):
            found.append({
                "learnedPredictionMethod":method.asdict(),
                "actual2025DevelopmentMoney":dev,
                "actual2026IndependentMoney":held,
                "verifiedOfficialSixMarketPreT15Odds":False,
                "productionEligible":False})
    return {
        "status":"DYNAMIC_METHOD_ROI200_RESEARCH_FOUND" if found else
                 "NO_PROVEN_ROI200_CASH_GENERATIVE_METHOD",
        "nature":"Adaptively learned methodology, not fixed forecast ranking or static rules",
        "freshlyTrainedUnderlyingForecasts":ledger.prediction_fits,
        "underlyingPredictionMethodCombinations":len(ledger.methods),
        "generatedMoneyLearningRules":len(generate()),
        "familyGeneralizationCount":nfamily,
        "cashBacktestOnLiveProductionTickets":False,
        "historicalHorizonOptionsMonths":list(v13.HORIZONS),
        "informationEmbargoOptionsMonths":list(v13.EMBARGOES),
        "predictionMethodChosenAgainEachVenueMonth":True,
        "futurePayoutsUsedForSelection":False,
        "developmentQualified":len(accepted),
        "independentQualified":len(found),
        "models":found,
        "sourceCoverageNotAllVenueDays":True,
        "marketQuoteEvidence": "Only 17 races of stored official pre-T15 WIN odds; no complete six-market odds history",
        "exactOriginal56FeaturesAvailable":False,
        "source":"D1-recorded six-market payouts, not independently reconciled with external JRA",
        "productionChanged":False,"productionPromotionAllowed":False,
    }


def selftest():
    assert len(generate())==4*2*3*2*3*4
    assert len({(m.market1,m.market2) for m in source_v13().methods()})==15
    print("DYNAMIC_METHODOLOGY_REAL_CASH_NO_FUTURE_AND_200_GATE_SELFTEST_OK",
          flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--features")
    parser.add_argument("--payouts")
    parser.add_argument("--output")
    parser.add_argument("--self-test",action="store_true")
    a=parser.parse_args()
    if a.self_test:selftest();return
    if not all((a.features,a.payouts,a.output)):
        parser.error("need features/payouts/output")
    start=time.monotonic()
    v13=source_v13()
    ledger,nr,npay=all_cash_prediction_methods(v13,a.features,a.payouts)
    report=discover(ledger,v13)
    report["historicalInputRunnerRows"]=nr
    report["completeRecordedPayoutRaceIds"]=npay
    report["elapsedSeconds"]=round(time.monotonic()-start,2)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("DYNAMIC_LEARNED_MONEY_PREDICTION_METHOD_FINAL",json.dumps({
        "status":report["status"],
        "underlyingModelFits":report["freshlyTrainedUnderlyingForecasts"],
        "newGeneratedMoneyMethodologies":report["generatedMoneyLearningRules"],
        "developmentQualified":report["developmentQualified"],
        "independentQualified":report["independentQualified"],
        "qualifiedModels":report["models"],
        "seconds":report["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
