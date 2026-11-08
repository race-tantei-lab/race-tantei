#!/usr/bin/env python3
"""2026 (Aug--Nov 7) independent chronological retest of 2025 winning candidate.

Candidate locked from earlier exploratory 2025 investigation:
  market_residual_calibrated, race-first LambdaRank with a residual
  bookmaker-market classifier and two-part payout prediction.

NO 2026 outcomes are used for training or choice:
  2025 runner abilities trained on <=2024 labels, run on 2025
  genuine FINAL win prices in 2025 Jan-Aug to fit market residual.
  2025 Sep-Dec actual JRA payouts fit the payout head.
  2026 runner ability refit on <=2025 historical labels.
  Model and payout head are frozen on 2026 Aug-Nov evaluation.
  2026 genuine FINAL win prices (not T15) enter predictions, BEFORE
  target JRA payout is joined for settlement. This is an archive proxy.

Do not call this a true prospective live test: target 2026 year data has
been inspected in earlier studies and archival FINAL odds are post-T15.
Only D1 2025 Jan-Dec + 2026 Aug-Nov 7 read-only bounded monthly lookups.
No production write or cash bet.
"""
from __future__ import annotations
from collections import defaultdict,Counter
import datetime as dt
import json,math,sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/2026-forward-2025-frozen-market-residual-JRA.json"
FROZEN="market_residual_calibrated"
ALL=("horse_model_only","pure_market","market_residual_calibrated","market_residual_blend")
START_2026="2026-08-09"
END_2026="2026-11-08"
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
UNORDERED={"ワイド","馬連","3連複"}
STAKE=2000
RACE_K=5

def load(path,name):
    import importlib.util
    p=ROOT/path
    spec=importlib.util.spec_from_file_location(name,p)
    if not spec or not spec.loader:raise RuntimeError("DEPENDENCY_NOT_FOUND "+path)
    ob=importlib.util.module_from_spec(spec);sys.modules[name]=ob;spec.loader.exec_module(ob)
    return ob

def read_actual_payouts(helper):
    payouts=defaultdict(dict);coverage={}
    for year,monthSet in ((2025,tuple(range(1,13))),(2026,(8,9,10,11))):
        for month in monthSet:
            begin=f"{year}-{month:02d}-"
            ending=(dt.date(year,month,1)+dt.timedelta(days=35)).replace(day=1).strftime("%Y-%m-")
            rows=helper.read_d1("""SELECT race_id raceId,bet_type betType,combination,
                  payout_yen payoutYen FROM rt_payouts
                  WHERE race_id>=? AND race_id<? ORDER BY race_id,bet_type,combination
                  LIMIT 4800""",[begin,ending])
            if len(rows)>=4800:raise RuntimeError("TRUNCATED_OFFICIAL_PAYOUT_MONTH "+begin)
            for row in rows:
                typ=row["betType"]
                if typ not in TYPES:continue
                combo=tuple(map(int,str(row["combination"]).split("-")))
                if len(combo)!=(1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2):
                    raise ValueError("BAD_JRA_PAYOUT_COMBINATION")
                if len(set(combo))!=len(combo):raise ValueError("DUPLICATED_JRA_HORSE")
                if typ in UNORDERED:combo=tuple(sorted(combo))
                key=(typ,combo);rid=row["raceId"];amount=int(row["payoutYen"])
                if amount<0:raise ValueError("NEGATIVE_JRA_PAYOUT")
                if key in payouts[rid] and payouts[rid][key]!=amount:raise AssertionError("CONFLICTING_JRA_PAYOUT")
                payouts[rid][key]=amount
            coverage[begin]={"rows":len(rows),"races":len(set(r["raceId"] for r in rows))}
            print("FROZEN_2026_REAL_PAYOUT_COVERAGE",begin,coverage[begin],flush=True)
    return payouts,coverage

def calibrate2025(groups,market2024):
    xx=[];yy=[];dates=set();n=0
    for day,rs in sorted(groups.items()):
        if not "2025-01-01"<=day[0]<"2025-09-01":continue
        dates.add(day)
        for r in rs:
            p=r["horseProbability"]["ranker_only"]
            q=r["marketQ"]
            vals=market2024.model_vs_market_x(p,q)
            paid=[key[1][0] for key,amount in r["payout"].items()
                if key[0]=="単勝" and int(amount)>0]
            if len(paid)!=1:raise RuntimeError("2025_CALIBRATION_UNIQUE_WINNER_MISSING")
            labels=np.asarray([int(h==paid[0]) for h in r["horses"]],dtype=np.int8)
            if sum(labels)!=1:raise AssertionError("NONUNIQUE_JRA_WINNER")
            xx.extend(vals.tolist());yy.extend(labels.tolist());n+=1
    if n<800 or len(xx)<10000:raise RuntimeError("2025_MARKET_CALIBRATION_NOT_ENOUGH")
    model=HistGradientBoostingClassifier(max_iter=110,learning_rate=.04,
        max_leaf_nodes=11,min_samples_leaf=110,l2_regularization=15,
        early_stopping=False,random_state=20261108)
    model.fit(np.asarray(xx,dtype=np.float32),np.asarray(yy,dtype=np.int8))
    print("FROZEN_2026_MARKET_CALIBRATOR_TRAINED",
       json.dumps({"races":n,"venueDays":len(dates),"first":"2025-01-01",
          "last":"2025-08-31","ticketTrainOverlap":False}),flush=True)
    return model,{"races":n,"venueDays":len(dates),"horseRows":len(xx),
         "first":"2025-01-01","last":"2025-08-31"}

def selftest():
    import numpy as np
    a=np.array([.45,.30,.25])
    assert abs(a.sum()-1)<1e-9
    assert FROZEN in ALL and RACE_K==5
    assert START_2026<END_2026 and END_2026<"2026-11-09"
    print("FROZEN_MARKET_RESIDUAL_2026_RETEST_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","f2026_hist")
    helper=load("scripts/research-extra-trees-2024-2025-paired-jra.py","f2026_payout")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","f2026_struct")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","f2026_tickets")
    market=load("scripts/research-market-residual-ranker-2025.py","f2026_market")
    research=load("scripts/research-market-2024-split-calibration-2025.py","f2026_calib")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=structural.top3_targets(archive)
    meta=helper.eligible_metadata(archive)
    assert len(meta)==len(counts) and len(t3)==len(X)
    assert all(meta[i]["date"]==str(dates[i]) and meta[i]["field"]==int(counts[i]) for i in range(len(counts)))
    marketM,q,odds,valid,validRace,totals=market.market_archive(archive,counts,offsets,meta)
    payout,coverage=read_actual_payouts(helper)
    # Train 2025 horse model strictly on <=2024 winners and placements.
    horse2025,train2025=structural.fit_horse_models(X,y,t3,counts,offsets,dates,2025)
    full2025,excluded2025,count2025=structural.year_groups(
        2025,X,counts,dates,offsets,meta,horse2025,payout)
    train2025=research.valid_market_groups(structural,market,q,odds,valid,full2025,2025)
    if len(train2025)<100:raise RuntimeError("2025_MARKET_CALIBRATION_TRAIN_DAYS_LT100")
    calibrator,info=calibrate2025(train2025,research)
    research.attach_calibrated(train2025,calibrator)
    payoutTraining=research.backtest_training_groups(train2025,"2025-09-01","2026-01-01")
    # Train ONLY the historically selected 2025 winning hypothesis.
    trX,trPaid,trHit,_=research.build_features(payoutTraining,market,tickets,FROZEN)
    hurdleHit,hurdlePayout,priors=structural.fit_hurdle(trX,trPaid,trHit)
    del trX,trPaid,trHit,horse2025
    print("FROZEN_2026_TICKET_PAYOUT_MODEL_TRAINED",json.dumps({
       "trainVenueDays":len(payoutTraining),"variant":FROZEN,
       "payoutLabelLastDate":"2025-12-28","no2026OutcomesInFit":True}),flush=True)
    horse2026,train2026=structural.fit_horse_models(X,y,t3,counts,offsets,dates,2026)
    # 2026 Aug-Nov 7 subset only, avoids high-cost D1 payout requests Jan-Jul.
    target=np.flatnonzero((dates>=START_2026)&(dates<END_2026))
    if len(target)<300:raise RuntimeError("NO_2026_AUG_NOV_HISTORY")
    lo=int(offsets[target[0]]);hi=int(offsets[target[-1]+1])
    scorer,placer=horse2026
    scores=scorer.predict(X[lo:hi],num_threads=2)
    top3=placer.predict_proba(X[lo:hi])[:,1]
    groupsRaw=defaultdict(list);cursor=0
    for i in target:
        i=int(i);m=meta[i];n=int(counts[i]);s=scores[cursor:cursor+n]
        p=structural.softmax(s,temp=1.4)
        pt=np.clip(top3[cursor:cursor+n],1e-6,1)
        cursor+=n
        groupsRaw[(m["date"],m["venue"])].append({
          "raceId":m["rid"],"date":m["date"],"venue":m["venue"],
          "raceNo":int(m["no"]),"horses":tuple(int(t) for t in m["horses"]),
          "t3":pt,"payout":payout.get(m["rid"],{}),
          "horseProbability":{"ranker_only":p}
        })
    assert cursor==len(scores)
    completed={};rejected=Counter()
    for day,rows in sorted(groupsRaw.items()):
        if len(rows)!=12 or {r["raceNo"] for r in rows}!=set(range(1,13)):
            rejected["not_12_races_venue_day"]+=1;continue
        if any({t for t,_ in r["payout"]}!=TYPES for r in rows):
            rejected["incomplete_six_market_JRA_payout"]+=1;continue
        if any(not valid.get(r["raceId"],False) for r in rows):
            rejected["not_all_genuine_FINAL_win_odds"]+=1;continue
        for r in rows:
            r["marketQ"]=q[r["raceId"]]
            r["marketOdds"]=odds[r["raceId"]]
        completed[day]=sorted(rows,key=lambda r:r["raceNo"])
    if len(completed)<15:raise RuntimeError("NO_ENOUGH_2026_COMPLETE_MARKET_VENUE_DAYS "+str(len(completed)))
    print("FROZEN_2026_POSTAUG_COHORT",json.dumps({"days":len(completed),
      "races":len(completed)*12,"excluded":dict(rejected)},ensure_ascii=False),flush=True)
    research.attach_calibrated(completed,calibrator)
    modelFeatures,_,_,modelMeta=research.build_features(completed,market,tickets,FROZEN)
    scores=structural.score_rows(modelFeatures,modelMeta,(hurdleHit,hurdlePayout),priors)
    output=structural.selected_portfolio(completed,scores,tickets)
    metrics=output["metrics"]
    yearlyMonths={k:v for k,v in output["byMonth"].items()}
    result={"study":"2026_aug_nov_frozen_2025_selected_market_residual_calibrated",
        "targetPeriod":[START_2026,END_2026],
        "2025HistoricalCandidateWasChosenAfter2025WasInspected":True,
        "2026DataPreviouslyInspectedInOtherStudies":True,
        "2026OutcomeOnlyUsedForSettlement":True,
        "2026HorseModelTrainedThrough":train2026["horseTrainThrough"],
        "marketCalibrator2025Training":info,
        "ticketValueTrainingMonths":"2025-09..2025-12",
        "train2025Horse":train2025,
        "stage2TrainingVenueDays":len(payoutTraining),
        "2026NoRefitOrModelChoice":True,
        "model":"market_residual_calibrated",
        "genuine2026Market":"archival FINAL win odds, NOT T-15",
        "2026RunnerFeatureT15Proven":False,
        "sameRaceHitAndJraPayoutRoi":metrics,
        "months":yearlyMonths,
        "excluded2026VenueDays":dict(rejected),
        "eligible2026VenueDays":len(completed),
        "actualJraPayoutCoverage":coverage,
        "sampleTickets":output["samplePredictions"],
        "productionEligible":False,
        "realCashBetsPlaced":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FROZEN_MARKET_RESIDUAL_2026_FINAL_JRA_PAIRED",
      json.dumps({"metrics":metrics,"2026VenueDays":len(completed),
        "months":yearlyMonths,"production":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
