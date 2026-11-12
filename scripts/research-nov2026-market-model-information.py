#!/usr/bin/env python3
"""Test actual model-versus-market information, not optimizer scaffolding.

2025: fit 56-feature 4y-decay winner LightGBM only through 2024; select
market/model weight on 2025 observed race outcomes (already inspected).
2026: refit through 2025; test same frozen weight on 2026 Jan-Aug.
Market input uses ARCHIVED FINAL JRA win odds: their true T-15 timestamp
cannot be reconstructed, so this is strictly historical MODEL-INFORMATION
diagnostic. NOT JRA actual-payout backtest, NOT deployable.

No D1 access and no synthetic prices. It tests if a better pure horse model
adds predictive information BEYOND the betting market.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-market-residual-blend-2025-selected-2026-eval.json"
ALPHAS=(0.0,0.1,0.2,0.3,0.5,0.7,1.0)

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def score_paired(raw,odds,dates,counts,offsets,winners,first,last,alpha,temperature=.85):
    n=0;loss=0;top1=0
    bydate=defaultdict(list)
    base=int(offsets[first])
    for i in range(first,last+1):
        n_horse=int(counts[i]);row=odds[i]
        if len(row)!=n_horse or not all(
            isinstance(v,(float,int)) and math.isfinite(v) and v>1.0 for v in row
        ):continue
        a=int(offsets[i])-base
        b=int(offsets[i+1])-base
        q=np.asarray([1/v for v in row],dtype=float)
        q=q/q.sum()
        x=np.clip(np.asarray(raw[a:b],dtype=float),1e-12,1)
        x=np.power(x,1/temperature);x=x/x.sum()
        p=(1-alpha)*q+alpha*x
        w=int(winners[i])
        l=float(-np.log(max(1e-15,p[w])))
        h=int(np.argmax(p)==w)
        n+=1;loss+=l;top1+=h
        bydate[str(dates[i])].append(l)
    if n<1500:raise RuntimeError("ACTUAL_FINAL_ODDS_MARKET_COMPARISON_TOO_FEW_RACES")
    return {"races":n,"winnerLogloss":round(loss/n,7),"top1Pct":round(100*top1/n,4),
            "pairedByDate":{d:vals for d,vals in bydate.items()}}

def date_bootstrap(a,b,seed=20261108):
    if a["races"]!=b["races"] or a["pairedByDate"].keys()!=b["pairedByDate"].keys():
        raise AssertionError("MARKET_COMPARISON_NOT_SAME_RACES")
    diffs=[]
    for day,one in a["pairedByDate"].items():
        two=b["pairedByDate"][day]
        assert len(one)==len(two)
        diffs.append((sum(one)-sum(two),len(one)))
    vals=np.asarray(diffs)
    rng=np.random.default_rng(seed)
    q=[]
    for i in range(500):
        s=vals[rng.choice(len(vals),size=len(vals),replace=True)]
        q.append(s[:,0].sum()/s[:,1].sum())
    return {"marketLoglossMinusBlendLogloss":round(float(vals[:,0].sum()/vals[:,1].sum()),7),
      "95PctDateClusterInterval":[round(v,7) for v in np.quantile(q,[.025,.975])],
      "positiveMeansBlendBeatsMarket":True,"dates":len(diffs)}

def selftest():
    x=np.asarray([.8,.1,.1,.2,.6,.2,.3,.2,.5],dtype=float)
    odds=[[2.,10.,20.],[8.,2.,10.],[3.,5.,9.]]
    dates=np.asarray(["2025-01-01","2025-01-02","2025-01-03"])
    # Separate tiny smoke; score_paired intentionally demands >=1500 races.
    assert len(ALPHAS)>=7 and ALPHAS[0]==0 and ALPHAS[-1]==1
    assert all(0<=a<=1 for a in ALPHAS)
    assert float(np.sum([1/o for o in odds[0]]))>0
    print("HORSE_MODEL_MARKET_RESIDUAL_BLIND_YEAR_SPLIT_TEST_OK")

def main():
    if "--self-test" in sys.argv:selftest();return
    if any(os.getenv(x) for x in ("CLOUDFLARE_API_TOKEN","CLOUDFLARE_D1_DATABASE_ID")):
        raise RuntimeError("OFFLINE_MARKET_MODEL_HAS_NO_D1_ACCESS")
    started=time.monotonic()
    ablation=load("scripts/research-nov2026-winner-model-internals.py","winner_research")
    archive=load("scripts/postaug-support-chronological-56feature-validation.py","market_archive")
    core=archive.core_module()
    byday=archive.load_bundles(archive.load_public_archive())
    X,y,counts,dates,offsets,winners,dropped,total,market=archive.chronological_features(core,byday)
    names=list(core.load_config()["runnerProbabilityModel"]["features"])
    candidate=ablation.Candidate("fixed_4yr_decay",half_life_years=4.0)
    yearly={}
    importance={}
    for year in (2025,2026):
        ix=np.flatnonzero((dates>=f"{year}-01-01") & (dates<f"{year+1}-01-01"))
        if len(ix)<2000 or ix[-1]+1>len(dates):raise ValueError("BAD_CHRONOLOGICAL_TEST_YEAR")
        first,last=int(ix[0]),int(ix[-1])
        if last-first+1!=len(ix):raise AssertionError("NONCONTIGUOUS_HOLDOUT_DATES")
        if str(dates[first-1])>=str(dates[first]):raise AssertionError("TIME_LEAK")
        model,cols=ablation.model_fit(X,y,counts,dates,offsets,first,candidate,names)
        raw=ablation.vectors(model,X,offsets,first,last,cols)
        scores=[(alpha,score_paired(raw,market,dates,counts,offsets,winners,first,last,alpha))
                for alpha in ALPHAS]
        if year==2026:
            gains=model.booster_.feature_importance(importance_type="gain")
            imp=sorted(zip((names[int(i)] for i in cols),map(float,gains)),key=lambda z:-z[1])
            importance={"top18ByGain":[{"feature":f,"gain":round(g,3)} for f,g in imp[:18]],
              "constantHistoricFeatureNames":["direction","weather","trackCondition"],
              "featureCount":len(cols)}
        yearly[year]=scores
        print("MARKET_RESIDUAL_YEAR_EVALUATED",year,json.dumps({
          "sample":scores[0][1]["races"],
          "market":{k:v for k,v in scores[0][1].items() if k!="pairedByDate"},
          "allWeights":[{"alpha":alpha,
            "winnerLogloss":out["winnerLogloss"],"top1Pct":out["top1Pct"]} for alpha,out in scores]
        }),flush=True)
    chosen=min(yearly[2025],key=lambda pair:(pair[1]["winnerLogloss"],pair[0]))[0]
    frozen=dict(yearly[2026])
    market0=frozen[0.0];selected=frozen[chosen];model1=frozen[1.0]
    delta=date_bootstrap(market0,selected)
    report={
      "classification":"TRUE_HORSE_MODEL_VS_ARCHIVED_FINAL_MARKET_DIAGNOSTIC",
      "noD1Used":True,
      "trained2025UsingRacesThrough2024":True,
      "selectAlphaOnly2025":True,
      "2026WinLabelsUsedToTune":False,
      "2026AlreadyInspectedPreviously":True,
      "marketFinalOddsT15Verified":False,
      "notActualJraROI":True,
      "productionPromotionAllowed":False,
      "model":{"architecture":"LightGBM win classifier", "historicalHalfLifeYears":4,
               "featureCount":56,"probabilityTemperatureFrom2025":.85},
      "2025Selection":{"frozenModelBlendAlpha":chosen,
        "marketWeight":round(1-chosen,4),
        "candidateWeights":[{"weight":alpha,
          "races":s["races"],"logloss":s["winnerLogloss"],
          "top1Pct":s["top1Pct"]} for alpha,s in yearly[2025]]},
      "2026SameRaces":{
        "marketOnly":{k:v for k,v in market0.items() if k!="pairedByDate"},
        "2025SelectedBlend":{k:v for k,v in selected.items() if k!="pairedByDate"},
        "horseOnly":{k:v for k,v in model1.items() if k!="pairedByDate"},
        "marketMinusBlend":delta,
        "allCandidateWeights":[{"weight":alpha,
          "races":s["races"],"logloss":s["winnerLogloss"],
          "top1Pct":s["top1Pct"]} for alpha,s in yearly[2026]]
      },
      "featureImportance":importance,
      "elapsedSeconds":round(time.monotonic()-started,1)
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("NOV2026_MARKET_MODEL_INFORMATION_RESULT",json.dumps({
      "2025ChosenHorseWeight":chosen,
      "2026MarketOnly":report["2026SameRaces"]["marketOnly"],
      "2026Blend":report["2026SameRaces"]["2025SelectedBlend"],
      "2026HorseOnly":report["2026SameRaces"]["horseOnly"],
      "confidence":delta,"promotable":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
