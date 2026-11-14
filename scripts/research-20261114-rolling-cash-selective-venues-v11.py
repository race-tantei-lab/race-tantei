#!/usr/bin/env python3
"""Freshly refitted rolling CASH models + causal optional-venue participation.

Fixes the EXTRA constraint repeatedly imposed by earlier research: requiring
bets on EVERY venue-day. User actually requires >=3 races PER CHOSEN VENUE.
We now search safe, genuinely forecast-only abstention rules (not hindsight
payout-selected skips). An eligible month-venue is chosen using preceding
monthly settled yen, or it is skipped ENTIRELY. On chosen venue-days buy
3 or 5 races as the model prescribed.

Trains every target-month payout forecaster afresh from prior 3/6/12/24/
36/60/96 months with 0/12-month embargo, plus adaptive venue/month
selection based ONLY on older settled predictions. No below200 candidate
is saved as a model. No main, D1, production edits.
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
OUT=ROOT/"analysis-results/20261114-rolling-cash-selective-venue-v11.json"
HORIZONS=(3,6,12,24,36)
THRESHOLDS=(95,110,125,150,175,200,250)
OBJECTIVES=("net_return","robust_return","hit_aware")
SCOPES=("venue","global")
SUPPORT=(30,100)
MIN_DEV_DAYS=20
MIN_HOLD_DAYS=6
MIN_DEV_RACES=80
MIN_HOLD_RACES=24


def imported(file,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    if spec is None or spec.loader is None:raise RuntimeError("MISSING_SOURCE")
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m


@dataclasses.dataclass(frozen=True)
class Selector:
    window: int
    threshold: int
    objective: str
    scope: str
    support: int

    def export(self):
        return dataclasses.asdict(self)


def make_selectors():
    return [Selector(*args) for args in itertools.product(
        HORIZONS,THRESHOLDS,OBJECTIVES,SCOPES,SUPPORT)]


def past_roi_matrix(ledger,t,window,scope,objective,v):
    lo=max(0,t-window)
    if scope=="venue":
        paid=ledger.prefix_paid[:,t,v]-ledger.prefix_paid[:,lo,v]
        spend=ledger.prefix_stake[:,t,v]-ledger.prefix_stake[:,lo,v]
        wins=ledger.prefix_hit[:,t,v]-ledger.prefix_hit[:,lo,v]
        races=ledger.prefix_races[:,t,v]-ledger.prefix_races[:,lo,v]
        big=ledger.max_paid[:,lo:t,v].max(axis=1) if t>lo else np.zeros(len(ledger.methods))
    else:
        paid=(ledger.prefix_paid[:,t]-ledger.prefix_paid[:,lo]).sum(axis=1)
        spend=(ledger.prefix_stake[:,t]-ledger.prefix_stake[:,lo]).sum(axis=1)
        wins=(ledger.prefix_hit[:,t]-ledger.prefix_hit[:,lo]).sum(axis=1)
        races=(ledger.prefix_races[:,t]-ledger.prefix_races[:,lo]).sum(axis=1)
        big=ledger.max_paid[:,lo:t,:].max(axis=(1,2)) if t>lo else np.zeros(len(ledger.methods))
    rate=100*paid/np.maximum(spend,1)
    robust=100*np.maximum(0,paid-big)/np.maximum(spend,1)
    if objective=="net_return":result=rate
    elif objective=="robust_return":result=robust
    elif objective=="hit_aware":
        result=robust-250*np.maximum(0,.20-wins/np.maximum(races,1))
    else:raise ValueError("UNKNOWN_ROI_OBJECTIVE")
    return result,races


def cash_account(ledger,picks,start,end,min_days,min_bets,core):
    received=staked=hit=nr=ndays=max_event=0
    year=collections.defaultdict(lambda:[0,0,0,0,0,0])
    skipped=0
    active=0
    for t,month in enumerate(ledger.months):
        if not(start<=month<=end):continue
        for v in range(10):
            d0=int(ledger.days[0,t,v])
            if d0==0:continue
            k=int(picks[t,v])
            if k<0:
                skipped+=d0
                continue
            p=int(ledger.paid[k,t,v]);s=int(ledger.stake[k,t,v])
            h=int(ledger.hit[k,t,v]);n=int(ledger.races[k,t,v])
            d=int(ledger.days[k,t,v]);mx=int(ledger.max_paid[k,t,v])
            if d!=d0 or n<3*d:
                raise RuntimeError("MISSING_REQUIRED_THREE_BOUGHT_RACES_IN_ACTIVE_VENUE")
            received+=p;staked+=s;hit+=h;nr+=n;ndays+=d;active+=1
            max_event=max(max_event,mx)
            yy=month[:4];z=year[yy]
            z[0]+=p;z[1]+=s;z[2]+=h;z[3]+=n;z[4]+=d;z[5]=max(z[5],mx)
    summary=core.cash_report(received,staked,hit,nr,ndays,max_event)
    if summary is not None:
        summary["activeVenueMonths"]=active
        summary["skippedVenueDays"]=skipped
        summary["qualified"]=(summary["qualified"] and
                             ndays>=min_days and nr>=min_bets)
    by_year={yearid:core.cash_report(*v) for yearid,v in sorted(year.items())}
    return summary,by_year


def select_adaptive(ledger,method):
    chosen=np.full((len(ledger.months),10),-1,dtype=np.int32)
    for t in range(len(ledger.months)):
        if t==0:continue
        for v in range(10):
            if ledger.days[0,t,v]==0:continue
            score,n=past_roi_matrix(ledger,t,method.window,method.scope,method.objective,v)
            eligible=np.where(n>=method.support,score,-1e9)
            k=int(np.argmax(eligible))
            if eligible[k]>=method.threshold:
                chosen[t,v]=k
    return chosen


def select_fixed(ledger,window,threshold,min_evidence):
    """Prior-only opt-in applied to each standalone trained forecaster."""
    out=np.full((len(ledger.methods),len(ledger.months),10),-1,dtype=np.int32)
    for t in range(1,len(ledger.months)):
        for v in range(10):
            if ledger.days[0,t,v]==0:continue
            score,n=past_roi_matrix(ledger,t,window,"venue","robust_return",v)
            eligible=(n>=min_evidence)&(score>=threshold)
            out[:,t,v]=np.where(eligible,np.arange(len(ledger.methods)),-1)
    return out


def search(ledger,core):
    chosen=[]
    tested_fixed=0
    for window,threshold,minobs in itertools.product(
        (3,6,12,24),THRESHOLDS,SUPPORT):
        masks=select_fixed(ledger,window,threshold,minobs)
        for k,method in enumerate(ledger.methods):
            dev,y=cash_account(ledger,masks[k],core.START_DEV,core.END_DEV,
                                MIN_DEV_DAYS,MIN_DEV_RACES,core)
            if dev and dev["qualified"]:
                chosen.append(("individually_retrained",{"cashMethod":method.export(),
                               "window":window,"threshold":threshold,"support":minobs},
                               dev,y,masks[k]))
            tested_fixed+=1
    meta=0
    for strategy in make_selectors():
        picks=select_adaptive(ledger,strategy)
        dev,y=cash_account(ledger,picks,core.START_DEV,core.END_DEV,
                            MIN_DEV_DAYS,MIN_DEV_RACES,core)
        if dev and dev["qualified"]:
            chosen.append(("adaptive_retrained_cash",strategy.export(),dev,y,picks))
        meta+=1
        if meta%105==0:
            print("SELECTIVE_CASH_METHOD_SEARCH",json.dumps({
                "adaptiveMethodsGenerated":meta,
                "totalAdaptiveMethods":len(make_selectors()),
                "developmentReadyForHoldout":len(chosen)}),flush=True)
    chosen.sort(key=lambda x:(x[2]["profitYen"],
                               x[2]["minusLargestRaceRoiPct"]),reverse=True)
    approved=[]
    for family,info,development,years,picks in chosen:
        forward,fy=cash_account(ledger,picks,core.START_HOLD,core.END_HOLD,
                               MIN_HOLD_DAYS,MIN_HOLD_RACES,core)
        if forward and forward["qualified"]:
            approved.append({
                "algorithmFamily":family,"learnedMethod":info,
                "developmentCash":development,"developmentYears":years,
                "independentCash":forward,"independentYears":fy,
                "JraPreT15Verified":False,"productionEligible":False})
    return {
        "status":"RETROSPECTIVE_ROI200_MODEL_CREATED" if approved else
                  "NO_VALID_ROI200_SELECTIVE_CASH_MODEL",
        "realMoneyForecastFamilies":len(ledger.methods),
        "baseFamiliesWithPriorCashBasedParticipation":tested_fixed,
        "adaptiveMethodsGenerated":meta,
        "developmentQualifiedCount":len(chosen),
        "independentQualifiedCount":len(approved),
        "models":approved,
        "trainWindowMonths":list(core.HORIZONS),
        "embargoWindowMonths":list(core.EMBARGO),
        "canSkipUnprofitableVenueMonths":True,
        "everyActiveVenueDayHasAtLeastThreeActualBoughtRaces":True,
        "minActiveVenueDaysDevelopment":MIN_DEV_DAYS,
        "minActiveVenueDaysHoldout":MIN_HOLD_DAYS,
        "developmentPeriod":core.START_DEV+".."+core.END_DEV,
        "independentPeriod":core.START_HOLD+".."+core.END_HOLD,
        "latestPeriodMissingMayNov2026":True,
        "thirdPartyCashNotOfficiallyReconciled":True,
        "finalOddsNotOfficialJraT15":True,
        "productionPromotionAllowed":False,"productionModified":False,
    }


def selftest():
    assert len(make_selectors())==5*7*3*2*2
    assert MIN_DEV_DAYS>MIN_HOLD_DAYS
    a=np.array([1.,4.,2.])
    b=np.array([30,5,50])
    allowed=np.where(b>=20,a,-1e9)
    assert int(np.argmax(allowed))==2
    assert not (allowed.max()>=150)
    print("SELECTIVE_FRESH_CASH_MONTHLY_ABSTENTION_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:selftest();return
    started=time.monotonic()
    core=imported("scripts/research-20261114-rolling-retrained-direct-cash-v10.py",
                  "selective_cash_rolling_model")
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py",
                  "selective_cash_source")
    _,races,pay,features,market,_=base.historic_cash()
    source=core.RefitCash(races,pay,features,market,base.FEATURES)
    ledger=core.Ledger(core.methods(),source.months)
    for month in source.months:
        if month<core.START_DEV:continue
        for horizon,lag in itertools.product(core.HORIZONS,core.EMBARGO):
            ledger.assign(month,source.direct_month_cash(month,horizon,lag))
    ledger.finish()
    report=search(ledger,core)
    report["historicalRaces"]=len(races)
    report["seconds"]=round(time.monotonic()-started,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("SELECTIVE_CASH_METHOD_DISCOVERY_FINAL",json.dumps({
        "status":report["status"],
        "baseMoneyForecastMethods":report["realMoneyForecastFamilies"],
        "testedFixedParticipation":report["baseFamiliesWithPriorCashBasedParticipation"],
        "testedAdaptiveParticipation":report["adaptiveMethodsGenerated"],
        "qualifiedBeforeHoldout":report["developmentQualifiedCount"],
        "qualifiedIndependent":report["independentQualifiedCount"],
        "onlyQualifiedModels":report["models"],"seconds":report["seconds"]},
        ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
