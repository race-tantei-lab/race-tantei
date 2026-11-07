#!/usr/bin/env python3
"""2024-vs-2025 strictly date-partitioned market residual + payout hurdle.

Real market prices only start in 2024 in the bundled archive. Earlier data
CANNOT train a market-calibration model. Do not fake missing prices.

2024 Jan-Aug data:
  pre-2024 horse LambdaRank predicts 2024 pre-result abilities;
  2024-05-04..08-31 JRA archived actual FINAL win market odds and actual
  winners train a SMALL residual calibration model (no 2025 outcomes).
2024 Sep-Dec data:
  same pre-2024 horse model, frozen market calibrator,
  payout hurdle ONLY trains on real official Sep-Dec 2024 payouts.
2025:
  horse ranker is trained through Dec 2024, market calibrator and payout
  model are FROZEN. No 2025 outcome enters ticket decisions. JRA actual
  payout is used only to settle.
No T-15 equivalence: these are archived FINAL WIN odds. This is NOT live
payout proof, not a production-ready model, and 2025 previously inspected.
Two distinct JRA bet types, 5 races/day/venue and fixed 2000yen per race
across all policies. Forecast market-ability disagreement, not count tweaks.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import json,math
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/market-residual-2024split-2025jra.json"
MODELS=("horse_model_only","pure_market","market_residual_calibrated","market_residual_blend")
SEED=20261108

def load(path,name):
    import importlib.util,sys
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_MARKET_HISTORICAL_HELPER")
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def model_vs_market_x(p,q):
    orderp=np.argsort(np.argsort(-p,kind="stable"),kind="stable")+1
    orderq=np.argsort(np.argsort(-q,kind="stable"),kind="stable")+1
    field=len(p)
    eps=1e-8
    e=lambda vec:float(-np.sum(vec*np.log(np.maximum(vec,eps)))/math.log(field))
    out=np.column_stack((
      np.log(np.maximum(p,eps)),np.log(np.maximum(q,eps)),
      np.clip(np.log(np.maximum(p,eps)/np.maximum(q,eps)),-7,7),
      p,q,np.asarray(orderp,dtype=float)/field,np.asarray(orderq,dtype=float)/field,
      np.full(field,field/18.0),
      np.full(field,e(p)),np.full(field,e(q)),
      np.full(field,float(np.max(q)-np.partition(q,-2)[-2])),
      np.full(field,float(np.sum(np.sort(p)[-3:]))),
      np.full(field,float(np.sum(np.sort(q)[-3:]))),
    ))
    return out.astype(np.float32)

def valid_market_groups(original,market,q,odds,valid,groups,year):
    result={};skipped=0
    for day,rs in sorted(groups.items()):
        if any(not valid.get(r["raceId"],False) for r in rs):
            skipped+=1;continue
        for r in rs:
            r["marketQ"]=q[r["raceId"]]
            r["marketOdds"]=odds[r["raceId"]]
            if len(r["marketQ"])!=len(r["horses"]):raise AssertionError("RACE_MARKET_SIZE_MISMATCH")
        result[day]=rs
    print("HISTORICAL_MARKET_YEAR_GROUPS",json.dumps({
       "year":year,"available":len(result),"skipped":skipped},ensure_ascii=False),flush=True)
    return result

def fit_residual_model(groups):
    xx=[];yy=[];days=set();races=0
    for day,rs in groups.items():
        if not "2024-05-04"<=day[0]<"2024-09-01":continue
        days.add(day);races+=len(rs)
        for r in rs:
            p=r["horseProbability"]["ranker_only"]
            q=r["marketQ"]
            X=model_vs_market_x(p,q)
            win=[key[1][0] for key,payout100 in r["payout"].items() if key[0]=="単勝" and payout100>0]
            if len(win)!=1:
                raise ValueError("MARKET_RESIDUAL_WON_HORSE_NOT_UNIQUE")
            horse=win[0]
            labels=np.asarray([int(h==horse) for h in r["horses"]],dtype=np.int8)
            if sum(labels)!=1:raise ValueError("MARKET_RESIDUAL_TARGET_INVALID")
            xx.extend(X.tolist());yy.extend(labels.tolist())
    X=np.asarray(xx,dtype=np.float32);y=np.asarray(yy,dtype=np.int8)
    if races<400 or len(X)<5000 or int(np.sum(y))!=races:
        raise RuntimeError("INSUFFICIENT_TRULY_OBSERVED_2024_MARKET_TRAIN_RACES")
    learner=HistGradientBoostingClassifier(
       max_iter=110,learning_rate=0.04,max_leaf_nodes=11,
       min_samples_leaf=110,l2_regularization=15.0,
       early_stopping=False,random_state=SEED)
    learner.fit(X,y)
    print("MARKET_RESIDUAL_2024_TRAINED",json.dumps({
      "races":races,"venueDays":len(days),"horseRows":len(X),
      "winLabels":int(np.sum(y))},ensure_ascii=False),flush=True)
    return learner,{"races":races,"venueDays":len(days),"horseRows":len(X)}

def attach_calibrated(groups,calibrator):
    for day,rs in groups.items():
        for r in rs:
            p=r["horseProbability"]["ranker_only"]
            q=r["marketQ"]
            X=model_vs_market_x(p,q)
            scores=np.maximum(calibrator.predict_proba(X)[:,1],1e-10)
            scores/=scores.sum()
            r["horseProbability"].update({
              "horse_model_only":p,
              "pure_market":q,
              "market_residual_calibrated":scores,
              "market_residual_blend":.55*q+.45*scores
            })

def backtest_training_groups(groups,begin,end):
    chosen={day:rs for day,rs in groups.items() if begin<=day[0]<end}
    if len(chosen)<30:raise RuntimeError("TOO_FEW_PAYOUT_TRAIN_VENUE_DAYS")
    return chosen

def build_features(groups,marketHelper,tickets,variant):
    x=[];paid=[];win=[];meta=[]
    for day,rs in sorted(groups.items()):
        for r in rs:
            v={**r,"probs":r["horseProbability"][variant]}
            bets=tickets.enumerate_tickets(v)
            if len(bets)<15:raise ValueError("TOO_FEW_OFFICIAL_TICKET_COMBINATIONS")
            order=np.argsort(-v["probs"],kind="stable")
            placeRank={int(i):j+1 for j,i in enumerate(np.argsort(-r["t3"],kind="stable"))}
            for ticket in bets:
                key,ix,prob,actual=ticket
                t3=np.asarray([r["t3"][i] for i in ix])
                ranks=[placeRank[i] for i in ix]
                t3_extra=[
                  *[float(r["t3"][int(i)]) for i in order[:3]],
                  float(sum(sorted(r["t3"],reverse=True)[:3])/3),
                  float(t3.mean()),float(t3.min()),
                  float(t3.prod()),float(sum(ranks)/36),
                  float(max(ranks)/18),float(len(bets)/200)]
                feats=tickets.features(v,ticket)+t3_extra+marketHelper.market_ticket_features(v,ticket,tickets)
                x.append(feats);paid.append(actual);win.append(int(actual>0))
                meta.append((day,r,ticket))
    xx=np.asarray(x,dtype=np.float32)
    yy=np.asarray(paid,dtype=np.float64);hits=np.asarray(win,dtype=np.int8)
    if len(xx)<10000 or not np.isfinite(xx).all():raise RuntimeError("INVALID_PRICE_HURDLE_FEATURE_ROWS")
    return xx,yy,hits,meta

def selftest():
    a=np.asarray([.5,.3,.2]);b=np.asarray([.4,.35,.25])
    x=model_vs_market_x(a,b)
    assert x.shape==(3,13) and np.isfinite(x).all()
    assert abs(x[:,4].sum()-1)<1e-7
    print("MARKET_RESIDUAL_CHRONO_SPLIT_SELFTEST_OK",flush=True)

def main():
    import sys
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","value_market_hist")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","value_market_payout")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","value_market_struct")
    ticket=load("scripts/research-two-stage-payout-value-2024-2025.py","value_market_tickets")
    market=load("scripts/research-market-residual-ranker-2025.py","value_market_close_source")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=structural.top3_targets(archive)
    meta=audit.eligible_metadata(archive)
    assert len(meta)==len(counts) and len(t3)==len(X)
    priceX,q,odds,valid,validRace,totals=market.market_archive(archive,counts,offsets,meta)
    actualPayouts,coverage=audit.payout_book()
    groups={};train={}
    for year in (2024,2025):
        (horse,top3),info=structural.fit_horse_models(X,y,t3,counts,offsets,dates,year)
        allgroups,invalid,n=structural.year_groups(year,X,counts,dates,offsets,
                    meta,(horse,top3),actualPayouts)
        groups[year]=valid_market_groups(structural,market,q,odds,valid,allgroups,year)
        train[str(year)]={"horseModel":info,"venueDays":len(groups[year]),
           "invalidPayoutGroups":invalid,"yearRaceCount":n}
        del horse,top3
    calibrator,marketTrain=fit_residual_model(groups[2024])
    for year in (2024,2025):attach_calibrated(groups[year],calibrator)
    # The 2024 payout model sees NO May-Aug rows used for market calibration,
    # and absolutely NO 2025 target labels or payouts.
    stage2Train=backtest_training_groups(groups[2024],"2024-09-01","2025-01-01")
    results={}
    for policy in MODELS:
        xtrain,paidtrain,hittrain,_=build_features(stage2Train,market,ticket,policy)
        hurdleP,hurdleReturn,priors=structural.fit_hurdle(xtrain,paidtrain,hittrain)
        x25,_,_,meta25=build_features(groups[2025],market,ticket,policy)
        scores=structural.score_rows(x25,meta25,(hurdleP,hurdleReturn),priors)
        scored=structural.selected_portfolio(groups[2025],scores,ticket)
        results[policy]={"metrics":scored["metrics"],
           "eligible2025VenueDays":scored["validVenueDays"],
           "excluded2025VenueDays":scored["unusableVenueDays"],
           "byMonth":scored["byMonth"],
           "payoutTrainRows":len(hittrain),"payoutTrainingMonths":["2024-09","2024-10","2024-11","2024-12"],
           "modelRunnerInputFeatures":13,
           "ticketValueFeatureCount":int(xtrain.shape[1]),
           "sampleTickets":scored["samplePredictions"]}
        print("CHRONO_MARKET_RESIDUAL_2025_PAIRED_JRA_ROI",json.dumps({
           "variant":policy,"metrics":scored["metrics"],
           "completedVenueDays":scored["validVenueDays"]},ensure_ascii=False),flush=True)
        del xtrain,paidtrain,hittrain,x25,meta25,hurdleP,hurdleReturn,scores
    report={"status":"RESEARCH_2024_INTRA_YEAR_SPLIT_MARKET_RESIDUAL_NOT_T15",
       "truthfulHistoricalMarketSource":"actual FINAL JRA win odds, NOT T15 observed",
       "zeroMarketAvailable2016to2023":True,
       "runnerBaseModelLabelsStrictlyPriorTargetYear":True,
       "marketCorrectionTraining":"2024 May-Aug observed JRA final odds and actual winners only",
       "marketCorrectionTrainingRows":marketTrain,
       "ticketPayoutHeadTraining":"2024 Sep-Dec official JRA payouts ONLY",
       "2025JraOutcomesNeverUsedForFeatureTraining":True,
       "historicalFinalOddsAreNotT15":True,
       "2025PreviouslyObservedInEarlierResearch":True,
       "noProductionPromotion":True,
       "payoutMarketMonthCoverage":coverage,
       "yearCohorts":train,"results":results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CHRONO_MARKET_RESIDUAL_MODEL_FINAL",json.dumps({
       "marketTrain":marketTrain,
       "policyResults":{k:v["metrics"] for k,v in results.items()},
       "researchNotT15":True},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
