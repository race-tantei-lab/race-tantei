#!/usr/bin/env python3
"""Offline independent 2026 horse-head study: genuine training, no D1 or odds.

Uses immutable archive races 2016-08-10 through 2026-08-09.
Runner 56-vectors are built chronologically; models fit ONLY through 2025.
2026 winner outcomes reserved solely for scoring and never fitted.
This is prediction-quality research ONLY, not a real JRA betting ROI claim.
Archived T-15 runner provenance is not established.
"""
from __future__ import annotations
from pathlib import Path
import importlib.util,json,sys
from collections import defaultdict
import numpy as np
import joblib
from lightgbm import LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-new-horse-heads-chronological-2026.json"
MODEL=ROOT/"analysis-results/nov2026-new-horse-heads-pre2026.joblib"

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m

def evaluate(dates,counts,offsets,y,probs,first_index,last_index):
    allscore=[]
    bymonth=defaultdict(list)
    cursor=0
    for idx in range(first_index,last_index+1):
        n=int(counts[idx])
        v=np.asarray(probs[cursor:cursor+n],dtype=float)
        cursor+=n
        if len(v)!=n or not np.isfinite(v).all():raise ValueError("MODEL_SCORE_ALIGNMENT_FAILED")
        if np.min(v)<0: raise ValueError("NEGATIVE_PROBABILITY")
        v=v/np.sum(v)
        start=int(offsets[idx]);end=int(offsets[idx+1])
        truth=np.flatnonzero(y[start:end])
        if len(truth)!=1:raise ValueError("NOT_UNIQUE_RACE_WINNER")
        winner=int(truth[0])
        record={
          "hitTop1":int(int(np.argmax(v))==winner),
          "hitTop3":int(winner in np.argsort(-v)[:3]),
          "winnerLogloss":float(-np.log(max(1e-15,v[winner]))),
          "winnerBrier":float(np.sum((v-np.eye(1,n,winner)[0])**2)/n)
        }
        allscore.append(record);bymonth[str(dates[idx])[:7]].append(record)
    assert cursor==len(probs)
    def summary(rows):
        n=len(rows)
        return {"races":n,"top1Pct":round(100*sum(r["hitTop1"] for r in rows)/n,4),
          "top3Pct":round(100*sum(r["hitTop3"] for r in rows)/n,4),
          "winnerLogloss":round(sum(r["winnerLogloss"] for r in rows)/n,6),
          "winnerBrier":round(sum(r["winnerBrier"] for r in rows)/n,6)}
    return {"aggregate":summary(allscore),"byMonth":{m:summary(v) for m,v in sorted(bymonth.items())}}

def main():
    import os
    for key in ("CLOUDFLARE_API_TOKEN","CLOUDFLARE_D1_DATABASE_ID"):
        if os.getenv(key):raise RuntimeError("OFFLINE_NO_D1_ENVIRONMENT_ALLOWED:"+key)
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","robust_offline_archive")
    robust=load("scripts/research-nov2026-fresh-robust200.py","robust_offline_new")
    struct=load("scripts/research-structural-ranker-twohead-2025.py","robust_offline_top3")
    byday=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),byday)
    top3=struct.top3_targets(byday)
    if not (len(X)==len(y)==len(top3) and len(counts)==len(dates)):
        raise RuntimeError("RESEARCH_PRE_RESULT_DATASET_MISALIGNED")
    testids=np.flatnonzero((dates>="2026-01-01")&(dates<="2026-08-09"))
    if len(testids)<2000:raise RuntimeError("NOT_ENOUGH_UNTOUCHED_2026_RACES")
    first=int(testids[0]);last=int(testids[-1])
    assert last-first+1==len(testids)
    assert str(dates[first])>="2026-01-01" and str(dates[last])<="2026-08-09"
    end=int(offsets[first])
    assert np.max(dates[:first])<"2026-01-01"
    model,info=robust.fit_horse(X,y,top3,counts,offsets,dates,2026)
    # New genuine fitted LightGBM ranking + independent win ExtraTrees.
    score=model[0].predict(X[end:int(offsets[last+1])])
    pred=[]
    c=0
    for i in range(first,last+1):
        n=int(counts[i]);r=score[c:c+n];c+=n
        ex=np.exp(np.clip((r-np.max(r))/1.4,-60,0))
        pred.extend((ex/ex.sum()).tolist())
    assert c==len(score)
    new_eval=evaluate(dates,counts,offsets,y,np.asarray(pred),first,last)
    # Fair strictly chronological 2026 holdout baseline; not the in-sample
    # 431.65% ten-year historical bankroll number.
    base=LGBMClassifier(n_estimators=150,learning_rate=.04,num_leaves=31,
      min_child_samples=80,reg_lambda=10,reg_alpha=.5,colsample_bytree=.8,
      random_state=20260812,n_jobs=2,verbosity=-1)
    base.fit(X[:end],y[:end])
    raw=base.predict_proba(X[end:int(offsets[last+1])])[:,1]
    baseline=[]
    cursor=0
    for i in range(first,last+1):
        n=int(counts[i]);v=np.clip(raw[cursor:cursor+n],1e-12,1)
        baseline.extend((v/v.sum()).tolist());cursor+=n
    assert cursor==len(raw)
    old_eval=evaluate(dates,counts,offsets,y,np.asarray(baseline),first,last)
    MODEL.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump({
      "name":"nov2026-three-horse-heads-pre2026-research",
      "trainer":"scripts/research-nov2026-fresh-robust200.py",
      "trainThrough":"2025-12-28",
      "horseRankEnsemble":model[0],
      "horseTop3Head":model[1],
      "researchOnly":True,
      "notValidPreT15ROI":True,
      "2026WinnersUsedInTraining":False,
      "training":info
    },MODEL,compress=3)
    evidence={
      "source":"immutable 2016-08-10..2026-08-09 canonical runner archive",
      "trainThrough":"2025-12-28",
      "target":"2026-01-01..2026-08-09",
      "all2026WinLabelsReservedForScoring":True,
      "2026AlreadyInspectedBeforeModelDesign":True,
      "features":56,
      "newHorseHead":new_eval,
      "chronologicalBaseline":old_eval,
      "noJraSixMarketRoiEvaluated":True,
      "noSyntheticOrPostResultOddsUsed":True,
      "runnerT15Proven":False,
      "productionPromotionAllowed":False
    }
    OUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NOV2026_NEW_HORSE_HEADS_2026_HOLDOUT",json.dumps(
      {"new":new_eval["aggregate"],"baseline":old_eval["aggregate"],
       "trainThrough":evidence["trainThrough"],
       "notRealJraROI":True},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
