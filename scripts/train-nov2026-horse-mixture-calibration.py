#!/usr/bin/env python3
"""2025-only time-ordered calibration of 3 newly trained 2026 horse heads.

1) Fit ranks/wins/placing using historical results <= 2024-12-31.
2) Choose one predeclared rank / win / top3 probability mixture by 2025
   logloss, never touching 2026 labels.
3) Refit all horse heads on <= 2025-12-31; evaluate only 2026 Jan-Aug.
This uses NO Cloudflare D1, NO JRA odds, and is NOT ticket ROI evidence.
Previous research saw 2025/26: not a pristine blind validation.
"""
from pathlib import Path
import json,importlib.util,sys,math
import numpy as np
from collections import defaultdict
import joblib

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-calibrated-horse-mixture-2025-to-2026.json"
MODEL=ROOT/"analysis-results/nov2026-calibrated-horse-mixture-frozen.joblib"
RANK_MIX=(0.0,0.1,0.2,0.35,0.5,0.65,0.8)
PLACE_MIX=(0.0,0.1,0.2,0.3)
TEMPERATURES=(0.9,1.2,1.5,2.0)

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec);sys.modules[spec.name]=obj;spec.loader.exec_module(obj);return obj

def normalize(values):
    v=np.asarray(values,dtype=np.float64)
    if not len(v) or not np.isfinite(v).all():raise ValueError("INVALID_MODEL_VECTOR")
    v=np.maximum(v,1e-12);return v/v.sum()

def probabilities(group,rawRank,rawWin,rawPlace,weights):
    a,b,t=weights
    if a<0 or b<0 or a+b>1 or t<=0:raise ValueError("INVALID_MIXTURE")
    rank=np.asarray(rawRank,dtype=np.float64)
    exps=np.exp(np.clip((rank-rank.max())/t,-60,0))
    pR=normalize(exps)
    pW=normalize(rawWin)
    pP=normalize(rawPlace)
    p=a*pR+b*pP+(1-a-b)*pW
    # Small uniform prior is fixed ahead of all validation, to avoid
    # unbounded log-loss from rare horses in imperfect class probabilities.
    p=.99*p+.01/len(p)
    return normalize(p)

def race_probabilities(models,X,counts,offsets,first,last,params):
    total=int(offsets[last+1])-int(offsets[first])
    x=X[int(offsets[first]):int(offsets[last+1])]
    ranker,winner,place=models
    rank=ranker.predict(x,num_threads=2)
    win=winner.predict_proba(x)[:,1]
    placep=place.predict_proba(x)[:,1]
    if not (len(rank)==len(win)==len(placep)==total):raise ValueError("PREDICT_LENGTH_MISMATCH")
    probs=[]
    c=0
    for i in range(first,last+1):
        n=int(counts[i])
        probs.extend(probabilities(i,rank[c:c+n],win[c:c+n],placep[c:c+n],params).tolist())
        c+=n
    assert c==total
    return np.asarray(probs,dtype=float)

def select_params(dates,counts,offsets,y,models,X,first,last):
    # Cache one set of raw predictions. Evaluate deterministic combinations
    # against 2025 labels only. Never re-optimize on 2026.
    x=X[int(offsets[first]):int(offsets[last+1])]
    ranker,winner,place=models
    scores=np.asarray(ranker.predict(x,num_threads=2))
    win=np.asarray(winner.predict_proba(x)[:,1])
    placep=np.asarray(place.predict_proba(x)[:,1])
    cache=[]
    c=0
    for i in range(first,last+1):
        n=int(counts[i]);yseg=y[int(offsets[i]):int(offsets[i+1])]
        ix=np.flatnonzero(yseg)
        if len(ix)!=1:raise ValueError("INVALID_2025_RACE_WINNER")
        r=scores[c:c+n];w=win[c:c+n];p=placep[c:c+n]
        cache.append((r,w,p,int(ix[0])));c+=n
    assert c==len(scores)
    result=[]
    for a in RANK_MIX:
        for b in PLACE_MIX:
            if a+b>1:continue
            for temp in TEMPERATURES:
                loss=0;hits=0;hits3=0
                for r,w,p,y0 in cache:
                    prob=probabilities(0,r,w,p,(a,b,temp))
                    loss-=math.log(max(1e-15,float(prob[y0])))
                    hits+=int(np.argmax(prob)==y0)
                    hits3+=int(y0 in np.argsort(-prob)[:3])
                n=len(cache)
                result.append({"rankWeight":a,"placeWeight":b,
                  "winWeight":round(1-a-b,4),"rankTemperature":temp,
                  "winnerLogloss":loss/n,"top1Pct":100*hits/n,"top3Pct":100*hits3/n})
    best=min(result,key=lambda x:(x["winnerLogloss"],-x["top3Pct"],
                                    -x["top1Pct"],x["rankWeight"],x["placeWeight"]))
    return (best["rankWeight"],best["placeWeight"],best["rankTemperature"]),best,len(result)

def main():
    import os
    for key in ("CLOUDFLARE_API_TOKEN","CLOUDFLARE_D1_DATABASE_ID"):
        if os.getenv(key):raise RuntimeError("D1_CREDENTIALS_MUST_NOT_BE_PRESENT")
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","mixed_offline_hist")
    robust=load("scripts/research-nov2026-fresh-robust200.py","mixed_offline_new")
    scoring=load("scripts/train-nov2026-new-horse-heads-offline.py","mixed_offline_scoring")
    struct=load("scripts/research-structural-ranker-twohead-2025.py","mixed_offline_top3")
    bundles=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),bundles)
    t3=struct.top3_targets(bundles)
    assert len(X)==len(y)==len(t3)
    byyear={}
    for year in (2025,2026):
        ids=np.flatnonzero((dates>=f"{year}-01-01")&(dates<f"{year+1}-01-01"))
        if len(ids)<2000:raise ValueError("YEAR_HOLDOUT_COVERAGE_INCOMPLETE")
        a,b=int(ids[0]),int(ids[-1])
        if b-a+1!=len(ids) or str(dates[a-1])>=f"{year}-01-01":
            raise ValueError("YEAR_NOT_CHRONOLOGICAL")
        model,info=robust.fit_horse(X,y,t3,counts,offsets,dates,year)
        byyear[year]=((model[0].ranker,model[0].win_model,model[1]),info,a,b)
        print("MIXED_HEAD_HISTORICAL_YEAR",year,json.dumps(info),flush=True)
    fitted2025,train2025,low2025,high2025=byyear[2025]
    params,chosen,count=select_params(dates,counts,offsets,y,
                                      fitted2025,X,low2025,high2025)
    frozen2026,train2026,low2026,high2026=byyear[2026]
    probs=race_probabilities(frozen2026,X,counts,offsets,low2026,high2026,params)
    result=scoring.evaluate(dates,counts,offsets,y,probs,low2026,high2026)
    # Honest fixed first version comparison on same 2026 race cohort.
    legacy=race_probabilities(frozen2026,X,counts,offsets,low2026,high2026,
                              (.6,0.,1.4))
    legacyResult=scoring.evaluate(dates,counts,offsets,y,legacy,low2026,high2026)
    MODEL.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump({
      "name":"pre2026-calibrated-threehead-horse-mixture",
      "trainedHorseRanker":frozen2026[0],
      "trainedWinnerExtraTrees":frozen2026[1],
      "trainedTop3HGB":frozen2026[2],
      "frozenMixRankPlaceTemp":params,
      "selectionValidationYear":2025,
      "scoredOutOfYear":2026,
      "runnerFeatures":56,
      "t15FeatureProven":False,
      "researchOnly":True
    },MODEL,compress=3)
    report={
      "selectedOn2025Only":True,
      "2026OutcomesUsedForSelection":False,
      "2025HyperparameterCandidates":count,
      "2025ValidationWinner":chosen,
      "2026ChronologicalHoldout":result,
      "2026ComparisonToFixedPrototypeBlend":legacyResult,
      "horseTraining":{"2025":train2025,"2026":train2026},
      "noMarketOddsOrPayoutTraining":True,
      "notActualJraROI":True,
      "productionPromotionEligible":False
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NOV2026_CALIBRATED_2025_TO_2026",json.dumps(
      {"selectedParams":chosen,"2026":result["aggregate"],
       "2026PrototypeComparison":legacyResult["aggregate"],"notJraROI":True},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
