#!/usr/bin/env python3
"""Prospective-style 2026-08..11 chronology-safe independent model search.
RESEARCH ONLY: no D1 writes, no publishing, no bet edits, no odds reconstruction.
All predictions use runner state strictly before the target race-day. Settlement
comes only from D1 actual JRA payouts; hit and ROI ALWAYS use identical tickets.
The Aug-Nov dates have already been inspected in earlier work, hence results
are retrospective and NOT untouched future proof.
"""
from __future__ import annotations
import collections
import datetime as dt
import importlib.util
import itertools
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier

ROOT=Path(__file__).resolve().parents[1]
START="2026-08-10"
END="2026-11-08"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
DEFAULT_TICKET={"単勝":(0,),"ワイド":(0,1),"馬連":(0,1),
                "馬単":(0,1),"3連複":(0,1,2),"3連単":(0,1,2)}
PAIRS={a+"__"+b:((a,DEFAULT_TICKET[a]),(b,DEFAULT_TICKET[b]))
       for a,b in itertools.combinations(TYPES,2)}
# Additional predeclared horse/position variants, no outcome-based construction.
PAIRS.update({
 "win1_wide12":(("単勝",(0,)),("ワイド",(0,1))),
 "win2_wide12":(("単勝",(1,)),("ワイド",(0,1))),
 "win3_wide12":(("単勝",(2,)),("ワイド",(0,1))),
 "win1_wide13":(("単勝",(0,)),("ワイド",(0,2))),
 "win2_wide13":(("単勝",(1,)),("ワイド",(0,2))),
 "wide13_quinella12":(("ワイド",(0,2)),("馬連",(0,1))),
 "wide23_quinella12":(("ワイド",(1,2)),("馬連",(0,1))),
 "wide12_quinella13":(("ワイド",(0,1)),("馬連",(0,2))),
 "wide12_exacta21":(("ワイド",(0,1)),("馬単",(1,0))),
 "wide12_exacta12":(("ワイド",(0,1)),("馬単",(0,1))),
 "win2_quinella12":(("単勝",(1,)),("馬連",(0,1))),
 "win1_trio123":(("単勝",(0,)),("3連複",(0,1,2))),
 "win2_trio123":(("単勝",(1,)),("3連複",(0,1,2))),
 "win1_exacta12":(("単勝",(0,)),("馬単",(0,1))),
 "wide12_trifecta123":(("ワイド",(0,1)),("3連単",(0,1,2))),
 "win1_quinella12":(("単勝",(0,)),("馬連",(0,1))),
 "wide12_quinella12":(("ワイド",(0,1)),("馬連",(0,1))),
 "wide12_trio123":(("ワイド",(0,1)),("3連複",(0,1,2))),
})
KS=(3,4,5)
STAKES=((1000,1000),(1400,600),(600,1400),(1800,200),(200,1800))
RANKERS=("top1","top2","gap","top3","entropy")
RESEARCH_OUTPUT=ROOT/"analysis-results/postaug-independent-paired-model-search-20261107.json"

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader: raise RuntimeError("MISSING_HELPER:"+str(path))
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def nums(s):
    values=tuple(int(n) for n in re.findall(r"\d+",str(s)))
    return values

def official_paid(payout,typ,horses,stake):
    key=tuple(sorted(horses)) if typ in UNORDERED else tuple(horses)
    return stake*int(payout.get((typ,key),0))//100

def settle(record, ranking, pair, split):
    horses=record["horses"]
    if len(horses)<3 or len(set(horses))!=len(horses):
        raise ValueError("INVALID_RUNNER_SET")
    paid=0
    winning_tickets=0
    for (typ,ix),stake in zip(pair,split):
        chosen=tuple(horses[ranking[j]] for j in ix)
        ret=official_paid(record["payout"],typ,chosen,stake)
        paid+=ret
        winning_tickets+=int(ret>0)
    return {"stake":sum(split),"return":paid,"hit":int(winning_tickets>0),
            "winningTickets":winning_tickets,"profit":int(paid>sum(split))}

def self_test():
    example={"horses":(1,2,3,4),"payout":{
        ("単勝",(1,)):250,("ワイド",(1,2)):170,
        ("馬連",(1,2)):760,("馬単",(1,2)):1430,
        ("3連複",(1,2,3)):2200,("3連単",(1,2,3)):9400}}
    for typ in TYPES:
        assert all(p[0]!=p[1] for p in PAIRS.values())
    win=settle(example,(0,1,2,3),PAIRS["win1_wide12"],(1000,1000))
    assert win=={"stake":2000,"return":4200,"hit":1,"winningTickets":2,"profit":1},win
    lose=settle(example,(3,2,1,0),PAIRS["win1_wide12"],(1000,1000))
    assert lose["return"]==0 and lose["hit"]==0
    assert official_paid(example["payout"],"馬連",(2,1),1000)==7600
    print("PAIRED_INDEPENDENT_MODEL_SELFTEST_OK",flush=True)

def gather_data():
    live=load("scripts/postaug-support-aug-nov-frozen-policy-recheck.py","postaug_d1_helper")
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","postaug_hist_helper")
    calendar=hist.load_public_archive()
    history=hist.load_bundles(calendar)
    core=hist.core_module()
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,history)
    assert dates[-1]=="2026-08-09" or dates[-1]<START
    # All 10-year archive labels are prior to our evaluation period.
    bydate,_=live.d1_bundles()
    pay=collections.defaultdict(dict)
    source_rows=0
    for month in ("2026-08","2026-09","2026-10","2026-11"):
        d1=month+"-01"
        until=(dt.date.fromisoformat(d1)+dt.timedelta(days=35)).replace(day=1).isoformat()
        rows=live.d1_query("""
          SELECT race_id raceId,bet_type betType,combination,payout_yen payoutYen
          FROM rt_payouts WHERE race_id>=? AND race_id<?
            AND bet_type IN ('単勝','ワイド','馬連','馬単','3連複','3連単')
          ORDER BY race_id,bet_type,combination LIMIT 5000
        """,[month+"-",until[:7]+"-"])
        if len(rows)>=5000: raise RuntimeError("PAYOUT_QUERY_TRUNCATED:"+month)
        for row in rows:
            typ=row["betType"]
            combo=nums(row["combination"])
            combo=tuple(sorted(combo)) if typ in UNORDERED else combo
            if len(combo)!=(1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2):
                raise ValueError("INVALID_JRA_PAYOUT_COMBO")
            amount=int(row["payoutYen"])
            if amount<0 or amount%10: raise ValueError("INVALID_OFFICIAL_PAYOUT")
            key=(typ,combo)
            rid=row["raceId"]
            if key in pay[rid] and pay[rid][key]!=amount:
                raise ValueError("CONFLICTING_JRA_PAYOUT")
            pay[rid][key]=amount
            source_rows+=1
    print("AUGNOV_SIX_TYPE_PAYOUT_ROWS",source_rows,flush=True)
    models={}
    for name, params in hist.CANDIDATES.items():
        model=hist.fit(X,y,offsets,np.arange(len(counts)),params)
        models[name]=model
        print("FITTED_MODEL",name,flush=True)
    extra=ExtraTreesClassifier(n_estimators=120,max_depth=14,min_samples_leaf=35,
                               max_features=0.7,n_jobs=2,random_state=20261107)
    extra.fit(X,y)
    models["independent_extra_trees_120"]=extra
    print("FITTED_MODEL independent_extra_trees_120",flush=True)
    # Persist the ACTUALLY FITTED independent model for reproducibility.
    # Research artifact only: no Worker integration, no D1 or public changes.
    import hashlib
    import joblib
    package=ROOT/"analysis-results/model-packages"
    package.mkdir(parents=True,exist_ok=True)
    filename=package/"postaug-extra-trees-120.joblib"
    joblib.dump(extra,filename,compress=3)
    reopened=joblib.load(filename)
    if not np.allclose(reopened.predict_proba(X[:40]),extra.predict_proba(X[:40]),atol=0,rtol=0):
        raise AssertionError("EXPORTED_MODEL_PREDICTION_PARITY_FAILED")
    digest=hashlib.sha256(filename.read_bytes()).hexdigest()
    manifest={"name":"postaug-extra-trees-120-research-v1",
      "algorithm":"sklearn.ensemble.ExtraTreesClassifier",
      "trainingDataEndDate":"2026-08-09","trainingUsesAugNovOutcomeLabels":False,
      "trainingRunnerRows":int(len(y)),"trainingRaces":int(len(counts)),
      "featureOrder":list(core.load_config()["runnerProbabilityModel"]["features"]),
      "featureCount":len(core.load_config()["runnerProbabilityModel"]["features"]),
      "trainingParameters":extra.get_params(),
      "modelArtifactSha256":digest,"artifactBytes":filename.stat().st_size,
      "frozenResearchTicketRule":{"model":"independent_extra_trees_120",
        "raceRank":"top3","tickets":"wide12_quinella13",
        "stakesYen":[200,1800],"racesPerVenueDay":3},
      "selectionStatus":"RETROSPECTIVE_HINDSIGHT_NOT_APPROVED_FOR_LIVE",
      "requiresProspectiveForwardAudit":True}
    (package/"postaug-extra-trees-120-manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("POSTAUG_EXTRATREES_SERIALIZED_PARITY_OK",json.dumps({
        "sha256":digest,"bytes":filename.stat().st_size,
        "trainingRows":len(y),"features":manifest["featureCount"]}),flush=True)
    del X,y,counts,dates,offsets
    state=hist.fresh_feature_state()
    for date,day in sorted(history.items()):
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    if state["throughDate"]!="2026-08-09":
        raise RuntimeError("ARCHIVE_STATE_DATE_MISMATCH")
    feat=tuple(core.load_config()["runnerProbabilityModel"]["features"])
    records=[]
    for date,day in sorted(bydate.items()):
        features=[]
        metadata=[]
        for bundle in sorted(day,key=lambda x:(x["race"]["venue"],int(x["race"]["raceNo"]))):
            r=bundle["race"]
            if not START<=date<END:continue
            active=sorted((a for a in bundle["runners"] if a.get("runnerStatus") in (None,"","active")),key=lambda x:int(x["horseNo"]))
            valid=bool(r["status"]=="finished" and len(active)>=3 and
                sum(x.get("finishPosition")==1 for x in bundle["results"])==1)
            if not valid:
                records.append({"date":date,"venue":r["venue"],"raceNo":int(r["raceNo"]),
                                "invalid":"missing_runner_or_result"})
                continue
            rows=[[float(core.ml_feature_row(state,r,x,len(active))[f]) for f in feat] for x in active]
            if not np.isfinite(rows).all():raise ValueError("NONFINITE_PRE_RESULT_FEATURE")
            features.extend(rows)
            metadata.append((r,active,len(rows)))
        if features:
            mat=np.asarray(features,dtype=np.float32)
            raw={name:model.predict_proba(mat)[:,1] for name,model in models.items()}
            left=0
            for r,active,n in metadata:
                probabilities={}
                for name,p in raw.items():
                    tmp=np.maximum(p[left:left+n],1e-12)
                    probabilities[name]=tmp/tmp.sum()
                probabilities["ensemble_all"]=sum(probabilities.values())/len(probabilities)
                probabilities["ensemble_gbm_only"]=(probabilities["adopted_complexity_500x127"]+
                    probabilities["regularized_150x31"])/2
                payout=pay.get(r["raceId"],{})
                types={k[0] for k in payout}
                rec={"date":date,"venue":r["venue"],"raceNo":int(r["raceNo"]),
                     "raceId":r["raceId"],"horses":tuple(int(v["horseNo"]) for v in active),
                     "payout":payout,"probabilities":probabilities}
                if set(TYPES)!=types:rec["invalid"]="INCOMPLETE_SIX_MARKET_JRA_PAYOUT"
                records.append(rec)
                left+=n
            assert left==len(mat)
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    print("AUGNOV_MODEL_ROWS",len(records),flush=True)
    return records

def summarize(outcomes):
    n=len(outcomes)
    stake=sum(x["stake"] for x in outcomes)
    ret=sum(x["return"] for x in outcomes)
    hits=sum(x["hit"] for x in outcomes)
    maximum=max((x["return"] for x in outcomes),default=0)
    return {"races":n,"hitRaces":hits,"hitRacePct":round(100*hits/n,2) if n else None,
            "returnYen":ret,"stakeYen":stake,"roiPct":round(100*ret/stake,2) if stake else None,
            "profitYen":ret-stake,"winningTickets":sum(x["winningTickets"] for x in outcomes),
            "trimmedLargestRaceRoiPct":round(100*(ret-maximum)/stake,2) if stake else None}

def rankscore(p,rule):
    order=np.argsort(-p,kind="stable")
    if rule=="top1":return float(p[order[0]])
    if rule=="top2":return float(p[order[0]]+p[order[1]])
    if rule=="gap":return float(p[order[0]]-p[order[1]])
    if rule=="top3":return float(p[order[0]]+p[order[1]]+p[order[2]])
    if rule=="entropy":return float(-sum(q*math.log(q) for q in p))
    raise ValueError(rule)

def run(records):
    all_groups=collections.defaultdict(list)
    for r in records:all_groups[(r["date"],r["venue"])].append(r)
    good={}
    exclusions=collections.Counter()
    for group,rows in all_groups.items():
        if len(rows)!=12 or {r["raceNo"] for r in rows}!=set(range(1,13)):
            exclusions["VENUE_DAY_NOT_12_RACES"]+=1;continue
        if any(r.get("invalid") for r in rows):
            exclusions["VENUE_DAY_MISSING_FINISH_OR_SIX_PAYOUTS"]+=1;continue
        good[group]=rows
    if len(good)<10:raise RuntimeError("INSUFFICIENT_COMPLETE_VENUE_DAYS:"+str(len(good))+" "+str(dict(exclusions)))
    print("AUGNOV_COMPLETE_VENUE_DAYS",len(good),json.dumps(dict(exclusions)),flush=True)
    names=("adopted_complexity_500x127","regularized_150x31",
           "independent_extra_trees_120","ensemble_all","ensemble_gbm_only")
    strategies=[]
    for name,ranking,pair,stakes,k in itertools.product(names,RANKERS,PAIRS,STAKES,KS):
        byperiod=collections.defaultdict(list)
        dates=collections.defaultdict(set)
        for (day,venue),rows in good.items():
            selection=sorted(rows,key=lambda row:(-rankscore(row["probabilities"][name],ranking),row["raceNo"]))[:k]
            for row in selection:
                order=tuple(int(i) for i in np.argsort(-row["probabilities"][name],kind="stable"))
                result=settle(row,order,PAIRS[pair],stakes)
                period="trainAugSep" if day<"2026-10-01" else "validateOct" if day<"2026-11-01" else "testNov"
                byperiod[period].append(result)
                dates[period].add(day)
        stats={p:summarize(byperiod[p]) for p in ("trainAugSep","validateOct","testNov")}
        for p in stats:stats[p]["days"]=len(dates[p])
        if stats["trainAugSep"]["races"]<30 or stats["validateOct"]["races"]<20 or stats["testNov"]["races"]<5:
            continue
        strategies.append({"model":name,"raceRanker":ranking,"tickets":pair,
          "stakeSplitYen":stakes,"racesPerVenueDay":k,"periods":stats,
          "all":summarize(sum(byperiod.values(),[]))})
    if not strategies:raise RuntimeError("NO_FULL_CHRONOLOGICAL_STRATEGIES")
    def dual(s,period):
        a=s["periods"][period]
        # BOTH dimensions required, never maximize ROI or hit rate alone.
        return min(a["roiPct"]/100,a["hitRacePct"]/35)*(
            0.5*a["roiPct"]/100+0.5*a["hitRacePct"]/35)
    # Discovery ONLY on Aug+Sep; freeze top 40, then use October to choose one.
    shortlist=sorted(strategies,key=lambda x:(-dual(x,"trainAugSep"),
        -x["periods"]["trainAugSep"]["hitRacePct"],str(x["model"])))[:40]
    chosen=sorted(shortlist,key=lambda x:(-dual(x,"validateOct"),
        -x["periods"]["validateOct"]["hitRacePct"],str(x["model"])))[0]
    topnov=sorted(shortlist,key=lambda x:(-dual(x,"testNov"),str(x["model"])))[:5]
    evidence={"status":"RETROSPECTIVE_2026_POSTAUG_RESEARCH_ONLY",
      "notFreshHoldout":"2026 Aug-Nov dates were inspected in earlier studies; no prospective superiority claim",
      "notActualPreT15TicketRecord":"2026 actual JRA payouts; hypothetical tickets selected from pre-result runner features, no after-race odds used",
      "noProductionMutation":True,"noD1Writes":True,
      "candidateCount":len(strategies),"completeVenueDays":len(good),
      "venueDaysRejected":dict(exclusions),
      "chosenByAugSepDiscoveryThenOctoberValidation":chosen,
      "topFiveOctoberValidationAmongAugSepFrozen40":sorted(shortlist,key=lambda x:-dual(x,"validateOct"))[:5],
      "topFiveNovemberHindsightDiagnosticNOTSelection":topnov,
      "highestOverallRoiWithAtLeast50PctHitInAllThreePeriods_DIAGNOSTIC_ONLY":
         sorted((s for s in strategies if all(s["periods"][p]["hitRacePct"]>=50 for p in
             ("trainAugSep","validateOct","testNov"))),
           key=lambda s:-s["all"]["roiPct"])[:10],
      "highestOverallHitWithAtLeast90PctRoi_DIAGNOSTIC_ONLY":
         sorted((s for s in strategies if s["all"]["roiPct"]>=90),
           key=lambda s:-s["all"]["hitRacePct"])[:10],
      "profitableEveryPeriodWithAtLeast35PctHit_DIAGNOSTIC_ONLY":
         sorted((s for s in strategies if all(s["periods"][p]["roiPct"]>=100 and
             s["periods"][p]["hitRacePct"]>=35 for p in
             ("trainAugSep","validateOct","testNov"))),
           key=lambda s:-s["all"]["roiPct"])[:10],
      "strategyRequirements":"3/4/5 per venue and exactly two distinct JRA bet types, original Light budget 2000 yen per race",
      "promotionEligible":False}
    RESEARCH_OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    RESEARCH_OUTPUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PAIRED_MODEL_SELECTION_AND_FUTURE_DIAGNOSTIC",json.dumps({
      "strategyCount":len(strategies),"completeVenueDays":len(good),
      "chosen":chosen,"top5Validation":evidence["topFiveOctoberValidationAmongAugSepFrozen40"],
      "bestAllRoiAtLeast50Hit":evidence["highestOverallRoiWithAtLeast50PctHitInAllThreePeriods_DIAGNOSTIC_ONLY"][:3],
      "bestAllHitAtLeast90Roi":evidence["highestOverallHitWithAtLeast90PctRoi_DIAGNOSTIC_ONLY"][:3],
      "allPeriodsProfitable":evidence["profitableEveryPeriodWithAtLeast35PctHit_DIAGNOSTIC_ONLY"][:3],
      "promotionEligible":False},ensure_ascii=False),flush=True)

def main():
    if "--self-test" in sys.argv:self_test();return
    records=gather_data()
    run(records)

if __name__=="__main__":main()
