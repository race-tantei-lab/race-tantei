#!/usr/bin/env python3
"""Structural horse-ranking + conditional top3 + two-part ticket payout model.

This is a REAL model change, not race-count / stake tuning.

Win horse model:
  LightGBM LambdaRank trained with winners grouped by race, rather than
  independent binary winner labels. Ranking uses only historical pre-result
  56 feature vectors from the canonical 10-year archive.

Placing model:
  Independent HistGradientBoosting top-three binary target, providing a
  second distribution that captures placing rather than assuming that
  winner ranks determine all exotic-ticket probabilities.

Bet payout model:
  Zero-inflated / hurdle: HistGradientBoostingClassifier P(ticket wins) x
  HistGradientBoostingRegressor E(actual JRA payout | ticket wins).
  Unlike prior direct Poisson regression on almost-all-zero payouts this
  explicitly models the winning tail of the JRA payout distribution.

Strict time separation:
  2024 horse features predicted by horse models fitted through 2023.
  Only 2024 actual JRA payouts train the ticket payout hurdle.
  2025 horse models refitted using only <=2024 results; 2024-trained
  hurdle is applied WITHOUT REFIT to 2025 ticket candidates.
  Any 2025 JRA payout is read ONLY for settling 2025 tickets.

Historical runner inputs not independently proved available at T-15 and
2025 dates previously seen in other research: RETROSPECTIVE RESEARCH,
not an untouched forward holdout, NOT profitable-live promotion evidence.
No final odds at all, synthetic odds never constructed, no D1 writes.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from pathlib import Path
import json
import math
import numpy as np
from lightgbm import LGBMRanker
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/structural-ranker-twohead-2024train-2025jra.json"
TYPE_ORDER=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAID_STAKE=2000
RACE_K=5
HORSE_VARIANTS=("ranker_only","ranker_top3_blend")
SEED=20261108

def top3_targets(bundle_dates):
    """Same filtered chronological horse order as core.chronological_features."""
    labels=[]
    for date,day in sorted(bundle_dates.items()):
        for bundle in day:
            runners=sorted((r for r in bundle["runners"]
                if r.get("runnerStatus") in (None,"","active")),
                key=lambda r:int(r["horseNo"]))
            if len(runners)<3:continue
            places={int(r["horseNo"]):r.get("finishPosition") for r in bundle["results"]}
            if sum(places.get(int(r["horseNo"]))==1 for r in runners)!=1:continue
            for r in runners:
                pos=places.get(int(r["horseNo"]))
                labels.append(int(pos is not None and 1<=pos<=3))
    return np.asarray(labels,dtype=np.int8)

def softmax(scores,temp=1.0):
    s=np.asarray(scores,dtype=np.float64)
    z=np.exp(np.clip((s-np.max(s))/temp,-60,0))
    return z/z.sum()

def fit_horse_models(X,y,t3,counts,offsets,dates,year):
    idx=np.flatnonzero(dates<f"{year}-01-01")
    if len(idx)<10000 or idx[-1]+1!=len(dates[dates<f"{year}-01-01"]):
        raise ValueError("UNEXPECTED_TRAIN_RACE_INDEX")
    maxrace=int(idx[-1]);end=int(offsets[maxrace+1])
    if str(dates[maxrace])>=f"{year}-01-01":raise ValueError("MODEL_TRAINED_ON_TEST_YEAR_LABELS")
    if sum(counts[:maxrace+1])!=end:raise AssertionError("LGBM_GROUP_ALIGNMENT")
    ranker=LGBMRanker(
        objective="lambdarank",metric="ndcg",
        n_estimators=190,learning_rate=0.04,num_leaves=25,
        min_child_samples=80,reg_lambda=8.0,
        colsample_bytree=0.85,random_state=SEED,n_jobs=2,verbosity=-1,
        lambdarank_truncation_level=5
    )
    ranker.fit(X[:end],y[:end].astype(np.int32),group=counts[:maxrace+1].tolist())
    top3=HistGradientBoostingClassifier(
        max_iter=120,learning_rate=0.04,max_leaf_nodes=25,
        min_samples_leaf=85,l2_regularization=8.0,
        early_stopping=False,random_state=SEED)
    top3.fit(X[:end],t3[:end])
    return (ranker,top3),{"horseTrainThrough":str(dates[maxrace]),
        "horseTrainRaces":maxrace+1,"horseTrainRunnerRows":end,
        "labelWinPrevalence":round(float(np.mean(y[:end])),6),
        "labelTop3Prevalence":round(float(np.mean(t3[:end])),6)}

def year_groups(year,X,counts,dates,offsets,meta,models,payout):
    target=np.flatnonzero((dates >= (f"{year}-05-04" if year==2024 else f"{year}-01-01"))
        & (dates<f"{year+1}-01-01"))
    if len(target)<2000:raise RuntimeError("TOO_FEW_TARGET_RACES")
    first=int(offsets[int(target[0])]);end=int(offsets[int(target[-1])+1])
    ranker,top3=models
    ranks=ranker.predict(X[first:end],num_threads=2)
    place=top3.predict_proba(X[first:end])[:,1]
    raw_by_date=defaultdict(list)
    cursor=0
    for i in target:
        i=int(i);n=int(counts[i]);m=meta[i]
        r=softmax(ranks[cursor:cursor+n],temp=1.4)
        p3=np.clip(place[cursor:cursor+n],1e-6,1)
        cursor+=n
        p3norm=p3/p3.sum()
        pblend=0.65*r+0.35*p3norm
        row={"raceId":m["rid"],"date":m["date"],
          "venue":m["venue"],"raceNo":int(m["no"]),
          "horses":tuple(int(h) for h in m["horses"]),
          "t3":p3,"payout":payout.get(m["rid"],{}),
          "horseProbability":{"ranker_only":r,"ranker_top3_blend":pblend}}
        raw_by_date[(row["date"],row["venue"])].append(row)
    assert cursor==len(ranks)==len(place)
    accepted={};exclusions=Counter()
    for day,rows in raw_by_date.items():
        if len(rows)!=12 or {r["raceNo"] for r in rows}!=set(range(1,13)):
            exclusions["not_12_races"]+=1;continue
        if any({k[0] for k in r["payout"]}!=set(TYPE_ORDER) for r in rows):
            exclusions["incomplete_actual_JRA_six_type_payouts"]+=1;continue
        accepted[day]=sorted(rows,key=lambda r:r["raceNo"])
    if len(accepted)<100:raise RuntimeError("COMPLETE_COHORT_TOO_SMALL:"+str(len(accepted)))
    return accepted,dict(exclusions),len(target)

def build_rows(groups,base,variant):
    """Return features/payout labels and race metadata with NO payout leakage."""
    feats=[];ret=[];hits=[];meta=[]
    for day,rs in sorted(groups.items()):
        for r in rs:
            v={**r,"probs":r["horseProbability"][variant]}
            candidates=base.enumerate_tickets(v)
            order=np.argsort(-v["probs"],kind="stable")
            place_ranks={int(h):i+1 for i,h in enumerate(np.argsort(-r["t3"],kind="stable"))}
            for ticket in candidates:
                key,ix,p,paid=ticket
                chosen_place=np.asarray([r["t3"][i] for i in ix],dtype=np.float64)
                place_rank=[place_ranks[i] for i in ix]
                extra=[
                  *[float(r["t3"][int(i)]) for i in order[:3]],
                  sum(sorted(r["t3"],reverse=True)[:3])/3,
                  float(np.mean(chosen_place)),float(np.min(chosen_place)),
                  float(np.prod(chosen_place)),float(sum(place_rank))/36,
                  float(max(place_rank))/18,
                  float(len(candidates))/200,
                ]
                feature=base.features(v,ticket)+extra
                feats.append(feature);ret.append(int(paid));hits.append(int(paid>0))
                meta.append((day,r,ticket))
    X=np.asarray(feats,dtype=np.float32)
    paid=np.asarray(ret,dtype=np.float64)
    hit=np.asarray(hits,dtype=np.int8)
    if X.shape[0]<10000 or not np.isfinite(X).all():
        raise RuntimeError("INVALID_MODEL_FEATURES_OR_ROW_COUNT")
    return X,paid,hit,meta

def fit_hurdle(X,paid,hit):
    assert int(hit.sum())>1500
    first=HistGradientBoostingClassifier(
      max_iter=110,learning_rate=0.045,max_leaf_nodes=21,
      min_samples_leaf=100,l2_regularization=10,
      early_stopping=False,random_state=SEED)
    first.fit(X,hit)
    positive=hit==1
    # Fit *conditional* payout size only on winners. Keep full uncapped
    # payout labels in settlement; training winsorization is explicit.
    amount=np.clip(paid[positive]/100,1,300)
    second=HistGradientBoostingRegressor(
      loss="poisson",max_iter=115,learning_rate=0.04,
      max_leaf_nodes=17,min_samples_leaf=40,l2_regularization=12,
      early_stopping=False,random_state=SEED)
    second.fit(X[positive],amount)
    # Frozen 2024-only per-type label priors for robust uplift shrinkage.
    baserates={}
    for i,typ in enumerate(TYPE_ORDER):
        mask=X[:,i]>0.5
        n=int(mask.sum());w=int(hit[mask].sum())
        baserates[typ]={"tickets":n,"wins":w,"hitPrior":(w+10)/(n+200),
            "wonReturnPrior":float(np.clip(np.mean(paid[mask & positive]/100),1,300))}
    return first,second,baserates

def score_rows(X,meta,models,baseRates):
    first,second=models
    pa=first.predict_proba(X)[:,1]
    paid=second.predict(X)
    by_race=defaultdict(list)
    for i,(day,r,ticket) in enumerate(meta):
        typ=ticket[0][0]
        prior=baseRates[typ]
        calibrated_hit=0.87*float(pa[i])+0.13*prior["hitPrior"]
        conditional_return=0.87*float(paid[i])+0.13*prior["wonReturnPrior"]
        expected=calibrated_hit*conditional_return
        by_race[(day,r["raceId"])].append({
          "key":ticket[0],"oddsFreePlHitProbability":float(ticket[2]),
          "learnedHitProbability":calibrated_hit,
          "expectedReturnMultiple":expected,
          "payout100":ticket[3],"raceNo":r["raceNo"],"venue":r["venue"],
          "date":r["date"],"raceId":r["raceId"],
        })
    return by_race

def selected_portfolio(groups,by_race,base):
    full=[]
    bad=Counter()
    per_month=defaultdict(list)
    for day,rs in sorted(groups.items()):
        choices=[]
        for r in rs:
            tickets=by_race[(day,r["raceId"])]
            byType={}
            for x in tickets:
                old=byType.get(x["key"][0])
                if old is None or x["expectedReturnMultiple"]>old["expectedReturnMultiple"]:
                    byType[x["key"][0]]=x
            pairs=[]
            ts=sorted(byType.values(),key=lambda x:-x["expectedReturnMultiple"])
            for i,a in enumerate(ts):
                for b in ts[i+1:]:
                    # Model probability floor: all selected pairs must have
                    # at least one candidate with estimated >=20% hit.
                    if max(a["learnedHitProbability"],b["learnedHitProbability"])<.20:continue
                    first,second=(1900,100) if a["expectedReturnMultiple"]>=b["expectedReturnMultiple"] else (100,1900)
                    utility=a["expectedReturnMultiple"]*first+b["expectedReturnMultiple"]*second
                    pairs.append((utility,a,b,first,second))
            if not pairs:continue
            utility,a,b,first,second=max(pairs,key=lambda x:x[0])
            payout=a["payout100"]*(first//100)+b["payout100"]*(second//100)
            choices.append({"raceId":r["raceId"],"date":r["date"],"venue":r["venue"],
                "raceNo":r["raceNo"],"modeledExpectedRoiPct":utility/PAID_STAKE*100,
                "stake":PAID_STAKE,"return":payout,"hit":int(a["payout100"]>0 or b["payout100"]>0),
                "tickets":[{"betType":a["key"][0],"combination":"-".join(map(str,a["key"][1])),
                            "stake":first,"learnedHitP":a["learnedHitProbability"]},
                           {"betType":b["key"][0],"combination":"-".join(map(str,b["key"][1])),
                            "stake":second,"learnedHitP":b["learnedHitProbability"]}]})
        if len(choices)<RACE_K:
            bad["not_enough_20pct_predicted_hit_candidates"]+=1;continue
        chosen=sorted(choices,key=lambda x:(-x["modeledExpectedRoiPct"],x["raceNo"]))[:RACE_K]
        full+=chosen;per_month[day[0][:7]]+=chosen
    return {"metrics":base.summarize(full),"validVenueDays":len(full)//RACE_K,
        "unusableVenueDays":dict(bad),
        "byMonth":{m:base.summarize(v) for m,v in sorted(per_month.items())},
        "samplePredictions":full[:3],
        "largestReturnRace":max((r["return"] for r in full),default=0)}

def self_test():
    s=softmax([2,3,4])
    assert abs(sum(s)-1)<1e-9 and s[2]>s[1]>s[0]
    sample={"runners":[{"horseNo":1},{"horseNo":2},{"horseNo":3}],
      "results":[{"horseNo":1,"finishPosition":1},{"horseNo":2,"finishPosition":2},
                 {"horseNo":3,"finishPosition":3}]}
    assert top3_targets({"2024-05-04":[sample]}).tolist()==[1,1,1]
    print("STRUCTURAL_RANKER_TWOHEAD_SELFTEST_OK",flush=True)

def main():
    import sys
    if "--self-test" in sys.argv:self_test();return
    base=__import__("importlib").util
    def load(path,name):
        spec=base.spec_from_file_location(name,ROOT/path)
        mod=base.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
        return mod
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","struct_history")
    payhelper=load("scripts/research-extra-trees-2024-2025-paired-jra.py","struct_payouts")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","struct_tickets")
    archive=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),archive)
    t3=top3_targets(archive)
    meta=payhelper.eligible_metadata(archive)
    assert len(meta)==len(counts) and len(t3)==len(y)==len(X)
    assert all(meta[i]["date"]==str(dates[i]) and meta[i]["field"]==int(counts[i]) for i in range(len(counts)))
    payouts,monthCoverage=payhelper.payout_book()
    years={};training={};exclusions={};targetRaces={}
    for year in (2024,2025):
        models,info=fit_horse_models(X,y,t3,counts,offsets,dates,year)
        groups,bad,n=year_groups(year,X,counts,dates,offsets,meta,models,payouts)
        years[year]=groups;training[year]=info;exclusions[year]=bad;targetRaces[year]=n
        print("STRUCTURAL_HORSE_RANKER_YEAR",json.dumps({"year":year,"training":info,
             "completeVenueDays":len(groups),"rejected":bad},ensure_ascii=False),flush=True)
        del models
    results={}
    for variant in HORSE_VARIANTS:
        trainX,trainPaid,trainHits,_=build_rows(years[2024],tickets,variant)
        hurdleA,hurdleB,priors=fit_hurdle(trainX,trainPaid,trainHits)
        testX,_,_,testMeta=build_rows(years[2025],tickets,variant)
        predicted=score_rows(testX,testMeta,(hurdleA,hurdleB),priors)
        out=selected_portfolio(years[2025],predicted,tickets)
        out["stage2TrainRows"]=len(trainHits)
        out["stage2TrainHitRatePct"]=round(100*np.mean(trainHits),3)
        out["stage2Features"]=int(trainX.shape[1])
        out["year2024PerBetTypePriors"]=priors
        results[variant]=out
        print("STRUCTURAL_2025_PAIRED_HIT_ROI",json.dumps({
          "model":variant,"metrics":out["metrics"],"validVenueDays":out["validVenueDays"],
          "stage2Rows":out["stage2TrainRows"]},ensure_ascii=False),flush=True)
        del trainX,trainPaid,trainHits,testX,testMeta,hurdleA,hurdleB
    report={
       "status":"RESEARCH_ONLY_NEW_LAMBDARANK_PLUS_TOP3_AND_ZERO_INFLATED_JRA_PAYOUT",
       "productionPromote":False,
       "userCriterion":"2025 hit >=20% then maximize payout ROI and highest payout trimmed ROI",
       "trainingHorse":"LGBMRanker LambdaRank 190 trees grouped within each race and HGB top3 120 iterations",
       "trainingTicket":"HGBClassifier P(ticket wins) and HGBPoissonRegressor E(JRA payout|win), 2024",
       "independentResultEvaluation":"2025 actual JRA D1 six-market payouts, no D1 writes",
       "historicalOddsUsedAsInput":False,"syntheticOddsUsed":False,
       "oddsT15Verified":False,"historicalFeaturesT15Verified":False,
       "2025PreviouslyReviewedInPriorResearch":True,
       "realMoneyReady":False,
       "horseModelsFittedBeforeEachTestYear":training,
       "stage2TrainPeriod":"2024-05-04 through 2024-12-31",
       "stage2EvalPeriod":"2025-01-01 through 2025-12-31",
       "plannedSelectionPerVenue":RACE_K,
       "venueDayCohort":{str(k):len(v) for k,v in years.items()},
       "payoutCoverage":monthCoverage,
       "excludedVenueDays":exclusions,
       "results":results
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("STRUCTURAL_RANKER_MODEL_AUDIT_COMPLETE",json.dumps({
        "modelResults":{k:v["metrics"] for k,v in results.items()},
        "promotion":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
