#!/usr/bin/env python3
"""Chronological independent model comparison, paired JRA hit + actual ROI.

Train strictly before each test year; evaluate 2024 and 2025 separately.
The 2024 race dates have been seen previously; this is RESEARCH, not pristine
evidence. Exact T-15 original ticket evidence is unavailable for these years.
No odds (final or fabricated) enter the decision. No D1 writes, no live actions.
All market outcomes are settled from actual JRA payout records already in D1.
For fairness, *all* model/policy variants use complete 12-race venue-days with
all six payout markets and the same valid date+venue cohort in each year.
No cherry-picking individual paid races after the outcome.
"""
from __future__ import annotations
import collections
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"analysis-results"/"research-2024-2025-multifamily-paired-jra-roi.json"
YEARS = (2024,2025)
MODELS = (
  "extratrees_120",
  "lightgbm_500",
  "lightgbm_150_regularized",
  "histgradientboosting_100",
  "ensemble_equal_four"
)
RULES = ("top1","top2","top3","gap","entropy")
K_VALUES = (3,4,5)
SPLITS = ((1000,1000),(1400,600),(600,1400),(1800,200),(200,1800))
STAKE_PER_RACE = 2000

def module(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name, ROOT/path)
    if not spec or not spec.loader: raise RuntimeError("IMPORT_HELPER_MISSING "+str(path))
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def check_protocol():
    research=module("scripts/research-postaug-independent-models-paired.py","paired_protocol")
    assert len(research.PAIRS)>=15
    assert all(a[0]!=b[0] for a,b in research.PAIRS.values())
    assert len(set(research.PAIRS))==len(research.PAIRS)
    assert all(x+y==STAKE_PER_RACE and x%100==0 and y%100==0 for x,y in SPLITS)
    for pair in research.PAIRS.values():
        for typ,position in pair:
            assert len(set(position))==len(position)
            assert max(position)<4
            assert len(position)==(1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2)
    return research

def train_models(hist,X,y,offsets,dates,year):
    indices=np.flatnonzero(dates<f"{year}-01-01")
    assert len(indices)>10000 and indices[0]==0 and indices[-1]==len(indices)-1
    end=int(offsets[int(indices[-1])+1])
    assert str(dates[int(indices[-1])])<f"{year}-01-01"
    models={}
    model=ExtraTreesClassifier(n_estimators=120,max_depth=14,min_samples_leaf=35,
        max_features=0.7,n_jobs=2,random_state=20261107)
    model.fit(X[:end],y[:end])
    models["extratrees_120"]=model
    for name,key in (("lightgbm_500","adopted_complexity_500x127"),
                     ("lightgbm_150_regularized","regularized_150x31")):
        models[name]=hist.fit(X,y,offsets,indices,hist.CANDIDATES[key])
    histboost=HistGradientBoostingClassifier(max_iter=100,learning_rate=0.05,
        max_leaf_nodes=31,min_samples_leaf=80,l2_regularization=8,
        random_state=20261107,early_stopping=False)
    histboost.fit(X[:end],y[:end])
    models["histgradientboosting_100"]=histboost
    return models,len(indices)

def assemble_year(hist,year,X,dates,counts,offsets,meta,models,payout):
    start=f"{year}-05-04" if year==2024 else f"{year}-01-01"
    target=np.flatnonzero((dates>=start)&(dates<f"{year+1}-01-01"))
    assert len(target)>2000
    low=int(offsets[int(target[0])])
    high=int(offsets[int(target[-1])+1])
    raws={name:m.predict_proba(X[low:high])[:,1] for name,m in models.items()}
    observed=collections.defaultdict(list)
    src=0
    all_types={"単勝","ワイド","馬連","馬単","3連複","3連単"}
    for idx in target:
        record=meta[int(idx)]
        n=int(counts[int(idx)])
        pp={}
        for name,r in raws.items():
            arr=np.maximum(r[src:src+n],1e-12)
            pp[name]=arr/arr.sum()
        pp["ensemble_equal_four"]=sum(pp.values())/len(pp)
        src+=n
        observed[(record["date"],record["venue"])].append({
           "date":record["date"],"venue":record["venue"],"no":int(record["no"]),
           "rid":record["rid"],"horses":record["horses"],
           "probs":pp,"payout":payout.get(record["rid"],{})
        })
    assert src==len(next(iter(raws.values())))
    accepted=[]
    rejected=collections.Counter()
    for (day,venue),races in sorted(observed.items()):
        if len(races)!=12 or {r["no"] for r in races}!=set(range(1,13)):
            rejected["missing_full_12_race_day"]+=1
            continue
        if any({typ for typ,_ in r["payout"]}!=all_types for r in races):
            rejected["missing_six_market_payout_in_12_races"]+=1
            continue
        accepted.append(((day,venue),sorted(races,key=lambda r:r["no"])))
    if len(accepted)<100: raise RuntimeError("INSUFFICIENT_ACTUAL_PAYOUT_COMPLETE_DAYS "+str(year)+" "+str(len(accepted)))
    return accepted,dict(rejected),len(target)

def win_odds_diagnostic_never_used(*args):
    raise AssertionError("ARCHIVED_FINAL_ODDS_MUST_NEVER_ENTER_SELECTION")

def build_matrices(complete,model,PAIRS,rule):
    import math
    nDays=len(complete)
    nPairs=len(PAIRS)
    returns=np.zeros((nDays,12,nPairs,2),dtype=np.int32)
    ranks=np.zeros((nDays,12),dtype=np.float64)
    months=[]
    for d,((date,venue),races) in enumerate(complete):
        months.append(date[:7])
        for j,r in enumerate(races):
            p=r["probs"][model]
            horse_ranks=np.argsort(-p,kind="stable")
            nums=[r["horses"][int(k)] for k in horse_ranks]
            if len(nums)<4: raise AssertionError("FEWER_THAN_FOUR_RUNNERS")
            p_desc=np.sort(p)[::-1]
            if rule=="top1": score=float(p_desc[0])
            elif rule=="top2": score=float(sum(p_desc[:2]))
            elif rule=="top3": score=float(sum(p_desc[:3]))
            elif rule=="gap": score=float(p_desc[0]-p_desc[1])
            elif rule=="entropy":score=float(-sum(t*math.log(t) for t in p))
            else:raise ValueError(rule)
            ranks[d,j]=score
            for pi,pair in enumerate(PAIRS):
                for leg,(typ,ix) in enumerate(pair):
                    horses=tuple(nums[k] for k in ix)
                    if typ in {"ワイド","馬連","3連複"}:horses=tuple(sorted(horses))
                    returns[d,j,pi,leg]=int(r["payout"].get((typ,horses),0))
    # stable order by score, race-no ascending for tie.
    order=np.argsort(-ranks,axis=1,kind="stable")
    idx=np.arange(nDays)[:,None]
    return returns[idx,order[:,:5],:,:],months

def evaluate_matrix(pays,months,pairnames,model,rank):
    nDays=len(months)
    entries=[]
    unit=np.asarray(SPLITS,dtype=np.int64)//100
    for k in K_VALUES:
        mat=pays[:,:k]
        hitmat=np.any(mat>0,axis=-1)
        hits=hitmat.sum(axis=(0,1))
        payout=mat[...,0,None]*unit[None,None,None,:,0]+mat[...,1,None]*unit[None,None,None,:,1]
        returned=payout.sum(axis=(0,1))
        largest=payout.max(axis=(0,1))
        allStake=nDays*k*STAKE_PER_RACE
        for pi,name in enumerate(pairnames):
            for si,(one,two) in enumerate(SPLITS):
                ret=int(returned[pi,si])
                nHits=int(hits[pi])
                entry={
                  "model":model,"raceSelector":rank,"ticketPair":name,
                  "betType1Yen":one,"betType2Yen":two,"racesPerVenueDay":k,
                  "metrics":{
                    "venueDays":nDays,"races":nDays*k,"hitRaces":nHits,
                    "hitRacePct":round(100*nHits/(nDays*k),2),
                    "stakeYen":allStake,"returnYen":ret,
                    "roiPct":round(100*ret/allStake,2),
                    "roiMinusLargestPaidRacePct":round(100*(ret-int(largest[pi,si]))/allStake,2),
                    "netYen":ret-allStake
                  }
                }
                entries.append(entry)
    return entries

def paired_quality(m):
    # Rates are not guaranteed profitable. Both metrics enter every ranking,
    # and one largest jackpot is held out for ROI quality risk.
    hit=m["hitRacePct"]
    roi=m["roiPct"]
    robust=m["roiMinusLargestPaidRacePct"]
    return round((hit/45)*(min(roi,180)/100)*(min(robust,150)/100),6)

def crossvalidate(byyear):
    key=lambda e:(e["model"],e["raceSelector"],e["ticketPair"],
                  e["betType1Yen"],e["betType2Yen"],e["racesPerVenueDay"])
    past={key(x):x for x in byyear["2024"]}
    fut={key(x):x for x in byyear["2025"]}
    assert len(past)==len(fut) and len(past)>=5000,(len(past),len(fut))
    ranked=sorted(past.values(),key=lambda x:(-paired_quality(x["metrics"]),
            -x["metrics"]["hitRacePct"],str(key(x))))
    candidate_top40=ranked[:40]
    def evidence(e):
        identity=key(e)
        return {"policy":{k:v for k,v in e.items() if k!="metrics"},
                "discovery2024":e["metrics"],"validation2025":fut[identity]["metrics"],
                "discoverComposite":paired_quality(e["metrics"]),
                "validationComposite":paired_quality(fut[identity]["metrics"])}
    shortlisted=[evidence(x) for x in candidate_top40]
    winner=shortlisted[0]
    # Report ALL shortlisted, rather than cherry-pick the 2025 winner after viewing it.
    # The top candidate is frozen by *2024 alone* and 2025 is evaluated exactly once.
    inpositive=sum(z["validation2025"]["roiPct"]>=100 and
                   z["validation2025"]["hitRacePct"]>=40 for z in shortlisted)
    bymodel={}
    for name in MODELS:
        opts=[v for v in past.values() if v["model"]==name]
        best=sorted(opts,key=lambda x:-paired_quality(x["metrics"]))[0]
        bymodel[name]=evidence(best)
    return {"candidateUniverse":len(past),
            "selectionPredeclared":"2024 only. 2025 never used to pick a winner",
            "best2024SelectedAnd2025ForwardEvaluated":winner,
            "top40By2024WithPaired2025Validation":shortlisted,
            "top40With2025HitAtLeast40AndROIAtLeast100":inpositive,
            "one2024WinnerPerModelAndIts2025Validation":bymodel,
            "2025WasPreviouslyInspected":True,
            "productionEligible":False}

def selftest():
    research=check_protocol()
    example=np.zeros((3,5,2,2),dtype=np.int32)
    # 1,000 + 1,000 yen ticket per race; one first win pays 400 yen per 100 yen.
    example[0,0,0,0]=400
    x=evaluate_matrix(example,["2024-05","2024-06","2024-07"],["pair0","pair1"],"a","b")
    a=next(z for z in x if z["ticketPair"]=="pair0" and z["racesPerVenueDay"]==3
        and z["betType1Yen"]==1000)
    assert a["metrics"]=={"venueDays":3,"races":9,"hitRaces":1,
       "hitRacePct":11.11,"stakeYen":18000,"returnYen":4000,
       "roiPct":22.22,"roiMinusLargestPaidRacePct":0.0,"netYen":-14000},a
    b=next(z for z in x if z["ticketPair"]=="pair1" and z["racesPerVenueDay"]==3
        and z["betType1Yen"]==1000)
    assert b["metrics"]["hitRacePct"]==0 and b["metrics"]["roiPct"]==0
    print("MULTIFAMILY_YEARWISE_PAIRED_HIT_ROI_SELFTEST_OK",
          json.dumps({"eligiblePairCount":len(research.PAIRS)}),flush=True)

def run():
    research=check_protocol()
    hist=module("scripts/postaug-support-chronological-56feature-validation.py","multifamily_hist")
    audit=module("scripts/research-extra-trees-2024-2025-paired-jra.py","multifamily_d1")
    data=hist.load_bundles(hist.load_public_archive())
    core=hist.core_module()
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,data)
    meta=audit.eligible_metadata(data)
    assert len(meta)==len(counts)
    assert all(meta[i]["date"]==str(dates[i]) and meta[i]["field"]==int(counts[i])
               for i in range(len(counts)))
    print("MULTIFAMILY_HISTORY_FEATURES_READY",len(counts),len(y),flush=True)
    # One bounded D1 fetch per month: reused for ALL four model families, all
    # rankers, all ticket pairs, all stake splits, every race (no repeated D1).
    pay,monthCoverage=audit.payout_book()
    outputs={}
    exclusions={}
    yearcounts={}
    pairnames=tuple(research.PAIRS)
    pairs=tuple(research.PAIRS.values())
    for year in YEARS:
        models,trainingRaces=train_models(hist,X,y,offsets,dates,year)
        complete,excluded,nTarget=assemble_year(hist,year,X,dates,counts,offsets,meta,models,pay)
        assert len(complete)>=100
        exclusions[str(year)]=excluded
        yearcounts[str(year)]={"trainingRaces":trainingRaces,
            "targetEligibleRaces":nTarget,"validCompleteVenueDays":len(complete)}
        entries=[]
        for name in MODELS:
            for rule in RULES:
                mat,months=build_matrices(complete,name,pairs,rule)
                entries.extend(evaluate_matrix(mat,months,pairnames,name,rule))
        outputs[str(year)]=entries
        print("MULTIFAMILY_YEAR_PRECOMPUTED",year,
            json.dumps({"candidateCount":len(entries),"coverage":yearcounts[str(year)],
                        "exclusions":excluded},ensure_ascii=False),flush=True)
        del models
    comparison=crossvalidate(outputs)
    report={"classification":"RETROSPECTIVE_YEARWISE_RESEARCH_NOT_T15_DEPLOYABLE",
        "dataLeakProtection":"models fitted only using years strictly before each eval year; same-day updates disallowed",
        "decisionInfo":"Only historical pre-result 56 feature vector, no archived odds",
        "settlementInfo":"Real JRA six-market D1 payout table; hypothetical pre-result-selected tickets",
        "notPristine2025":"2024/25 previously inspected in prior studies; strict chronological split but not untouched selection audit",
        "promotionEligible":False,
        "featureProvenanceT15Verified":False,
        "officialPreT15Odds":False,
        "candidateModels":MODELS,"rankers":RULES,
        "ticketPairCount":len(pairnames),"candidateCount":comparison["candidateUniverse"],
        "stakeSplits":SPLITS,"venueDayRaceCounts":K_VALUES,
        "sameVenueDayCohortForAllModels":True,
        "yearCoverage":yearcounts,"invalidVenueDays":exclusions,
        "payoutMonthCoverage":monthCoverage,
        "comparison":comparison,
        "requiredNext":"Freeze candidate and gather prospective before-T15 future JRA official market snapshots with same paired hit+ROI and missing-date accounting"}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MULTIFAMILY_CHRONO_PAIRED_COMPARE",json.dumps({
        "candidates":comparison["candidateUniverse"],
        "years":yearcounts,"selected":comparison["best2024SelectedAnd2025ForwardEvaluated"],
        "top40ForwardProfitableAndHit40":comparison["top40With2025HitAtLeast40AndROIAtLeast100"],
        "perFamily":comparison["one2024WinnerPerModelAndIts2025Validation"],
        "promotionEligible":False},ensure_ascii=False),flush=True)

if __name__=="__main__":
    if "--self-test" in sys.argv:selftest()
    else:run()
