#!/usr/bin/env python3
"""Fundamentally market-relative multi-target + ticket-ranking model experiment.

Separate from previous 'tune stake' studies. Three NEW core modeling changes:
 * Win probability CatBoost learns market-price residuals jointly with 56 form,
   horse/jockey/trainer, speed, surface features (not just bare win-only score).
 * CatBoost/Tweedie actual-JRA ticket payout learners include modeled PRICE
   discrepancy features and market rank, rather than just horse ranking.
 * Direct LightGBM LambdaRank learns *within-race profitable ticket ordering*
   from historical actual payouts, a new objective distinct from win accuracy.

WARNING: The archive has *historical FINAL JRA win odds*, NOT true T-15
snapshots. These are used here ONLY as an exploratory market proxy; no claim
of actual pre-T15 live reproducibility. No 2025 test results enter fitting.
Horse models trained on dates BEFORE target year; payout models 2024 only.
All candidate families use five races/venue/day, distinct two ticket types,
fixed 1000+1000 yen. Same exact 2025 JRA payout date/venue cohort.
No production writes, no synthetic odds, no deployed-model promotion.
"""
from __future__ import annotations
import collections
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
import numpy as np
import lightgbm as lgb
from catboost import CatBoostClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/market-residual-ticket-lambdarank-2025-jra.json"

def import_model(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("IMPORT_FAILED:"+path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

base=import_model("scripts/research-multitarget-ranking-payout-value.py","market_base_model")
base.HORSE_FAMILIES=("ranker_ordinal","catboost_win_top3","hybrid_three_target",
                     "market_relative_catboost_win")
base.TICKET_FAMILIES=("lightgbm_tweedie","catboost_hit_x_payout","ticket_payout_lambdarank")
ORIGINAL_TICKET_FEATURES=base.ticket_features
MARKET_COLS=("normalizedOfficialFinalWinImplied","logFinalOdds",
             "marketRankFraction","missingFinalOdds")

def market_context(market_venues,counts):
    if len(market_venues)!=len(counts):raise AssertionError("MARKET_RACE_MISMATCH")
    rows=[];race_markets=[];missing=0;all_count=0
    for i,prices in enumerate(market_venues):
        if len(prices)!=int(counts[i]):raise AssertionError("ODDS_HORSE_COUNT_MISMATCH")
        n=len(prices)
        finite=[p is not None and math.isfinite(float(p)) and float(p)>=1.0 and float(p)<=1000
                for p in prices]
        valid=[min(1000.0,max(1.0,float(x))) if good else 250.0
               for x,good in zip(prices,finite)]
        m=base.normalize([1.0/z for z in valid])
        order=np.argsort(-m,kind="stable")
        ranks=np.empty(n,dtype=int)
        ranks[order]=np.arange(n)
        race=[]
        for j in range(n):
            values=(float(m[j]),math.log(valid[j]),float(ranks[j]+1)/n,
                    float(not finite[j]))
            rows.append(values);race.append(values)
            missing+=int(not finite[j]);all_count+=1
        race_markets.append(np.asarray(race,dtype=np.float64))
    return np.asarray(rows,dtype=np.float32),race_markets,{"total":all_count,
        "missingOrInvalid":missing,"coveragePct":round(100*(all_count-missing)/all_count,2)}

def market_ticket_features(row,ticket,cols,horse_family):
    raw=ORIGINAL_TICKET_FEATURES(row,ticket,cols,horse_family)
    odds=np.asarray(row["market"],dtype=np.float64)
    prob=np.asarray(row["probabilities"][horse_family],dtype=np.float64)
    positions=ticket[1]
    mp=np.asarray(odds[:,0],dtype=np.float64)
    market_ticket_p=base.combo_probability(ticket[0][0],positions,mp)
    selected=[odds[int(i)] for i in positions]
    sp=[float(prob[int(i)]) for i in positions]
    feature=[
      float(market_ticket_p),
      math.log(max(market_ticket_p,1e-9)),
      float(ticket[2]/max(market_ticket_p,1e-9)),
      math.log(max(ticket[2],1e-9))-math.log(max(market_ticket_p,1e-9)),
      float(max(sp)/max(mp[int(i)] for i in positions)),
      float(np.mean([mp[int(i)] for i in positions])),
      float(np.max([mp[int(i)] for i in positions])),
      float(np.min([mp[int(i)] for i in positions])),
      float(np.mean([z[1] for z in selected])),
      float(np.max([z[1] for z in selected])),
      float(np.mean([z[2] for z in selected])),
      float(np.mean([z[3] for z in selected])),
    ]
    return raw+feature

base.ticket_features=market_ticket_features

def train_market_win(X,market,win_y,dates,offsets,year):
    ix=np.flatnonzero((dates>=f"{year-5}-01-01")&(dates<f"{year}-01-01"))
    if len(ix)<5000:raise RuntimeError("MARKET_HORSE_TRAIN_TOO_SMALL")
    lo=int(offsets[ix[0]]);hi=int(offsets[ix[-1]+1])
    features=np.hstack([X[lo:hi],market[lo:hi]])
    m=CatBoostClassifier(iterations=280,depth=6,learning_rate=0.06,
       loss_function="Logloss",l2_leaf_reg=16.0,thread_count=2,verbose=False,
       random_seed=20261108,allow_writing_files=False)
    m.fit(features,win_y[lo:hi])
    return m,{"lastTrainDate":str(dates[ix[-1]]),"trainedRunnerRows":hi-lo,
      "trainingIncludesHistoricFinalMarketOdds_PROXY_NOT_T15":True}

def include_market_family(year,groups,cat_market,X,market,dates,counts,offsets,meta,market_per_race):
    ix=np.flatnonzero((dates>=(f"{year}-05-04" if year==2024 else f"{year}-01-01"))
         &(dates<f"{year+1}-01-01"))
    if not len(ix):raise AssertionError("MARKET_TARGET_MISSING")
    lo=int(offsets[ix[0]]);hi=int(offsets[ix[-1]+1])
    cat_raw=np.asarray(cat_market.predict_proba(np.hstack([X[lo:hi],market[lo:hi]]))[:,1])
    market_pred={}
    offset=0
    for idx in ix:
        idx=int(idx);n=int(counts[idx])
        rid=meta[idx]["raceId"]
        market_pred[rid]=base.normalize(cat_raw[offset:offset+n])
        offset+=n
    if offset!=len(cat_raw):raise AssertionError("MARKET_YEAR_OFFSET_MISMATCH")
    selected=0
    for rs in groups.values():
        for row in rs:
            rid=row["raceId"]
            row["market"]=market_per_race[rid]
            target=market_pred[rid]
            row["probabilities"]["market_relative_catboost_win"]=base.normalize(
                0.78*target+0.22*row["probabilities"]["ranker_ordinal"])
            selected+=1
    return selected

def ranker_group_counts(meta):
    sizes=[]
    last=None
    for day,race_no,*_ in meta:
        key=(day,race_no)
        if key!=last:
            sizes.append(1);last=key
        else:sizes[-1]+=1
    if sum(sizes)!=len(meta):raise AssertionError("PAYOUT_RACE_GROUP_ALIGNMENT")
    if min(sizes)<30 or max(sizes)>100:raise AssertionError("UNEXPECTED_TICKET_CANDIDATES")
    return np.asarray(sizes,dtype=np.int32)

def payout_rank_target(real_multiples):
    # 0 for no payout, escalating graded utility for actual paid tickets.
    # Labels are outcomes from TRAINING YEAR ONLY; no 2025 labels in model fit.
    return np.digitize(np.asarray(real_multiples),[0.01,2.0,5.0,10.0,25.0,60.0]).astype(np.int8)

def train_direct_ticket_ranker(X,train_y,meta):
    groups=ranker_group_counts(meta)
    labels=payout_rank_target(train_y)
    ranker=lgb.LGBMRanker(objective="lambdarank",metric="ndcg",
       label_gain=[0,1,2,5,12,25,50],n_estimators=220,
       num_leaves=27,learning_rate=0.04,min_child_samples=130,
       colsample_bytree=0.8,reg_lambda=25.0,random_state=20261108,
       n_jobs=2,verbosity=-1)
    ranker.fit(X,labels,group=groups)
    return ranker,{"trainTicketRows":int(len(labels)),"raceGroups":int(len(groups)),
        "labelCounts":dict(collections.Counter(map(int,labels)))}

def run():
    hist=import_model("scripts/postaug-support-chronological-56feature-validation.py","market_hist")
    audit=import_model("scripts/research-extra-trees-2024-2025-paired-jra.py","market_d1")
    archive=hist.load_bundles(hist.load_public_archive())
    core=hist.core_module()
    X,win_y,counts,dates,offsets,_,_,_,archivedOdds=hist.chronological_features(core,archive)
    rank_y,top3_y,meta=base.truth_rows(archive,counts,win_y)
    market,market_per_row,coverage=market_context(archivedOdds,counts)
    assert len(market)==len(X)
    market_by_rid={meta[i]["raceId"]:market_per_row[i] for i in range(len(meta))}
    if coverage["coveragePct"]<95:raise RuntimeError("HISTORICAL_FINAL_MARKET_COVERAGE_TOO_LOW")
    print("HISTORIC_FINAL_JRA_MARKET_PROXY_COVERAGE",json.dumps(coverage),flush=True)
    payouts,payoutMonths=audit.payout_book()
    groups={};excluded={};trainInfo={}
    for year in (2024,2025):
        coreHorse,auditHorse=base.train_horse_models(year,X,win_y,top3_y,rank_y,counts,dates,offsets)
        m,marketAudit=train_market_win(X,market,win_y,dates,offsets,year)
        full,errors,sourceRaces=base.year_groups(year,coreHorse,X,counts,dates,offsets,meta,payouts)
        added=include_market_family(year,full,m,X,market,dates,counts,offsets,meta,market_by_rid)
        groups[year]=full
        trainInfo[str(year)]={"preYearHorseModels":auditHorse,
          "marketResidualClassifier":marketAudit,"racesWithValidPayout":added}
        excluded[str(year)]={"excludedVenueDays":errors,
          "completeVenueDays":len(full),"sourceRaces":sourceRaces}
        print("MARKET_RESIDUAL_HORSE_FAMILY_READY",json.dumps({
            "year":year,"completeVenueDays":len(full),"training":trainInfo[str(year)]}),flush=True)
        del coreHorse,m
    indices=base.field_indices(core.load_config()["runnerProbabilityModel"]["features"])
    results={};rankAudit={}
    for family in base.HORSE_FAMILIES:
        xTrain,yTrain,trainMeta,trainKinds=base.model_ticket_rows(groups[2024],family,indices)
        ticketModels,modelsAudit=base.train_ticket_models(xTrain,yTrain)
        ticketRanker,rAudit=train_direct_ticket_ranker(xTrain,yTrain,trainMeta)
        rankAudit[family]=rAudit
        testX,_,testMeta,testKinds=base.model_ticket_rows(groups[2025],family,indices)
        predicted=base.predict_ticket_models(ticketModels,testX)
        predicted["ticket_payout_lambdarank"]=ticketRanker.predict(testX)
        one=base.evaluate_one_family(groups[2025],testMeta,predicted,family)
        results.update(one)
        print("MARKET_RELATIVE_FAMILY_REAL_JRA_ROI",json.dumps({
            "horseModel":family,"results":{k:{"selected":v["modelSelectedFive"],
               "fixedSameFive":v["fixedSameFiveRaces"]} for k,v in one.items()}},
            ensure_ascii=False),flush=True)
        del xTrain,yTrain,testX,predicted,ticketModels,ticketRanker
    eligible=[(k,v) for k,v in results.items() if v["modelSelectedFive"]["passes20PctHitFloor"]]
    best=sorted(eligible,key=lambda kv:-kv[1]["modelSelectedFive"]["roiPct"])[:5]
    report={"classification":"EXPLORATORY_ONLY_HISTORICAL_FINAL_ODDS_NOT_T15",
      "newHorseModel":"CatBoost 56 historic form features + normalized final JRA win market-implied probabilities and residuals",
      "newTicketObjectives":["Tweedie actual payout","CatBoost true-ticket-hit times positive payout",
                             "LGBM LambdaRank directly ordering 2024 JRA payout labels within races"],
      "horseTrainThrough":"2023 for 2024; 2024 for 2025",
      "ticketFitYears":["2024"],"validationYear":"2025",
      "archivedFinalOddsNOTT15":True,"actualT15OfficialOddsProven":False,
      "productionEligible":False,"usedHistoricalFinalOddsAsFeatures":True,
      "allRacesSameFixedBudgetAnd5PerVenueDay":True,
      "marketCoverage":coverage,"yearAudit":trainInfo,"venueDayCoverage":excluded,
      "payoutMonths":payoutMonths,"ticketRankerTraining":rankAudit,
      "test2025":results,
      "best2025InHindsightNOT_VALID_SELECTION":[{"model":k,"hitAndRoi":v["modelSelectedFive"],
         "sameFiveRaces":v["fixedSameFiveRaces"]} for k,v in best]}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MARKET_RELATIVE_RESULT_2025_FINAL_ODDS_PROXY_NOT_T15",json.dumps({
      "numEvaluated":len(results),"marketCoverage":coverage,
      "topFiveHindsightOnly":report["best2025InHindsightNOT_VALID_SELECTION"],
      "promotionEligible":False},ensure_ascii=False),flush=True)

def selftest():
    b=base
    m,v,c=market_context([[2.0,3.0,6.0]],np.asarray([3]))
    assert m.shape==(3,4)
    assert np.isclose(m[:,0].sum(),1.0)
    assert c["coveragePct"]==100
    assert list(payout_rank_target([0,1,3,6,12,30,90]))==[0,1,2,3,4,5,6]
    assert list(ranker_group_counts([(("2024-06-01","東京"),1,1,None,0)]*40))==[40]
    assert b.combo_probability("ワイド",(0,1),np.array([0.5,0.3,0.2]))==1.0
    print("MARKET_RESIDUAL_AND_TICKET_RANKER_SELFTEST_OK",flush=True)

if __name__=="__main__":
    if "--self-test" in sys.argv:selftest()
    else:run()
