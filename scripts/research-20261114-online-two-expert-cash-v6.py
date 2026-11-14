#!/usr/bin/env python3
"""Generate and audit a causally selected TWO-expert cash ticket portfolio.

Unlike the preceding single-expert model, this program composes two
independently ticket-generating algorithms into a portfolio for each venue
each month. The algorithms may buy different races; records are merged at
the race level BEFORE computing purchase counts, hit rate and the largest
one-race payout. Cash exposure changes using only earlier-month settlements.

Base model candidates: 672 historically causal previous-month trained
JRA payout predictors selecting among 765 1- or 2-market ticket structures.
Meta model candidates: varied windows, shrinkage, cash objectives, venue
specificity, different trained-algorithm families and relative stake weights.

An algorithm exists as an output model *only* if both the 2017-24 discovery
ledger AND an independently later 2025-26Apr ledger cross all of:
ROI >= 200%; ROI after one highest-paying RACE >= 200%; hit race rate
>= 20%; >= 3 bought races PER venue day, without skipped venue-days.

All cash is retrospective third-party JRA-derived, historical odds are
final WIN odds (NOT verified official T-minus-15); this is read-only research.
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
OUT=ROOT/"analysis-results/20261114-two-expert-adaptive-portfolio-v6.json"
MONEY_PER_RACE=2000
LEARNING=(3,6,12,24,60,96)
POOLING=("global","venue","mixed")
GOALS=("trim","payout_halftrim","cash_profit","hit_balanced","win_concentration")
SHRINKAGES=(25,250)
MIN_RACES=(40,200)
STAKE=("flat","high_conviction","reverse_edge")
DIVERSITY=("lag","blend","slate","none")
SECOND_WEIGHT=(0.25,0.5,1.0)
DEV_START,DEV_END="201701","202412"
HOLD_START,HOLD_END="202501","202604"


def imported(path, name):
    src=ROOT/path
    s=importlib.util.spec_from_file_location(name,src)
    if s is None or s.loader is None:raise RuntimeError("MISSING_RESEARCH_SOURCE:"+str(src))
    m=importlib.util.module_from_spec(s)
    sys.modules[name]=m
    s.loader.exec_module(m)
    return m


@dataclasses.dataclass(frozen=True)
class PortfolioMethod:
    lookback: int
    scope: str
    objective: str
    shrink: int
    min_bets: int
    stake_plan: str
    diversity: str
    weight: float

    def to_dict(self):
        return dataclasses.asdict(self)


def portfolio_methods():
    # Systematic finite family, no handpicked outcome-defined winners.
    # Diverse base actions and predictor families are evaluated dynamically.
    return [PortfolioMethod(*arg) for arg in itertools.product(
        LEARNING,POOLING,GOALS,SHRINKAGES,MIN_RACES,
        STAKE,DIVERSITY,SECOND_WEIGHT)]


def source_scores(index, method, month):
    t=index.mi[month]
    ix=index.indices[month]
    group=index.groups[method.scope][ix]
    total,counts,wins=index.build_history(method.cap,method.scope)
    end=max(0,t-method.lag_months)
    start=max(0,end-method.horizon)
    n=counts[end]-counts[start]
    gross=total[end]-total[start]
    hit=wins[end]-wins[start]
    ratio=gross/(np.maximum(1,n)[:,None]*MONEY_PER_RACE)
    w=(n[:,None]/(n[:,None]+method.shrink))*(hit/(hit+5.))
    learned=np.clip(.76+w*(ratio-.76),0.,25.)
    signal=((1.-method.blend)*learned[group]+
            method.blend*index.pred[ix])
    action=np.argmax(signal,axis=1)
    confidence=signal[np.arange(len(ix)),action]
    paid=index.cash[ix,action]
    return ix,confidence,paid


class RaceLedger:
    def __init__(self,n_methods,n_races,index):
        self.paid=np.zeros((n_methods,n_races),dtype=np.int64)
        self.selected=np.zeros((n_methods,n_races),dtype=np.uint8)
        self.indices=index
        self.venue_month={}
        for month,inds in index.indices.items():
            grouping=collections.defaultdict(list)
            for i in inds:
                r=index.rows[int(i)]
                grouping[int(r["venue"])-1].append(int(i))
            for v,idx in grouping.items():
                self.venue_month[(month,v)]=np.asarray(idx,dtype=np.int32)


def cache_base(index,base_methods,v5):
    monthly=v5.Account(index.months,base_methods)
    races=RaceLedger(len(base_methods),len(index.rows),index)
    for k,method in enumerate(base_methods):
        for t,month in enumerate(index.months):
            ix,confidence,paid=source_scores(index,method,month)
            c=np.zeros(v5.N_VENUES,np.int64)
            h=np.zeros(v5.N_VENUES,np.int32)
            b=np.zeros(v5.N_VENUES,np.int64)
            nr=np.zeros(v5.N_VENUES,np.int32)
            d=np.zeros(v5.N_VENUES,np.int32)
            for group in index.daily[month]:
                subset=np.asarray(group,dtype=np.int32)
                best=subset[np.argsort(-confidence[subset],kind="stable")]
                chosen=best[:method.slate]
                venue=int(index.rows[int(ix[int(group[0])])]["venue"])-1
                cash=paid[chosen]
                abs_ix=ix[chosen]
                races.paid[k,abs_ix]=cash
                races.selected[k,abs_ix]=1
                c[venue]+=int(cash.sum(dtype=np.int64))
                h[venue]+=int(np.count_nonzero(cash))
                b[venue]=max(b[venue],int(cash.max()))
                nr[venue]+=len(chosen)
                d[venue]+=1
            monthly.insert(k,t,(c,h,b,nr,d))
        if (k+1)%84==0:
            print("TWO_EXPERT_BASE_METHOD_CASH_PROGRESS",json.dumps({
                "trained":k+1,"total":len(base_methods),
                "perRaceLedgerFilledBeforeMetaSelection":True}),flush=True)
    monthly.prefix()
    return monthly,races


def cash_score_vector(account,t,v,meta):
    """Scores all base algorithms using only months < t."""
    lo=max(0,t-meta.lookback)
    a,b,c=(account.cash_prefix,account.hit_prefix,account.races_prefix)
    if meta.scope=="global":
        paid=np.sum(a[:,t]-a[:,lo],axis=1,dtype=np.int64)
        hit=np.sum(b[:,t]-b[:,lo],axis=1,dtype=np.int64)
        races=np.sum(c[:,t]-c[:,lo],axis=1,dtype=np.int64)
        biggest=np.max(account.biggest[:,lo:t,:],axis=(1,2)) if t>lo else np.zeros(len(account.methods))
    elif meta.scope=="venue":
        paid=a[:,t,v]-a[:,lo,v]
        hit=b[:,t,v]-b[:,lo,v]
        races=c[:,t,v]-c[:,lo,v]
        biggest=np.max(account.biggest[:,lo:t,v],axis=1) if t>lo else np.zeros(len(account.methods))
    else:
        pg=np.sum(a[:,t]-a[:,lo],axis=1,dtype=np.int64)
        hg=np.sum(b[:,t]-b[:,lo],axis=1,dtype=np.int64)
        ng=np.sum(c[:,t]-c[:,lo],axis=1,dtype=np.int64)
        paid=2*(a[:,t,v]-a[:,lo,v])+pg
        hit=2*(b[:,t,v]-b[:,lo,v])+hg
        races=2*(c[:,t,v]-c[:,lo,v])+ng
        biggest=np.max(account.biggest[:,lo:t,:],axis=(1,2)) if t>lo else np.zeros(len(account.methods))
    denom=np.maximum(1,races)*MONEY_PER_RACE
    gross=100.*paid/denom
    trimmed=100.*np.maximum(0,paid-biggest)/denom
    if meta.objective=="trim":score=trimmed
    elif meta.objective=="payout_halftrim":score=.5*trimmed+.5*gross
    elif meta.objective=="cash_profit":score=gross
    elif meta.objective=="hit_balanced":
        score=trimmed-400*np.maximum(0,.2-hit/np.maximum(1,races))
    elif meta.objective=="win_concentration":
        score=trimmed-100*biggest/np.maximum(1,paid)
    else:raise ValueError("INVALID_CASH_OBJECTIVE")
    score=100+(score-100)*races/(races+meta.shrink)
    return np.where(races>=meta.min_bets,score,-1e9)


def two_methods(monthly,t,v,meta):
    score=cash_score_vector(monthly,t,v,meta)
    ranks=np.argsort(-score,kind="stable")
    first=int(ranks[0]) if score[int(ranks[0])]>-1e8 else 0
    original=monthly.methods[first]
    second=None
    for j in ranks:
        j=int(j)
        if j==first or score[j]<=-1e8:continue
        other=monthly.methods[j]
        if meta.diversity=="lag" and other.lag_months==original.lag_months:continue
        if meta.diversity=="blend" and other.blend==original.blend:continue
        if meta.diversity=="slate" and other.slate==original.slate:continue
        second=j
        break
    if second is None:
        for j in ranks:
            if int(j)!=first and score[int(j)]>-1e8:
                second=int(j);break
    if second is None:
        # Empty prior cache: fallback to two predetermined distinct experts,
        # never to a chosen method with future money.
        second=1 if first!=1 else 0
    return first,second,float(score[first])


SELECTED_META_CACHE={}


def frozen_pair(monthly,t,v,meta):
    # The choice depends ONLY on months [0,t), never on target-month payouts.
    key=(meta.lookback,meta.scope,meta.objective,meta.shrink,meta.min_bets,
         meta.diversity,t,v)
    if key not in SELECTED_META_CACHE:
        SELECTED_META_CACHE[key]=two_methods(monthly,t,v,meta)
    return SELECTED_META_CACHE[key]


def quantile_stake(method, score,v5):
    return v5.multiplier(method.stake_plan,score)


def portfolio_metrics(stake, paid, hit, distinct_races, days, biggest):
    if not stake or not distinct_races:return None
    return {"stakeYen":int(stake),"paidYen":int(paid),
            "profitYen":int(paid-stake),"boughtDistinctRaces":int(distinct_races),
            "venueDays":int(days),"largestPaidRaceYen":int(biggest),
            "roiPct":round(100*paid/stake,6),
            "minusLargestRaceRoiPct":round(100*(paid-biggest)/stake,6),
            "hitRaces":int(hit),"hitPct":round(100*hit/distinct_races,6),
            "minThreeVenueDayGuaranteed":bool(distinct_races>=3*days),
            "qualified":bool(paid>=2*stake+biggest
                             and 5*hit>=distinct_races
                             and distinct_races>=3*days)}


def replay(monthly,races,meta,start,stop,v5,record_decisions=False):
    stake=paid=hit=distinct=days=biggest=0
    byyear=collections.defaultdict(lambda:[0,0,0,0,0,0])
    decisions=[]
    for t,month in enumerate(monthly.months):
        if month<start or month>stop:continue
        for v in range(v5.N_VENUES):
            day_count=int(monthly.days[0,t,v])
            if day_count==0:continue
            a,b,score=frozen_pair(monthly,t,v,meta)
            u1=quantile_stake(meta,score,v5)
            u2=max(1,int(round(u1*meta.weight)))
            idx=races.venue_month.get((month,v))
            if idx is None:raise RuntimeError("MISSING_VENUE_MONTH_RACES")
            chosen_a=races.selected[a,idx]>0
            chosen_b=races.selected[b,idx]>0
            bought=chosen_a|chosen_b
            nr=int(bought.sum())
            if nr<3*day_count:
                raise RuntimeError("LESS_THAN_THREE_DISTINCT_RACES_IN_VENUE_DAY")
            return_race=(u1*races.paid[a,idx]+u2*races.paid[b,idx])
            # Once methods are chosen, the cash returned and the amount
            # staked are summed at identical RACE IDs, not separate bets.
            cash=int(return_race[bought].sum(dtype=np.int64))
            max_race=int(return_race[bought].max())
            h=int(np.count_nonzero(return_race[bought]))
            cost=int(MONEY_PER_RACE*(u1*chosen_a.sum()+u2*chosen_b.sum()))
            stake+=cost;paid+=cash;hit+=h;distinct+=nr;days+=day_count
            biggest=max(biggest,max_race)
            yy=month[:4];yearly=byyear[yy]
            yearly[0]+=cost;yearly[1]+=cash;yearly[2]+=h
            yearly[3]+=nr;yearly[4]+=day_count;yearly[5]=max(yearly[5],max_race)
            if record_decisions:decisions.append({
                "month":month,"venue":v+1,"baseExpert1":a,"baseExpert2":b,
                "stakeMultiplier1":u1,"stakeMultiplier2":u2,
                "boughtDistinctRaces":nr,"venueDays":day_count})
    outcome=portfolio_metrics(stake,paid,hit,distinct,days,biggest)
    yearly={str(yy):portfolio_metrics(x[0],x[1],x[2],x[3],x[4],x[5])
            for yy,x in sorted(byyear.items())}
    return outcome,yearly,decisions


def generate_meta_methods():
    # This is a comprehensive Cartesian enumeration of this NEW family:
    # 6 * 3 * 5 * 2 * 2 * 3 * 4 * 3 = 6480 online strategies.
    # Evaluate each only with actually selected ticket-level cash.
    return portfolio_methods()


def research(monthly,ledger,v5):
    variants=generate_meta_methods()
    complete=[]
    for i,m in enumerate(variants):
        st,years,_=replay(monthly,ledger,m,DEV_START,DEV_END,v5)
        if st is not None and st["qualified"]:
            complete.append((m,st,years))
        if (i+1)%360==0:
            print("TWO_EXPERT_ADAPTIVE_META_SEARCH",json.dumps({
                "scanned":i+1,"total":len(variants),
                "qualifiedMethodsReadyForIndependentHoldout":len(complete)}),flush=True)
    complete.sort(key=lambda t:(t[1]["profitYen"],
                                 t[1]["minusLargestRaceRoiPct"]),reverse=True)
    adopted=[]
    # Never choose candidate or hyperparameters using independent period cash.
    for m,historical,byyear in complete:
        held,forward_years,_=replay(monthly,ledger,m,HOLD_START,HOLD_END,v5)
        if held and held["qualified"]:
            adopted.append({"metaMethod":m.to_dict(),"developmentCash":historical,
                            "developmentYears":byyear,"holdoutCash":held,
                            "holdoutYears":forward_years,
                            "officialHistoricalTMinus15SnapshotsVerified":False,
                            "productionEligible":False})
    return {"status":"RESEARCH_QUALIFIED_TICKET_PORTFOLIO_FOUND" if adopted else
            "NO_PROVEN_200PCT_CASH_PORTFOLIO",
            "baseCashTicketGenerators":len(monthly.methods),
            "newMetaMethodVariations":len(variants),
            "cashActionsPerRace":765,"actualJraSixMarketPayoutTemplates":1030,
            "developmentPeriod":DEV_START+".."+DEV_END,
            "independentPeriod":HOLD_START+".."+HOLD_END,
            "developmentApprovedCount":len(complete),
            "independentApprovedCount":len(adopted),
            "models":adopted,
            "currentMonthCashUsedBeforePrediction":False,
            "sameRaceDuplicatePaymentsReconciled":True,
            "minimumThreeRacesEveryVenueDay":True,
            "unreconciledThirdPartyHistoricalPayouts":True,
            "usesHistoricalFinalWinOddsNotOfficialPreT15":True,
            "researchOnly":True,"productionModified":False,
            "productionPromotionAllowed":False}


def selftest():
    assert len(generate_meta_methods())==6480
    dummy=portfolio_metrics(600,1600,3,3,1,100)
    assert dummy["qualified"] is True
    assert not portfolio_metrics(600,1600,3,3,1,500)["qualified"]
    assert not portfolio_metrics(600,1600,0,3,1,100)["qualified"]
    # A 2-method portfolio must only count a race ONCE for hit/race count.
    a=np.array([1,1,0,0],dtype=np.uint8)
    b=np.array([1,0,1,0],dtype=np.uint8)
    assert int((a|b).sum())==3
    assert MONEY_PER_RACE*(a.sum()+b.sum())==8000
    print("TWO_EXPERT_CASH_PORTFOLIO_GATE_AND_UNION_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:selftest();return
    started=time.monotonic()
    v5=imported("scripts/research-20261114-online-meta-cash-action-v5.py","cash_v5")
    v3=imported("scripts/research-20261114-causal-action-method-generator-v3.py","cash_v3")
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py","cash_base_20261114")
    core,race_rows,payout,features,market,slots=base.historic_cash()
    picks,forecast,_,by_month=base.monthly_frozen_predictions(
        race_rows,payout,features,market,slots)
    if len(by_month)!=136 or len(race_rows)<30000:
        raise RuntimeError("MISSING_COMPLETE_HISTORICAL_CASH_ARCHIVE")
    cash,pred=v3.templates_from_frozen_predictions(payout,picks,forecast)
    index=v3.Index(race_rows,cash,pred,features["fieldSize"][:,0])
    methods=v5.make_base_methods(v3)
    monthly,ledger=cache_base(index,methods,v5)
    report=research(monthly,ledger,v5)
    report["sourceRaces"]=len(race_rows)
    report["elapsedSeconds"]=round(time.monotonic()-started,3)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("TWO_EXPERT_CASH_MODEL_SEARCH_FINAL",json.dumps({
        "status":report["status"],
        "baseTicketMethods":report["baseCashTicketGenerators"],
        "onlinePolicyMethodsTested":report["newMetaMethodVariations"],
        "qualifiedDevelopment":report["developmentApprovedCount"],
        "qualifiedIndependent":report["independentApprovedCount"],
        "models":report["models"],
        "elapsedSeconds":report["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
