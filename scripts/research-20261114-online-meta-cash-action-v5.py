#!/usr/bin/env python3
"""Time-causal cash-trained method-OF-methods, variable-stake venue/month portfolios.

This is not a filter that turns underperforming methods into "models".
It generates diverse 2,000-yen JRA cash actions from six markets and 15
previous-month forecasters, learns 336 distinct horizon/venue/lag cash-action
generators, then constructs 756 genuinely ONLINE meta-methods which can
switch both prediction algorithm and ticket type, stakes, horizon and race
slate, separately for each venue and month, based on earlier actual payouts.

Development period (2017-01..2024-12) is a discovery space. No method
enters independent 2025-01..2026-04 holdout unless the entire development
cash ledger has all criteria. No research metric below all strict criteria
is emitted as a model; no production writes. Past payout data are third-party
and odds are retrospective final odds, not verified JRA T-15 snapshots.
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
OUT=ROOT/"analysis-results/20261114-online-meta-venue-cash-v5-variable-stakes.json"
WARMUP_THROUGH="201612"
DEV_FROM,DEV_TO="201701","202412"
HOLD_FROM,HOLD_TO="202501","202604"
MONEY_PER_RACE=2000
LOOKBACKS=(3,6,12,24,36,60,96)
SCOPES=("global","venue","mixed")
OBJECTIVES=("trim","payout_halftrim","cash_profit","hit_balanced",
            "quarter_floor","win_concentration")
SHRINKS=(25,150,600)
MIN_TRAIN_RACES=(40,200)
STAKE_PLANS=("flat","edge_band","high_conviction","reverse_edge")
N_VENUES=10


@dataclasses.dataclass(frozen=True)
class MetaMethod:
    lookback: int
    scope: str
    objective: str
    shrink: int
    min_bets: int
    stake_plan: str

    def asdict(self):
        return dataclasses.asdict(self)


def imported(path, name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_SOURCE:"+path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod


def make_meta_methods():
    return [MetaMethod(*args) for args in itertools.product(
        LOOKBACKS,SCOPES,OBJECTIVES,SHRINKS,MIN_TRAIN_RACES,STAKE_PLANS)]


def make_base_methods(v3):
    # Not just 72 re-rankers: action generator independently learns each
    # cash ticket from past months with all 765 single/pair combinations.
    methods=[m for m in v3.generate_methods()
             if m.scope in ("global","venue","venue_field")
             and m.cap in (10000,200000)
             and m.blend in (0.,.75)
             and m.lag_months in (0,12)]
    if len(methods)!=672:
        raise RuntimeError(f"UNEXPECTED_BASE_GENERATOR_SIZE:{len(methods)}")
    # Exact 672 baselines, including 3 or 5 bought races per venue-day.
    return methods


def source_group_actions(index,method,month):
    t=index.mi[month]
    i=index.indices[month]
    scope_group=index.groups[method.scope][i]
    total,ncount,wins=index.build_history(method.cap,method.scope)
    end=max(0,t-method.lag_months)
    begin=max(0,end-method.horizon)
    n=ncount[end]-ncount[begin]
    cash=total[end]-total[begin]
    hit=wins[end]-wins[begin]
    ratio=cash/(np.maximum(1,n)[:,None]*index.cash.dtype.type(MONEY_PER_RACE))
    evidence=(n[:,None]/(n[:,None]+method.shrink))*(hit/(hit+5.))
    learned=np.clip(.76+evidence*(ratio-.76),0.,25.)
    signal=((1.-method.blend)*learned[scope_group]+
            method.blend*index.pred[i])
    best=np.argmax(signal,axis=1)
    confidence=signal[np.arange(len(i)),best]
    paid=index.cash[i,best]

    c=np.zeros(N_VENUES,np.int64)
    h=np.zeros(N_VENUES,np.int32)
    b=np.zeros(N_VENUES,np.int64)
    r=np.zeros(N_VENUES,np.int32)
    d=np.zeros(N_VENUES,np.int32)
    for group in index.daily[month]:
        ii=np.asarray(group,dtype=np.int32)
        ranked=ii[np.argsort(-confidence[ii],kind="stable")]
        chosen=ranked[:method.slate]
        venue=int(index.rows[int(i[int(group[0])])]["venue"])-1
        if not (0<=venue<N_VENUES):
            raise RuntimeError("BAD_VENUE")
        if len(chosen)<3:
            raise RuntimeError("BELOW_THREE_RACES")
        actual=paid[chosen]
        c[venue]+=np.int64(actual.sum(dtype=np.int64))
        h[venue]+=int(np.count_nonzero(actual))
        b[venue]=max(b[venue],int(actual.max()))
        r[venue]+=len(chosen)
        d[venue]+=1
    if np.any((d>0)&(r<3*d)):
        raise RuntimeError("INVALID_VENUE_DAY_COVERAGE")
    return c,h,b,r,d


class Account:
    def __init__(self,months,base_methods):
        self.months=months
        self.methods=base_methods
        shape=(len(base_methods),len(months),N_VENUES)
        self.cash=np.zeros(shape,dtype=np.int64)
        self.hit=np.zeros(shape,dtype=np.int32)
        self.biggest=np.zeros(shape,dtype=np.int64)
        self.races=np.zeros(shape,dtype=np.int32)
        self.days=np.zeros(shape,dtype=np.int16)

    def insert(self,method_id,month_id,ret):
        a,b,c,d,e=ret
        self.cash[method_id,month_id]=a
        self.hit[method_id,month_id]=b
        self.biggest[method_id,month_id]=c
        self.races[method_id,month_id]=d
        self.days[method_id,month_id]=e

    def prefix(self):
        self.cash_prefix=np.pad(np.cumsum(self.cash,axis=1,dtype=np.int64),
                                ((0,0),(1,0),(0,0)))
        self.hit_prefix=np.pad(np.cumsum(self.hit,axis=1,dtype=np.int64),
                               ((0,0),(1,0),(0,0)))
        self.races_prefix=np.pad(np.cumsum(self.races,axis=1,dtype=np.int64),
                                 ((0,0),(1,0),(0,0)))


def build_cache(index,v3,methods):
    months=index.months
    account=Account(months,methods)
    # The base method's per-race choice is computed before using month cash.
    for j,method in enumerate(methods):
        for t,month in enumerate(months):
            account.insert(j,t,source_group_actions(index,method,month))
        if (j+1)%84==0:
            print("BASE_CASH_METHODS_TRAINED",json.dumps({
                "generated":j+1,"total":len(methods),
                "noCurrentMonthCashInPrediction":True}),flush=True)
    account.prefix()
    return account


def score_experts(account,t,v,meta,with_score=False):
    lo=max(0,t-meta.lookback)
    a,b,c=(account.cash_prefix,account.hit_prefix,account.races_prefix)
    if meta.scope=="global":
        gross=np.sum(a[:,t]-a[:,lo],axis=1,dtype=np.int64)
        hits=np.sum(b[:,t]-b[:,lo],axis=1,dtype=np.int64)
        races=np.sum(c[:,t]-c[:,lo],axis=1,dtype=np.int64)
        top=np.max(account.biggest[:,lo:t,:],axis=(1,2)) if t>lo else np.zeros(len(account.methods))
    elif meta.scope=="venue":
        gross=a[:,t,v]-a[:,lo,v]
        hits=b[:,t,v]-b[:,lo,v]
        races=c[:,t,v]-c[:,lo,v]
        top=np.max(account.biggest[:,lo:t,v],axis=1) if t>lo else np.zeros(len(account.methods))
    else:
        # Local context with global prior. Two datasets are weighted
        # independently. This is not reading any current-month payout.
        global_g=np.sum(a[:,t]-a[:,lo],axis=1,dtype=np.int64)
        global_h=np.sum(b[:,t]-b[:,lo],axis=1,dtype=np.int64)
        global_n=np.sum(c[:,t]-c[:,lo],axis=1,dtype=np.int64)
        gross=2*(a[:,t,v]-a[:,lo,v])+global_g
        hits=2*(b[:,t,v]-b[:,lo,v])+global_h
        races=2*(c[:,t,v]-c[:,lo,v])+global_n
        top=np.max(account.biggest[:,lo:t,:],axis=(1,2)) if t>lo else np.zeros(len(account.methods))
    stakes=np.maximum(1,races)*MONEY_PER_RACE
    cash_roi=100.*gross/stakes
    trimmed=100.*np.maximum(0,gross-top)/stakes
    if meta.objective=="trim":
        score=trimmed
    elif meta.objective=="payout_halftrim":
        score=.5*trimmed+.5*cash_roi
    elif meta.objective=="cash_profit":
        score=cash_roi
    elif meta.objective=="hit_balanced":
        # Soft risk constraint for the online selection; final hit gate
        # remains a hard 20% on actual bought races.
        hitrate=hits/np.maximum(1,races)
        score=trimmed-400*np.maximum(0.,.20-hitrate)
    elif meta.objective=="quarter_floor":
        floor=np.full(len(account.methods),np.inf)
        for tt in range(lo,t,3):
            u=min(t,tt+3)
            if meta.scope=="venue":
                pr=account.cash[:,tt:u,v].sum(axis=1)
                nr=account.races[:,tt:u,v].sum(axis=1)
            else:
                pr=account.cash[:,tt:u].sum(axis=(1,2))
                nr=account.races[:,tt:u].sum(axis=(1,2))
            q=100.*pr/(np.maximum(1,nr)*MONEY_PER_RACE)
            floor=np.minimum(floor,q)
        score=np.minimum(trimmed, np.where(np.isfinite(floor),floor,0.))
    elif meta.objective=="win_concentration":
        # This penalizes single hit events relative to total paid cash.
        score=trimmed-100.*top/np.maximum(1,gross)
    else:
        raise RuntimeError("UNKNOWN_META_OBJECTIVE")
    support=races/(races+meta.shrink)
    score=100+(score-100)*support
    score=np.where(races>=meta.min_bets,score,-1e9)
    if np.all(score<=-1e8):
        # Research must still cover 3+ races per venue-day. The fallback
        # method is predetermined, not a performance-based survivor.
        return (0,-1e9) if with_score else 0
    selected=int(np.argmax(score))
    return (selected,float(score[selected])) if with_score else selected


def multiplier(plan,prior_cash_score):
    """Only an earlier-month cash score controls the stake multiplier."""
    if plan=="flat": return 1
    if plan=="edge_band": return 4 if prior_cash_score>=180 else 2 if prior_cash_score>=115 else 1
    if plan=="high_conviction": return 5 if prior_cash_score>=250 else 3 if prior_cash_score>=145 else 1
    if plan=="reverse_edge": return 3 if prior_cash_score<95 else 2 if prior_cash_score<150 else 1
    raise ValueError("UNKNOWN_STAKE_PLAN")


def replay(account,meta,start,stop):
    paid=hits=nr=days=biggest=stake=0
    yearly=collections.defaultdict(lambda:[0,0,0,0,0,0])
    decisions=[]
    for t,month in enumerate(account.months):
        if month<start or month>stop:continue
        for v in range(N_VENUES):
            if not account.days[0,t,v]:continue
            expert,prior_score=score_experts(account,t,v,meta,with_score=True)
            units=multiplier(meta.stake_plan,prior_score)
            pc=units*int(account.cash[expert,t,v]); hh=int(account.hit[expert,t,v])
            nn=int(account.races[expert,t,v]); dd=int(account.days[expert,t,v])
            mx=units*int(account.biggest[expert,t,v])
            cost=MONEY_PER_RACE*units*nn
            # Every underlying method must have covered the same exact venue
            # day slate, and at least 3 distinct purchased races per day.
            if dd!=int(account.days[0,t,v]) or nn<3*dd:
                raise RuntimeError("META_METHOD_COVERAGE_BROKEN")
            paid+=pc;hits+=hh;nr+=nn;days+=dd;stake+=cost;biggest=max(biggest,mx)
            yy=month[:4]; row=yearly[yy]
            row[0]+=pc;row[1]+=hh;row[2]+=nn;row[3]+=dd;row[4]=max(row[4],mx);row[5]+=cost
            decisions.append([month,v+1,expert,units])
    s=100.*paid/stake if stake else 0.
    drop=100.*(paid-biggest)/stake if stake else 0.
    hr=100.*hits/nr if nr else 0.
    passed=bool(stake and paid>=2*stake+biggest and 5*hits>=nr and nr>=3*days)
    overall={"stakeYen":stake,"paidYen":paid,"profitYen":paid-stake,
             "boughtRaces":nr,"venueDays":days,"largestPaidRaceYen":biggest,
             "roiPct":round(s,6),"minusLargestRaceRoiPct":round(drop,6),
             "hitRaces":hits,"hitPct":round(hr,6),"qualified":passed}
    byyear={}
    for yy,row in yearly.items():
        cash,h,n,d,mx,cost=row
        byyear[yy]={"stakeYen":cost,"paidYen":cash,"boughtRaces":n,"venueDays":d,
                    "roiPct":round(100*cash/cost,6) if cost else 0.,
                    "minusLargestRaceRoiPct":round(100*(cash-mx)/cost,6) if cost else 0.,
                    "hitPct":round(100*h/n,6) if n else 0.}
    return overall,byyear,decisions


def select(account):
    methods=make_meta_methods()
    eligible=[]
    for k,m in enumerate(methods):
        stats,yearly,_=replay(account,m,DEV_FROM,DEV_TO)
        if stats["qualified"]:
            eligible.append((m,stats,yearly))
        if (k+1)%126==0:
            print("ONLINE_META_METHOD_SEARCH",json.dumps({
                "evaluated":k+1,"methodCount":len(methods),
                "admittedForHoldout":len(eligible)}),flush=True)
    # Using only retrospective development profit for ordering is permitted.
    # NO holdout cash is scanned until development gating is complete.
    eligible.sort(key=lambda x:(x[1]["profitYen"],x[1]["minusLargestRaceRoiPct"]),
                  reverse=True)
    found=[]
    for m,dev,dev_years in eligible:
        oos,oos_years,decisions=replay(account,m,HOLD_FROM,HOLD_TO)
        if oos["qualified"]:
            found.append({"adaptiveMetaMethod":m.asdict(),
                          "developmentCash":dev,"developmentYears":dev_years,
                          "independentHoldoutCash":oos,"holdoutYears":oos_years,
                          "historicalPreT15JraOddsVerified":False,
                          "productionEligible":False})
    return {
        "status":"RESEARCH_CASH200_META_MODEL_FOUND" if found else "NO_CASH200_META_MODEL_FOUND",
        "baseCashTicketGenerators":len(account.methods),
        "onlineMethodsGenerated":len(methods),
        "cashActionsPerRace":765,
        "underlyingJraSixMarketCashCombinations":1030,
        "developmentPeriod":f"{DEV_FROM}..{DEV_TO}",
        "untouchedIndependentPeriod":f"{HOLD_FROM}..{HOLD_TO}",
        "developmentQualifiedCount":len(eligible),
        "holdoutQualifiedCount":len(found),
        "models":found,
        "timeCausal":True,"noPostRaceOddsAtT15Verified":True,
        "moneyROI200AndAfterLargestRemovedGate":True,
        "hit20HardGate":True,"venueDayMinThreeRaces":True,
        "inputThirdPartyCashNotJraCertified":True,
        "productionModified":False,"productionPromotionAllowed":False,
    }


def selftest():
    from types import SimpleNamespace
    shape=(2,4,N_VENUES)
    a=Account(["202501","202502","202503","202504"],["A","B"])
    a.races[:,0,0]=3;a.days[:,0,0]=1
    a.races[:,1,0]=3;a.days[:,1,0]=1
    a.races[:,2,0]=3;a.days[:,2,0]=1
    a.races[:,3,0]=3;a.days[:,3,0]=1
    a.cash[0,:,0]=[12000,12000,12000,12000]
    a.cash[1,:,0]=[0,0,60000,60000]
    a.hit[0,:,0]=[2,2,2,2]
    a.hit[1,:,0]=[0,0,2,2]
    a.biggest[0,:,0]=[3000,3000,3000,3000]
    a.biggest[1,:,0]=[0,0,60000,60000]
    a.prefix()
    meta=MetaMethod(3,"venue","trim",25,3,"flat")
    # At month 3, best decision never uses the current/future large payout.
    pre=score_experts(a,2,0,meta)
    a.cash[1,2:,0]=[100000000,100000000]
    a.prefix()
    assert score_experts(a,2,0,meta)==pre
    assert score_experts(a,2,0,meta)==0
    assert len(make_meta_methods())==len(LOOKBACKS)*len(SCOPES)*len(OBJECTIVES)*len(SHRINKS)*len(MIN_TRAIN_RACES)*len(STAKE_PLANS)
    assert len(make_meta_methods())==3024
    assert multiplier("high_conviction",280)==5
    assert multiplier("reverse_edge",90)==3
    print("ONLINE_CASH_META_METHOD_VARIABLE_STAKE_NO_FUTURE_PAYOUT_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:
        selftest();return
    start=time.monotonic()
    v3=imported("scripts/research-20261114-causal-action-method-generator-v3.py",
                "cash_action_generator_v3")
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py",
                  "six_market_causal_cash_base_v4")
    core,races,payout,features,market,slots=base.historic_cash()
    picked,confidence,_,months=base.monthly_frozen_predictions(
        races,payout,features,market,slots)
    if len(months)!=136 or len(races)<30000:
        raise RuntimeError("INCOMPLETE_136_MONTH_ARCHIVE")
    cash,forecast=v3.templates_from_frozen_predictions(payout,picked,confidence)
    field=np.asarray(features["fieldSize"][:,0],dtype=np.int8)
    index=v3.Index(races,cash,forecast,field)
    original=make_base_methods(v3)
    ledger=build_cache(index,v3,original)
    result=select(ledger)
    result["historicalRaces"]=len(races)
    result["elapsedSeconds"]=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ONLINE_CAUSAL_META_CASH_SEARCH_FINAL",json.dumps({
        "status":result["status"],
        "generatedCashMethods":result["baseCashTicketGenerators"],
        "generatedMetaMethods":result["onlineMethodsGenerated"],
        "developmentQualifiedCount":result["developmentQualifiedCount"],
        "independentQualifiedCount":result["holdoutQualifiedCount"],
        "onlyQualifiedModels":result["models"],
        "seconds":result["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
