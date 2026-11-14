#!/usr/bin/env python3
"""Double-nested ONLINE CASH method-of-methods discovery, time-causal.

At date t, choose BOTH:
1. one of 672 money-ticket generators with 765 six-market cash actions,
   using any of 756 genuine earlier-month learning procedures; then
2. choose the prior-month best PROCEDURE (not the best horse or filter) among
   those 756 methods based only on *their prior already-settled cash returns*.
   Also determine cash stake via a previous-month confidence score.

This is not fitting one permanent condition on 2017-24 to apply elsewhere.
Both levels change by venue/month; model class itself is learned chronologically.
Search outer-method PARAMETERS using 2017-24, separately audit unseen
2025-26Apr. Never label below-200 as a model. Exact stake/return and
maximum SINGLE RACE removed; hit >=20% and >=3 venue-day races.
Historical third-party final win odds are not official JRA T-15 snapshots.
Research only, no deployment, no D1 or historic-bet edits.
"""
from __future__ import annotations

import collections
import dataclasses
import importlib.util
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-double-online-cash-meta-v9.json"
HORIZONS=(3,6,12,24,36,60)
SCOPES=("global","venue","mixed")
GOALS=("trim","gross","balanced","hit_floor","jackpot_penalty","cash_margin")
SHRINK=(50,400)
MIN_RACES=(30,150)
STAKE_PLANS=("flat","edge_band","high_conviction","reverse_edge")
DEV_START,DEV_END="201701","202412"
HOLD_START,HOLD_END="202501","202604"
COST_UNIT=2000
NV=10


def imported(p,name):
    f=ROOT/p
    s=importlib.util.spec_from_file_location(name,f)
    if s is None or s.loader is None:raise RuntimeError("MISSING_SOURCE:"+str(f))
    m=importlib.util.module_from_spec(s)
    sys.modules[name]=m
    s.loader.exec_module(m)
    return m


@dataclasses.dataclass(frozen=True)
class Outer:
    lookback: int
    scope: str
    objective: str
    shrink: int
    min_races: int
    stake_plan: str

    def asdict(self):
        return dataclasses.asdict(self)


def methods():
    return [Outer(*a) for a in itertools.product(
        HORIZONS,SCOPES,GOALS,SHRINK,MIN_RACES,STAKE_PLANS)]


def eligible_inner_methods(v5):
    return [m for m in v5.make_meta_methods() if m.stake_plan=="flat"]


class MethodLedger:
    def __init__(self,n_methods,account):
        self.account=account
        shape=(n_methods,len(account.months),NV)
        self.paid=np.zeros(shape,dtype=np.int64)
        self.stake=np.zeros(shape,dtype=np.int64)
        self.hit=np.zeros(shape,dtype=np.int32)
        self.races=np.zeros(shape,dtype=np.int32)
        self.biggest=np.zeros(shape,dtype=np.int64)
        self.prior_score=np.full(shape,-1e9,dtype=np.float32)
        self.chosen_base=np.zeros(shape,dtype=np.int16)
        self.months=account.months

    def fill(self,selectors,v5):
        for mi,meta in enumerate(selectors):
            for t,month in enumerate(self.months):
                for v in range(NV):
                    if self.account.days[0,t,v]==0:continue
                    base,score=v5.score_experts(self.account,t,v,meta,with_score=True)
                    c=int(self.account.cash[base,t,v])
                    h=int(self.account.hit[base,t,v])
                    nr=int(self.account.races[base,t,v])
                    mx=int(self.account.biggest[base,t,v])
                    days=int(self.account.days[base,t,v])
                    if nr<3*days or days!=int(self.account.days[0,t,v]):
                        raise RuntimeError("BASE_META_METHOD_MISSED_VENUE_DAY")
                    self.paid[mi,t,v]=c
                    self.stake[mi,t,v]=nr*COST_UNIT
                    self.hit[mi,t,v]=h
                    self.races[mi,t,v]=nr
                    self.biggest[mi,t,v]=mx
                    self.prior_score[mi,t,v]=score
                    self.chosen_base[mi,t,v]=base
            if (mi+1)%108==0:
                print("META_METHODS_CASH_LEDGER",json.dumps({
                    "completedInnerMetaMethods":mi+1,
                    "total":len(selectors),
                    "noCurrentMonthPayoutInMethodChoice":True}),flush=True)
        self.prefix_paid=np.pad(np.cumsum(self.paid,axis=1,dtype=np.int64),
                                ((0,0),(1,0),(0,0)))
        self.prefix_stake=np.pad(np.cumsum(self.stake,axis=1,dtype=np.int64),
                                 ((0,0),(1,0),(0,0)))
        self.prefix_hit=np.pad(np.cumsum(self.hit,axis=1,dtype=np.int64),
                               ((0,0),(1,0),(0,0)))
        self.prefix_races=np.pad(np.cumsum(self.races,axis=1,dtype=np.int64),
                                 ((0,0),(1,0),(0,0)))


MAX_CACHE={}
DECISION_CACHE={}


def max_before(ledger,lo,t,v,scope):
    key=(lo,t,v,scope)
    if key not in MAX_CACHE:
        if t==lo:out=np.zeros(len(ledger.paid),dtype=np.int64)
        elif scope=="venue":
            out=np.max(ledger.biggest[:,lo:t,v],axis=1)
        else:
            out=np.max(ledger.biggest[:,lo:t,:],axis=(1,2))
        MAX_CACHE[key]=out
    return MAX_CACHE[key]


def historical_score(ledger,t,v,meta):
    """All inputs are *prior* months; target t is completely excluded."""
    lo=max(0,t-meta.lookback)
    c=ledger.prefix_paid;s=ledger.prefix_stake
    h=ledger.prefix_hit;n=ledger.prefix_races
    if meta.scope=="venue":
        paid=c[:,t,v]-c[:,lo,v]
        stake=s[:,t,v]-s[:,lo,v]
        hits=h[:,t,v]-h[:,lo,v]
        races=n[:,t,v]-n[:,lo,v]
    else:
        pg=np.sum(c[:,t]-c[:,lo],axis=1,dtype=np.int64)
        sg=np.sum(s[:,t]-s[:,lo],axis=1,dtype=np.int64)
        hg=np.sum(h[:,t]-h[:,lo],axis=1,dtype=np.int64)
        ng=np.sum(n[:,t]-n[:,lo],axis=1,dtype=np.int64)
        if meta.scope=="mixed":
            paid=pg+2*(c[:,t,v]-c[:,lo,v])
            stake=sg+2*(s[:,t,v]-s[:,lo,v])
            hits=hg+2*(h[:,t,v]-h[:,lo,v])
            races=ng+2*(n[:,t,v]-n[:,lo,v])
        else:
            paid,stake,hits,races=pg,sg,hg,ng
    largest=max_before(ledger,lo,t,v,meta.scope)
    gross=100.*paid/np.maximum(1,stake)
    trim=100.*np.maximum(0,paid-largest)/np.maximum(1,stake)
    if meta.objective=="trim":
        score=trim
    elif meta.objective=="gross":
        score=gross
    elif meta.objective=="balanced":
        score=.5*trim+.5*gross
    elif meta.objective=="hit_floor":
        score=trim-400*np.maximum(0.,.20-hits/np.maximum(1,races))
    elif meta.objective=="jackpot_penalty":
        score=trim-100*largest/np.maximum(1,paid)
    elif meta.objective=="cash_margin":
        # Monetary net profit PER 100 yen of genuine earlier stakes.
        score=100+100*(paid-stake)/np.maximum(1,stake)
    else:
        raise RuntimeError("UNKNOWN_OUTER_MONEY_SCORE")
    evidence=races/(races+meta.shrink)
    score=100+(score-100)*evidence
    return np.where(races>=meta.min_races,score,-1e9)


def choose_meta(ledger,t,v,meta):
    key=(meta.lookback,meta.scope,meta.objective,
         meta.shrink,meta.min_races,t,v)
    if key not in DECISION_CACHE:
        score=historical_score(ledger,t,v,meta)
        if np.all(score<=-1e8):
            # No hindsight search when insufficient history.
            DECISION_CACHE[key]=0
        else:
            DECISION_CACHE[key]=int(np.argmax(score))
    return DECISION_CACHE[key]


def cash_metrics(paid,stake,hits,n,days,max_event):
    if stake<=0 or n<=0:return None
    return {"paidYen":int(paid),"stakeYen":int(stake),
            "cashProfitYen":int(paid-stake),
            "roiPct":round(100*paid/stake,5),
            "roiWithoutLargestRacePct":round(100*(paid-max_event)/stake,5),
            "biggestRacePaidYen":int(max_event),
            "boughtRaces":int(n),"venueDays":int(days),
            "hitRacePct":round(100*hits/n,5),"hitRaces":int(hits),
            "qualifies":bool(paid>=2*stake+max_event and
                             5*hits>=n and n>=3*days)}


def replay(ledger,outer,v5,start,through):
    total_p=total_s=total_h=total_n=total_days=biggest=0
    yearly=collections.defaultdict(lambda:[0,0,0,0,0,0])
    for t,mon in enumerate(ledger.months):
        if not start<=mon<=through:continue
        for v in range(NV):
            ndays=int(ledger.account.days[0,t,v])
            if not ndays:continue
            mid=choose_meta(ledger,t,v,outer)
            # Stakes are determined from that INNER method's pre-result
            # confidence, not from current-month paid money.
            confidence=float(ledger.prior_score[mid,t,v])
            units=v5.multiplier(outer.stake_plan,confidence)
            c=int(ledger.paid[mid,t,v])*units
            stake=int(ledger.stake[mid,t,v])*units
            hits=int(ledger.hit[mid,t,v])
            count=int(ledger.races[mid,t,v])
            event=int(ledger.biggest[mid,t,v])*units
            if count<3*ndays:raise RuntimeError("NESTED_METHOD_BROKE_VENUE_DAY_COVERAGE")
            total_p+=c;total_s+=stake;total_h+=hits
            total_n+=count;total_days+=ndays;biggest=max(biggest,event)
            row=yearly[mon[:4]]
            row[0]+=c;row[1]+=stake;row[2]+=hits;row[3]+=count
            row[4]+=ndays;row[5]=max(row[5],event)
    whole=cash_metrics(total_p,total_s,total_h,total_n,total_days,biggest)
    by_year={y:cash_metrics(*r) for y,r in sorted(yearly.items())}
    return whole,by_year


def search(ledger,v5):
    attempted=methods()
    developmental=[]
    for i,method in enumerate(attempted):
        stat,year=replay(ledger,method,v5,DEV_START,DEV_END)
        if stat and stat["qualifies"]:
            developmental.append((method,stat,year))
        if (i+1)%216==0:
            print("DOUBLE_ONLINE_META_MONEY_SEARCH",json.dumps({
                "generated":i+1,"total":len(attempted),
                "eligibleForIndependentPeriod":len(developmental)}),flush=True)
    developmental.sort(
        key=lambda x:(x[1]["cashProfitYen"],x[1]["roiWithoutLargestRacePct"]),
        reverse=True)
    adopted=[]
    for method,dev,history in developmental:
        future,years=replay(ledger,method,v5,HOLD_START,HOLD_END)
        if future and future["qualifies"]:
            adopted.append({"outerLearnableMethod":method.asdict(),
                            "developmentCash":dev,"developmentYears":history,
                            "independentCash":future,"independentYears":years,
                            "verifiedJraT15Odds":False,
                            "productionEligible":False})
    return {
        "status":"DOUBLE_ONLINE_ROI200_MODEL_FOUND_RESEARCH" if adopted else
                 "NO_VALID_DOUBLE_ONLINE_ROI200_MODEL",
        "baseCashForecasters":len(ledger.account.methods),
        "adaptiveInnerMetaMethods":len(ledger.paid),
        "generatedOuterPredictionMethodMethods":len(attempted),
        "developmentQualifiedMethods":len(developmental),
        "independentQualifiedMethods":len(adopted),
        "models":adopted,
        "developmentPeriod":DEV_START+".."+DEV_END,
        "independentPeriod":HOLD_START+".."+HOLD_END,
        "noSameMonthOrFutureCashInSelection":True,
        "cashROI200AfterLargestRaceAndHit20HardGated":True,
        "venueDayMinThreeHardGated":True,
        "historicalOddsAreFinalNotOfficialT15":True,
        "thirdPartyCashLabelsNotJraReconciled":True,
        "productionPromotionAllowed":False,
        "researchOnly":True,"productionModified":False,
    }


def selftest():
    assert len(methods())==len(HORIZONS)*len(SCOPES)*len(GOALS)*len(SHRINK)*len(MIN_RACES)*len(STAKE_PLANS)
    assert len(methods())==1728
    good=cash_metrics(2000,700,3,3,1,200)
    assert good["qualifies"]
    assert not cash_metrics(1400,700,3,3,1,200)["qualifies"]
    assert not cash_metrics(2000,700,0,3,1,200)["qualifies"]
    print("DOUBLE_ONLINE_ADAPTIVE_CASH_GATE_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:selftest();return
    started=time.monotonic()
    v5=imported("scripts/research-20261114-online-meta-cash-action-v5.py","nested_cash_v5")
    v3=imported("scripts/research-20261114-causal-action-method-generator-v3.py","nested_cash_v3")
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py","nested_cash_base")
    core,races,payout,features,market,slots=base.historic_cash()
    best,confidence,_,months=base.monthly_frozen_predictions(
        races,payout,features,market,slots)
    if len(months)!=136 or len(races)<30000:
        raise RuntimeError("INVALID_PINNED_PAYOUT_HISTORY")
    cash,score=v3.templates_from_frozen_predictions(payout,best,confidence)
    index=v3.Index(races,cash,score,features["fieldSize"][:,0])
    account=v5.build_cache(index,v3,v5.make_base_methods(v3))
    choices=eligible_inner_methods(v5)
    if len(choices)!=756:raise RuntimeError("MISSING_META_GENERATOR_FAMILIES")
    led=MethodLedger(len(choices),account)
    led.fill(choices,v5)
    report=search(led,v5)
    report["sourceRaces"]=len(races)
    report["elapsedSeconds"]=round(time.monotonic()-started,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("DOUBLE_ONLINE_CASH_MODEL_SEARCH_FINAL",json.dumps({
        "status":report["status"],
        "base":report["baseCashForecasters"],
        "inner":report["adaptiveInnerMetaMethods"],
        "outer":report["generatedOuterPredictionMethodMethods"],
        "developmentQualified":report["developmentQualifiedMethods"],
        "independentQualified":report["independentQualifiedMethods"],
        "onlyValidModels":report["models"],
        "elapsedSeconds":report["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
