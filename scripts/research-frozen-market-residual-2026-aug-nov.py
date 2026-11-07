#!/usr/bin/env python3
"""Read-only Aug10-Nov7 2026 test for 2024-frozen market residual and payout learner.

2024 market correction fit using actual final win odds May-Aug 2024.
2024 payout model fit using actual JRA payouts Sep-Dec 2024.
Winner ranking strength model fit through 2026-08-09; no test-period labels.
2026 Aug-Nov JRA payouts ONLY settle simulated candidate tickets.
Archive 2026 win odds NOT timestamp-proven T15, so this is a retrospective
closing-market simulation, NOT an actual locked-bets performance claim.
No synthetic odds, no D1 writes and no production modifications.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from pathlib import Path
import datetime as dt
import json,math,re,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
START,END="2026-08-10","2026-11-08"
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
UNORDERED={"ワイド","馬連","3連複"}
OUT=ROOT/"analysis-results/2026aug-market-residual-jra-payout-not-t15.json"

def load(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_SCRIPT:"+path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def actual_market(active):
    odds=[]
    for a in active:
        try:v=float(a.get("winOdds"))
        except (TypeError,ValueError):return None
        if not math.isfinite(v) or v<=1:return None
        odds.append(v)
    odds=np.asarray(odds,dtype=np.float64)
    q=1/odds;q/=q.sum()
    return q,odds

def six_market_book(live):
    out=defaultdict(dict)
    summary={}
    for month in ("2026-08","2026-09","2026-10","2026-11"):
        stop=(dt.date.fromisoformat(month+"-01")+dt.timedelta(days=35)).replace(day=1).strftime("%Y-%m")
        rows=live.d1_query("""SELECT race_id raceId,bet_type betType,combination,
          payout_yen payoutYen FROM rt_payouts WHERE race_id>=? AND race_id<?
          AND bet_type IN ('単勝','ワイド','馬連','馬単','3連複','3連単')
          ORDER BY race_id,bet_type,combination LIMIT 5000""",[month+"-",stop+"-"])
        if len(rows)>=5000:raise ValueError("D1_PAYOUT_MONTH_TRUNCATED")
        for row in rows:
            typ=row["betType"]
            combo=tuple(int(x) for x in re.findall(r"\d+",str(row["combination"])))
            if typ in UNORDERED:combo=tuple(sorted(combo))
            expected=1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2
            if len(combo)!=expected:raise ValueError("INVALID_JRA_PAYOUT_COMBO")
            n=int(row["payoutYen"])
            if n<0 or n%10:raise ValueError("INVALID_JRA_REAL_PAYOUT")
            k=(typ,combo);rid=row["raceId"]
            if k in out[rid] and out[rid][k]!=n:raise ValueError("CONFLICTING_OFFICIAL_JRA_PAYOUT")
            out[rid][k]=n
        summary[month]={"payoutRows":len(rows),"races":len({r["raceId"] for r in rows})}
        print("AUGNOV_JRA_PAYOUT_MONTH",month,summary[month],flush=True)
    return out,summary

def pre_result_2026(live,hist,core,archive,ranker,placer,calib,payout,marketwalk):
    state=hist.fresh_feature_state()
    for date,day in sorted(archive.items()):
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    assert state["throughDate"]=="2026-08-09"
    features=core.load_config()["runnerProbabilityModel"]["features"]
    bydate,_=live.d1_bundles()
    allgroups=defaultdict(list)
    rejected=Counter()
    for date,day in sorted(bydate.items()):
        if not START<=date<END:continue
        candidates=[]
        for bundle in sorted(day,key=lambda x:(x["race"]["venue"],int(x["race"]["raceNo"]))):
            r=bundle["race"]
            active=sorted((a for a in bundle["runners"] if a.get("runnerStatus") in (None,"","active")),
                key=lambda x:int(x["horseNo"]))
            group=(date,r["venue"])
            proto={"date":date,"venue":r["venue"],"raceNo":int(r["raceNo"]),
                "raceId":r["raceId"],"payout":payout.get(r["raceId"],{})}
            if r["status"]!="finished" or len(active)<3 or sum(
                    x.get("finishPosition")==1 for x in bundle["results"])!=1:
                rejected["MISSING_RESULT_OR_VALID_RUNNERS"]+=1
                allgroups[group].append({**proto,"invalid":"NO_FINISHED_RESULT"})
                continue
            market=actual_market(active)
            if market is None:
                rejected["MISSING_REAL_FINAL_WIN_ODDS"]+=1
                allgroups[group].append({**proto,"invalid":"NO_REAL_WIN_ODDS"})
                continue
            if {k[0] for k in proto["payout"]}!=TYPES:
                rejected["MISSING_ACTUAL_SIX_TYPE_JRA_PAYOUT"]+=1
                allgroups[group].append({**proto,"invalid":"NO_SIX_TYPE_PAYOUT"})
                continue
            feat=np.asarray([[float(core.ml_feature_row(state,r,x,len(active))[name]) for name in features]
                for x in active],dtype=np.float32)
            if not np.all(np.isfinite(feat)):
                rejected["NONFINITE_FEATURES"]+=1
                allgroups[group].append({**proto,"invalid":"BAD_FEATURE_VECTOR"})
                continue
            candidates.append((group,proto,active,market,feat))
        # The state is NEVER updated with any same-day result before the
        # complete day's candidate model features are already calculated.
        if candidates:
            batch=np.concatenate([x[-1] for x in candidates],axis=0)
            ranked=ranker.predict(batch,num_threads=2)
            top3=placer.predict_proba(batch)[:,1]
            cursor=0
            for group,proto,active,(q,odds),feat in candidates:
                n=len(active)
                raw=np.asarray(ranked[cursor:cursor+n],dtype=float)
                p=np.exp(np.clip((raw-np.max(raw))/1.4,-60,0));p/=p.sum()
                t3=np.clip(top3[cursor:cursor+n],1e-6,1)
                cursor+=n
                corrected=calib.predict_proba(marketwalk.model_vs_market_x(p,q))[:,1]
                corrected=np.maximum(corrected,1e-10);corrected/=corrected.sum()
                allgroups[group].append({**proto,"horses":tuple(int(x["horseNo"]) for x in active),
                  "t3":t3,"marketQ":q,"marketOdds":odds,
                  "horseProbability":{"ranker_only":p,
                                       "market_residual_calibrated":corrected}})
            assert cursor==len(ranked)==len(top3)
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    eligible={};exclusion=Counter()
    for group,rows in allgroups.items():
        if len(rows)!=12 or {r["raceNo"] for r in rows}!=set(range(1,13)):
            exclusion["VENUE_DAY_NOT_ALL_12_RACES"]+=1;continue
        if any("invalid" in x for x in rows):
            exclusion["VENUE_DAY_MISSING_ANY_OFFICIAL_ODDS_PAYOUT_OR_RESULT"]+=1;continue
        eligible[group]=sorted(rows,key=lambda x:x["raceNo"])
    if len(eligible)<10:raise RuntimeError("INSUFFICIENT_COMPLETE_2026_MARKET_VENUE_DAYS")
    print("AUGNOV_MARKET_ELIGIBLE_VENUE_DAYS",json.dumps({
      "complete":len(eligible),"exclusions":dict(exclusion),
      "reasons":dict(rejected)},ensure_ascii=False),flush=True)
    return eligible,dict(exclusion),dict(rejected)

def selftest():
    m=actual_market([{"winOdds":"2.0"},{"winOdds":"5.0"},{"winOdds":"10.0"}])
    assert m is not None and abs(sum(m[0])-1)<1e-12
    assert actual_market([{"winOdds":2},{"winOdds":None},{"winOdds":3}]) is None
    print("AUGNOV_MARKET_RESIDUAL_BACKTEST_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","aug_historical")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","aug_payout_historical")
    market=load("scripts/research-market-residual-ranker-2025.py","aug_market")
    walk=load("scripts/research-market-2024-split-calibration-2025.py","aug_walkforward")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","aug_structural")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","aug_tickets")
    live=load("scripts/postaug-support-aug-nov-frozen-policy-recheck.py","aug_d1")
    archive=hist.load_bundles(hist.load_public_archive())
    core=hist.core_module()
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,archive)
    t3=structural.top3_targets(archive)
    meta=audit.eligible_metadata(archive)
    _,mq,odd,valid,_,_=market.market_archive(archive,counts,offsets,meta)
    payouts24,_=audit.payout_book()
    (horse24,place24),info24=structural.fit_horse_models(X,y,t3,counts,offsets,dates,2024)
    groups24,_,_=structural.year_groups(2024,X,counts,dates,offsets,
                    meta,(horse24,place24),payouts24)
    groups24=walk.valid_market_groups(structural,market,mq,odd,valid,groups24,2024)
    residual,trainInfo=walk.fit_residual_model(groups24)
    walk.attach_calibrated(groups24,residual)
    september=walk.backtest_training_groups(groups24,"2024-09-01","2025-01-01")
    X24,y24,h24,_=walk.build_features(september,market,tickets,
                                     "market_residual_calibrated")
    a,b,priors=structural.fit_hurdle(X24,y24,h24)
    del horse24,place24,X24,y24,h24
    (rank26,place26),info26=structural.fit_horse_models(
        X,y,t3,counts,offsets,dates,2027)
    if info26["horseTrainThrough"]!="2026-08-09":
        raise AssertionError("HORSE_RANKER_HAS_WRONG_LAST_LABEL_DATE")
    payouts26,monthPayouts=six_market_book(live)
    groups26,bad,missing=pre_result_2026(live,hist,core,archive,
        rank26,place26,residual,payouts26,walk)
    X26,_,_,meta26=walk.build_features(groups26,market,tickets,
                                       "market_residual_calibrated")
    forecasts=structural.score_rows(X26,meta26,(a,b),priors)
    portfolio=structural.selected_portfolio(groups26,forecasts,tickets)
    result={"status":"REAL_2026_JRA_PAYOUT_COUNTERFACTUAL_FINAL_WIN_ODDS_NOT_T15",
       "trainMarketCorrection":"2024 May-Aug FINAL JRA win odds and historical winner",
       "trainPayoutHead":"2024 Sep-Dec official JRA payout only",
       "horseTrainingLastDate":info26["horseTrainThrough"],
       "exclude2026AugNovLabelsFromAllModels":True,
       "noTrueT15QuoteTimestampForHistoricWinOdds":True,
       "noActualFrozenPreT15Tickets":True,
       "2026PeriodPreviouslyInspectedInOtherStudies":True,
       "promotionEligible":False,
       "dateFrom":START,"dateToInclusive":"2026-11-07",
       "sourceMonthPayouts":monthPayouts,
       "marketCorrectionTrain":trainInfo,
       "completeD1VenueDays":len(groups26),"excludedD1VenueDays":bad,
       "missingEvidence":missing,"selectedVenueDays":portfolio["validVenueDays"],
       "samePopulationHitAndRoi":portfolio["metrics"],
       "monthlyResults":portfolio["byMonth"],
       "excludedByModeledHitFloor":portfolio["unusableVenueDays"],
       "sampleTickets":portfolio["samplePredictions"]}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AUGNOV_MARKET_RESIDUAL_JRA_RETURN_AUDIT",json.dumps({
        "metrics":result["samePopulationHitAndRoi"],"months":result["monthlyResults"],
        "venueDays":result["completeD1VenueDays"],
        "promotionEligible":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
