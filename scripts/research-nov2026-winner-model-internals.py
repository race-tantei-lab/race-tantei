#!/usr/bin/env python3
"""Real-data, chronological 56-feature horse winner model ablation.

Model change, not ticket-count manipulation. Fit alternative LightGBM winner
models on races through 2024, choose on 2025 only, refit through 2025, compare
with the same baseline on 2026 Jan-Aug. Tests several ways to fight drift,
calendar/draw overfitting and overcomplex trees. Market diagnostic uses
archived FINAL win odds only (never claimed T-15 or actual JRA 6-type ROI).
No Cloudflare D1 read, no production predictions/writes.
2026 outcomes have been inspected in prior research, not pristine holdout.
"""
from __future__ import annotations

from dataclasses import asdict,dataclass
from collections import defaultdict
from pathlib import Path
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np
from lightgbm import LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-real-56feature-ablation-2025-select-2026-test.json"
FROZEN_SEED=20261108

@dataclass(frozen=True)
class Candidate:
    name:str
    n_estimators:int=150
    num_leaves:int=31
    min_child_samples:int=80
    half_life_years:float=0.0
    ablate:str="none"
    reg_lambda:float=10.0

CANDIDATES=(
    Candidate("baseline_150x31_no_time_decay"),
    Candidate("recency_4yr_decay",half_life_years=4.0),
    Candidate("recency_2yr_decay",half_life_years=2.0),
    Candidate("no_draw_calendar_4yr",half_life_years=4.0,ablate="no_draw_calendar"),
    Candidate("no_weak_context_4yr",half_life_years=4.0,ablate="no_weak_context"),
    Candidate("smaller_trees_4yr",n_estimators=200,num_leaves=15,min_child_samples=140,
              reg_lambda=18.0,half_life_years=4.0),
)
ABLATE={
   "none":frozenset(),
   "no_draw_calendar":frozenset(("horseNoRaw","horseNo","frameNo",
                                 "drawPct","monthSin","monthCos","raceNo")),
   "no_weak_context":frozenset(("horseNoRaw","horseNo","frameNo",
                                "drawPct","monthSin","monthCos","raceNo",
                                "weather","trackCondition","direction",
                                "horseWeight","weightChange")),
}
TEMPERATURES=(0.85,1.0,1.15,1.35)

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("OFFLINE_RESEARCH_MODULE_NOT_FOUND")
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

def feature_columns(names:list[str],ablate:str)->np.ndarray:
    assert len(names)==56 and len(set(names))==56
    assert ablate in ABLATE
    remove=ABLATE[ablate]
    assert remove.issubset(names)
    keep=np.asarray([i for i,n in enumerate(names) if n not in remove],dtype=np.int64)
    assert len(keep)>=44
    return keep

def model_fit(X,y,counts,dates,offsets,first_test:int,candidate:Candidate,names):
    assert first_test>8000 and first_test<len(counts)
    nrows=int(offsets[first_test])
    keep=feature_columns(names,candidate.ablate)
    features=np.ascontiguousarray(X[:nrows,keep],dtype=np.float32)
    sample_weight=None
    if candidate.half_life_years:
        target_year=int(str(dates[first_test])[:4])
        years=np.asarray([int(str(z)[:4]) for z in dates[:first_test]],dtype=np.float64)
        race_w=np.exp(-math.log(2)*np.maximum(0,target_year-years)/candidate.half_life_years)
        sample_weight=np.repeat(race_w,counts[:first_test]).astype(np.float32)
        assert len(sample_weight)==nrows
    m=LGBMClassifier(n_estimators=candidate.n_estimators,learning_rate=.04,
      num_leaves=candidate.num_leaves,min_child_samples=candidate.min_child_samples,
      reg_lambda=candidate.reg_lambda,reg_alpha=.5,
      colsample_bytree=.8,random_state=FROZEN_SEED,
      n_jobs=2,verbosity=-1)
    m.fit(features,y[:nrows],sample_weight=sample_weight)
    return m,keep

def vectors(model,X,offsets,first:int,last:int,columns:np.ndarray):
    lo=int(offsets[first]);hi=int(offsets[last+1])
    raw=np.asarray(model.predict_proba(np.ascontiguousarray(X[lo:hi,columns]))[:,1],
                   dtype=np.float64)
    if len(raw)!=hi-lo or not np.all(np.isfinite(raw)):
        raise RuntimeError("NONFINITE_OR_MISALIGNED_WINNER_SCORE")
    return raw

def evaluate(raw,counts,dates,offsets,winners,first,last,temperature:float,
             market:list|None=None):
    if temperature<=0:raise ValueError("INVALID_TEMPERATURE")
    start=int(offsets[first])
    losses=[];hits=[];top3=[];market_loss=[];market_hits=[]
    record=[];month=defaultdict(list)
    for i in range(first,last+1):
        a=int(offsets[i])-start;b=int(offsets[i+1])-start
        v=np.clip(raw[a:b],1e-12,1)
        # Temperature rescales calibrated logit-free, normalized probability
        # only. It must be chosen on an earlier year, never the test period.
        v=np.power(v,1/temperature)
        p=v/v.sum()
        w=int(winners[i])
        if not (len(p)==int(counts[i]) and 0<=w<len(p)):
            raise AssertionError("HORSE_RACE_WINDOW_INVALID")
        loss=float(-np.log(max(1e-15,p[w])))
        h=int(int(np.argmax(p))==w)
        top=int(w in np.argsort(-p)[:3])
        date=str(dates[i]);day=date[:10]
        losses.append(loss);hits.append(h);top3.append(top)
        month[date[:7]].append((loss,h,top))
        record.append((day,loss))
        if market is not None:
            odds=market[i]
            if len(odds)==len(p) and all(isinstance(z,(float,int)) and np.isfinite(z) and z>1 for z in odds):
                q=np.asarray([1.0/float(z) for z in odds])
                q=q/q.sum()
                market_loss.append(float(-np.log(max(1e-15,q[w]))))
                market_hits.append(int(np.argmax(q)==w))
    def summary(seq):
        return {"races":len(seq),"winnerLogloss":round(float(np.mean([r[0] for r in seq])),7),
           "top1Pct":round(100*np.mean([r[1] for r in seq]),4),
           "top3Pct":round(100*np.mean([r[2] for r in seq]),4)}
    rows=list(zip(losses,hits,top3))
    result={"aggregate":summary(rows),
            "monthly":{k:summary(v) for k,v in sorted(month.items())},
            "pairedByDateLoss":record,
            "finalOddsMarketDiagnostic":{
                "races":len(market_loss),
                "winnerLogloss":round(float(np.mean(market_loss)),7) if market_loss else None,
                "top1Pct":round(100*float(np.mean(market_hits)),4) if market_hits else None,
                "marketOddsCapturedAtT15":False,
                "bettingRoi":None
            }}
    return result

def temperature_search(raw,counts,dates,offsets,winners,first,last):
    metrics=[]
    for t in TEMPERATURES:
        q=evaluate(raw,counts,dates,offsets,winners,first,last,t)
        metrics.append((t,q["aggregate"]))
    metrics.sort(key=lambda row:(row[1]["winnerLogloss"],-row[1]["top1Pct"],row[0]))
    return metrics[0],metrics

def days_bootstrap_baseline_vs_champion(baseline,champion,seed:int=FROZEN_SEED):
    first=defaultdict(list);second=defaultdict(list)
    for d,loss in baseline["pairedByDateLoss"]:first[d].append(loss)
    for d,loss in champion["pairedByDateLoss"]:second[d].append(loss)
    assert set(first)==set(second)
    day_diff=[]
    for day in sorted(first):
        assert len(first[day])==len(second[day])
        day_diff.append((float(np.sum(first[day])-np.sum(second[day])),len(first[day])))
    rng=np.random.default_rng(seed)
    ix=np.arange(len(day_diff))
    vals=np.asarray(day_diff)
    boot=[]
    for _ in range(400):
        sample=rng.choice(ix,size=len(ix),replace=True)
        rows=vals[sample]
        boot.append(float(rows[:,0].sum()/rows[:,1].sum()))
    return {
      "baselineMinusWinnerLogloss":round(float(vals[:,0].sum()/vals[:,1].sum()),7),
      "95PctDateClusterBootstrap":[round(float(z),7) for z in np.quantile(boot,[.025,.975])],
      "dates":len(first),
      "positiveMeansCandidateImproves":True}

def self_test():
    names=[f"x{i}" for i in range(44)]+["horseNoRaw","horseNo","frameNo","drawPct",
     "monthSin","monthCos","raceNo","weather","trackCondition","direction","horseWeight","weightChange"]
    assert len(feature_columns(names,"no_draw_calendar"))==49
    assert len(feature_columns(names,"no_weak_context"))==44
    counts=np.asarray([3,4,3])
    offsets=np.asarray([0,3,7,10])
    dates=np.asarray(["2025-01-01","2025-01-02","2025-01-03"])
    winners=np.asarray([0,1,2])
    raw=np.asarray([.7,.2,.1,.1,.3,.5,.1,.1,.2,.6])
    outcome=evaluate(raw,counts,dates,offsets,winners,0,2,1)
    assert outcome["aggregate"]["races"]==3
    assert outcome["aggregate"]["top1Pct"]==round(100*2/3,4)
    assert outcome["finalOddsMarketDiagnostic"]["bettingRoi"] is None
    assert len(CANDIDATES)>=5
    print("REAL_56FEATURE_MODEL_ABLATION_TEST_READY_NO_D1")

def main():
    if "--self-test" in sys.argv:self_test();return
    for key in ("CLOUDFLARE_API_TOKEN","CLOUDFLARE_D1_DATABASE_ID"):
        if os.getenv(key):raise RuntimeError("OFFLINE_ONLY_MODEL_STUDY_NO_D1_CREDENTIALS")
    start=time.monotonic()
    archive=load("scripts/postaug-support-chronological-56feature-validation.py","ablation_archive")
    core=archive.core_module()
    byday=archive.load_bundles(archive.load_public_archive())
    X,y,counts,dates,offsets,winners,dropped,race_count,market=archive.chronological_features(core,byday)
    feature_names=list(core.load_config()["runnerProbabilityModel"]["features"])
    available=np.asarray([int(str(v)[:4]) for v in dates])
    val=np.flatnonzero(available==2025)
    test=np.flatnonzero(available==2026)
    if len(val)<2000 or len(test)<2000 or val[-1]+1!=test[0]:
        raise RuntimeError("NONCHRONOLOGICAL_2025_2026_SPLITS")
    assert str(dates[val[0]-1])<"2025-01-01"
    assert str(dates[test[0]-1])<"2026-01-01"
    const=[feature_names[i] for i in range(56) if np.std(X[:int(offsets[val[0]]),i])<1e-8]
    print("HORSE_MODEL_FEATURE_ABLATION_PROVENANCE",json.dumps({
      "sourceRaces":race_count,"eligible":len(counts),"trainThrough2024":int(val[0]),
      "2025ValidationRaces":len(val),"2026EvaluationRaces":len(test),
      "constantFeaturesThrough2024":const}),flush=True)
    fit25=[]
    for c in CANDIDATES:
        model,cols=model_fit(X,y,counts,dates,offsets,int(val[0]),c,feature_names)
        raw=vectors(model,X,offsets,int(val[0]),int(val[-1]),cols)
        (temp,chosen),full_grid=temperature_search(raw,counts,dates,offsets,winners,int(val[0]),int(val[-1]))
        fit25.append((chosen["winnerLogloss"],c,temp,chosen,full_grid))
        print("HORSE_MODEL_2025_VALIDATION",c.name,json.dumps({
          "temperature":temp,"validation":chosen,"predictors":len(cols),
          "halflifeYears":c.half_life_years},ensure_ascii=False),flush=True)
        del model
    fit25.sort(key=lambda x:(x[0],x[1].name))
    _,winner,temperature,chosen,_=fit25[0]
    out={}
    for c,t in [(CANDIDATES[0],1.0),(winner,temperature)]:
        label="baseline" if c==CANDIDATES[0] and t==1.0 else "chosenBy2025"
        model,cols=model_fit(X,y,counts,dates,offsets,int(test[0]),c,feature_names)
        raw=vectors(model,X,offsets,int(test[0]),int(test[-1]),cols)
        q=evaluate(raw,counts,dates,offsets,winners,int(test[0]),int(test[-1]),t,market)
        out[label]=q
        print("HORSE_MODEL_2026_FIXED_POLICY",label,c.name,json.dumps({
          "temperature":t,"metrics":q["aggregate"],
          "diagnosticMarket":q["finalOddsMarketDiagnostic"]
        },ensure_ascii=False),flush=True)
        del model
    # If the baseline is the chosen model, both evaluations must coincide;
    # explicitly mark true tie rather than count a false improvement.
    comp=days_bootstrap_baseline_vs_champion(out["baseline"],out["chosenBy2025"])
    for q in out.values():q.pop("pairedByDateLoss")
    report={
      "classification":"REAL_2025_SELECTED_2026_WINNER_MODEL_ONLY",
      "2026RunnerFeaturesHistoricalT15Verified":False,
      "2026AlreadyInspectedByPriorResearchers":True,
      "2026LabelsUsedToFitOrSelect":False,
      "trainThrough2024Validate2025SelectCandidate":True,
      "retrainThrough2025ThenScore2026":True,
      "actualSixMarketJraRoiComputed":False,
      "actualSixMarketJraRoiPct":None,
      "trainingFeatureCount":56,
      "featureConstantThrough2024":const,
      "candidateModels":[{"candidate":asdict(c),"selectedTempOn2025":t,
        "2025Validation":v} for _,c,t,v,_ in fit25],
      "frozen2025SelectedCandidate":asdict(winner),
      "frozen2025Temperature":temperature,
      "year2026":out,
      "clusteredDifference":comp,
      "notProfitableInProductionProven":True,
      "productionPromotionAllowed":False,
      "elapsedSeconds":round(time.monotonic()-start,1)
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("HORSE_MODEL_INTERNALS_2026_ACTUAL_RESULT",json.dumps({
      "winner":winner.name,"temperature":temperature,
      "2026Winner":out["chosenBy2025"]["aggregate"],
      "2026Baseline":out["baseline"]["aggregate"],
      "pairedLoglossDelta":comp,
      "notActualJraRoi":True},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
