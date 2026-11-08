#!/usr/bin/env python3
"""Fresh robust JRA horse + six-market payout learner, frozen Nov-2026 research.

OUTCOME: train through 2025, settle ONLY actual JRA 2026 Jan-Aug winnings.
No 2026 payouts used in fitting, hyperparameters, course choice or tuning.
Historical runner archive is not verified to have been captured at T-15.
Prior researchers saw 2026 outcomes, hence 2026 is retrospective stress,
NOT a new blind prospective holdout. NEVER promote on this study alone.
No production DB writes, bets, odds invention, or midrace predictions.

Changes versus the prior 127.95% payout model:
* Discriminative LightGBM race-grouped ranker blended with an independent
  extremely randomized winner model, plus top-three HGB.
* P(ticket hits) is fitted separately from E(payout | hit).
* The conditional paid tail is learned in log space after per-JRA-market
  training-only 95th-percentile winsorization, with explicit tail shrinkage.
* Choose 5 races per full venue-day, 2 distinct types per race, modeled hit
  floor >=20%, and settle actual JRA payouts on identical cohorts.
* The largest SINGLE paid ticket is removed while retaining the FULL stake.
* Reject any model failing minimum hit20 AND actual ROI200 AND trimmed ROI200.
"""
from __future__ import annotations

import collections
from collections import defaultdict, Counter
from pathlib import Path
import importlib.util
import json
import math
import sys

import numpy as np
from lightgbm import LGBMRanker
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, HistGradientBoostingRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-robust200-fresh-model-evidence.json"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAID_STAKE=2000
RACE_K=5
MIN_HIT_PCT=20.0
MIN_ROI_PCT=200.0
MIN_TRIM_ROI_PCT=200.0

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_CODE:"+path)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    return m

class WinEnsemble:
    def __init__(self,ranker,win_model):
        self.ranker=ranker
        self.win_model=win_model
    def predict(self,X,num_threads=2):
        ranks=self.ranker.predict(X,num_threads=num_threads)
        win=np.clip(self.win_model.predict_proba(X)[:,1],1e-6,1-1e-6)
        if not np.isfinite(ranks).all():raise ValueError("INVALID_RANKER")
        return 0.6*np.asarray(ranks)+0.4*np.log(win/(1-win))

def fit_horse(X,y,t3,counts,offsets,dates,year):
    indices=np.flatnonzero(dates<f"{year}-01-01")
    if len(indices)<10000:raise ValueError("INSUFFICIENT_CHRONOLOGICAL_TRAINING")
    finish=int(indices[-1]);end=int(offsets[finish+1])
    assert int(sum(counts[:finish+1]))==end
    assert str(dates[finish])<f"{year}-01-01"
    ranker=LGBMRanker(
      objective="lambdarank",metric="ndcg",
      n_estimators=155,learning_rate=0.035,num_leaves=15,
      min_child_samples=105,reg_lambda=12.0,colsample_bytree=0.75,
      random_state=20261108,n_jobs=2,verbosity=-1,
      lambdarank_truncation_level=5)
    ranker.fit(X[:end],y[:end].astype(np.int32),group=counts[:finish+1].tolist())
    winner=ExtraTreesClassifier(
      n_estimators=150,max_depth=12,min_samples_leaf=80,max_features=0.65,
      random_state=20261108,n_jobs=2)
    winner.fit(X[:end],y[:end])
    place=HistGradientBoostingClassifier(
      max_iter=170,learning_rate=0.035,max_leaf_nodes=17,
      min_samples_leaf=110,l2_regularization=15.0,
      early_stopping=False,random_state=20261108)
    place.fit(X[:end],t3[:end])
    return (WinEnsemble(ranker,winner),place),{
      "trainLastDate":str(dates[finish]),"trainRaces":finish+1,
      "trainRunnerRows":end,"ranker":"LightGBM LambdaRank",
      "winner":"ExtraTrees","placing":"HistGradientBoosting"}

def type_caps(X,paid,hit):
    caps={}
    for i,kind in enumerate(TYPES):
        winners=(X[:,i]>.5)&(hit>0)
        labels=np.asarray(paid[winners],dtype=np.float64)/100.0
        if len(labels)<10:raise RuntimeError("INSUFFICIENT_WINNERS_FOR_MARKET:"+kind)
        caps[kind]=float(max(1,np.quantile(labels,.95)))
    return caps

def fit_payout(X,paid,hit):
    if len(X)<10000 or X.shape[1]!=40 or np.sum(hit)<1500:
        raise RuntimeError("INSUFFICIENT_PAYOUT_CANDIDATES")
    pa=HistGradientBoostingClassifier(
      max_iter=160,learning_rate=0.035,max_leaf_nodes=17,
      min_samples_leaf=120,l2_regularization=18,
      early_stopping=False,random_state=20261108)
    pa.fit(X,hit)
    caps=type_caps(X,paid,hit)
    winners=hit>0
    y=np.empty(int(winners.sum()))
    positiveX=X[winners]
    positivePaid=paid[winners]
    for j,idx in enumerate(np.flatnonzero(winners)):
        typ=TYPES[int(np.argmax(X[idx,:6]))]
        y[j]=math.log(max(1,min(positivePaid[j]/100.0,caps[typ])))
    conditional=HistGradientBoostingRegressor(
      loss="squared_error",max_iter=165,learning_rate=0.04,
      max_leaf_nodes=17,min_samples_leaf=60,l2_regularization=28,
      early_stopping=False,random_state=20261108)
    conditional.fit(positiveX,y)
    priors={}
    for i,typ in enumerate(TYPES):
        mask=X[:,i]>.5
        total=int(mask.sum());wins=int((mask&winners).sum())
        winv=np.minimum(paid[mask&winners]/100.0,caps[typ])
        priors[typ]={
          "hit":(wins+15)/(total+150),
          "conditionalPaid":float(np.mean(winv)) if len(winv) else 1.0,
          "wins":wins,"tickets":total}
    return (pa,conditional,caps,priors)

def estimate_payout(X,metadata,models):
    pa,conditional,caps,priors=models
    probs=pa.predict_proba(X)[:,1]
    amounts=np.exp(conditional.predict(X))
    if not np.isfinite(amounts).all():raise RuntimeError("NONFINITE_PAYOUT")
    by_race=defaultdict(list)
    for i,(day,r,t) in enumerate(metadata):
        kind=t[0][0]
        prior=priors[kind]
        calibrated=.80*float(probs[i])+.20*float(prior["hit"])
        conditionalPaid=.75*float(np.clip(amounts[i],1,caps[kind]))+.25*prior["conditionalPaid"]
        # Penalize lucrative but scarcely hit combinations; prevent a single
        # modeled jackpot from dominating all five race slots.
        tailPenalty=1/(1+0.20*max(0,conditionalPaid-15)/15)
        utility=calibrated*conditionalPaid*tailPenalty
        by_race[(day,r["raceId"])].append({
          "key":t[0],"payout100":int(t[3]),
          "hitP":calibrated,"riskAdjustedE":utility})
    return by_race

def select_and_settle(groups,scored):
    all_records=[]
    missing=Counter()
    for day,rs in sorted(groups.items()):
        pool=[]
        for race in rs:
            rows=scored.get((day,race["raceId"]),[])
            bestByType={}
            for row in rows:
                typ=row["key"][0]
                prior=bestByType.get(typ)
                if prior is None or row["riskAdjustedE"]>prior["riskAdjustedE"]:
                    bestByType[typ]=row
            if len(bestByType)!=len(TYPES):continue
            opts=sorted(bestByType.values(),key=lambda q:-q["riskAdjustedE"])
            best=None
            for i,a in enumerate(opts):
                for b in opts[i+1:]:
                    if max(a["hitP"],b["hitP"])<.20:continue
                    stakeA=1900 if a["riskAdjustedE"]>=b["riskAdjustedE"] else 100
                    stakeB=2000-stakeA
                    score=stakeA*a["riskAdjustedE"]+stakeB*b["riskAdjustedE"]
                    if best is None or score>best[0]:
                        best=(score,a,b,stakeA,stakeB)
            if not best:continue
            score,a,b,stakeA,stakeB=best
            ticketReturns=[a["payout100"]*(stakeA//100),b["payout100"]*(stakeB//100)]
            pool.append({
              "date":race["date"],"venue":race["venue"],"raceId":race["raceId"],
              "score":float(score)/2000,"stake":PAID_STAKE,
              "returned":sum(ticketReturns),"largestTicketReturn":max(ticketReturns),
              "hit":int(any(x>0 for x in ticketReturns)),
              "tickets":[{"betType":v["key"][0],
                  "combination":"-".join(map(str,v["key"][1])),
                  "stakeYen":stake,"hitP":v["hitP"],
                  "returnYen":ret} for v,stake,ret in
                  [(a,stakeA,ticketReturns[0]),(b,stakeB,ticketReturns[1])]]
            })
        if len(pool)<RACE_K:
            missing["fewer_than_5_model_eligible_races"]+=1
            continue
        all_records.extend(sorted(pool,key=lambda x:(-x["score"],x["raceId"]))[:RACE_K])
    return all_records,dict(missing)

def summarize(records):
    n=len(records)
    if not n:return {"races":0,"promotionEligible":False}
    if n%RACE_K:raise AssertionError("INCOMPLETE_VENUE_DAY")
    stake=sum(int(x["stake"]) for x in records)
    returned=sum(int(x["returned"]) for x in records)
    biggest=max((int(t["returnYen"]) for r in records for t in r["tickets"]),default=0)
    biggestRace=max(int(r["returned"]) for r in records)
    hit=sum(int(r["hit"]) for r in records)
    out={
      "races":n,"venueDays":n//RACE_K,"stakeYen":stake,"returnYen":returned,
      "hitRaces":hit,"hitRatePct":round(100*hit/n,4),
      "roiPct":round(100*returned/stake,4),
      "roiExcludeLargestTicketKeepAllStakePct":round(100*(returned-biggest)/stake,4),
      "roiExcludeLargestRaceKeepAllStakePct":round(100*(returned-biggestRace)/stake,4),
      "largestPaidTicketYen":biggest,"largestPaidRaceYen":biggestRace,
      "promotionEligible":False,
    }
    return out

def self_test():
    def row(day,rid,ret1,ret2):
        return {"date":day,"raceId":rid,"venue":"東京",
          "score":1.0,"stake":2000,"returned":ret1+ret2,
          "largestTicketReturn":max(ret1,ret2),"hit":int(ret1>0 or ret2>0),
          "tickets":[{"returnYen":ret1},{"returnYen":ret2}]}
    rows=[row("2026-01-03",f"test{i}",r1,r2) for i,(r1,r2) in
      enumerate([(19000,0),(0,10000),(0,0),(11000,0),(0,0)])]
    result=summarize(rows)
    assert result["stakeYen"]==10000
    assert result["returnYen"]==40000
    assert result["roiPct"]==400
    assert result["roiExcludeLargestTicketKeepAllStakePct"]==210
    assert result["roiExcludeLargestRaceKeepAllStakePct"]==210
    # Never remove stake with a missed or refunded ticket; never subtract the
    # maximum twice. 200.00 is included, 199.99 fails, hit below 20 fails.
    gate_ok={**result,"races":500,"allEligibleVenueDaysCovered":True}
    assert passes_numeric_gate(gate_ok) is True
    assert not passes_numeric_gate(result), "at least 500 races required"
    for x in ("hitRatePct","roiPct","roiExcludeLargestTicketKeepAllStakePct",
              "roiExcludeLargestRaceKeepAllStakePct"):
        bad=dict(gate_ok);bad[x]=19.99 if x=="hitRatePct" else 199.99
        assert not passes_numeric_gate(bad)
    print("NOV2026_FRESH_ROBUST_200_MODEL_SELF_TEST_OK",flush=True)

def passes_numeric_gate(result):
    return (result.get("allEligibleVenueDaysCovered") is True
      and result.get("races",0)>=500
      and result.get("hitRatePct",0)>=MIN_HIT_PCT
      and result.get("roiPct",0)>=MIN_ROI_PCT
      and result.get("roiExcludeLargestTicketKeepAllStakePct",0)>=MIN_TRIM_ROI_PCT
      and result.get("roiExcludeLargestRaceKeepAllStakePct",0)>=MIN_TRIM_ROI_PCT)

def main():
    if "--self-test" in sys.argv:
        self_test();return
    # The D1 quota is live-critical on race days. External orchestration must
    # never invoke full historical data queries before the JRA race-day ends.
    import os,datetime as dt
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    if now.weekday() in (5,6) and now.hour<22:
        raise RuntimeError("D1_RESEARCH_BLOCKED_DURING_RACE_DAY")
    hist=module("scripts/postaug-support-chronological-56feature-validation.py","fresh_archive")
    helper=module("scripts/research-extra-trees-2024-2025-paired-jra.py","fresh_official")
    struct=module("scripts/research-structural-ranker-twohead-2025.py","fresh_struct")
    tickets=module("scripts/research-two-stage-payout-value-2024-2025.py","fresh_tickets")
    payouts_source=module("scripts/research-payout-hurdle-pooled-2026.py","fresh_payouts")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    top3=struct.top3_targets(archive)
    meta=helper.eligible_metadata(archive)
    if len(meta)!=len(counts) or len(top3)!=len(y):
        raise ValueError("MODEL_ARCHIVE_ALIGNMENT_MISMATCH")
    payouts,payout_coverage=payouts_source.official_paid_payouts(helper)
    periods={}
    training={}
    for year in (2024,2025,2026):
        model,info=fit_horse(X,y,top3,counts,offsets,dates,year)
        groups,excluded,raw=struct.year_groups(year,X,counts,dates,offsets,meta,model,payouts)
        periods[year]=groups
        training[str(year)]={"horse":info,"acceptedVenueDays":len(groups),
          "excludedVenueDays":excluded,"rawRaces":raw}
        print("NOV26_NEW_HORSE_MODEL",year,json.dumps(training[str(year)]),flush=True)
    X24,p24,h24,_=struct.build_rows(periods[2024],tickets,"ranker_only")
    X25,p25,h25,_=struct.build_rows(periods[2025],tickets,"ranker_only")
    # Frozen 2024+25 payout fit. Independent 2026 actual payouts only settle.
    Xtrain=np.concatenate((X24,X25),axis=0)
    model=fit_payout(Xtrain,np.concatenate((p24,p25)),np.concatenate((h24,h25)))
    X26,_,_,metadata=struct.build_rows(periods[2026],tickets,"ranker_only")
    score=estimate_payout(X26,metadata,model)
    bets,excluded=select_and_settle(periods[2026],score)
    metrics=summarize(bets)
    metrics["eligibleVenueDays"]=len(periods[2026])
    metrics["fullySelectedVenueDays"]=len(bets)//RACE_K
    metrics["allEligibleVenueDaysCovered"]=(
      len(bets)==RACE_K*len(periods[2026]) and not excluded)
    months=defaultdict(list)
    for item in bets:months[item["date"][:7]].append(item)
    monthly={}
    for month,items in months.items():
        if len(items)%RACE_K:raise AssertionError("MONTH_NOT_WHOLE_VENUE_DAYS")
        monthly[month]=summarize(items)
    numeric=passes_numeric_gate(metrics)
    output={
      "researchVersion":"nov2026-fresh-win-ensemble-logpaid-p95",
      "evaluation":"RETROSPECTIVE_2026_JAN_AUG_ACTUAL_JRA_NOT_T15_PROVEN",
      "trainingHorseEnd":"2025-12-28",
      "payoutTrainingYears":[2024,2025],
      "2026ResultLabelsUsedForTraining":False,
      "2026AlreadyInspectedPriorToThisStudy":True,
      "exactPreT15RunnerProvenance":False,
      "exactPreT15OfficialMarketQuotesPresentInTraining":False,
      "metrics":metrics,
      "monthlyActualJraMetrics":monthly,
      "yearTrainingAudit":training,
      "officialPayoutMonthCoverage":payout_coverage,
      "excludedVenueDays":excluded,
      "maxPaidTicketRemovedButStakeRetained":True,
      "maxPaidRaceRemovedButStakeRetained":True,
      "minimumHitPct":MIN_HIT_PCT,
      "minimumRoiPct":MIN_ROI_PCT,
      "minimumRoiMinusLargestPct":MIN_TRIM_ROI_PCT,
      "numericGatePassed":numeric,
      "productionPromotionAllowed":False,
      "missingProspectiveT15ProvenanceBlocksPromotion":True,
      "immutableProductionBetsWritten":False,
      "createdFromFrozenResearchArchitecture":True,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NOV2026_FRESH_ROBUST200_REAL_JRA",json.dumps(
      {"metrics":metrics,"numericGatePassed":numeric,
       "promotionAllowed":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
