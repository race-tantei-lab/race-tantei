#!/usr/bin/env python3
"""Past-only rank-spectrum CASH ticket generator (not 72 selector re-ranker).

Previous cash machine learning always took the single maximal *predicted*
return action among 765 distinct ticket pairs/singles. That biases a
high-variance heavy-tail predictor toward wildly overestimated longshots.
Here, generate NEW actual bets by choosing alternative within-race ranks
0/1/3/7/15/31/63/127/255/511/764 for 96 distinct causal forecast methods,
and rank venue-day races by cash-score strength or expected uncertainty.

Every variant is replayed through 2017-2024 after 2015-2016 causal
history. Only methods clearing ALL required yen-based gates are subsequently
tested on untouched 2025-2026Apr data. No failed method is registered as
a "model"; largest winning RACE payout removed, with entire stake retained.
The mirror is third-party, with final WIN quotes, not official pre-T15 odds.
"""
from __future__ import annotations
import dataclasses
import importlib.util
import itertools
import json
import sys
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-cash-rank-spectrum-v7.json"
VALID_FROM,VALID_THROUGH="201701","202412"
HOLD_FROM,HOLD_THROUGH="202501","202604"
COST=2000
ACTION_RANK=(0,1,3,7,15,31,63,127,255,511,764)
DAY_RANK=("high","low","gap")


def load(p,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/p)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj


@dataclasses.dataclass(frozen=True)
class Variant:
    source: object
    action_rank: int
    day_rank: str

    def export(self):
        return {**dataclasses.asdict(self.source),
                "actionRank":self.action_rank,
                "dayRank":self.day_rank}


def rank_bases(v5,v3):
    # Orthogonal method family: focus on materially different horizons,
    # exposure regimes and feature-pooling structures.
    return [m for m in v5.make_base_methods(v3)
            if m.horizon in (6,24,96) and m.scope in ("global","venue")
            and m.cap in (10000,200000) and m.shrink==50
            and m.blend in (0.,.75) and m.lag_months in (0,12)]


def generate_methods(v5,v3):
    # 96 historical cash experts * 11 within-race positions *
    # 3 different venue-day ranking schemes = 3168 generated actions.
    bases=rank_bases(v5,v3)
    if len(bases)!=96:raise RuntimeError("RANK_SPECTRUM_BASE_FAMILY_SIZE")
    return [Variant(model,k,dr) for model,k,dr in itertools.product(
        bases,ACTION_RANK,DAY_RANK)]


def history_score(index,method,month):
    t=index.mi[month]
    i=index.indices[month]
    groups=index.groups[method.scope][i]
    total,counts,hits=index.build_history(method.cap,method.scope)
    end=max(0,t-method.lag_months)
    first=max(0,end-method.horizon)
    n=counts[end]-counts[first]
    returned=total[end]-total[first]
    winning=hits[end]-hits[first]
    estimated=returned/(np.maximum(1,n)[:,None]*COST)
    support=(n[:,None]/(n[:,None]+method.shrink))*(winning/(winning+5.))
    forecast=np.clip(.76+support*(estimated-.76),0,25.)
    signal=(1.-method.blend)*forecast[groups]+method.blend*index.pred[i]
    return i,signal


def settle(index,var,month):
    i,signal=history_score(index,var.source,month)
    rank=min(var.action_rank,signal.shape[1]-1)
    if rank==0:choice=np.argmax(signal,axis=1)
    elif rank==signal.shape[1]-1:choice=np.argmin(signal,axis=1)
    else:choice=np.argpartition(-signal,kth=rank,axis=1)[:,rank]
    score=signal[np.arange(len(i)),choice]
    actual=index.cash[i,choice]
    paid=hit=count=largest=days=0
    for venue_day in index.daily[month]:
        seq=np.asarray(venue_day,dtype=np.int32)
        if len(seq)<3:raise RuntimeError("VENUE_DAY_LESS_THAN_THREE")
        if var.day_rank=="high":order=np.argsort(-score[seq],kind="stable")
        elif var.day_rank=="low":order=np.argsort(score[seq],kind="stable")
        else:order=np.argsort(-np.abs(score[seq]-1.0),kind="stable")
        chosen=seq[order[:var.source.slate]]
        values=actual[chosen]
        paid+=int(values.sum(dtype=np.int64))
        hit+=int(np.count_nonzero(values))
        count+=len(chosen)
        largest=max(largest,int(values.max()))
        days+=1
    return paid,hit,count,largest,days


def metrics(stake,paid,hits,n,largest,days):
    if not stake:return None
    return {"stakeYen":stake,"paidYen":paid,"profitYen":paid-stake,
            "boughtRaces":n,"venueDays":days,
            "cashRoiPct":round(100*paid/stake,5),
            "minusLargestRaceRoiPct":round(100*(paid-largest)/stake,5),
            "hitRacePct":round(100*hits/n,5),
            "largestPaidRaceYen":largest,
            "qualifies":bool(paid>=2*stake+largest and hits*5>=n and n>=3*days)}


def evaluate(index,var,start,end):
    sum_paid=sum_hits=n=big=days=0
    annual={}
    for month in index.months:
        if not(start<=month<=end):continue
        pp,hh,nn,mx,dd=settle(index,var,month)
        sum_paid+=pp;sum_hits+=hh;n+=nn;big=max(big,mx);days+=dd
        y=month[:4]
        s=annual.setdefault(y,[0,0,0,0,0])
        s[0]+=pp;s[1]+=hh;s[2]+=nn;s[3]=max(s[3],mx);s[4]+=dd
    total=metrics(n*COST,sum_paid,sum_hits,n,big,days)
    years={year:metrics(x[2]*COST,x[0],x[1],x[2],x[3],x[4])
           for year,x in sorted(annual.items())}
    return total,years


def search(index,v5,v3):
    variants=generate_methods(v5,v3)
    qualified=[]
    for j,m in enumerate(variants):
        cash,annual=evaluate(index,m,VALID_FROM,VALID_THROUGH)
        if cash and cash["qualifies"]:
            qualified.append((m,cash,annual))
        if (j+1)%672==0:
            print("CASH_RANK_SPECTRUM_PROGRESS",json.dumps({
                "scanned":j+1,"total":len(variants),
                "qualifiedDevelopment":len(qualified)}),flush=True)
    qualified.sort(key=lambda x:(x[1]["profitYen"],
                    x[1]["minusLargestRaceRoiPct"]),reverse=True)
    verified=[]
    for m,dev,years in qualified:
        forward,fyears=evaluate(index,m,HOLD_FROM,HOLD_THROUGH)
        if forward and forward["qualifies"]:
            verified.append({
                "method":m.export(),"developmentCash":dev,"years":years,
                "forwardCash":forward,"forwardYears":fyears,
                "officialPreT15PricesChecked":False,
                "productionEligible":False})
    return {
        "status":"MODEL_ROI200_QUALIFIED_RETROSPECTIVE" if verified else
                 "NO_ROI200_CASH_METHOD_FOUND",
        "methodGenerationArchitecture":"rank spectrum of diverse cash-return predictions, not win classifiers",
        "baseMethods":len(rank_bases(v5,v3)),
        "spectrumRanks":list(ACTION_RANK),"dayPriorityMethods":list(DAY_RANK),
        "generatedCashMethods":len(variants),
        "qualifiedDevelopmentCount":len(qualified),
        "qualifiedIndependentCount":len(verified),
        "models":verified,
        "developmentPeriod":VALID_FROM+".."+VALID_THROUGH,
        "independentPeriod":HOLD_FROM+".."+HOLD_THROUGH,
        "retrospectiveFinalOddsNotPreT15":True,
        "thirdPartyPayoutMirrorNotJraReconciled":True,
        "productionPromotionAllowed":False,
        "productionModified":False,
    }


def selftest():
    assert len(ACTION_RANK)==11
    assert len(DAY_RANK)==3
    assert metrics(6000,14000,3,3,1000,1)["qualifies"] is True
    assert metrics(6000,14000,3,3,3000,1)["qualifies"] is False
    assert metrics(6000,14000,0,3,1000,1)["qualifies"] is False
    score=np.array([[1.,2.,3.],[3.,2.,1.]])
    col=np.argpartition(-score,kth=1,axis=1)[:,1]
    assert col.tolist()==[1,1]
    print("CASH_RANK_SPECTRUM_NO_SUB200_MODEL_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:selftest();return
    ts=time.monotonic()
    v3=load("scripts/research-20261114-causal-action-method-generator-v3.py","cash_rank_v3")
    v5=load("scripts/research-20261114-online-meta-cash-action-v5.py","cash_rank_v5")
    base=load("scripts/research-20261114-broad-causal-cash-sweep.py","cash_rank_base")
    core,races,payout,features,market,slots=base.historic_cash()
    picked,signal,_,months=base.monthly_frozen_predictions(
        races,payout,features,market,slots)
    if len(months)!=136:raise RuntimeError("CASH_ARCHIVE_NOT_136_MONTHS")
    cash,pred=v3.templates_from_frozen_predictions(payout,picked,signal)
    index=v3.Index(races,cash,pred,features["fieldSize"][:,0])
    result=search(index,v5,v3)
    result["historicalRaceCount"]=len(races)
    result["elapsedSeconds"]=round(time.monotonic()-ts,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CASH_RANK_SPECTRUM_FINAL",json.dumps({
        "status":result["status"],
        "generated":result["generatedCashMethods"],
        "qualifiedDevelopment":result["qualifiedDevelopmentCount"],
        "qualifiedIndependent":result["qualifiedIndependentCount"],
        "models":result["models"],
        "elapsedSeconds":result["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
