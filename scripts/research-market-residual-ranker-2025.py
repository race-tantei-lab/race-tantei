#!/usr/bin/env python3
"""Genuine model-core market-relative race ranking and payout-hurdle study.

TRAIN/EVAL WARNING: 2016-2025 archive has historically saved *FINAL* JRA WIN
odds, NOT verified pre-T15 quotes. This is an exploratory closing-odds
benchmark and MUST NOT be called production-equivalent or a forward betting
profit even if historical JRA settlement ROI happens to exceed 100%.
No synthetic, estimated or post-result winning odds are treated as official
pre-T15 inputs. Missing final odds reject the entire 12-race venue-day.

Core change:
 - race-grouped LambdaRank gets 8 new price-relative market fields together
   with original 56 pre-result horse attributes.
 - value head gets 11 explicit model-vs-market mispricing fields, learns
   P(ticket pays) * E(actual JRA payout | hit) from 2024 true payouts.
 - evaluate raw market-ranking, market-corrected rank, and blended model
   using IDENTICAL yearwise training architecture, 2025 true JRA payouts.
 - each 2024 model uses labels through 2023, 2025 model labels through
   2024. 2024 payouts train the hurdle only, 2025 payouts settle only.
 - same 5 races/venue, 2 distinct bet types, ¥2000/race; actual race hit
   >=20% is the user's selection gate, and real ROI matters most.
Research only; no D1 or Worker mutations, no production promotion.
"""
from __future__ import annotations
from collections import defaultdict,Counter
import json,math
from pathlib import Path
import numpy as np
from lightgbm import LGBMRanker
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/market-relative-ranking-2025-exploratory-close-odds.json"
MODEL_VARIANTS=("market_ranker","market_corrected_blend","market_implied_only")
SEED=20261108

def load(path,name):
    import importlib.util,sys
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("REQUIRED_HELPER_MISSING:"+path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

def market_archive(bundles,counts,offsets,meta):
    market=[]
    q_by_id={}
    odds_by_id={}
    valid={}
    valid_arrays=[]
    overrounds=[]
    for day,records in sorted(bundles.items()):
        for b in records:
            active=sorted((r for r in b["runners"]
                    if r.get("runnerStatus") in (None,"","active")),
                    key=lambda r:int(r["horseNo"]))
            if len(active)<3:continue
            places={int(r["horseNo"]):r.get("finishPosition") for r in b["results"]}
            if sum(places.get(int(r["horseNo"]))==1 for r in active)!=1:continue
            rid=b["race"]["raceId"]
            raw=[b["archivedMarketOdds"].get(int(r["horseNo"])) for r in active]
            good=all(x is not None and math.isfinite(x) and x>1
                     for x in raw)
            valid[rid]=good
            if good:
                odds=np.asarray(raw,dtype=np.float64)
                implied=1.0/odds
                overround=float(implied.sum())
                q=implied/overround
                rank=np.argsort(np.argsort(-q,kind="stable"),kind="stable")+1
                entropy=-sum(q*np.log(q))/math.log(len(q))
                strength_gap=float(np.sort(q)[-1]-np.sort(q)[-2])
                rows=np.column_stack((np.log(odds),q,rank/len(q),
                   q*np.log(len(q)),np.full(len(q),overround),
                   np.full(len(q),entropy),np.full(len(q),strength_gap),
                   np.asarray(rank==1,dtype=float)))
            else:
                # Missing archival quotes: zeros for shape only; never use
                # these rows in model fit or reported policy evaluation.
                q=np.zeros(len(active),dtype=np.float64)
                odds=np.zeros(len(active),dtype=np.float64)
                rows=np.zeros((len(active),8),dtype=np.float64)
                overround=0.
            market.extend(rows.tolist())
            q_by_id[rid]=q
            odds_by_id[rid]=odds
            valid_arrays.append(good)
            overrounds.append(overround)
    M=np.asarray(market,dtype=np.float32)
    good=np.asarray(valid_arrays,dtype=np.bool_)
    assert M.shape==(int(offsets[-1]),8)
    assert len(good)==len(counts)==len(meta)
    assert sum(len(x) for x in [market])==int(offsets[-1])
    yearcov=defaultdict(lambda:{"races":0,"completeWinOdds":0})
    for i,m in enumerate(meta):
        year=str(m["date"])[:4]
        yearcov[year]["races"]+=1
        yearcov[year]["completeWinOdds"]+=int(good[i])
    print("MARKET_ARCHIVE_VALID_COUNTS",json.dumps({
        "totalRaces":len(good),"validRaces":int(np.sum(good)),
        "byYear":dict(yearcov)},ensure_ascii=False),flush=True)
    if sum(good)<1000:raise RuntimeError("NOT_ENOUGH_REAL_MARKET_ODDS_TO_USE_FOR_2024_2025")
    return M,q_by_id,odds_by_id,valid,good,overrounds

def fit_market_ranker(X,y,counts,dates,offsets,valid,year):
    past=np.flatnonzero((dates<f"{year}-01-01")&valid)
    if len(past)<10000 or str(dates[past[-1]])>=f"{year}-01-01":
        raise RuntimeError("MARKET_RANKER_TRAIN_LEAK_OR_MISSING")
    # Retain complete race group boundaries while removing invalid odds.
    index=np.concatenate([np.arange(offsets[i],offsets[i+1]) for i in past])
    groups=counts[past].tolist()
    if len(index)!=sum(groups):raise AssertionError("MARKET_QID_GROUP_MISMATCH")
    model=LGBMRanker(objective="lambdarank",n_estimators=220,
        learning_rate=0.035,num_leaves=31,min_child_samples=65,
        reg_lambda=10,colsample_bytree=0.84,
        lambdarank_truncation_level=5,random_state=SEED,n_jobs=2,verbosity=-1)
    model.fit(X[index],y[index].astype(np.int32),group=groups)
    return model,{"trainingTargetYear":year,"trainingThrough":str(dates[past[-1]]),
      "trainingCompleteRaces":len(past),"trainingRunnerRows":len(index)}

def aug_market_groups(year, Xaug, Xbase, counts, dates, offsets, meta,
                      model, top3, payout, q, odds, valid):
    structural=load("scripts/research-structural-ranker-twohead-2025.py",
                    "market_struct_helper_"+str(year))
    groups,rejected,target=structural.year_groups(year,Xaug,counts,dates,offsets,
          meta,(model,Top3Adapter(top3)),payout)
    accepted={};added=0
    for key,rows in groups.items():
        if any(not valid.get(r["raceId"],False) for r in rows):
            added+=1
            continue
        for r in rows:
            rid=r["raceId"]
            r["marketQ"]=q[rid]
            r["marketOdds"]=odds[rid]
            r["horseProbability"]["market_ranker"]=r["horseProbability"]["ranker_only"]
            r["horseProbability"]["market_corrected_blend"]=(
                .60*r["horseProbability"]["ranker_only"]+.40*r["marketQ"])
            r["horseProbability"]["market_implied_only"]=r["marketQ"]
        accepted[key]=rows
    rejected["venue_days_missing_final_win_odds"]=added
    if len(accepted)<100:raise RuntimeError("NOT_ENOUGH_COMPLETE_SIX_PAYOUT_PLUS_FINAL_ODDS_DAYS")
    return accepted,rejected,target

class Top3Adapter:
    def __init__(self,m):self.m=m
    def predict_proba(self,X):return self.m.predict_proba(X[:,:56])

def market_ticket_features(r,ticket,ticketHelper):
    k,idx,p,actual=ticket
    q=r["marketQ"]
    odds=r["marketOdds"]
    pprice=max(1e-10,ticketHelper.probability(k[0],idx,q))
    own=max(1e-10,p)
    pts=np.asarray([q[i] for i in idx],dtype=np.float64)
    prices=np.asarray([odds[i] for i in idx],dtype=np.float64)
    best=sorted(q,reverse=True)
    return [
        pprice,math.log(pprice),
        own/pprice,np.clip(math.log(own/pprice),-6,6),
        float(pts.max()),float(pts.min()),float(pts.mean()),
        float(np.log(prices).mean()),float(np.log(prices).max()),
        float(sum(best[:3])),
        float(sum(q*q)),
    ]

def build_price_rows(groups,struct,tickets,variant):
    fx=[];returned=[];wins=[];meta=[]
    for day,rows in sorted(groups.items()):
        for r in rows:
            row={**r,"probs":r["horseProbability"][variant]}
            bets=tickets.enumerate_tickets(row)
            top_order=np.argsort(-row["probs"],kind="stable")
            place_rank={int(i):j+1 for j,i in enumerate(np.argsort(-r["t3"],kind="stable"))}
            for ticket in bets:
                k,ix,p,paid=ticket
                x3=np.asarray([r["t3"][i] for i in ix])
                pos=[place_rank[i] for i in ix]
                additional=[
                    *[float(r["t3"][int(i)]) for i in top_order[:3]],
                    float(sum(sorted(r["t3"],reverse=True)[:3])/3),
                    float(np.mean(x3)),float(np.min(x3)),
                    float(np.prod(x3)),float(sum(pos)/36),
                    float(max(pos)/18),float(len(bets)/200),
                ]
                vals=tickets.features(row,ticket)+additional
                vals+=market_ticket_features(row,ticket,tickets)
                fx.append(vals);returned.append(int(paid))
                wins.append(int(paid>0))
                meta.append((day,r,ticket))
    X=np.asarray(fx,dtype=np.float32)
    p=np.asarray(returned,dtype=np.float64)
    hit=np.asarray(wins,dtype=np.int8)
    if len(X)<10000 or not np.isfinite(X).all():raise ValueError("MARKET_FEATURES_INVALID")
    return X,p,hit,meta

def self_test():
    # market win probabilities are actual closing-market fractions, not
    # synthetic official JRA preT15 market quotes.
    odds=np.asarray([2.,5.,10.])
    q=1/odds;q/=q.sum()
    assert abs(q.sum()-1)<1e-12
    assert q[0]>q[1]>q[2] and all(x>0 for x in q)
    assert len(MODEL_VARIANTS)==3
    print("MARKET_RESIDUAL_MODEL_SELFTEST_OK",flush=True)

def main():
    import sys
    if "--self-test" in sys.argv:self_test();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","market_hist")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","market_payouts")
    base=load("scripts/research-two-stage-payout-value-2024-2025.py","market_tickets")
    structural=load("scripts/research-structural-ranker-twohead-2025.py","market_struct")
    arcs=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),arcs)
    t3=structural.top3_targets(arcs)
    meta=audit.eligible_metadata(arcs)
    assert len(X)==len(y)==len(t3) and len(meta)==len(counts)
    M,q,odds,valid,valid_groups,overrounds=market_archive(arcs,counts,offsets,meta)
    Xmarket=np.concatenate([X,M],axis=1)
    paid,coverage=audit.payout_book()
    training={};bad={};groups={}
    for year in (2024,2025):
        model,info=fit_market_ranker(Xmarket,y,counts,dates,offsets,valid_groups,year)
        # Independent placing target: do not waste CPU re-fitting a second
        # unrelated win-ranker just to retrieve its top-three head.
        train_races=np.flatnonzero(dates<f"{year}-01-01")
        bound=int(offsets[int(train_races[-1])+1])
        top3=HistGradientBoostingClassifier(
            max_iter=120,learning_rate=0.04,max_leaf_nodes=25,
            min_samples_leaf=85,l2_regularization=8,
            early_stopping=False,random_state=SEED)
        top3.fit(X[:bound],t3[:bound])
        evals,rej,n=aug_market_groups(year,Xmarket,X,counts,dates,offsets,meta,
                          model,top3,paid,q,odds,valid)
        groups[year]=evals;training[str(year)]=info;bad[str(year)]=rej
        print("MARKET_RESIDUAL_YEAR_TRAIN",json.dumps({
            "year":year,"marketModel":info,"venueDays":len(evals),
            "rejected":rej,"raceCount":n},ensure_ascii=False),flush=True)
        del model,top3
    results={}
    for policy in MODEL_VARIANTS:
        trainX,trainPaid,trainHits,_=build_price_rows(groups[2024],structural,base,policy)
        cls,cond,priors=structural.fit_hurdle(trainX,trainPaid,trainHits)
        testX,_,_,meta25=build_price_rows(groups[2025],structural,base,policy)
        forecasts=structural.score_rows(testX,meta25,(cls,cond),priors)
        result=structural.selected_portfolio(groups[2025],forecasts,base)
        results[policy]={"metrics":result["metrics"],
            "validVenueDays":result["validVenueDays"],
            "unusableVenueDays":result["unusableVenueDays"],
            "monthly":result["byMonth"],
            "trainTicketRows":len(trainHits),"features":int(trainX.shape[1]),
            "samplePredictions":result["samplePredictions"]}
        print("MARKET_RESIDUAL_2025_PAIRED_HIT_ROI",json.dumps({
          "policy":policy,"metrics":result["metrics"],
          "validVenueDays":result["validVenueDays"],
          "trainRows":len(trainHits)},ensure_ascii=False),flush=True)
        del trainX,trainPaid,trainHits,testX,meta25,cls,cond,forecasts
    report={"status":"EXPLORATORY_HISTORICAL_FINAL_WIN_ODDS_RESEARCH_ONLY",
        "NO_claim_preT15":True,
        "historicalWinOdds":"official archived final odds only; timestamps not T15 verified",
        "noSixMarketBetOddsFromFinalSnapshots":True,
        "mayNotBeUsedToClaimLiveExpectedRoi":True,
        "runnerFeatures":56+8,
        "ticketFeatures":int(next(iter(results.values()))["features"]),
        "trainedJraPayoutHurdleOnlyOn2024":True,
        "trainedHorseYearwiseWithoutTestResults":True,
        "testActualJraPayoutsOnly2025":True,
        "2025HadBeenPreviouslyInspected":True,
        "roiIsActualD1JraPayoutButBetSelectionsAreHypothetical":True,
        "promotionAllowed":False,
        "validArchiveRaces":int(np.sum(valid_groups)),
        "archiveRaceCount":len(valid_groups),
        "marketModelTraining":training,"excludedVenueDays":bad,
        "actualJraPayoutMonthCoverage":coverage,"results":results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MARKET_RESIDUAL_MODEL_AUDIT_COMPLETE",json.dumps({
      "results":{k:v["metrics"] for k,v in results.items()},
      "anyProvenProspectiveProfit":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
