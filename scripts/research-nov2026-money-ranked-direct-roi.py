#!/usr/bin/env python3
"""NEW cash-ranking horse-market ticket policy, optimized ONLY for financial ROI.

Train LightGBM *ranking of actual monetary ticket returns* rather than winning-
horse accuracy or payout probability. Every active priced horse is a counter-
factual win ticket; the old model's final selected tickets are NEVER used.

2024: fit payout-ranked LightGBM monetary heads on every quoted win ticket.
2025: tune prize-tail grades, odds tilts and full-stake ticket allocation;
       select by REALIZED ROI after removing largest ticket and largest race.
2026: freeze 2025 policy and model structure, refit cash rankers through 2025,
       settle against 2026 observed race outcomes and final-odds payout proxy.

This is not yet a deployable model: missing T-15 historical prices, actual
payoff ledger for new tickets, and true independently uninspected 2026 data.
The archive WIN-market final-odds proxy usually matches actual paid WIN
payout but can differ. These limitations are non-negotiable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict,replace
from itertools import product
from pathlib import Path
import argparse
import importlib.util
import json
import hashlib
import math
import os
import sys
import time
import numpy as np
from lightgbm import LGBMRanker

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"analysis-results/nov2026-new-direct-cash-ranking-2026-roi-proxy.json"
CASH_OBJECTIVES=("cash_amount","cash_capped","cash_tail")
ODDS_TILTS=(-0.5,0.0,0.4,0.8,1.2)
ODDS_WINDOWS=((1,9999),(1,10),(3,30),(5,100),(10,300))
K_TICKETS=(1,2,3,5)
VENUE_DAY_RACES=(1,3,5,12)
CASH_THRESHOLDS=(0.,0.6,0.9,1.2,1.6,2.0)
STAKE_MODES=("equal","topheavy")
BASE_RACE_STAKE=1000
SEED=20261108

def import_module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("RESEARCH_DEPENDENCY_NOT_FOUND")
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def payout_grade(payout,mode):
    """Cash-only race ranking label. Losers are zero JRA returned cash."""
    x=np.asarray(payout,dtype=float)
    if np.any(x<0) or not np.isfinite(x).all():
        raise ValueError("INVALID_JRA_CASH_RETURN")
    if mode=="cash_capped":
        x=np.minimum(x,15)
    if mode=="cash_amount":
        breaks=(1.,2.,4.,8.,15.,30.)
    elif mode=="cash_capped":
        breaks=(1.,2.,3.,5.,8.,12.)
    elif mode=="cash_tail":
        breaks=(1.,3.,6.,12.,25.,60.)
    else:raise ValueError("UNKNOWN_MONETARY_LOSS")
    v=np.zeros(len(x),dtype=np.int32)
    win=x>0
    v[win]=1+np.searchsorted(breaks,x[win],side="right")
    assert np.max(v)<=7
    return v

def model_for_cash():
    return LGBMRanker(
       objective="lambdarank",metric="ndcg",
       label_gain=[0,1,2,5,12,30,65,130],
       n_estimators=160,learning_rate=.045,
       num_leaves=15,min_child_samples=90,reg_lambda=18.,
       reg_alpha=1.,colsample_bytree=.78,
       random_state=SEED,n_jobs=2,verbosity=-1,
    )

def fit_cash_ranker(F,pay,raceidx,meta,train_through,mode,fast=False):
    years=np.asarray([int(m["date"][:4]) for m in meta],dtype=np.int16)
    used=(years>=2024)&(years<=train_through)
    mask=used[raceidx]
    if int(mask.sum())<(500 if fast else 15000):
        raise RuntimeError("INSUFFICIENT_QUOTED_HISTORICAL_CASH_TICKETS")
    rid=raceidx[mask]
    # Each qualifying race is grouped before outcome-based monetary ranking.
    sizes=np.bincount(rid).astype(int)
    groups=sizes[sizes>0].tolist()
    if sum(groups)!=int(mask.sum()) or len(groups)<(20 if fast else 1000):
        raise RuntimeError("CASH_NDCG_GROUPS_INVALID")
    grades=payout_grade(pay[mask],mode)
    if not np.any(grades>0):
        raise RuntimeError("NO_PAID_WINNERS_TO_LEARN_MONEY")
    learner=model_for_cash()
    if fast:
        learner.set_params(n_estimators=12,num_leaves=7,min_child_samples=5)
    # NOTE real monetary payout multiplied by 100-yen stake is label, never
    # the stock horse-winner accuracy score or a future test outcome.
    learner.fit(F[mask],grades,group=groups)
    return learner,{"throughYear":train_through,"trainingTicketCandidates":int(mask.sum()),
      "trainingRaces":len(groups),"cashObjective":mode,
      "noOldSelectedTicketInputs":True}

def scored_modes(cash_models,F,odds,year,meta,raceidx):
    years=np.asarray([int(m["date"][:4]) for m in meta],dtype=np.int16)
    selection=(years[raceidx]==year)
    if selection.sum()<20000:raise RuntimeError("INSUFFICIENT_HOLDOUT_QUOTES")
    result={}
    for objective,fit in cash_models.items():
        raw=np.asarray(fit.predict(F[selection]),dtype=np.float64)
        if len(raw)!=int(selection.sum()) or not np.isfinite(raw).all():
            raise RuntimeError("NONFINITE_FROZEN_CASH_SCORE")
        # Cash-prize ranking head outputs an unbounded relative utility.
        # A clipped exponential enforces nonnegative modeled buying signal.
        cash_power=np.exp(np.clip(raw,-5,5)*.32)
        for tilt in ODDS_TILTS:
            signal=cash_power*np.power(
                np.asarray(odds[selection],dtype=np.float64),tilt)
            if not np.isfinite(signal).all():raise ValueError("NONFINITE_PAYOUT_TILT")
            key=f"{objective}|odds_exp={tilt:+.1f}"
            scored=np.zeros(len(F),dtype=np.float32)
            scored[selection]=np.asarray(np.clip(signal,1e-8,1e5),dtype=np.float32)
            result[key]=scored
    return result

def money_policies(keys):
    from types import SimpleNamespace
    # No redundant monetary stake levels: multiplying every race's full
    # allocation uniformly leaves ROI and 200% gates invariant.
    # Backtest only real purchase-legal whole ¥100 ticket stakes.
    for key,(lower,upper),betcount,threshold,nr,stake in product(
        keys,ODDS_WINDOWS,K_TICKETS,CASH_THRESHOLDS,
        VENUE_DAY_RACES,STAKE_MODES
    ):
        yield SimpleNamespace(
          mode=key,bet_count=betcount,
          odds_min=float(lower),odds_max=float(upper),
          min_modeled_cash=threshold,max_races_per_venue_day=nr,
          stake_mode=stake,race_budget=BASE_RACE_STAKE)

def choose_2025(base,predictions,ridx,horsenos,odds,pay,meta,stride):
    pre=base.pre_result_candidates(predictions,odds,ridx,horsenos,meta,2025)
    best=None;tries=0;qualified=0;positive=0
    top_by_model=defaultdict(lambda:[0,0,-999.])
    for i,p in enumerate(money_policies(tuple(predictions))):
        # Never use i % stride: product() orders max_races and stake last,
        # so e.g. stride=8 would select ONLY one-race-per-day policies and
        # wrongly reject the entire grid at 500+ race minimum.
        slot=int.from_bytes(hashlib.blake2b(
            repr(vars(p)).encode("utf-8"),digest_size=8
        ).digest(),"little")%stride
        if slot!=0:continue
        tries+=1
        rows=base.settle_with_frozen_policy(pre[p.mode],ridx,horsenos,odds,pay,meta,p)
        if len(rows)<500:continue
        qualified+=1
        m=base.money_metrics(rows,500)
        if m["passesHistoricalNumerical200"]:positive+=1
        q=top_by_model[p.mode];q[0]+=1;q[1]+=int(m["passesHistoricalNumerical200"])
        q[2]=max(q[2],m["minusLargestRaceRoiPct"])
        # Returns ONLY: no logloss/top1/other horse prediction metrics.
        metric=(
          int(m["passesHistoricalNumerical200"]),
          m["minusLargestRaceRoiPct"],
          m["minusLargestTicketRoiPct"],
          m["roiPct"],
          int(m["hitRacePct"]>=20),
          m["races"],
          -p.race_budget,
        )
        if best is None or metric>best[0]:best=(metric,p,m)
        if tries%500==0:
            print("DIRECT_CASH_2025_SEARCH",tries,"eligible",qualified,flush=True)
    if best is None:raise RuntimeError("NO_FROZEN_2025_CASH_POLICY_FOUND")
    return best,{"policyTrials":tries,"policiesWithAtLeast500Races":qualified,
      "historically2025PassingNumerical200":positive,
      "byModel":{k:{"eligible":v[0],"passed2025":v[1],"best2025TrimmedROI":v[2]}
                 for k,v in sorted(top_by_model.items())}}

def unit():
    sample=np.asarray([0,1,1.99,2,3.99,4,10,100],dtype=float)
    a=payout_grade(sample,"cash_amount")
    b=payout_grade(sample,"cash_capped")
    assert len(a)==len(b)==8 and a[0]==0 and a[-1]>0
    from types import SimpleNamespace
    policy=list(money_policies(("cash_amount|odds_exp=+0.0",)))
    assert policy and all(p.race_budget==1000 for p in policy)
    subsample=[p for p in policy if int.from_bytes(hashlib.blake2b(
        repr(vars(p)).encode("utf-8"),digest_size=8
    ).digest(),"little")%8==0]
    assert set(p.max_races_per_venue_day for p in subsample)==set(VENUE_DAY_RACES)
    assert set(p.stake_mode for p in subsample)==set(STAKE_MODES)
    assert set(p.bet_count for p in subsample)==set(K_TICKETS)
    rng=np.random.default_rng(SEED)
    X=rng.normal(size=(600,64)).astype(np.float32)
    y=np.zeros(600);y[::12]=rng.uniform(3,80,50)
    rid=np.repeat(np.arange(50,dtype=np.int32),12)
    dates=[{"date":"2024-07-06","venue":"東京","raceId":str(i)} for i in range(50)]
    m,_=fit_cash_ranker(X,y,rid,dates,2024,"cash_amount",fast=True)
    out=m.predict(X[:16])
    assert len(out)==16 and np.isfinite(out).all()
    print("DIRECT_JRA_MONEY_RANKER_TRAINING_AND_FULL_STAKE_ACCOUNTING_UNIT_OK")

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--self-test",action="store_true")
    cli.add_argument("--policy-stride",type=int,default=8)
    args=cli.parse_args()
    if args.self_test:unit();return
    if not 1<=args.policy_stride<=64:raise ValueError("INVALID_PREDECLARED_POLICY_STEP")
    if os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_D1_DATABASE_ID"):
        raise RuntimeError("THIS_STUDY_MUST_NOT_ACCESS_LIVE_CLOUDFLARE")
    start=time.monotonic()
    base=import_module("scripts/research-nov2026-all-runner-direct-money.py","cash_ranker_base")
    hist=import_module("scripts/postaug-support-chronological-56feature-validation.py","cash_ranker_hist")
    calendar=hist.load_public_archive()
    bundles=hist.load_bundles(calendar)
    X,_,counts,dates,offsets,winners,skipped,nsource,quoted=hist.chronological_features(
        hist.core_module(),bundles)
    indexed=base.standalone_runner_index(bundles,counts,winners)
    F,pay,raceidx,horse,odds,meta=base.all_runner_money_dataset(
        X,winners,counts,offsets,quoted,indexed)
    print("DIRECT_CASH_RANKING_INPUT",json.dumps({
      "pricedSingleWinCandidates":len(pay),"eligibleRaces":len(meta),
      "preselectedOldModelBetsUsed":0,
      "historicalT15Verified":False,
      "actualJraPayoutOriginalsVerified":False
    }),flush=True)
    fit25={};train25={}
    for objective in CASH_OBJECTIVES:
        fit25[objective],train25[objective]=fit_cash_ranker(
            F,pay,raceidx,meta,2024,objective)
    cash25=scored_modes(fit25,F,odds,2025,meta,raceidx)
    best,search=choose_2025(base,cash25,raceidx,horse,odds,pay,meta,
                             args.policy_stride)
    _,policy,out25=best
    print("DIRECT_CASH_RANKING_2025_CHOSEN",json.dumps({
      "rule":vars(policy),"2025RoiPct":out25["roiPct"],
      "trimmedTicketRoi":out25["minusLargestTicketRoiPct"],
      "trimmedRaceRoi":out25["minusLargestRaceRoiPct"],
      "search":{k:v for k,v in search.items() if k!="byModel"}
    }),flush=True)
    chosen_objective=policy.mode.split("|",1)[0]
    fit26,training26=fit_cash_ranker(F,pay,raceidx,meta,2025,
                                    chosen_objective)
    cash26=scored_modes({chosen_objective:fit26},F,odds,2026,meta,raceidx)
    pre26=base.pre_result_candidates(cash26,odds,raceidx,horse,meta,2026)
    sel=base.settle_with_frozen_policy(pre26[policy.mode],raceidx,horse,odds,pay,
                                      meta,policy)
    outcome=base.money_metrics(sel,300)
    print("DIRECT_CASH_RANKING_2026_FROZEN_CASH_RESULT",json.dumps({
      "policy":vars(policy),"2026":outcome,
      "validAdoption200":False},ensure_ascii=False),flush=True)
    report={
      "research":"direct financial ticket-return ranker, monetary graded labels",
      "oldPredictionsOrPreselectedBetsUsed":False,
      "source":"ALL RUNNER archived final WIN odds, 2024-2026",
      "payoutSource":"winner decimal final odds proxy (NOT actual JRA payout ledger)",
      "2026WasPreviouslyInspected":True,
      "realT15PricesAvailable":False,
      "eligibleSingleWinBetTypesOnly":True,
      "notAllSixMarkets":True,
      "fit2024CashObjectives":train25,
      "cashObjectivesTested":list(CASH_OBJECTIVES),
      "oddsBiasesTested":list(ODDS_TILTS),
      "cashPolicySearch2025":search,
      "chosen2025Policy":vars(policy),
      "2025MonetaryReturn":out25,
      "fitThrough2025Cash":training26,
      "2026MoneyResult":outcome,
      "2026NoReoptimization":True,
      "productionPromotable":False,
      "realizedTrimmedRoiRequirementPct":200,
      "elapsedSec":round(time.monotonic()-start,2)
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print("DIRECT_CASH_RANKING_REPORT_OK",OUTPUT,flush=True)

if __name__=="__main__":main()
