#!/usr/bin/env python3
"""StableCash v2: NEW direct-money learner on ALL eligible runners, not old tickets.

Unlike v1, candidates are independently enumerated from EVERY active horse in
34k+ archive races: no old-model preselected combinations or old model weights.
Exact official JRA place/quinella payouts are NOT present. This study tests
only single WIN tickets with payout reconstructed from archived FINAL win odds
times ¥100 (a labelled final-odds PAYOUT PROXY; not a verified actual rt_payouts
amount). Final odds are NOT T−15. This is research, not deployable evidence.

First split: fit direct JRA monetary return (win_final_odds * winner flag)
with 2019-24 outcomes; choose cash model, race, odds, bet count and allocation
using 2025 cash payouts only. Refit through 2025, then settle 2026 Jan-Aug.
All 2026 candidates, dates and returns are frozen ahead of 2026 evaluation.
The 2026 events were previously researched, so this is not pristine forward
evidence; do not infer future 200% ROI even if the proxy passes.

No API calls, Cloudflare D1 access, production Worker/DB modifications.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np
from lightgbm import LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-all-runner-new-money-model-2025-selected-2026-proxy.json"
SEED=20261108
MODEL_MODES=("raw_tweedie","capped_tweedie","stable_min_era","blended_stability")
ODDS_WINDOWS=((1.0,9999.0),(1.0,10.0),(3.0,30.0),(5.0,100.0),(10.0,300.0))
RACE_SELECTION_COUNTS=(1,3,5,12)
BET_COUNTS=(1,2,3,5)
VALUE_THRESHOLDS=(0.,.8,1.,1.15,1.4,1.8)
STAKE_TYPES=("equal","topheavy")
BET_BUDGETS=(500,1000,3000)
MIN_VAL_RACES=500
MIN_TEST_RACES=300


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("HISTORICAL_HELPER_MISSING")
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj


def standalone_runner_index(by_date,counts,winners):
    """Reconstruct ALL pre-bet candidate race IDs; verify 56-feature alignment."""
    rows=[]
    for day in sorted(by_date):
        for b in by_date[day]:
            horses=sorted([r for r in b["runners"]
                if r.get("runnerStatus") in (None,"","active")],
                key=lambda r:r["horseNo"])
            if len(horses)<3:continue
            places={x["horseNo"]:x.get("finishPosition") for x in b["results"]}
            winners_idx=[i for i,h in enumerate(horses) if places.get(h["horseNo"])==1]
            if len(winners_idx)!=1:continue
            race=b["race"]
            rows.append({
              "raceId":str(race["raceId"]),"date":str(race["raceDate"]),
              "venue":str(race["venue"]),"raceNo":int(race["raceNo"]),
              "surface":str(race["surface"] or ""),
              "distance":int(race["distanceM"] or 0),
              "horseNos":[int(x["horseNo"]) for x in horses],
              "winnerIndex":winners_idx[0]})
    if len(rows)!=len(counts):
        raise ValueError(f"ALL_RUNNER_RACE_ALIGNMENT:{len(rows)}:{len(counts)}")
    for i,r in enumerate(rows):
        if len(r["horseNos"])!=int(counts[i]) or r["winnerIndex"]!=int(winners[i]):
            raise ValueError("HORSE_ROW_ORDER_IS_NOT_CHRONOLOGICAL")
    return rows


def all_runner_money_dataset(X,winners,counts,offsets,odds,metadata):
    """Every runner is one real final-odds quoted ¥100 WIN ticket candidate."""
    if len(odds)!=len(counts) or len(metadata)!=len(counts):
        raise ValueError("MARKET_AND_RUNNER_ALIGNMENT_FAILED")
    features=[];paid=[];race_indices=[];runner_nos=[];priced=[];kept=[]
    for ridx,meta in enumerate(metadata):
        raw=odds[ridx]
        if len(raw)!=int(counts[ridx]):raise ValueError("SINGLE_WIN_MARKET_NOT_ALL_RUNNERS")
        try:
            all_odds=np.asarray(raw,dtype=np.float64)
        except (ValueError,TypeError):
            continue
        wagerable=np.isfinite(all_odds)&(all_odds>=1.0)&(all_odds<=9999)
        w=int(winners[ridx])
        if not (0<=w<len(all_odds)):raise ValueError("UNIQUE_WINNER_MISSING")
        # Missing quotes mean this runner could not be bet on in the
        # historical snapshot. Exclude THAT runner, not all other horses.
        # If the eventual winner has no actual quoted odds, no payout
        # proxy can be constructed, so discard the entire race.
        if not wagerable[w] or int(wagerable.sum())<3:continue
        indices=np.flatnonzero(wagerable)
        arr=all_odds[wagerable]
        n=len(arr)
        inv=1/arr
        fav=float(np.min(arr))
        book=float(np.sum(inv))
        # Pre-result runner features and book quotations only; NO labels.
        odds_features=np.column_stack((
            np.log(arr),inv,np.log1p(arr)/10.,
            np.sqrt(arr)/100.,
            arr/(arr+100.),
            np.full(n,n/18.),
            np.full(n,book),
            arr/(fav+1.),
        )).astype(np.float32)
        a,b=int(offsets[ridx]),int(offsets[ridx+1])
        xx=np.hstack((X[a:b][wagerable],odds_features))
        if xx.shape!=(n,64) or not np.isfinite(xx).all():
            raise ValueError("PRODUCED_CASH_FEATURES_INVALID")
        # FINAL odds are a payout proxy; not a verified T-15 actual paid row.
        money=np.zeros(n,dtype=np.float32)
        money[indices==w]=float(all_odds[w])    # yen returned per ¥100 stake /100
        features.append(xx)
        paid.append(money)
        race_indices.extend([len(kept)]*n)
        runner_nos.extend([meta["horseNos"][int(j)] for j in indices])
        priced.extend(arr.tolist())
        kept.append(meta)
    if not features:raise RuntimeError("NO_COMPLETE_ALL_RUNNER_WIN_MARKET")
    F=np.concatenate(features)
    y=np.concatenate(paid)
    ridx=np.asarray(race_indices,dtype=np.int32)
    horse=np.asarray(runner_nos,dtype=np.int16)
    odds_arr=np.asarray(priced,dtype=np.float32)
    if len(F)!=len(y) or len(F)!=len(ridx):
        raise RuntimeError("ACTUAL_WIN_CANDIDATES_INCOMPLETE")
    if len(set(x["raceId"] for x in kept))!=len(kept):
        raise RuntimeError("DUPLICATE_RACES_IN_ACTUAL_WIN_UNIVERSE")
    return F,y,ridx,horse,odds_arr,kept


def new_money_estimator(objective,train_n:int):
    return LGBMRegressor(
       objective="tweedie",tweedie_variance_power=1.3,
       n_estimators=12 if train_n<5000 else 125,
       learning_rate=.035,
       num_leaves=11 if train_n<5000 else 19,
       min_child_samples=15 if train_n<5000 else 180,
       min_split_gain=.03,
       reg_lambda=24.,reg_alpha=1.5,
       colsample_bytree=.75,
       random_state=SEED,n_jobs=2,verbosity=-1)


@dataclass
class NewCashHeads:
    raw:LGBMRegressor
    capped:LGBMRegressor
    early:LGBMRegressor
    late:LGBMRegressor
    cap:float
    first_year:int
    last_year:int
    training_ticket_candidates:int


def fit_new_money(F,y,race_idx,meta,first_year,last_year,fast=False):
    # Exactly this calendar range is training; no target-year labels used.
    years=np.asarray([int(m["date"][:4]) for m in meta])
    races=(years>=first_year)&(years<=last_year)
    rowmask=races[race_idx]
    xx=np.asarray(F[rowmask],dtype=np.float32)
    yy=np.asarray(y[rowmask],dtype=np.float64)
    era=years[race_idx[rowmask]]
    if len(xx)<(1000 if fast else 10000) or not np.isfinite(yy).all() or np.any(yy<0):
        raise ValueError("INSUFFICIENT_MONEY_TRAINING")
    winners=yy[yy>0]
    if len(winners)<(20 if fast else 200):raise ValueError("INSUFFICIENT_MONETARY_PAYOFFS")
    # Training labels only. 95th-percentile winner return protects against
    # a single outlying payout dominating the learned cash expected value.
    cap=float(np.quantile(winners,.95))
    label_cap=np.minimum(yy,cap)
    # Split historical training races by chronological MEDIAN RACE DATE,
    # not midpoint calendar year. This balances windows even when an older
    # archive year has many missing final-odds quotes.
    recorded_days=np.asarray([m["date"] for m in meta])
    train_days=recorded_days[race_idx[rowmask]]
    div_day=sorted(set(train_days))[len(set(train_days))//2]
    early=train_days<div_day
    if early.sum()<(300 if fast else 4000) or (~early).sum()<(300 if fast else 4000):
        raise ValueError(f"DISJOINT_MONEY_ERAS_TOO_SHORT:{int(early.sum())}:{int((~early).sum())}")
    raw=new_money_estimator("raw",len(xx))
    trim=new_money_estimator("capped",len(xx))
    older=new_money_estimator("era",int(early.sum()))
    newer=new_money_estimator("era",int((~early).sum()))
    raw.fit(xx,yy)
    trim.fit(xx,label_cap)
    older.fit(xx[early],label_cap[early])
    newer.fit(xx[~early],label_cap[~early])
    return NewCashHeads(raw,trim,older,newer,cap,first_year,last_year,len(xx))


def cash_prediction(models:NewCashHeads,F):
    F=np.asarray(F,dtype=np.float32)
    forecasts=[]
    for m in (models.raw,models.capped,models.early,models.late):
        q=np.asarray(m.predict(F),dtype=np.float64)
        if not np.isfinite(q).all() or np.any(q<0):
            raise RuntimeError("NEW_CASH_PREDICTION_NONFINITE")
        forecasts.append(np.clip(q,1e-8,1e4))
    raw,cap,early,late=forecasts
    stable=np.minimum(early,late)
    era_drift=np.abs(np.log(np.maximum(early,1e-7)/np.maximum(late,1e-7)))
    blend=(.15*raw+.45*cap+.4*stable)/(1+.25*era_drift)
    return {
      "raw_tweedie":raw,"capped_tweedie":cap,
      "stable_min_era":stable,"blended_stability":blend
    }


@dataclass(frozen=True)
class BettingPolicy:
    mode:str
    bet_count:int
    odds_min:float
    odds_max:float
    min_modeled_cash:float
    max_races_per_venue_day:int
    stake_mode:str
    race_budget:int


def policies():
    from itertools import product
    for mode,bet_count,(lower,upper),threshold,limit,allocation,budget in product(
        MODEL_MODES,BET_COUNTS,ODDS_WINDOWS,VALUE_THRESHOLDS,
        RACE_SELECTION_COUNTS,STAKE_TYPES,BET_BUDGETS
    ):
        if budget<bet_count*100:continue
        yield BettingPolicy(mode,bet_count,lower,upper,threshold,limit,
                            allocation,budget)


def pre_result_candidates(cash,market_odds,race_idxs,runner_ids,metadata,year):
    """Generate all non-hindsight tickets based on every eligible runner."""
    by_mode={mode:defaultdict(list) for mode in cash}
    for i,rid in enumerate(race_idxs):
        m=metadata[int(rid)]
        if int(m["date"][:4])!=year:continue
        for mode,pred in cash.items():
            by_mode[mode][int(rid)].append((
              float(pred[i]),float(market_odds[i]),int(runner_ids[i]),int(i)))
    for mode in by_mode:
        for rid in by_mode[mode]:
            by_mode[mode][rid].sort(key=lambda r:(-r[0],r[2]))
    return by_mode


def settle_with_frozen_policy(
    precomputed:dict,race_idx,horse_num,odds,paid,m,policy:BettingPolicy
):
    selected_by_day=defaultdict(list)
    for rid,ordered in precomputed.items():
        race=m[rid]
        matches=[v for v in ordered if policy.odds_min<=v[1]<policy.odds_max]
        if len(matches)<policy.bet_count:continue
        chosen=matches[:policy.bet_count]
        if chosen[0][0]<policy.min_modeled_cash:continue
        if policy.stake_mode=="topheavy":
            stakes=[100]*len(chosen)
            stakes[0]+=policy.race_budget-sum(stakes)
        elif policy.stake_mode=="equal":
            stakes=[100*(policy.race_budget//100//len(chosen))]*len(chosen)
            for j in range(policy.race_budget//100-sum(stakes)//100):
                stakes[j]+=100
        else:raise ValueError("UNRECOGNIZED_MONEY_STAKING")
        if sum(stakes)!=policy.race_budget:
            raise AssertionError("MONEY_STAKES_NOT_CONSERVED")
        expected=sum(q[0]*stake for q,stake in zip(chosen,stakes))/policy.race_budget
        selected_by_day[(race["date"],race["venue"])].append(
            (expected,race["raceId"],chosen,stakes,race))
    records=[]
    for day,races in selected_by_day.items():
        races.sort(key=lambda q:(-q[0],q[1]))
        for expected,identifier,chosen,stakes,race in races[:policy.max_races_per_venue_day]:
            tickets=[]
            for (pred,price,horse,i),stake in zip(chosen,stakes):
                # The only lookup of return label happens AFTER policies,
                # rankings, race choices, and stakes have all been decided.
                returned=int(round(float(paid[i])*stake))
                tickets.append({"horseNo":horse,"stakeYen":stake,
                  "returnYen":returned,"archivedFinalOdds":price})
            records.append({"raceId":identifier,"date":race["date"],
               "venue":race["venue"],"modelExpectedGrossReturn":expected,
               "stakeYen":sum(stakes),
               "returnYen":sum(x["returnYen"] for x in tickets),
               "tickets":tickets})
    return records


def money_metrics(rows,min_races:int):
    if not rows:return {"races":0,"passesHistoricalNumerical200":False}
    stake=sum(r["stakeYen"] for r in rows)
    gross=sum(r["returnYen"] for r in rows)
    biggest=max(t["returnYen"] for r in rows for t in r["tickets"])
    biggest_race=max(r["returnYen"] for r in rows)
    hit=sum(r["returnYen"]>0 for r in rows)
    n=len(rows)
    months=defaultdict(lambda:[0,0,0])
    for r in rows:
        a=months[r["date"][:7]]
        a[0]+=r["stakeYen"];a[1]+=r["returnYen"];a[2]+=1
    return {
      "races":n,"stakeYen":stake,"returnYen":gross,"profitYen":gross-stake,
      "roiPct":round(gross/stake*100,4),
      "minusLargestTicketRoiPct":round((gross-biggest)/stake*100,4),
      "minusLargestRaceRoiPct":round((gross-biggest_race)/stake*100,4),
      "largestTicketReturnYen":biggest,
      "largestRaceReturnYen":biggest_race,
      "hitRaces":hit,"hitRacePct":round(hit/n*100,4),
      "months":{month:{"races":v[2],"roiPct":round(100*v[1]/v[0],4)}
                for month,v in sorted(months.items())},
      "passesHistoricalNumerical200":(
        n>=min_races and hit/n>=.2 and gross>=2*stake and
        gross-biggest>=2*stake and gross-biggest_race>=2*stake)
    }


def select_policy_by_2025(races,models,odds,horseids,race_idx,paid,metadata):
    pre=pre_result_candidates(models,odds,race_idx,horseids,metadata,2025)
    best=None
    examined=0
    eligible=0
    top_models=defaultdict(list)
    for pol in policies():
        examined+=1
        rows=settle_with_frozen_policy(
            pre[pol.mode],race_idx,horseids,odds,paid,metadata,pol)
        if len(rows)<MIN_VAL_RACES:continue
        eligible+=1
        m=money_metrics(rows,MIN_VAL_RACES)
        key=(int(m["passesHistoricalNumerical200"]),
             m["minusLargestRaceRoiPct"],m["minusLargestTicketRoiPct"],
             float(m["hitRacePct"])>=20,
             m["races"],-pol.race_budget)
        if best is None or key>best[0]:
            best=(key,pol,m)
        top_models[pol.mode].append(m["minusLargestRaceRoiPct"])
        if examined%5000==0:
            print("NEW_ALL_RUNNER_2025_MONEY_POLICY_PROGRESS",examined,
                  "eligible",eligible,flush=True)
    if best is None:raise RuntimeError("NEW_CASH_NO_VALIDATION_PORTFOLIO")
    return best[1],best[2],examined,eligible,{
       k:{"tested":len(v),"max2025TrimmedRaceROI":max(v)} for k,v in top_models.items()
    }


def self_test():
    rows=[{
        "raceId":"a","date":"2026-01-01","venue":"東京",
        "stakeYen":1000,"returnYen":4000,"tickets":[
            {"stakeYen":800,"returnYen":4000},
            {"stakeYen":200,"returnYen":0}]
    },{
        "raceId":"b","date":"2026-01-01","venue":"東京",
        "stakeYen":1000,"returnYen":3000,"tickets":[
            {"stakeYen":500,"returnYen":3000},
            {"stakeYen":500,"returnYen":0}]
    }]
    m=money_metrics(rows,2)
    assert m["stakeYen"]==2000
    assert m["returnYen"]==7000 and m["roiPct"]==350.
    assert m["minusLargestTicketRoiPct"]==150.
    assert m["minusLargestRaceRoiPct"]==150.
    assert not m["passesHistoricalNumerical200"]
    # The training target is monetary return, never rank or horse accuracy.
    rng=np.random.default_rng(SEED)
    X=np.zeros((1200,64),dtype=np.float32)
    X[:,:56]=rng.normal(size=(1200,56))
    y=np.zeros(1200,dtype=np.float32)
    y[::10]=np.clip(rng.lognormal(2,1,len(y[::10])),1,1000)
    ids=np.repeat(np.arange(100),12)
    meta=[{"date":f"202{(i//20)+0}-01-01","venue":"東京",
          "raceId":str(i)} for i in range(100)]
    result=fit_new_money(X,y,ids,meta,2020,2024,fast=True)
    pred=cash_prediction(result,X[:9])
    assert len(pred)==len(MODEL_MODES)
    assert all(len(p)==9 and np.isfinite(p).all() and (p>0).all()
               for p in pred.values())
    print("NOV2026_NO_OLD_BETS_ALL_RUNNER_DIRECT_MONETARY_LEARNER_UNIT_OK")


def main():
    if "--self-test" in sys.argv:self_test();return
    if any(os.getenv(z) for z in ("CLOUDFLARE_API_TOKEN",
                                  "CLOUDFLARE_D1_DATABASE_ID")):
        raise RuntimeError("NO_LIVE_D1_SECRETS_FOR_OFFLINE_MODEL")
    started=time.monotonic()
    hist=module("scripts/postaug-support-chronological-56feature-validation.py",
                "all_runner_offline_historical")
    calendar=hist.load_public_archive()
    bydate=hist.load_bundles(calendar)
    X,won,counts,dates,offsets,winners,excluded,source_races,archived_final_odds=(
      hist.chronological_features(hist.core_module(),bydate))
    metadata=standalone_runner_index(bydate,counts,winners)
    F,y,raceidx,horseids,odds,eligible=all_runner_money_dataset(
      X,winners,counts,offsets,archived_final_odds,metadata)
    print("NEW_ALL_RUNNER_WIN_CASH_UNIVERSE",json.dumps({
      "sourceRaces":source_races,
      "eligibleChronologicalRaces":len(counts),
      "racesWithWinnerQuoteAndAtLeastThreeQuotedHorses":len(eligible),
      "bettableWinTicketCandidatesWithRealFinalQuotes":len(y),
      "sourceRacesByYear":{str(year):sum(r["date"].startswith(str(year)) for r in eligible)
                           for year in range(2016,2027)},
      "oldPreselectedTicketRowsUsed":0,
      "sourceOddsFinalNotT15":True,
      "payoutIsFinalOddsProxyNotConfirmedRtPayouts":True,
      "excluded":excluded},ensure_ascii=False),flush=True)
    models25=fit_new_money(F,y,raceidx,eligible,2019,2024)
    predictions25=cash_prediction(models25,F)
    policy,m25,examined,elig_count,model_research=select_policy_by_2025(
      eligible,predictions25,odds,horseids,raceidx,y,eligible)
    print("NEW_ALL_RUNNER_CASH_2025_FROZEN",json.dumps({
      "policy":asdict(policy),"money":{k:v for k,v in m25.items() if k!="months"},
      "sampled":examined,"eligible":elig_count},ensure_ascii=False),flush=True)
    models26=fit_new_money(F,y,raceidx,eligible,2020,2025)
    predictions26=cash_prediction(models26,F)
    pre26=pre_result_candidates(predictions26,odds,raceidx,horseids,eligible,2026)
    purchased26=settle_with_frozen_policy(
        pre26[policy.mode],raceidx,horseids,odds,y,eligible,policy)
    m26=money_metrics(purchased26,MIN_TEST_RACES)
    print("NEW_ALL_RUNNER_CASH_2026_RESULT",json.dumps({
      "policyFrozenIn2025":asdict(policy),
      "2025ValidationROI":m25["roiPct"],
      "2025ValidationMaxPayoutExcludedROI":m25["minusLargestTicketRoiPct"],
      "2026Cash":m26},ensure_ascii=False),flush=True)
    report={
      "researchName":"NEW ALL-RUNNER DIRECT WIN-CASH JRA FINAL ODDS",
      "trainingTarget":"gross final-win-odds-derived JRA payout per 100 yen ticket incl zero",
      "oldModelPredictionsOrSelectedBetsEverUsed":False,
      "candidateGenerator":"ALL qualifying horses in each historical race",
      "yearsForInitialTrain":"2019-2024",
      "frozen2025MonetarySelection":asdict(policy),
      "2025MoneyValidation":m25,
      "monetaryModelAlternatives":list(MODEL_MODES),
      "other2025MonetaryModels":model_research,
      "2025PoliciesScored":examined,
      "2025PoliciesWithAtLeast500Bets":elig_count,
      "2026PayoutModelRetrainThrough":"2025-12-31",
      "2026Result":{"actualWinPayoutsVerified":False,"roiMetrics":m26},
      "2026RecordsAlreadyInspectedPreviously":True,
      "historicalBetMarket":"単勝 only, all runners independently enumerated",
      "2026T15OfficialBetOddsAvailable":False,
      "dataUsesArchivedFinalOdds":True,
      "returnAmountsDerivedFromFinalOddsNotVerifiedPayoutLedger":True,
      "noFutureSelectedTicketLeakage":True,
      "productionPromotionAllowed":False,
      "reason":"final odds not T15, payout ledger not verified, prior inspection of 2026",
      "elapsedSec":round(time.monotonic()-started,2)
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NEW_ALL_RUNNER_CASH_ARCHIVE_REPORT_WRITTEN",OUT,flush=True)


if __name__=="__main__":main()
