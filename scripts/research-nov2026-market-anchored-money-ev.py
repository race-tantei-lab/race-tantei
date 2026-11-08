#!/usr/bin/env python3
"""Market-anchored expected CASH return learner on NEW all-runner WIN tickets.

This is a new *monetary selection* architecture, not horse-accuracy research.
Candidate universe = every individually quoted runner (NO old stored bets).
Cash signal = independently modeled P(real-money-return>0)*price and/or direct
Tweedie gross payout, shrunk towards the bookmaker's normalized probability.

Chronology (strict):
    train heads 2024 -> choose purchase rules using 2025H1 *cash ROI only*
    freeze rules -> evaluate 2025H2 cash and 2026 independently
    refit payout heads through end 2025 before frozen 2026 purchase decisions.

Historical market quotations are FINAL odds, NOT verified -15-minute odds.
JRA exact official paid amount for every newly generated WIN bet is absent.
Therefore all financial amounts in this script are explicit final-odds payoff
PROXIES (a prior independent sample saw 24/7,266 actual-payout mismatches).
No production promotion permitted, even if nominal 200% appears.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-market-anchored-money-EV-2025H1-selected-2025H2-2026.json"
SEED=20261108
CASH_SIGNALS=("market_plus_20","market_plus_50","market_plus_80",
              "market_plus_100","tweedie_cash","cash_market_50","cash_market_75")
ODDS_BANDS=((1.,9999.),(1.,10.),(3.,30.),(5.,100.),(10.,300.))
MIN_CASH=(0.,.8,1.,1.1,1.25,1.5,2.)
BET_COUNTS=(1,2,3,5)
DAY_RACE_CAPS=(1,3,5,12)
BUDGETS=(500,1000,3000)
STAKES=("equal","topheavy")

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:raise RuntimeError("OFFLINE_RESEARCH_SOURCE_MISSING")
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def heads(X,paid,idx,meta,through):
    years=np.asarray([int(z["date"][:4]) for z in meta])
    mask=(years[idx]>=2024)&(years[idx]<=through)
    trainX=np.asarray(X[mask],dtype=np.float32)
    payout=np.asarray(paid[mask],dtype=np.float64)
    if len(trainX)<20000 or (payout>0).sum()<1000:
        raise RuntimeError("MONEY_LABEL_YEAR_SPLIT_TOO_SMALL")
    target=(payout>0).astype(int)
    classifier=LGBMClassifier(
        n_estimators=170,learning_rate=.035,num_leaves=17,
        min_child_samples=160,reg_lambda=20.,reg_alpha=1.,
        colsample_bytree=.8,random_state=SEED,n_jobs=2,verbosity=-1)
    direct=LGBMRegressor(
        objective="tweedie",tweedie_variance_power=1.2,
        n_estimators=170,learning_rate=.035,num_leaves=17,
        min_child_samples=160,reg_lambda=20.,reg_alpha=1.,
        colsample_bytree=.8,random_state=SEED,n_jobs=2,verbosity=-1)
    # Both models use chronological training labels only; the selection
    # objective on later periods is always actual cash ROI.
    classifier.fit(trainX,target)
    direct.fit(trainX,payout)
    return classifier,direct

def money_scores(classifier,direct,F,odds,raceids,meta):
    # Full price-book win probabilities are normalized within each race.
    # Every original horse must have a positive price at intended entry.
    n=len(F)
    p=np.asarray(classifier.predict_proba(F)[:,1],dtype=np.float64)
    cash=np.asarray(direct.predict(F),dtype=np.float64)
    price=np.asarray(odds,dtype=np.float64)
    if not (len(p)==len(cash)==len(price)==len(raceids)==n):
        raise RuntimeError("CASH_FORECAST_LABEL_MISALIGNMENT")
    if np.any(price<1) or np.any(~np.isfinite(price)):
        raise RuntimeError("OFFICIAL_FINAL_QUOTES_INVALID")
    rawmarket=1/price
    # independent 2024/2025 model can be miscalibrated in absolute
    # probability, so normalize cash-positive forecast by race.
    bookp=np.empty(n,dtype=np.float64)
    fittedp=np.empty(n,dtype=np.float64)
    for rid in np.unique(raceids):
        ix=np.flatnonzero(raceids==rid)
        q=rawmarket[ix]
        bookp[ix]=q/q.sum()
        v=np.clip(p[ix],1e-8,1.)
        fittedp[ix]=v/v.sum()
    result={}
    for alpha in (.2,.5,.8,1.):
        # anchored expected JRA money (not classifier hit-rate metric)
        result[f"market_plus_{int(100*alpha)}"]=price*(
            (1-alpha)*bookp+alpha*fittedp)
    # Train-only cash return direct forecast; market 0.8 is a cash prior,
    # NOT retrospective realized return. Different shrink strengths
    # tested only via 2025 H1 ROI.
    money=np.clip(cash,0.,100.)
    prior=np.clip(price*bookp,0.,100.)
    result["tweedie_cash"]=money
    result["cash_market_50"]=.5*money+.5*prior
    result["cash_market_75"]=.75*money+.25*prior
    if set(result)!=set(CASH_SIGNALS) or any(np.any(~np.isfinite(v)) for v in result.values()):
        raise RuntimeError("MODELED_JRA_MONEY_NONFINITE")
    return result

def policies(base):
    from itertools import product
    for signal,n,(minimum,maximum),threshold,limit,alloc,budget in product(
        CASH_SIGNALS,BET_COUNTS,ODDS_BANDS,MIN_CASH,DAY_RACE_CAPS,STAKES,BUDGETS):
        if budget<n*100:continue
        yield base.BettingPolicy(signal,n,minimum,maximum,threshold,limit,alloc,budget)

def cash_test_policy(base,pre,policy,raceids,horse,odds,paid,meta,dates):
    subset={k:v for k,v in pre[policy.mode].items()
            if dates[0]<=meta[k]["date"]<dates[1]}
    rows=base.settle_with_frozen_policy(
       subset,raceids,horse,odds,paid,meta,policy)
    return base.money_metrics(rows,150)

def select_on_h1(base,pre,raceids,horse,odds,paid,meta,stride):
    top=None;search=0;valid=0;passed=0
    for p in policies(base):
        h=int.from_bytes(hashlib.blake2b(repr(asdict(p)).encode(),
                                         digest_size=8).digest(),"little")
        if h%stride:continue
        search+=1
        m=cash_test_policy(base,pre,p,raceids,horse,odds,paid,meta,
                           ("2025-01-01","2025-07-01"))
        if m["races"]<150:continue
        valid+=1
        passed+=int(m["passesHistoricalNumerical200"])
        # ALWAYS choose on 2025H1 ONLY; no 2025H2/2026 outcome inspected.
        # Prefer robust ROI, enough participating races, then hit-frequency
        # only as a prerequisite (not prediction accuracy).
        rank=(int(m["passesHistoricalNumerical200"]),
             m["minusLargestRaceRoiPct"],
             m["minusLargestTicketRoiPct"],
             m["roiPct"],int(m["hitRacePct"]>=20),m["races"])
        if top is None or rank>top[0]:top=(rank,p,m)
    if top is None:raise RuntimeError("NO_VIABLE_CASH_PORTFOLIO_2025H1")
    return top[1],top[2],{
        "monetaryPoliciesExamined":search,"validAtLeast150Races":valid,
        "H1HistoricalNominal200Pass":passed
    }

def basic_unit(base):
    # All stakes count when trimming biggest payout, using the real
    # currency accounting method already tested by archived JRA proxy.
    rows=[{"raceId":"x","date":"2025-01-01","stakeYen":1000,
           "returnYen":3000,"tickets":[{"returnYen":3000}]},
          {"raceId":"y","date":"2025-01-01","stakeYen":1000,
           "returnYen":2000,"tickets":[{"returnYen":2000}]}]
    m=base.money_metrics(rows,2)
    assert m["roiPct"]==250
    assert m["minusLargestTicketRoiPct"]==100
    assert not m["passesHistoricalNumerical200"]
    assert len(CASH_SIGNALS)==7
    assert len(list(policies(base)))>10000
    print("NEW_MARKET_ANCHORED_ACTUAL_CASH_ROI_ACCOUNTING_UNIT_OK")

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--self-test",action="store_true")
    cli.add_argument("--policy-stride",type=int,default=16)
    args=cli.parse_args()
    if os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_D1_DATABASE_ID"):
        raise RuntimeError("OFFLINE_RESEARCH_NO_D1_ALLOWED")
    if not 1<=args.policy_stride<=64:raise ValueError("MONEY_POLICY_STRIDE_INVALID")
    base=load("scripts/research-nov2026-all-runner-direct-money.py","roi_money_source")
    if args.self_test:basic_unit(base);return
    started=time.monotonic()
    hist=load("scripts/postaug-support-chronological-56feature-validation.py",
              "money_market_historical")
    calendar=hist.load_public_archive()
    histdata=hist.load_bundles(calendar)
    runner_X,win,counts,dates,offsets,winner_indexes,excluded,source_total,quotations=(
       hist.chronological_features(hist.core_module(),histdata))
    metadata=base.standalone_runner_index(histdata,counts,winner_indexes)
    F,pay,ridx,horses,prices,races=base.all_runner_money_dataset(
       runner_X,winner_indexes,counts,offsets,quotations,metadata)
    model24=heads(F,pay,ridx,races,2024)
    cash25=money_scores(*model24,F,prices,ridx,races)
    pre25=base.pre_result_candidates(cash25,prices,ridx,horses,races,2025)
    policy,from_h1,counts=select_on_h1(base,pre25,ridx,horses,prices,pay,races,args.policy_stride)
    h2=cash_test_policy(base,pre25,policy,ridx,horses,prices,pay,races,
                        ("2025-07-01","2026-01-01"))
    print("MARKET_CASH_2025_H1_FROZEN",json.dumps({
       "2025H1":from_h1,"2025H2":h2,"policy":asdict(policy),
       "search":counts},ensure_ascii=False),flush=True)
    model25=heads(F,pay,ridx,races,2025)
    cash26=money_scores(*model25,F,prices,ridx,races)
    pre26=base.pre_result_candidates(cash26,prices,ridx,horses,races,2026)
    final=cash_test_policy(base,pre26,policy,ridx,horses,prices,pay,races,
                           ("2026-01-01","2027-01-01"))
    print("NEW_MARKET_ANCHORED_CASH_2026_ROI",json.dumps({
       "2025H1":from_h1["roiPct"],"2025H2":h2["roiPct"],
       "2026":final,"policy":asdict(policy),
       "eligibility":False},ensure_ascii=False),flush=True)
    report={
      "classification":"NEW_MARKET_ANCHORED_DIRECT_CASH_MODEL_ROI_ONLY",
      "modelArchitecture":"win-market-shrunk expected cash and direct Tweedie monetary payout",
      "allBetCandidateTicketsGeneratedIndependently":True,
      "oldSelectedTicketUsed":False,
      "cashPrices":"archived FINAL win odds (NOT official T-15)",
      "actualJRAOfficialPayoutAmountsIndependentlyVerified":False,
      "already2026Known":True,
      "2024ModelTrainingOnly":True,
      "2025H1OnlyForMoneyPolicySelection":True,
      "2025H2UnchangedHoldout":True,
      "2026UnchangedOutOfTimeAfterRefit":True,
      "2025Search":counts,"selectedCashPolicy":asdict(policy),
      "2025H1ActualMoneyProxy":from_h1,
      "2025H2ActualMoneyProxy":h2,
      "2026MonetaryProxy":final,
      "allConditionsPassedIncludingOutlierRemovedAndT15":False,
      "promotionAllowed":False,
      "elapsedSeconds":round(time.monotonic()-started,2)
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("MARKET_ANCHORED_CASH_RESEARCH_REPORT_SAVED",OUT,flush=True)

if __name__=="__main__":main()
