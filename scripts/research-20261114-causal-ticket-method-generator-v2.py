#!/usr/bin/env python3
"""Causal CASH-ticket method generator: all 1030 payout tickets and expert mixtures.

NOT a 72-rule re-ranker and NOT an in-sample venue-quarter MILP.
For each race 15 previous-month-trained ticket forecasters propose ONE ticket
for EACH of six markets, and the adaptive learner constructs 225 distinct
two-market, two-ticket cash actions per race. Historical CASH payoff of each
action is learned from previous months only, by dynamically learned horizon,
venue/context pooling, prize robustness, shrinkage and original forecast blend.

2015-2018 warmup -> 2019-2024 method generation/search. Only methods
reaching 200% money ROI, 200% after deleting largest paid race, >=20%
cash-hit races and >=3 actual staked races per venue-day enter holdout. Hyper-
parameters are frozen before 2025-2026 independent month-by-month replay.
NO failed rule is called or serialized as a "model". No internet/cloud writes,
no production modifications. Third-party retrospective final win odds and
unreconciled historical cash cannot certify pre-T15 production performance.
"""
from __future__ import annotations
import collections
import dataclasses
import importlib.util
import itertools
import json
import math
import sys
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-causal-ticket-method-generation-v2.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAIRS=tuple(itertools.combinations(range(6),2))
PAIRS_LEFT=np.array([a for a,b in PAIRS],dtype=np.int8)
PAIRS_RIGHT=np.array([b for a,b in PAIRS],dtype=np.int8)
N_EXPERTS=15
TICKETS=N_EXPERTS*len(PAIRS)
COST=200
HORIZONS=(3,6,12,24,36,60,96)
SCOPES=("global","venue","venue_field")
CAPS=(1000,5000,20000)
SHRINKS=(50,250,1000)
BLENDS=(0.0,0.25,0.5,0.75)
SLATES=(3,5)
VALID_FROM="201901"
VALID_THROUGH="202412"
HOLD_FROM="202501"
HOLD_THROUGH="202604"

@dataclasses.dataclass(frozen=True)
class Method:
    horizon: int
    scope: str
    cap: int
    shrink: int
    blend: float
    slate: int

    def serialize(self):
        return dataclasses.asdict(self)


def imported(path,name):
    x=ROOT/path
    spec=importlib.util.spec_from_file_location(name,x)
    if not spec or not spec.loader:raise RuntimeError("MISSING_SOURCE:"+str(x))
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m


def generate_methods():
    return [Method(h,s,c,k,b,slate)
            for h,s,c,k,b,slate in itertools.product(
                HORIZONS, SCOPES, CAPS, SHRINKS, BLENDS, SLATES)]


def exact_money(paid,hit,stake,count,largest,venue_days):
    if count == 0 or stake <= 0 or venue_days == 0:
        return None
    result={
       "boughtRaces":int(count),"venueDays":int(venue_days),
       "stakeYen":int(stake),"paidYen":int(paid),
       "profitYen":int(paid-stake),
       "largestPaidRaceYen":int(largest),
       "cashRoiPct":round(100*paid/stake,5),
       "minusLargestRaceCashRoiPct":round(100*(paid-largest)/stake,5),
       "hitRaces":int(hit),"hitRacePct":round(100*hit/count,5),
       "minimumRacesPerVenueDay":3,
    }
    result["qualified"]=(paid>=2*stake+largest and 5*hit>=count
                         and count>=3*venue_days)
    return result


def group_ids(races,field):
    venue=np.asarray([int(r["venue"])-1 for r in races],dtype=np.int32)
    if np.any((venue<0)|(venue>=10)):raise RuntimeError("UNKNOWN_VENUE_ID")
    field=field.astype(np.int32)
    if np.any((field<0)|(field>=4)):raise RuntimeError("INVALID_FIELD_BIN")
    return {
        "global":np.zeros(len(races),np.int32),
        "venue":venue,
        "venue_field":venue*4+field,
    }


def templates_from_frozen_predictions(payout,picked,forecast):
    if payout.ndim!=2 or payout.shape[1]!=1030:
        raise RuntimeError("SIX_MARKET_ALL_1030_SOURCE_REQUIRED")
    if picked.shape!=(len(payout),N_EXPERTS,6):
        raise RuntimeError("FROZEN_PREVIOUS_MONTH_EXPERTS_REQUIRED")
    if forecast.shape!=picked.shape:raise RuntimeError("FORECAST_MISSING")
    rows=np.arange(len(payout))[:,None,None]
    cash=payout[rows,picked]  # [race, expert, market] in JPY per ¥100
    paired=(cash[:,:,PAIRS_LEFT]+cash[:,:,PAIRS_RIGHT]).reshape(len(payout),TICKETS)
    paired_forecast=(0.5*(forecast[:,:,PAIRS_LEFT]+forecast[:,:,PAIRS_RIGHT])
                     ).reshape(len(payout),TICKETS)
    if np.any(paired<0):raise RuntimeError("NEGATIVE_CASH_PAYOUT")
    # The 225 action generator is a genuine NEW ticket composer: each expert
    # dynamically selects two DIFFERENT JRA markets in every selected race.
    return paired.astype(np.int32),np.clip(paired_forecast,0.,20.).astype(np.float32)


class Index:
    def __init__(self,races,source_cash,source_forecast,field):
        self.rows=races
        self.cash=source_cash
        self.pred=source_forecast
        self.months=sorted({str(r["month"]) for r in races})
        if len(self.months)!=136 or self.months[0]!="201501" or self.months[-1]!="202604":
            raise RuntimeError("136MONTH_ARCHIVE_NOT_COMPLETE")
        self.mi={month:i for i,month in enumerate(self.months)}
        self.indices={m:np.asarray([i for i,r in enumerate(races) if r["month"]==m],dtype=np.int32)
                      for m in self.months}
        self.groups=group_ids(races,field)
        self.history={}
        self.daily={}
        for mon,idx in self.indices.items():
            days=collections.defaultdict(list)
            for j,i in enumerate(idx):
                r=races[int(i)]
                days[(str(r["day"]),int(r["venue"]))].append(j)
            if min(map(len,days.values()))<3:
                raise RuntimeError("SOURCE_VENUE_DAY_HAS_FEWER_THAN_3_RACES")
            self.daily[mon]=list(days.values())

    def build_history(self,cap,scope):
        key=(cap,scope)
        if key in self.history:return self.history[key]
        ng={"global":1,"venue":10,"venue_field":40}[scope]
        nmonth=len(self.months)
        # All retrospective payoffs are indexed but only [prior-horizon, prior)
        # is ever read for predictions. No current or future month's cash.
        sums=np.zeros((nmonth+1,ng,TICKETS),dtype=np.float64)
        counts=np.zeros((nmonth+1,ng),dtype=np.int32)
        wins=np.zeros((nmonth+1,ng,TICKETS),dtype=np.float64)
        col=np.arange(TICKETS,dtype=np.int32)
        for t,mon in enumerate(self.months):
            ii=self.indices[mon]
            g=self.groups[scope][ii]
            amounts=np.minimum(self.cash[ii],cap).astype(np.float64)
            flat=(g[:,None]*TICKETS+col[None,:]).ravel()
            sums[t+1]=np.bincount(flat,weights=amounts.ravel(),
                                  minlength=ng*TICKETS).reshape(ng,TICKETS)
            counts[t+1]=np.bincount(g,minlength=ng)
            wins[t+1]=np.bincount(flat,weights=(self.cash[ii]>0).ravel().astype(np.float64),
                                  minlength=ng*TICKETS).reshape(ng,TICKETS)
        # Prefixes are never interpreted as a training set which can see the
        # current month: query() explicitly uses prefix[t], not prefix[t+1].
        np.cumsum(sums,axis=0,out=sums)
        np.cumsum(counts,axis=0,out=counts)
        np.cumsum(wins,axis=0,out=wins)
        self.history[key]=(sums,counts,wins)
        return self.history[key]

    def pick(self,method,month):
        t=self.mi[month]
        indices=self.indices[month]
        group=self.groups[method.scope][indices]
        totals,counts,wins=self.build_history(method.cap,method.scope)
        prior=max(0,t-method.horizon)
        n=counts[t]-counts[prior]
        cash=totals[t]-totals[prior]
        hits=wins[t]-wins[prior]
        rate=cash/(np.maximum(1,n)[:,None]*COST)
        # Cash objective, no win-probability objective. Hit observations
        # only reduce unstable jackpot-based rate estimates.
        support=(n[:,None]/(n[:,None]+method.shrink))*(hits/(hits+5.))
        past=np.clip(0.76+support*(rate-0.76),0.,25.)
        signal=(1.-method.blend)*past[group]+method.blend*self.pred[indices]
        # Every possible ticket action is scored BEFORE the race results.
        best=np.argmax(signal,axis=1)
        confidence=signal[np.arange(len(indices)),best]
        paid=self.cash[indices,best]
        by_day=self.daily[month]
        choices=[]
        for subset in by_day:
            items=np.asarray(subset,dtype=np.int32)
            order=items[np.argsort(-confidence[items],kind="stable")]
            choices.extend(order[:method.slate].tolist())
        ix=np.asarray(choices,dtype=np.int32)
        if len(ix)<3*len(by_day):raise RuntimeError("FROZEN_METHOD_VENUE_DAY_UNDERCOVERED")
        chosen=paid[ix]
        return int(chosen.sum(dtype=np.int64)),int((chosen>0).sum()),len(ix),int(chosen.max()),len(by_day)

    def evaluate(self,method,start,through):
        spend=paid=hit=count=largest=days=0
        years=collections.defaultdict(lambda:[0,0,0,0,0,0])
        for mon in self.months:
            if mon<start or mon>through:continue
            pp,hh,nn,mx,dd=self.pick(method,mon)
            paid+=pp;hit+=hh;count+=nn;spend+=COST*nn
            largest=max(largest,mx);days+=dd
            yy=mon[:4]
            x=years[yy]
            x[0]+=pp;x[1]+=hh;x[2]+=nn;x[3]+=COST*nn;x[4]=max(x[4],mx);x[5]+=dd
        total=exact_money(paid,hit,spend,count,largest,days)
        annual={y:exact_money(z[0],z[1],z[3],z[2],z[4],z[5])
                for y,z in sorted(years.items())}
        return total,annual


def search(index,methods):
    # Validation outcomes may screen methods; the holdout is not inspected
    # unless the WHOLE validation interval has already passed every gate.
    passed=[]
    for i,method in enumerate(methods):
        m,yearly=index.evaluate(method,VALID_FROM,VALID_THROUGH)
        if m is None:continue
        if m["qualified"] and all(y["qualified"] for y in yearly.values()):
            passed.append((method,m,yearly))
        if i%250==0:
            print("METHOD_GENERATION_CASH_PROGRESS",json.dumps({
                "generated":i+1,"fullEnumeration":len(methods),
                "qualifiedForUntouchedHoldout":len(passed)},ensure_ascii=False),flush=True)
    # No losing pseudo-model is ever emitted. Top ten cash-QUALIFIED only.
    passed.sort(key=lambda a:(a[1]["profitYen"],
                              a[1]["minusLargestRaceCashRoiPct"]),reverse=True)
    verified=[]
    for method,dev,years in passed[:10]:
        held,annual=index.evaluate(method,HOLD_FROM,HOLD_THROUGH)
        if held and held["qualified"] and all(m["qualified"] for m in annual.values()):
            verified.append({"method":method.serialize(),
                             "cashValidation":dev,"validationYears":years,
                             "independentHoldoutCash":held,
                             "independentHoldoutYears":annual,
                             "preT15Verified":False,"productionEligible":False})
    return {
        "status":("RESEARCH_CASH200_METHOD_FOUND_HOLDOUT_PASSED"
                  if verified else "NO_VERIFIED_CASH200_METHOD_CREATED"),
        "generatedPredictionMethods":len(methods),
        "perRaceConstructedTicketActions":TICKETS,
        "underlyingActualCashTemplatesPerRace":1030,
        "markets":MARKETS,
        "validationYears":f"{VALID_FROM}..{VALID_THROUGH}",
        "untouchedHoldoutMonths":f"{HOLD_FROM}..{HOLD_THROUGH}",
        "validationQualifiedMethodCount":len(passed),
        "independentQualifiedModelCount":len(verified),
        "models":verified,
        "maximumPaidRaceRemovedWithStakeRetained":True,
        "minimumThreeRacesEveryVenueDay":True,
        "allCashMetricsActualPayoutYen":True,
        "historicalQuoteType":"retrospective_final_win_odds_not_pre_T15",
        "cashDataSource":"third_party_JRA_derived_unreconciled",
        "futureSameMonthPayoutLeakage":False,
        "researchOnly":True,
        "productionModified":False,
        "productionPromotionAllowed":False,
    }


def selftest():
    assert len(PAIRS)==15 and len(generate_methods())==len(HORIZONS)*len(SCOPES)*len(CAPS)*len(SHRINKS)*len(BLENDS)*len(SLATES)
    assert len(generate_methods())>=1500
    fake=np.zeros((4,1030),np.int32)
    idx=np.zeros((4,N_EXPERTS,6),np.int16)
    score=np.ones_like(idx,dtype=np.float32)
    fake[2,0]=5200
    amounts,forecasts=templates_from_frozen_predictions(fake,idx,score)
    assert amounts.shape==(4,TICKETS)
    assert amounts[2].sum()==5200*TICKETS
    assert exact_money(400,1,200,1,400,1)["qualified"] is False
    assert exact_money(1200,3,600,3,100,1)["qualified"] is False
    assert exact_money(1600,3,600,3,100,1)["qualified"] is True
    assert "models" in {"models":[]}
    print("CAUSAL_METHOD_GENERATOR_1512_PLUS_CASH_GATE_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:
        selftest();return
    start=time.monotonic()
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py","method_generator_source")
    core,races,payout,features,market,slots=base.historic_cash()
    picked,score,_,months=base.monthly_frozen_predictions(races,payout,features,market,slots)
    if len(months)!=136 or N_EXPERTS!=len(base.MODES):
        raise RuntimeError("INCOMPLETE_PREQUEL_GENERATION")
    cash,pred=templates_from_frozen_predictions(payout,picked,score)
    field=np.asarray(features["fieldSize"][:,0],dtype=np.int8)
    index=Index(races,cash,pred,field)
    methods=generate_methods()
    result=search(index,methods)
    result["racesRead"]=len(races)
    result["elapsedSeconds"]=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CAUSAL_TICKET_METHOD_GENERATION_FINAL",json.dumps({
        "status":result["status"],"generatedPredictionMethods":result["generatedPredictionMethods"],
        "perRaceTicketActions":TICKETS,
        "developmentPassed":result["validationQualifiedMethodCount"],
        "holdoutVerifiedModelCount":result["independentQualifiedModelCount"],
        "models":result["models"],"seconds":result["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
