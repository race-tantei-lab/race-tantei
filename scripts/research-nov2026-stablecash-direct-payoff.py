#!/usr/bin/env python3
"""NEW model: StableCash -- direct monetary JRA returns with temporal robustness.

The objective is NOT horse-win accuracy, top-3 accuracy, log loss, or AUC.
We fit realized gross JRA cash returned per 100-yen ticket, INCLUDING LOSERS:
  1) raw Tweedie expected return over ALL winning/losing tickets,
  2) capped-profit Poisson regression, where the training-only upper cap of
     each market's paid tickets limits the influence of rare jackpots,
  3) two models independently trained on early and late historical eras.
The stable payoff forecast penalizes disagreement between earlier/later eras.
This is a structurally new objective versus the previous two-stage hurdle
P(ticket wins)*E(amount|win) and does not fit any horse-win head.

Training 2024 -> freeze candidate models + staking policy on ACTUAL 2025
JRA payoff; retrain using 2024+2025 -> settle 2026 actual JRA payoffs.
Policy may vary races/venue-day, number of bets (1..64), six bet markets,
ticket combinations, total race budget, allocation, and abstention.
Selection MUST NEVER inspect current target race payout; settlement does.
True official T-15 quotes are not available in historical archive, so this
model CANNOT be promoted even if a retrospective cash result looks high.

No main changes, no D1 writes, no real tickets purchased. Historical D1
reads are protected before 22:00 JST to preserve race-day free quota.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from lightgbm import LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"analysis-results/nov2026-new-stablecash-direct-JRA-return-result.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
MODEL_MODES=("raw_cash","capped_cash","era_min_cash","stable_cash","stable_aggressive_cash")
RANDOM_SEED=20261108


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:
        raise RuntimeError("REQUIRED_RESEARCH_DEPENDENCY_MISSING:"+path)
    result=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=result
    spec.loader.exec_module(result)
    return result


@dataclass
class StableCash:
    raw:LGBMRegressor
    capped:LGBMRegressor
    era_early:LGBMRegressor
    era_late:LGBMRegressor
    market_caps:dict[str,float]
    market_mean:dict[str,float]
    market_rows:dict[str,int]
    trained_first_date:str
    trained_last_date:str
    labeled_train_rows:int


def cash_estimator(kind:str,fast:bool):
    config=dict(
      n_estimators=12 if fast else 150,
      learning_rate=.045, num_leaves=9 if fast else 17,
      min_child_samples=15 if fast else 120,
      reg_lambda=18.0,reg_alpha=1.0,
      colsample_bytree=.8,random_state=RANDOM_SEED,
      n_jobs=2,verbosity=-1
    )
    if kind=="raw":
        return LGBMRegressor(objective="tweedie",tweedie_variance_power=1.25,**config)
    if kind in ("capped","era"):
        return LGBMRegressor(objective="poisson",**config)
    raise ValueError("UNRECOGNIZED_CASH_MODEL_FAMILY")


def fit_stable_cash(
    X:np.ndarray,payout100:np.ndarray,metadata:list,fast:bool=False
)->StableCash:
    """Fit only chronological TRAINING JRA monetary outcome labels.

    Historical regime heads are fit to disjoint chronological eras.
    Same-period outcome data is never touched by the evaluation scorer.
    """
    X=np.asarray(X,dtype=np.float32)
    paid=np.asarray(payout100,dtype=np.float64)
    if X.ndim!=2 or X.shape[1]!=40 or len(paid)!=len(X) or len(metadata)!=len(X):
        raise ValueError("JRA_CASH_TRAINING_MATRIX_INVALID")
    if len(X)<600 or not np.isfinite(X).all() or not np.isfinite(paid).all() or np.any(paid<0):
        raise ValueError("INSUFFICIENT_OR_INVALID_JRA_CASH_TRAINING")
    if not np.allclose(X[:,:6].sum(axis=1),1):
        raise ValueError("MARKET_TYPES_NOT_EXCLUSIVE")
    days=[str(day[0]) for day,_,_ in metadata]
    if days!=sorted(days):
        raise ValueError("CASH_TRAINING_MUST_BE_CHRONOLOGICAL")
    unique_days=sorted(set(days))
    if len(unique_days)<8:
        raise ValueError("TOO_FEW_DISJOINT_CASH_TRAINING_DATES")
    midpoint=unique_days[len(unique_days)//2]
    early=np.asarray([day<midpoint for day in days],dtype=bool)
    if not fast and (int(early.sum())<1000 or int((~early).sum())<1000):
        raise RuntimeError("EARLY_AND_LATE_MONETARY_FOLDS_TOO_SMALL")
    # Market-specific payout caps are from train-winning tickets only.
    multipliers=paid/100.0
    caps={}; means={}; counts={}
    capped=np.empty(len(X),dtype=np.float64)
    all_positive=multipliers[paid>0]
    if len(all_positive)<(2 if fast else 100):
        raise RuntimeError("REAL_JRA_ACTUAL_PAID_EVENTS_TOO_SPARSE")
    fallback_cap=max(1.,float(np.quantile(all_positive,.95)))
    for i,market in enumerate(MARKETS):
        select=X[:,i]>.5
        win=select&(paid>0)
        # The historical selected-bet archive can contain fewer winners in
        # exotic market types. Never hallucinate labels: use a documented
        # TRAINING-ONLY pooled fallback, with zero confidence on empty types.
        if int(win.sum())<(2 if fast else 30):
            cap=fallback_cap
        else:
            cap=max(1.,float(np.quantile(multipliers[win],.95)))
        capped[select]=np.minimum(multipliers[select],cap)
        caps[market]=cap
        means[market]=float(np.mean(capped[select])) if np.any(select) else 0.0
        counts[market]=int(select.sum())
    # Every race contributes equal total weight regardless of field size or
    # count of horse combinations; prevents triple-ticket pool dominance.
    keys=[(str(day[0]),str(r["raceId"])) for day,r,_ in metadata]
    repeats=Counter(keys)
    weights=np.asarray([1/repeats[k] for k in keys],dtype=np.float32)
    weights/=float(np.mean(weights))
    raw=cash_estimator("raw",fast)
    trim=cash_estimator("capped",fast)
    earlier=cash_estimator("era",fast)
    later=cash_estimator("era",fast)
    raw.fit(X,multipliers,sample_weight=weights)
    trim.fit(X,capped,sample_weight=weights)
    earlier.fit(X[early],capped[early],sample_weight=weights[early])
    later.fit(X[~early],capped[~early],sample_weight=weights[~early])
    return StableCash(
      raw,trim,earlier,later,caps,means,counts,
      unique_days[0],unique_days[-1],len(X)
    )


def cash_scores(fit:StableCash,X:np.ndarray)->dict[str,np.ndarray]:
    """Direct E[returned yen / invested yen] and time-fold robustness."""
    X=np.asarray(X,dtype=np.float32)
    if X.ndim!=2 or X.shape[1]!=40 or not np.isfinite(X).all():
        raise ValueError("INVALID_JRA_CASH_INFERENCE_FEATURES")
    def forecast(m):
        val=np.asarray(m.predict(X),dtype=np.float64)
        if not np.isfinite(val).all() or np.any(val<0):
            raise RuntimeError("MONETARY_MODEL_NONFINITE")
        return np.clip(val,1e-8,1000)
    raw=forecast(fit.raw)
    cap=forecast(fit.capped)
    early=forecast(fit.era_early)
    late=forecast(fit.era_late)
    # The minimum of disjoint train eras punishes recent-only jackpot regimes.
    era_min=np.minimum(early,late)
    disagreement=np.abs(np.log(np.maximum(early,1e-8)/np.maximum(late,1e-8)))
    # Explicitly suppress unstable past-profit signal and single-tail jumps.
    stable=(.15*raw+.50*cap+.35*era_min)/(1+.2*disagreement)
    aggressive=(.35*raw+.35*cap+.30*era_min)/(1+.10*disagreement)
    # Market priors arise only from the earlier TRAINING payouts.
    market_id=np.argmax(X[:,:6],axis=1)
    market_avg=np.asarray([fit.market_mean[MARKETS[int(i)]] for i in market_id])
    n=np.asarray([fit.market_rows[MARKETS[int(i)]] for i in market_id])
    shrink=n/(n+4000)
    candidates={
      "raw_cash":raw,"capped_cash":cap,"era_min_cash":era_min,
      "stable_cash":stable,"stable_aggressive_cash":aggressive
    }
    out={}
    for name,pred in candidates.items():
        adj=shrink*pred+(1-shrink)*market_avg
        if not np.isfinite(adj).all() or np.any(adj<0):
            raise RuntimeError("CASH_FORECAST_ADJUSTMENT_FAILED")
        out[name]=np.clip(adj,1e-8,1000)
    return out


def by_race_scores(X:np.ndarray,metadata:list,model:StableCash,mode:str)->dict:
    allm=cash_scores(model,X)
    if mode not in allm:raise ValueError("UNKNOWN_RETURN_MODEL_MODE")
    value=allm[mode]
    by=defaultdict(list)
    for i,(day,r,ticket) in enumerate(metadata):
        # ticket[3] is the ACTUAL paid JRA payout, intentionally transferred
        # to the evaluator only. None of the X columns reads ticket[3].
        stake_return=int(ticket[3])
        kind=str(ticket[0][0])
        if kind!=MARKETS[int(np.argmax(X[i,:6]))]:
            raise ValueError("PAYOUT_CANDIDATE_MARKET_NOT_ALIGNED")
        by[(day,str(r["raceId"]))].append({
          "key":ticket[0],
          "riskAdjustedE":float(value[i]),
          # The external flexible selector optionally ranks by a 'hitP'
          # key; treat this as scaled cash-confidence proxy, NOT a true
          # hit-probability forecast or model performance measure.
          "hitP":float(np.clip(value[i]/(model.market_caps[kind]+1),1e-6,.99)),
          "payout100":stake_return
        })
    return by


def exact_roi_portfolio(engine,groups,scores,policies,minimum:int):
    """Discover on an earlier year. Report EXACT original-stake max trimming."""
    trials=[]
    for ix,p in enumerate(policies):
        selected,missed=engine.select(groups,scores,p)
        m=engine.summarize(selected,len(groups))
        if m["races"]<minimum:continue
        metric={
          "roi":m["roiPct"],
          "singleTicketTrim":m["trimLargestTicketRoiPct"],
          "singleRaceTrim":m["trimLargestRaceRoiPct"],
          "hit":m["hitRacePct"],
          "races":m["races"],
          "covered":m["venueDayCoveragePct"] or 0
        }
        trials.append((p,m,metric))
        if ix%1000==0:print("NEW_CASH_POLICY_EXPLORE",ix,len(policies),flush=True)
    trials.sort(key=lambda x:(
      int(engine.robust_numeric_gate(x[1],minimum)),
      x[2]["singleRaceTrim"],
      x[2]["singleTicketTrim"],
      x[2]["hit"]>=20,
      x[2]["covered"],
      x[2]["races"],
      -x[0].budget),reverse=True)
    return trials


def self_test():
    rng=np.random.default_rng(RANDOM_SEED)
    days=[f"2024-07-{k:02d}" for k in range(1,13)]
    xs=[];ys=[];meta=[]
    for d in days:
        for race_no in range(1,16):
            r={"raceId":f"{d}-tokyo-{race_no:02d}"}
            for typ in range(6):
                row=np.zeros(40,dtype=np.float32)
                row[typ]=1.
                row[6:]=rng.normal(0,1,34)
                # Fake ONLY for model-shape unit training, NEVER called JRA.
                prize=100*(5+typ) if rng.random()<(.10+.02*typ) else 0
                xs.append(row);ys.append(prize)
                meta.append(((d,"東京"),r,((MARKETS[typ],(1,2)),(),.1,prize)))
    X=np.asarray(xs);p=np.asarray(ys)
    fit=fit_stable_cash(X,p,meta,fast=True)
    forecasts=cash_scores(fit,X[:23])
    assert set(forecasts)==set(MODEL_MODES)
    assert all(len(q)==23 and np.isfinite(q).all() and (q>0).all()
               for q in forecasts.values())
    q=by_race_scores(X[:24],meta[:24],fit,"stable_cash")
    assert len(q)==4 and all(len(v)==6 for v in q.values())
    # A jackpot must not influence predictions unless it is in the
    # TRAINING labels. At evaluation, changing only the settlement field
    # MUST leave rankings and modeled expected cash unchanged.
    changed=[(day,r,(t[0],t[1],t[2],2_000_000)) for day,r,t in meta[:24]]
    a=by_race_scores(X[:24],changed,fit,"stable_cash")
    for key in q:
        assert [v["riskAdjustedE"] for v in q[key]]==[
          v["riskAdjustedE"] for v in a[key]]
    assert q[next(iter(q))][0]["payout100"]!=2_000_000
    assert a[next(iter(a))][0]["payout100"]==2_000_000
    print("NEW_STABLECASH_DIRECT_MONETARY_TWEEDIE_FOLD_MODEL_SELFTEST_OK")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--actual-jra",action="store_true")
    ap.add_argument("--policies",type=int,default=1200)
    ap.add_argument("--min-races",type=int,default=150)
    args=ap.parse_args()
    if args.self_test:self_test();return
    if not args.actual_jra:raise RuntimeError("REAL_JRA_PAYOUT_REPLAY_MUST_BE_EXPLICIT")
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    if now.hour<22:raise RuntimeError("CLOUDFLARE_D1_ACTUAL_JRA_RESEARCH_BLOCKED_BEFORE_22_JST")
    if not os.getenv("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("REAL_JRA_OFFICIAL_PAYOUT_READONLY_ACCESS_NOT_CONNECTED")
    if not (100<=args.policies<=12000 and 100<=args.min_races<=1000):
        raise ValueError("CASH_POLICY_SAMPLE_SIZE_INVALID")
    start=time.monotonic()
    hist=module("scripts/postaug-support-chronological-56feature-validation.py","cash_hist")
    helper=module("scripts/research-extra-trees-2024-2025-paired-jra.py","cash_jra")
    structural=module("scripts/research-structural-ranker-twohead-2025.py","cash_tickets")
    tickets=module("scripts/research-two-stage-payout-value-2024-2025.py","cash_candidate_generator")
    payout_source=module("scripts/research-payout-hurdle-pooled-2026.py","cash_payout_reader")
    engine=module("scripts/research-flexible-portfolio-search.py","cash_portfolio")
    calendar=hist.load_public_archive()
    archive=hist.load_bundles(calendar)
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=structural.top3_targets(archive)
    meta=helper.eligible_metadata(archive)
    if len(meta)!=len(counts) or len(y)!=len(t3):
        raise RuntimeError("ARCHIVED_ACTUAL_JRA_RACE_ALIGNMENT_FAILED")
    payouts,coverage=payout_source.official_paid_payouts(helper)
    period={}
    for year in (2024,2025,2026):
        horse,_=structural.fit_horse_models(X,y,t3,counts,offsets,dates,year)
        groups,bad,_=structural.year_groups(year,X,counts,dates,offsets,meta,horse,payouts)
        for day,races in groups.items():
            for r in races:
                info=calendar[r["raceId"]]
                r["surface"]=info["surface"]
                r["distanceM"]=info["distanceM"]
                r["fieldSize"]=len(r["horses"])
        period[year]=groups
        print("NEW_CASH_YEAR_OFFICIAL_GROUPS",year,len(groups),bad,flush=True)
    x24,p24,_,m24=structural.build_rows(period[2024],tickets,"ranker_only")
    x25,p25,_,m25=structural.build_rows(period[2025],tickets,"ranker_only")
    x26,_,_,m26=structural.build_rows(period[2026],tickets,"ranker_only")
    if not all(q.shape[1]==40 for q in (x24,x25,x26)):
        raise RuntimeError("CASH_FEATURE_COUNTS_CHANGED")
    candidate_policies=engine.all_policies(args.policies,seed=RANDOM_SEED)
    print("NEW_CASH_MODELS_TRAINING_REAL_JRA_PAID",len(x24),len(x25),
          len(x26),"candidatePolicies",len(candidate_policies),flush=True)
    model25=fit_stable_cash(x24,p24,m24)
    val={}
    winners=[]
    for mode in MODEL_MODES:
        score=by_race_scores(x25,m25,model25,mode)
        engine.clear_rank_cache()
        selected=exact_roi_portfolio(
          engine,period[2025],score,candidate_policies,args.min_races)
        if not selected:
            val[mode]={"status":"NO_2025_CASH_POLICY_WITH_ENOUGH_ACTUAL_RACES"}
            continue
        best=selected[0]
        val[mode]={"fittedOnly2024JraCash":True,
          "tested2025MonetaryPolicyCount":len(selected),
          "bestPolicy":vars(best[0]),"cash2025":best[1],
          "passingHistorical200Candidates":sum(
            engine.robust_numeric_gate(row[1],args.min_races) for row in selected)}
        winners.append((best[1]["trimLargestRaceRoiPct"],mode,best[0]))
        print("NEW_CASH_2025_VALIDATION_ROI",mode,json.dumps({
          "roi":best[1]["roiPct"],
          "minusLargestTicket":best[1]["trimLargestTicketRoiPct"],
          "minusLargestRace":best[1]["trimLargestRaceRoiPct"],
          "tickets":best[0].ticket_count,
          "races":best[1]["races"],"hit":best[1]["hitRacePct"]
        },ensure_ascii=False),flush=True)
    if not winners:raise RuntimeError("NO_JRA_2025_ROI_CANDIDATE")
    # CRITICAL: lock both model variant and betting policy before ANY 2026
    # payouts are touched. Monetary objective only, no horse accuracy metrics.
    winners.sort(key=lambda x:(-x[0],x[1],repr(x[2])))
    _,mode,policy=winners[0]
    model26=fit_stable_cash(
      np.concatenate((x24,x25),axis=0),
      np.concatenate((p24,p25),axis=0),
      m24+m25
    )
    final_scores=by_race_scores(x26,m26,model26,mode)
    engine.clear_rank_cache()
    rows,exclusions=engine.select(period[2026],final_scores,policy)
    evaluated=engine.summarize(rows,len(period[2026]))
    evaluated["year2026ActualRoi200AndLargestTicket200AndLargestRace200"] = (
      engine.robust_numeric_gate(evaluated,args.min_races))
    monthly=defaultdict(list)
    for r in rows:monthly[r["date"][:7]].append(r)
    bymonth={m:engine.summarize(q) for m,q in sorted(monthly.items())}
    report={
      "status":"NOV2026_NEW_DIRECT_JRA_CASH_MODEL_ACTUAL_HISTORICAL_REPLAY",
      "modelName":"StableCash v1 - Tweedie gross return / capped Poisson / 2 disjoint era minima",
      "modelIsNewNotPriorHurdleOrHorseWinModel":True,
      "modelsDirectCashMultipliers":list(MODEL_MODES),
      "target":"actual gross JRA yen returned for every 100 yen of ticket stake incl zero payout",
      "monetaryTrainYears":[2024,2025],
      "modelSelectionOn2025ActualJraOnly":True,
      "2026PaidOutcomesNotUsedToFitOrPick":True,
      "historicalResultsPreviouslyInspected":True,
      "2026PreT15OfficialOddsProven":False,
      "sourcePayoutYearMonthCoverage":coverage,
      "policySearchNumber":len(candidate_policies),
      "candidatePolicyFreedom":"0..12 races/venue-day, 1..64 tickets, 63 market subsets, variable stakes and abstention",
      "modeScores2025":val,
      "modeAndPolicyFrozenBefore2026":{"mode":mode,"policy":vars(policy)},
      "actualJra2026":evaluated,
      "monthly2026ActualJra":bymonth,
      "excludedVenueDays":exclusions,
      "realCashPurchases":False,
      "promotionAllowed":False,
      "whyNotProduction":"2026 already inspected, runner/official odds not T15, prospective robust ROI unproven",
      "elapsedSeconds":round(time.monotonic()-start,1)
    }
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NEW_STABLECASH_REAL_2026_JRA_ROI",json.dumps({
      "2015FrozenModel":mode,
      "roiPct":evaluated["roiPct"],
      "roiMinusLargestTicketPct":evaluated["trimLargestTicketRoiPct"],
      "roiMinusLargestRacePct":evaluated["trimLargestRaceRoiPct"],
      "hitRacePct":evaluated["hitRacePct"],
      "pass200":evaluated["year2026ActualRoi200AndLargestTicket200AndLargestRace200"],
      "productionAllowed":False
    },ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
