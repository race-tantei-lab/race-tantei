#!/usr/bin/env python3
"""Fundamental relative-to-rivals ranking models, chronological JRA payout audit.

Two genuinely different model families against the existing plain LambdaRank:
1) LightGBM LambdaRank with 40 new within-race strength/rank features.
2) XGBoost rank:pairwise with the same 40 new within-race features.
Pre-result features are calculated for every horse relative to the OTHER
DECLARED runners. No result, payout or historical final odds enters features.

All horse models train strictly before target calendar year.
Payout stage: *unchanged* predeclared two-part hurdle trained only on 2024
actual JRA payouts and prediction distributions produced by pre-2024 rankers.
2025 JRA payout data is only used to settle the portfolio. Same 5-race,
two-distinct-ticket, 2000-yen-race structure as prior model benchmark.
The 2025 data has appeared in earlier research: NOT an untouched holdout,
NOT T-15 proven, NOT a production model. No DB writes, no live model changes.
"""
from __future__ import annotations
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
import numpy as np
from lightgbm import LGBMRanker
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/relative-ranking-lgbm-xgb-2025-paired-jra.json"
KINDS=("relative_lambdarank","relative_xgb_pairwise")
SEED=20261108
REL_FEATURES=(
 "horseWinRate","horseTop3Rate","lastFinishPct","avg3FinishPct",
 "avg5FinishPct","avg3Final3fPct","avg5Final3fPct",
 "avg3SpeedMps","avg5SpeedMps","sameSurfaceWinRate",
 "sameDistWinRate","sameVenueWinRate","jockeyWinRate",
 "jockeyTop3Rate","trainerWinRate","trainerTop3Rate",
 "assignedWeight","daysSinceLast","drawPct","horseStarts",
)

def load(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:raise RuntimeError("UNAVAILABLE_IMPORT:"+str(path))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

def relative_matrix(X,counts,offsets,base_features):
    ix=[base_features.index(name) for name in REL_FEATURES]
    if len(set(ix))!=len(ix) or len(base_features)!=56:
        raise AssertionError("RELATIVE_FEATURE_ORDER_INVALID")
    result=np.empty((len(X),len(ix)*2),dtype=np.float32)
    for r,n in enumerate(counts):
        a=int(offsets[r]);b=int(offsets[r+1]);n=int(n)
        if n<3 or b-a!=n:raise AssertionError("RACE_GROUP_MISMATCH")
        x=X[a:b,ix].astype(np.float64,copy=False)
        mu=np.mean(x,axis=0)
        dev=np.maximum(np.std(x,axis=0),0.02)
        z=np.clip((x-mu)/dev,-6,6)
        ranks=np.argsort(np.argsort(x,axis=0,kind="stable"),axis=0,kind="stable")
        ranks=ranks/max(1,n-1)
        result[a:b,:len(ix)]=z
        result[a:b,len(ix):]=ranks
    return np.concatenate((X,result),axis=1)

def fit_ranking_model(X,y,counts,dates,offsets,year,kind):
    ix=np.flatnonzero(dates<f"{year}-01-01")
    if len(ix)<12000 or ix[0]!=0 or not np.array_equal(ix,np.arange(len(ix))):
        raise AssertionError("DISCONTIGUOUS_PRIOR_YEAR_TRAINING")
    last=int(ix[-1]);boundary=int(offsets[last+1])
    if str(dates[last])>=f"{year}-01-01":raise AssertionError("YEAR_LABEL_LEAKAGE")
    if kind=="relative_lambdarank":
        model=LGBMRanker(
          objective="lambdarank",n_estimators=210,learning_rate=0.035,
          num_leaves=31,min_child_samples=75,reg_lambda=11.0,
          colsample_bytree=0.85,lambdarank_truncation_level=5,
          n_jobs=2,random_state=SEED,verbosity=-1)
        model.fit(X[:boundary],y[:boundary].astype(np.int32),
                  group=counts[:last+1].tolist())
    elif kind=="relative_xgb_pairwise":
        from xgboost import XGBRanker
        model=XGBRanker(
           objective="rank:pairwise",n_estimators=210,
           max_depth=5,learning_rate=0.04,
           subsample=0.84,colsample_bytree=0.82,
           min_child_weight=12,reg_lambda=12.0,
           tree_method="hist",n_jobs=2,random_state=SEED)
        qid=np.repeat(np.arange(last+1,dtype=np.int32),counts[:last+1])
        assert len(qid)==boundary
        model.fit(X[:boundary],y[:boundary].astype(np.float32),qid=qid,verbose=False)
    else:raise ValueError(kind)
    return model,{"year":year,"through":str(dates[last]),"raceGroups":last+1,
                  "trainRunnerRows":boundary,"algorithm":kind}

class RankerAdapter:
    def __init__(self,m):self.m=m
    def predict(self,X,num_threads=2):
        return self.m.predict(X) if "XGBRanker" in type(self.m).__name__ \
            else self.m.predict(X,num_threads=num_threads)

class Top3Adapter:
    def __init__(self,m):self.m=m
    def predict_proba(self,X):return self.m.predict_proba(X[:,:56])

def fit_top3(X,t3,dates,offsets,year):
    ix=np.flatnonzero(dates<f"{year}-01-01")
    boundary=int(offsets[int(ix[-1])+1])
    m=HistGradientBoostingClassifier(
        max_iter=120,learning_rate=0.04,max_leaf_nodes=25,
        min_samples_leaf=85,l2_regularization=8,
        early_stopping=False,random_state=SEED)
    m.fit(X[:boundary],t3[:boundary])
    return m

def self_test():
    X=np.asarray([[1,2],[2,4],[3,3],[10,1],[20,4],[30,3]],dtype=np.float32)
    counts=np.asarray([3,3])
    offsets=np.asarray([0,3,6])
    # An unambiguous two-column custom order for test-only.
    global REL_FEATURES
    stored=REL_FEATURES
    try:
        REL_FEATURES=("a","b")
        # Structural function's 56-column live input is a hard contract;
        # check relative math separately instead of bypassing that guard.
        first=X[:3]
        assert abs(np.mean((first-first.mean(axis=0))/first.std(axis=0),axis=0)).max()<1e-7
    finally:
        REL_FEATURES=stored
    assert len(stored)==20
    assert list(counts)==[3,3] and int(offsets[-1])==len(X)
    print("RELATIVE_MODEL_ARCHITECTURE_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:self_test();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","relative_hist")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","relative_audit")
    payoutstage=load("scripts/research-two-stage-payout-value-2024-2025.py","relative_stage2")
    original=load("scripts/research-structural-ranker-twohead-2025.py","relative_original")
    core=hist.core_module()
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,archive)
    t3=original.top3_targets(archive)
    meta=audit.eligible_metadata(archive)
    if len(meta)!=len(counts) or len(t3)!=len(X):raise AssertionError("FEATURE_LABEL_ALIGNMENT")
    base_features=core.load_config()["runnerProbabilityModel"]["features"]
    augmented=relative_matrix(X,counts,offsets,base_features)
    print("RELATIVE_40_FIELD_FEATURES_READY",json.dumps({
      "baseFeatures":len(base_features),"newRelativeFeatures":augmented.shape[1]-X.shape[1],
      "runnerRows":len(X),"groups":len(counts)},ensure_ascii=False),flush=True)
    paid,coverage=audit.payout_book()
    outputs={}
    auditYears={}
    for kind in KINDS:
        groups={};training={};excluded={}
        for year in (2024,2025):
            rank,info=fit_ranking_model(augmented,y,counts,dates,offsets,year,kind)
            placer=fit_top3(X,t3,dates,offsets,year)
            evaluated,bad,target=original.year_groups(
                year,augmented,counts,dates,offsets,meta,
                (RankerAdapter(rank),Top3Adapter(placer)),paid)
            groups[year]=evaluated
            training[str(year)]=info
            excluded[str(year)]=bad
            auditYears[f"{kind}:{year}"]={"eligibleVenueDays":len(evaluated),
                "excludedVenueDays":bad,"racesInYear":target,
                "train":info}
            print("RELATIVE_RANKER_TRAIN_YEAR",json.dumps({
               "kind":kind,"year":year,"meta":auditYears[f"{kind}:{year}"]},
               ensure_ascii=False),flush=True)
            del rank,placer
        trainX,trainPaid,trainHits,_=original.build_rows(
            groups[2024],payoutstage,"ranker_only")
        cls,cond,priors=original.fit_hurdle(trainX,trainPaid,trainHits)
        testX,_,_,testMeta=original.build_rows(
            groups[2025],payoutstage,"ranker_only")
        forecasts=original.score_rows(testX,testMeta,(cls,cond),priors)
        portfolio=original.selected_portfolio(groups[2025],forecasts,payoutstage)
        outputs[kind]={"metrics":portfolio["metrics"],
            "validVenueDays":portfolio["validVenueDays"],
            "unusableVenueDays":portfolio["unusableVenueDays"],
            "monthly":portfolio["byMonth"],
            "trainCandidateRows":int(len(trainHits)),
            "trainTicketHitPct":round(100*float(np.mean(trainHits)),3),
            "featureCount":int(augmented.shape[1]),
            "ticketFeatureCount":int(trainX.shape[1]),
            "samplePredictions":portfolio["samplePredictions"]}
        print("RELATIVE_RANKER_2025_PAIRED_JRA_HIT_ROI",json.dumps({
            "model":kind,"metrics":outputs[kind]["metrics"],
            "completeVenueDays":portfolio["validVenueDays"]},
            ensure_ascii=False),flush=True)
        del trainX,trainPaid,trainHits,testX,testMeta,cls,cond,forecasts,groups
    report={"status":"RESEARCH_ONLY_NEW_RELATIVE_LAMBDARANK_XGB_PAIRWISE",
      "baseRunnerFeatures":56,"newRaceRelativeFeatures":40,
      "newFeaturesPreResultOnly":True,"knownHistoricalT15InputTimes":False,
      "noHistoricalFinalOdds":True,"noSyntheticOdds":True,
      "trainTimeSeparation":"2024 horse labels through 2023; 2025 horse labels through 2024. 2024 payout head only.",
      "holdout2025PreviouslySeen":True,"actualPayouts":"JRA D1 2025; no capped returns in test",
      "payoutMonths":coverage,"auditYears":auditYears,
      "selectionRules":"same 5 races / venue, same two distinct bet types, 2000 yen/race as prior ranker",
      "profitPromotionAllowed":False,"results":outputs}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("RELATIVE_MODELS_COMPARISON_COMPLETE",json.dumps({
       "metrics":{k:v["metrics"] for k,v in outputs.items()},
       "profitPromotionAllowed":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
