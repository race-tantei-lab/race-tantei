#!/usr/bin/env python3
"""Genuinely time-retrained 56-feature LightGBM, SIX bet markets, TWO tickets.

Research only; no JRA pre-T15 market-odds archive exists beyond 17 isolated
WIN races. Consequently, ticket *combination* generation here uses
Plackett-Luce conditional probabilities from a freshly fitted historical
runner model, without pretending to have official six-market pre-T15 quotes.
All monetary returns are settled on D1-stored six-market winning payouts,
only on venue-days where EVERY original preselected race has a fully
recorded six-market payout. Missing venue-days are disclosed, never
silently counted as wins/losses. This is a conditional research sample,
NOT completed full-period live evidence and NOT original-policy replication.

Per target month:
  * Retrain a fresh 56-feature runner LightGBM on 3,6,12,24,36,60,96
    preceding months; also a 12-month embargo alternative, without future
    labels. The exact original 56 columns are used, but some reconstructed
    historical input fields were unavailable; not byte-identical originals.
  * Predict all originally preselected races BEFORE using target outcomes.
  * Compose SIX distinct market tickets from predicted horse Plackett-Luce
    combinations and rank alternative candidate positions by probability.
  * Produce exactly TWO DIFFERENT JRA markets per bought race, experiment
    with 15 market pairings, 3 cash splits, 4 within-market ranks, 3 or 5
    races per participating venue-day and 2 pre-result race-priority rules.
  * Reconcile cash with D1-recorded 6-market payouts. No win-probability
    score or log-loss is used for acceptance.

Only methods with combined cash ROI >=200%, ROI >=200% after excluding the
largest paid *race* but retaining all stakes, >=20% hit *races*, >=3
bought races per active venue-day and >=25 development venue-days enter
independent 2026-01..08 testing; holdout also requires >=15 days.
2025 development outcomes may choose a method; 2026 results NEVER choose
a method. No false below-200 "model" is emitted.

NOTE: Six-market odds/quotes are not present at the time of purchase;
this is a strictly read-only retrospective *payout search*. Even a
numerical survivor would be "research only" until official pre-T15 market
odds and independent full-year 2017-2026 cash evidence are available.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import gzip
import importlib.util
import itertools
import json
import math
import os
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"config/ten-year-completed-model.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAIR_MARKETS=tuple(itertools.combinations(range(6),2))
HORIZONS=(3,6,12,24,36,60,96)
EMBARGOES=(0,12)
RANKS=(0,1,2,4)
SPLITS=((1000,1000),(1500,500),(500,1500))
SLATES=(3,5)
PRIORITIES=("high","low")
DEV_START="2025-01-01"
DEV_STOP="2026-01-01"
HOLD_END="2026-08-09"
MIN_DEV_DAYS=25
MIN_HOLD_DAYS=15
MIN_TRAIN_RUNNERS=1200
FIELDS=("paid","stake","hits","races","days","maxRacePaid")
NV=10


def import_python(path,name):
    f=ROOT/path
    spec=importlib.util.spec_from_file_location(name,f)
    if not spec or not spec.loader:raise RuntimeError("RESEARCH_IMPORT_MISSING:"+str(f))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod


@dataclasses.dataclass(frozen=True)
class Method:
    horizon: int
    embargo: int
    risk: int
    market1: str
    market2: str
    firstStake: int
    secondStake: int
    racesPerDay: int
    raceOrder: str

    def record(self):
        return dataclasses.asdict(self)


def methods():
    return [Method(h,e,r,MARKETS[a],MARKETS[b],sa,sb,slate,order)
            for h,e,r,(a,b),(sa,sb),slate,order in itertools.product(
                HORIZONS,EMBARGOES,RANKS,PAIR_MARKETS,SPLITS,SLATES,PRIORITIES)]


def read_cash(path):
    result=collections.defaultdict(lambda:collections.defaultdict(dict))
    with gzip.open(path,"rt",encoding="utf8") as src:
        for line in src:
            if not line.strip():continue
            row=json.loads(line)
            if row.get("source")!="D1_recorded_JRA_cash_unreconciled":
                raise RuntimeError("NONCANONICAL_PAYOUT_PROVENANCE")
            key=str(row["raceId"])
            market=str(row["market"])
            ticket=str(row["ticket"])
            paid=int(row["payoutYenPer100"])
            if market not in MARKETS or paid<=0:
                raise RuntimeError("INVALID_SIXMARKET_PAYOUT")
            if ticket in result[key][market]:
                raise RuntimeError("DUPLICATE_TICKET_CASH_ENTRY")
            result[key][market][ticket]=paid
    complete={}
    for rid,bet_types in result.items():
        if all(k in bet_types for k in MARKETS):
            complete[rid]=dict(bet_types)
    if len(complete)<8000:
        raise RuntimeError("SIX_MARKET_COMPLETE_RACES_MISSING")
    return complete


def model_fit(df,x,y,target_month,horizon,embargo,cfg):
    end=target_month.to_timestamp()-pd.DateOffset(months=embargo)
    start=end-pd.DateOffset(months=horizon)
    eligible=((df["date"]<end)&(df["date"]>=start)&
              (df["originalDemandSelected"]==1)).to_numpy()
    idx=np.flatnonzero(eligible)
    if len(idx)<MIN_TRAIN_RUNNERS:
        return None
    if not df.iloc[idx]["date"].max()<end:
        raise RuntimeError("FUTURE_OR_SAME_MONTH_LABEL_IN_TRAINING")
    parameters=dict(cfg["runnerProbabilityModel"]["params"])
    parameters.update(n_jobs=3,verbosity=-1)
    # Original original 500 trees, 127 leaves, 56 original feature columns.
    if parameters.get("n_estimators")!=500 or parameters.get("num_leaves")!=127:
        raise RuntimeError("ORIGINAL_MODEL_ARCHITECTURE_NOT_PRESERVED")
    model=lgb.LGBMClassifier(**parameters)
    model.fit(x[idx],y[idx])
    return model


def candidate_tickets(race_probs,horse_numbers,canonical):
    """The six markets share original production Plackett-Luce cp/positions.

    This is NOT an oracle. Ticket order uses only pre-settlement predicted
    horse probabilities. No win/payout columns are used for candidate choice.
    """
    p=np.asarray(race_probs,dtype=np.float64)
    p=np.maximum(p,1e-6)
    p/=np.sum(p)
    nums=np.asarray(horse_numbers,dtype=np.int32)
    if len(nums)<3 or len(nums)!=len(p) or len(set(nums.tolist()))!=len(nums):
        raise RuntimeError("INVALID_HORSE_CANDIDATES")
    top=np.argsort(-p,kind="stable")[:min(6,len(p))]
    confidence=np.empty((len(RANKS),6),np.float32)
    tickets=[]
    for market,kind in enumerate(MARKETS):
        choices=[]
        for local in canonical.positions(kind,len(top)):
            absolute=tuple(int(top[z]) for z in local)
            pr=float(canonical.cp(kind,absolute,p))
            if pr>0 and math.isfinite(pr):
                combo=canonical.combo(kind,absolute,nums)
                choices.append((pr,combo))
        choices.sort(key=lambda a:(-a[0],a[1]))
        if not choices:
            raise RuntimeError("ZERO_CANDIDATES_IN_MARKET:"+kind)
        per=[]
        for ir,k in enumerate(RANKS):
            val,combo=choices[min(k,len(choices)-1)]
            per.append(combo)
            confidence[ir,market]=val
        tickets.append(per)
    # tuples indexed [risk,market]
    chosen=tuple(tuple(tickets[m][r] for m in range(6))
                 for r in range(len(RANKS)))
    return chosen,confidence


def month_feature_indices(frame):
    selected=frame.loc[
        (frame["originalDemandSelected"]==1)&
        (frame["raceDate"]>=DEV_START)&
        (frame["raceDate"]<=HOLD_END)]
    if selected.empty:raise RuntimeError("NO_SELECTED_TARGET_RACES")
    group={}
    for month,positions in selected.groupby("month",sort=True).indices.items():
        # Pandas group.indices is relative to filtered frame; use absolute.
        values=selected.index.to_numpy()[positions]
        group[month]=np.asarray(values,dtype=np.int64)
    if len(group)<19:raise RuntimeError("TOO_FEW_2025_2026_TARGET_MONTHS")
    return group


def fixed_day_groups(frame,indices,calendar,cash):
    rid=frame["raceId"].to_numpy()
    dates=frame["raceDate"].to_numpy()
    groups=collections.defaultdict(dict)
    for i in indices:
        race_id=str(rid[i])
        venue=calendar.get(race_id)
        if venue is None:raise RuntimeError("UNKNOWN_ORIGINAL_FROZEN_RACE:"+race_id)
        key=(str(dates[i]),venue)
        groups[key][race_id]=True
    valid=[]
    omitted=[]
    map_venue={v:i for i,v in enumerate(
        ("東京","中山","京都","阪神","中京","新潟","福島","小倉","札幌","函館"))}
    for (date,venue),races in sorted(groups.items()):
        if len(races)!=5:
            # Historical original selection always picks five.
            raise RuntimeError(f"FROZEN_PRESELECTED_DAY_NOT_FIVE:{date}:{venue}:{len(races)}")
        if any(rid not in cash for rid in races):
            omitted.append({"day":date,"venue":venue,"missingRaceIds":[k for k in races if k not in cash]})
            continue
        valid.append((date,map_venue[venue],tuple(races)))
    return valid,omitted


def target_month_predictions(frame,x,indices,model,canonical,calendar,cash):
    pred=model.predict_proba(x[indices])[:,1]
    if not np.all(np.isfinite(pred)):
        raise RuntimeError("NONFINITE_RETRAINED_LIGHTGBM_PROBABILITY")
    rid=frame["raceId"].to_numpy()
    horses=frame["horseNoRaw"].to_numpy()
    by_race=collections.defaultdict(list)
    for pos,i in enumerate(indices):
        by_race[str(rid[i])].append((int(horses[i]),float(pred[pos])))
    # The ORIGINAL five-race selection is fixed without looking at
    # the existence or magnitude of any future payout record.
    days,omitted=fixed_day_groups(frame,indices,calendar,cash)
    race_ids=sorted({r for _,_,rows in days for r in rows})
    lookup={r:i for i,r in enumerate(race_ids)}
    score=np.zeros((len(race_ids),len(RANKS),len(MARKETS)),np.float32)
    returns=np.zeros_like(score,dtype=np.int32)
    for i,race_id in enumerate(race_ids):
        rows=by_race[race_id]
        no=[z[0] for z in rows]
        probability=[z[1] for z in rows]
        combos,conf=candidate_tickets(probability,no,canonical)
        score[i]=conf
        for r in range(len(RANKS)):
            for k,market in enumerate(MARKETS):
                returns[i,r,k]=int(cash[race_id][market].get(combos[r][k],0))
    day_indices=[(date,v,np.asarray([lookup[r] for r in rows],np.int32))
                 for date,v,rows in days]
    return day_indices,returns,score,omitted


class MoneyLedger:
    def __init__(self,variants,months):
        self.methods=variants
        self.mi={m:i for i,m in enumerate(months)}
        self.months=list(months)
        self.key_to_id={m:i for i,m in enumerate(variants)}
        self.ledger=np.zeros((len(variants),len(months),NV,len(FIELDS)),np.int64)
        self.days_omitted={}
        self.days_covered={}
        self.prediction_fits=0

    def append(self,month,horizon,embargo,dayidx,cash,probs,omitted):
        t=self.mi[month]
        self.days_omitted[month]=omitted
        self.days_covered[month]=len(dayidx)
        for risk in range(len(RANKS)):
            for pair_id,(a,b) in enumerate(PAIR_MARKETS):
                ratings=(probs[:,risk,a]+probs[:,risk,b])
                first=cash[:,risk,a]
                second=cash[:,risk,b]
                for order in PRIORITIES:
                    for slate in SLATES:
                        for date,venue,subset in dayidx:
                            signs= -ratings[subset] if order=="high" else ratings[subset]
                            ranked=subset[np.argsort(signs,kind="stable")[:slate]]
                            if len(ranked)<3:
                                raise RuntimeError("CASH_MODEL_SELECTED_UNDER_THREE_RACES")
                            for sa,sb in SPLITS:
                                method=Method(horizon,embargo,risk,MARKETS[a],MARKETS[b],
                                              sa,sb,slate,order)
                                k=self.key_to_id[method]
                                payouts=(first[ranked]*(sa//100)+second[ranked]*(sb//100))
                                row=self.ledger[k,t,venue]
                                row[0]+=int(np.sum(payouts,dtype=np.int64))
                                row[1]+=int(len(ranked)*(sa+sb))
                                row[2]+=int(np.count_nonzero(payouts))
                                row[3]+=len(ranked)
                                row[4]+=1
                                row[5]=max(int(row[5]),int(payouts.max()))

    def pref(self):
        self.prefix={}
        for key,j in (("paid",0),("stake",1),("hits",2),("races",3)):
            a=np.cumsum(self.ledger[:,:,:,j],axis=1,dtype=np.int64)
            self.prefix[key]=np.pad(a,((0,0),(1,0),(0,0)))
        return self


def summarise(selected,ledger,start,end,min_days):
    paid=stake=hit=races=days=maxp=0
    by_year=collections.defaultdict(lambda:[0]*6)
    for t,month in enumerate(ledger.months):
        if not (start<=str(month)<end):continue
        for v in range(NV):
            k=int(selected[t,v])
            if k<0:continue
            row=ledger.ledger[k,t,v]
            if row[4]==0:continue
            if row[3]<3*row[4]:
                raise RuntimeError("VENUE_DAY_THREE_RACE_GATE_BROKEN")
            paid+=int(row[0]);stake+=int(row[1]);hit+=int(row[2])
            races+=int(row[3]);days+=int(row[4]);maxp=max(maxp,int(row[5]))
            yy=month[:4];ys=by_year[yy]
            for j in range(5):ys[j]+=int(row[j])
            ys[5]=max(ys[5],int(row[5]))
    out={
        "stakeYen":stake,"receivedYen":paid,"profitYen":paid-stake,
        "hitRaces":hit,"boughtRaces":races,"venueDays":days,
        "largestPaidRaceYen":maxp,
        "cashRoiPct":round(100*paid/stake,5) if stake else None,
        "cashRoiAfterLargestPaidRacePct":round(100*(paid-maxp)/stake,5) if stake else None,
        "hitRacePct":round(100*hit/races,5) if races else None,
        "qualified":bool(stake and days>=min_days and
           paid>=2*stake+maxp and 5*hit>=races and races>=3*days)
    }
    return out


def static_choice(index,ledger):
    ar=np.full((len(ledger.months),NV),index,np.int32)
    return ar


@dataclasses.dataclass(frozen=True)
class Meta:
    months: int
    scope: str
    objective: str
    shrink: int

    def record(self):return dataclasses.asdict(self)


def meta_variants():
    return [Meta(*a) for a in itertools.product(
        (3,6,12),("venue","all"),("trim","cash","hit_protected"),(50,300))]


def online_choice(ledger,meta):
    result=np.full((len(ledger.months),NV),0,np.int32)
    for t,month in enumerate(ledger.months):
        lo=max(0,t-meta.months)
        if lo==t:continue
        for v in range(NV):
            if meta.scope=="venue":
                cash=ledger.prefix["paid"][:,t,v]-ledger.prefix["paid"][:,lo,v]
                stake=ledger.prefix["stake"][:,t,v]-ledger.prefix["stake"][:,lo,v]
                hits=ledger.prefix["hits"][:,t,v]-ledger.prefix["hits"][:,lo,v]
                n=ledger.prefix["races"][:,t,v]-ledger.prefix["races"][:,lo,v]
                biggest=ledger.ledger[:,lo:t,v,5].max(axis=1)
            else:
                cash=(ledger.prefix["paid"][:,t]-ledger.prefix["paid"][:,lo]).sum(axis=1)
                stake=(ledger.prefix["stake"][:,t]-ledger.prefix["stake"][:,lo]).sum(axis=1)
                hits=(ledger.prefix["hits"][:,t]-ledger.prefix["hits"][:,lo]).sum(axis=1)
                n=(ledger.prefix["races"][:,t]-ledger.prefix["races"][:,lo]).sum(axis=1)
                biggest=ledger.ledger[:,lo:t,:,5].max(axis=(1,2))
            original=100*cash/np.maximum(1,stake)
            robust=100*np.maximum(0,cash-biggest)/np.maximum(1,stake)
            if meta.objective=="trim":value=robust
            elif meta.objective=="cash":value=original
            else:value=robust-300*np.maximum(0,.2-hits/np.maximum(1,n))
            # Under-supported methods cannot be selected for a target month.
            stable=100+(value-100)*n/(n+meta.shrink)
            stable=np.where(n>=30,stable,-1e9)
            if stable.max()>-1e8:
                result[t,v]=int(np.argmax(stable))
    return result


def evaluate(ledger,diagnostics):
    selected=[]
    for k,method in enumerate(ledger.methods):
        s=summarise(static_choice(k,ledger),ledger,"2025-01","2026-01",MIN_DEV_DAYS)
        if s["qualified"]:
            selected.append(("base",method.record(),s,static_choice(k,ledger)))
    for meta in meta_variants():
        picks=online_choice(ledger,meta)
        s=summarise(picks,ledger,"2025-01","2026-01",MIN_DEV_DAYS)
        if s["qualified"]:
            selected.append(("adaptive",meta.record(),s,picks))
    # NO holdout results influence development filtering or ordering.
    selected.sort(key=lambda x:(x[2]["profitYen"],
                                  x[2]["cashRoiAfterLargestPaidRacePct"]),reverse=True)
    found=[]
    for family,rule,dev,picks in selected:
        forward=summarise(picks,ledger,"2026-01","2026-09",MIN_HOLD_DAYS)
        if forward["qualified"]:
            found.append({
                "family":family,"method":rule,
                "2025DiscoveryCash":dev,"2026IndependentCashThroughAug09":forward,
                "officialPreT15OddsVerified":False,
                "fullHistorical2017To2026CoverageVerified":False,
                "productionEligible":False,
            })
    return {
        "status":"RESEARCH_CASH200_TWOTICKET_FOUND" if found else
                 "NO_PROVEN_SIXMARKET_CASH200_56MODEL",
        "original56RunnerFeatureSchema":True,
        "originalFeatureStateExactReconstruction":False,
        "originalTrainingConfigurationTrees":500,
        "modelRefitsPerTargetMonth":len(HORIZONS)*len(EMBARGOES),
        "forecastHistoryMonths":list(HORIZONS),
        "informationLagMonths":list(EMBARGOES),
        "sixMarkets":list(MARKETS),
        "perRaceDistinctMarketTickets":2,
        "marketPairCount":len(PAIR_MARKETS),
        "stakeSplits":SPLITS,
        "generatedCashStrategyMethods":len(ledger.methods),
        "adaptiveMetaMethodCount":len(meta_variants()),
        "sourceCoveredVenueDaysByMonth":diagnostics["covered"],
        "sourceExcludedIncompleteVenueDaysByMonth":diagnostics["excluded"],
        "tradingUniverseRestrictedToRetainedOriginallySelectedFivePerVenueDay":True,
        "scoreSource":"Newly trained 56-feature LightGBM + original Plackett-Luce conditional horse probabilities; no actual market odds",
        "cashSource":"D1 recorded six-market payout; JRA outside reconciliation pending",
        "fullSixMarketOfficialPricesAtT15Available":False,
        "developmentWindow":"2025-01..2025-12",
        "independentWindow":"2026-01..2026-08-09",
        "developmentQualifiedCount":len(selected),
        "independentQualifiedCount":len(found),
        "models":found,
        "productionModified":False,
        "productionPromotionAllowed":False
    }


def selftest():
    from types import SimpleNamespace
    assert len(methods())==7*2*4*15*3*2*2
    assert len(meta_variants())==3*2*3*2
    dummy=SimpleNamespace()
    from unittest.mock import Mock
    c=import_python("scripts/build-ten-year-public-history-assets.py","frozen_pl_formula")
    combos,confidence=candidate_tickets([.5,.3,.15,.05],[1,4,7,9],c)
    assert len(combos)==4 and len(combos[0])==6
    assert combos[0][0]=="1"
    assert combos[0][1]=="1-4" and combos[0][2]=="1-4"
    assert confidence.shape==(4,6)
    # Money must be counted at RACE level, dropping the largest paid
    # RACE while keeping its original 2000-yen stake.
    paid=[10000,10000,10000]
    assert (sum(paid)-max(paid))/(3*2000)>2
    print("SIXMARKET_FRESH_56PL_TWOTICKET_CASH_GATE_SELFTEST_OK",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--features")
    parser.add_argument("--payouts")
    parser.add_argument("--output")
    parser.add_argument("--self-test",action="store_true")
    a=parser.parse_args()
    if a.self_test:selftest();return
    if not all([a.features,a.payouts,a.output]):parser.error("missing input or output")
    t0=time.monotonic()
    v12=import_python("scripts/research-retrained-original56-win-cash-v12.py",
                      "original_56cash_source_v13")
    pl=import_python("scripts/build-ten-year-public-history-assets.py",
                     "original_pl_ticket_generator_v13")
    config=json.loads(CONFIG.read_text(encoding="utf8"))
    features=config["runnerProbabilityModel"]["features"]
    frame,x,y=v12.feature_frame(a.features,features)
    settled=read_cash(a.payouts)
    calendar=v12.calendar_venues()
    groups=month_feature_indices(frame)
    months=list(sorted(groups))
    opts=methods()
    led=MoneyLedger(opts,months)
    excluded={}
    covered={}
    for month in months:
        rix=groups[month]
        for h,e in itertools.product(HORIZONS,EMBARGOES):
            model=model_fit(frame,x,y,month,h,e,config)
            if model is None:raise RuntimeError(f"INSUFFICIENT_HISTORICAL_TRAINING:{month}:{h}:{e}")
            dayidx,cash,probs,miss=target_month_predictions(
                frame,x,rix,model,pl,calendar,settled)
            led.append(month,h,e,dayidx,cash,probs,miss)
            del model
            led.prediction_fits+=1
        covered[str(month)]=len(dayidx)
        excluded[str(month)]=len(miss)
        print("ROLLING_RETRAINED_SIXMARKET_56_MONTH",json.dumps({
            "month":str(month),"freshModelFits":led.prediction_fits,
            "settledVenueDays":len(dayidx),
            "excludedVenueDaysDueToIncompleteCash":len(miss),
            "noFutureOutcomeInPrediction":True},ensure_ascii=False),flush=True)
    led.pref()
    result=evaluate(led,{"covered":covered,"excluded":excluded})
    result["freshModelFits"]=led.prediction_fits
    result["historyInputRows"]=len(frame)
    result["sixMarketFullySettledRaceIds"]=len(settled)
    result["elapsedSeconds"]=round(time.monotonic()-t0,2)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ROLLING_RETRAINED_SIXMARKET_56_CASH_FINAL",json.dumps({
        "status":result["status"],
        "trainedModels":result["freshModelFits"],
        "generatedPredictionMethods":result["generatedCashStrategyMethods"],
        "adaptiveMethodModels":result["adaptiveMetaMethodCount"],
        "developmentQualifiedCount":result["developmentQualifiedCount"],
        "independentQualifiedCount":result["independentQualifiedCount"],
        "onlyValidResearchModels":result["models"],
        "seconds":result["elapsedSeconds"]
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
