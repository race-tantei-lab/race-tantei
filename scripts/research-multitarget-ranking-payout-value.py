#!/usr/bin/env python3
"""New horse and payout architectures, chronological JRA actual-return audit.

Fundamental modeling changes (NO race-count or stake optimization):
  1. LightGBM LambdaRank on ordinal 0/non-top3, 1/top3, 2/winner labels
  2. CatBoost independent win and top-three classifiers
  3. Hybrid of ranking, win and top-three forecasts
  4. LightGBM Tweedie direct expected payout (zero-heavy, positive tail)
  5. CatBoost two-stage ticket-hit + conditional paid-payout model

Horse labels: <= 2023 for 2024 forecasts, <= 2024 for 2025 forecasts.
Ticket payout labels: only actual JRA 2024; evaluation: actual JRA 2025.
Zero outcome, official odds, horse/field result, and payout from EVALUATION
race are NEVER input features. Original historical final odds are NOT T-15.
Same two different ticket types, fixed 1000+1000 yen, 5 races/venue/day;
also report fixed race numbers 1..5 to isolate true model improvement.
Historic feature timestamps are NOT independently proven T-15.
Results are RETROSPECTIVE research, NOT evidence of future live profit.
No D1 writes; monthly range-bounded payout reads shared across all models.
"""
from __future__ import annotations
import collections
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
from catboost import CatBoostClassifier,CatBoostRegressor
from sklearn.metrics import log_loss

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results"/"multiobjective-ranker-catboost-tweedie-2025-jra.json"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
ODDS_AND_OUTCOME_FORBIDDEN={"finishPosition","raceDate","raceId","labelWin",
"labelTop3","winOdds","popularity","odds","payout","returnYen"}
HORSE_FAMILIES=("ranker_ordinal","catboost_win_top3","hybrid_three_target")
TICKET_FAMILIES=("lightgbm_tweedie","catboost_hit_x_payout")
RESEARCH_STAKE=(1000,1000)
MAX_MULTIPLE_TRAIN=80.0
RANK_TEMPERATURE=2.5

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("SOURCE_NOT_FOUND "+str(path))
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def truth_rows(archive,counts,y):
    """Same dated order, same active field, exact race/result join as feature builder."""
    ordinal=[]
    top3=[]
    meta=[]
    idx=0
    for date in sorted(archive):
        for bundle in archive[date]:
            runners=sorted([r for r in bundle["runners"]
                if r.get("runnerStatus") in (None,"","active")],
                key=lambda r:int(r["horseNo"]))
            if len(runners)<3:continue
            results={int(row["horseNo"]):row.get("finishPosition") for row in bundle["results"]}
            winners=[r for r in runners if results.get(int(r["horseNo"]))==1]
            if len(winners)!=1:continue
            n=len(runners)
            if idx>=len(counts) or int(counts[idx])!=n:raise AssertionError("RACE_ORDER_FIELD_MISMATCH")
            pos=[results.get(int(r["horseNo"])) for r in runners]
            one=[int(p==1) for p in pos]
            if sum(one)!=1:raise AssertionError("MORE_THAN_ONE_WINNER")
            ts=[int(isinstance(p,int) and 1<=p<=3) for p in pos]
            rank=[2 if a else 1 if b else 0 for a,b in zip(one,ts)]
            ordinal.extend(rank);top3.extend(ts)
            meta.append({"date":date,"venue":bundle["race"]["venue"],"raceNo":int(bundle["race"]["raceNo"]),
                "raceId":bundle["race"]["raceId"],
                "horseNos":tuple(int(r["horseNo"]) for r in runners)})
            idx+=1
    if idx!=len(counts) or len(y)!=len(ordinal) or not np.array_equal(np.asarray(ordinal)==2,y==1):
        raise AssertionError("CHRONOLOGICAL_LABEL_AND_METADATA_MISMATCH")
    return np.asarray(ordinal,dtype=np.int8),np.asarray(top3,dtype=np.int8),meta

def normalize(v):
    p=np.maximum(np.asarray(v,dtype=np.float64),1e-12)
    return p/p.sum()

def ranking_softmax(v):
    z=np.clip(np.asarray(v,dtype=np.float64)/RANK_TEMPERATURE,-30,30)
    a=np.exp(z-z.max())
    return normalize(a)

def train_horse_models(year,X,win_y,top3_y,rank_y,counts,dates,offsets):
    train_idx=np.flatnonzero((dates>=f"{year-5}-01-01")&(dates<f"{year}-01-01"))
    if len(train_idx)<5000:raise AssertionError("SHORT_PREYEAR_TRAINING")
    start=int(offsets[int(train_idx[0])]);end=int(offsets[int(train_idx[-1])+1])
    assert not (dates[train_idx]>=f"{year}-01-01").any()
    group=counts[train_idx]
    if int(group.sum())!=end-start:raise AssertionError("GROUP_TRAIN_ALIGNMENT")
    ranker=lgb.LGBMRanker(objective="lambdarank",metric="ndcg",label_gain=[0,1,3],
       n_estimators=210,num_leaves=31,min_child_samples=70,learning_rate=0.045,
       colsample_bytree=0.85,reg_lambda=18.0,reg_alpha=0.5,
       max_position=3,random_state=20261108,n_jobs=2,verbosity=-1)
    ranker.fit(X[start:end],rank_y[start:end],group=group)
    common=dict(iterations=250,depth=5,learning_rate=0.055,l2_leaf_reg=12.0,
        thread_count=2,random_seed=20261108,verbose=False,allow_writing_files=False)
    cat_win=CatBoostClassifier(loss_function="Logloss",**common)
    cat_top3=CatBoostClassifier(loss_function="Logloss",**dict(common,random_seed=20261109))
    cat_win.fit(X[start:end],win_y[start:end])
    cat_top3.fit(X[start:end],top3_y[start:end])
    return (ranker,cat_win,cat_top3),{"trainingFirstRace":str(dates[train_idx[0]]),
        "trainingLastRace":str(dates[train_idx[-1]]),
        "trainingRaces":len(train_idx),"trainingRunners":end-start,
        "rankerObjective":"lambdarank top3 ordinal labels with gain [0,1,3]",
        "catboostTargets":["win","top3"]}

def year_groups(year,models,X,counts,dates,offsets,meta,payout):
    ix=np.flatnonzero((dates>=(f"{year}-05-04" if year==2024 else f"{year}-01-01"))
        &(dates<f"{year+1}-01-01"))
    if len(ix)<1000:raise AssertionError("NO_TARGET_YEAR")
    start=int(offsets[int(ix[0])]);end=int(offsets[int(ix[-1])+1])
    ranker,win,top3=models
    scores=np.asarray(ranker.predict(X[start:end]),dtype=np.float64)
    wc=win.predict_proba(X[start:end])[:,1]
    tc=top3.predict_proba(X[start:end])[:,1]
    grouped=collections.defaultdict(list)
    offset=0
    for i in ix:
        i=int(i)
        m=meta[i];n=int(counts[i]);st=offset;en=st+n
        r=ranking_softmax(scores[st:en])
        w=normalize(wc[st:en])
        t=normalize(tc[st:en])
        h=normalize(0.35*r+0.4*w+0.25*t)
        probabilities={"ranker_ordinal":r,"catboost_win_top3":normalize(0.65*w+0.35*t),
                       "hybrid_three_target":h}
        grouped[(m["date"],m["venue"])].append({"date":m["date"],"venue":m["venue"],
            "raceNo":m["raceNo"],"raceId":m["raceId"],
            "horseNos":m["horseNos"],"baseX":X[start+st:start+en],
            "probabilities":probabilities,"payout":payout.get(m["raceId"],{})})
        offset=en
    if offset!=end-start:raise AssertionError("BAD_PROBABILITY_OFFSET")
    full={};excluded=collections.Counter()
    for day,rows in sorted(grouped.items()):
        if len(rows)!=12 or {r["raceNo"] for r in rows}!=set(range(1,13)):
            excluded["NOT_COMPLETE_12_RACE_VENUE_DAY"]+=1
        elif any({t for t,_ in row["payout"]}!=set(TYPES) for row in rows):
            excluded["SIX_JRA_PAYOUT_MARKETS_INCOMPLETE"]+=1
        else:full[day]=sorted(rows,key=lambda x:x["raceNo"])
    return full,dict(excluded),int(len(ix))

def combo_probability(kind,idx,prob):
    def two(a,b):return float(prob[a]*prob[b]/max(1e-12,1-prob[a]))
    def three(a,b,c):return two(a,b)*float(prob[c])/max(1e-12,1-prob[a]-prob[b])
    if kind=="単勝":return float(prob[idx[0]])
    if kind=="馬単":return two(*idx)
    if kind=="馬連":return two(*idx)+two(*idx[::-1])
    if kind=="3連単":return three(*idx)
    if kind=="3連複":return sum(three(*order) for order in itertools.permutations(idx))
    if kind=="ワイド":
        a,b=idx
        return sum(sum(three(*order) for order in itertools.permutations((a,b,c)))
            for c in range(len(prob)) if c not in idx)
    raise AssertionError("INVALID_TYPE")

def tickets(row,horse_family):
    prob=row["probabilities"][horse_family]
    ranked=np.argsort(-prob,kind="stable")
    top=tuple(map(int,ranked[:min(5,len(ranked))]))
    top4=top[:4]
    specs={"単勝":[(n,) for n in top],
     "ワイド":list(itertools.combinations(top,2)),
     "馬連":list(itertools.combinations(top,2)),
     "馬単":list(itertools.permutations(top4,2)),
     "3連複":list(itertools.combinations(top,3)),
     "3連単":list(itertools.permutations(top4,3))}
    out=[]
    for typ,ranksets in specs.items():
        for ix in ranksets:
            num=[row["horseNos"][a] for a in ix]
            if typ in UNORDERED:num.sort()
            key=(typ,tuple(num))
            p=combo_probability(typ,ix,prob)
            if not 0<p<=1.000000001:raise AssertionError("INVALID_PL_TICKET_PROB")
            paid=int(row["payout"].get(key,0))
            if paid<0:raise AssertionError("NEGATIVE_REAL_JRA_PAYOUT")
            out.append((key,ix,p,paid))
    return out

# Horse features used to learn *conditional payoffs*, not merely win probability.
USED_FEATURE_NAMES=("horseWinRate","horseTop3Rate","jockeyWinRate",
 "jockeyTop3Rate","trainerWinRate","trainerTop3Rate","avg3FinishPct",
 "avg3SpeedMps","lastSpeedMps","sameDistWinRate","sameDistTop3Rate",
 "lastFinal3fPct","horseStarts","daysSinceLast","age","assignedWeight",
 "drawPct","distanceChange")
def field_indices(features):
    if len(features)!=56:raise AssertionError("56_FEATURES_CHANGED")
    if any(x in ODDS_AND_OUTCOME_FORBIDDEN for x in features):
        raise AssertionError("LEAKED_FINISH_RESULT_OR_FINAL_ODDS")
    return [features.index(name) for name in USED_FEATURE_NAMES]

def ticket_features(row,ticket,ind,horse_family):
    key,ix,p,paid=ticket
    probs=row["probabilities"][horse_family]
    order=np.argsort(-probs,kind="stable")
    positions=[int(np.where(order==a)[0][0])+1 for a in ix]
    ps=[float(probs[i]) for i in ix]
    padded=(positions+[0,0,0])[:3]
    pp=(ps+[0.0,0.0,0.0])[:3]
    top=np.sort(probs)[::-1]
    entropy=-float(np.sum(probs*np.log(np.maximum(probs,1e-12))))/math.log(len(probs))
    raw=np.asarray(row["baseX"],dtype=np.float64)[list(ix)][:,ind]
    avg=raw.mean(axis=0);upper=raw.max(axis=0);lower=raw.min(axis=0)
    x=[
        *[int(key[0]==t) for t in TYPES],
        len(probs)/18,row["raceNo"]/12,
        float(top[0]),float(top[1]),float(top[2]),sum(top[:3]),
        float(top[0]-top[1]),entropy,
        float(p),math.log(max(p,1e-9)),
        len(ix)/3,padded[0]/6,padded[1]/6,padded[2]/6,
        sum(positions)/15,max(positions)/6,
        pp[0],pp[1],pp[2],sum(ps),float(np.prod(ps)),
        float(max(ps)),float(min(ps)),
        int(key[0] in ("馬単","3連単")),
        int(1 in positions),
    ]
    for t in (avg,upper,lower,upper-lower):x.extend(float(v) for v in t)
    return x

def model_ticket_rows(groups,horse_family,feature_ix,include_payout=True):
    features=[];paid=[];meta=[];counts=collections.Counter()
    for day,rs in groups.items():
        for race in rs:
            for ticket in tickets(race,horse_family):
                features.append(ticket_features(race,ticket,feature_ix,horse_family))
                paid.append(ticket[3] / 100.0)
                meta.append((day,race["raceNo"],ticket[0],ticket[2],ticket[3]))
                counts[ticket[0][0]]+=1
    if not features:raise RuntimeError("NO_RESEARCH_TICKET_ROWS")
    return np.asarray(features,dtype=np.float32),np.asarray(paid,dtype=np.float32),meta,dict(counts)

def train_ticket_models(X,y):
    # Two fundamentally different objectives:
    # tweedie: directly predicts unconditional payout including zero returns;
    # two-stage: probability of hitting * times * conditional positive payout.
    # Training targets clipped at 80x only, actual JRA payout remains uncapped in evaluation.
    yc=np.clip(y,0,MAX_MULTIPLE_TRAIN)
    tw=lgb.LGBMRegressor(objective="tweedie",tweedie_variance_power=1.35,
      n_estimators=260,num_leaves=25,min_child_samples=130,learning_rate=0.045,
      reg_lambda=18.0,reg_alpha=0.25,colsample_bytree=0.85,
      random_state=20261108,n_jobs=2,verbosity=-1)
    tw.fit(X,yc)
    shared=dict(iterations=260,depth=5,learning_rate=0.055,l2_leaf_reg=15.0,
        thread_count=2,random_seed=20261108,verbose=False,allow_writing_files=False)
    hit=CatBoostClassifier(loss_function="Logloss",**shared)
    hit.fit(X,np.asarray(y>0,dtype=np.int8))
    positive=np.flatnonzero(y>0)
    if len(positive)<500:raise AssertionError("NOT_ENOUGH_REAL_HITTING_JRA_TICKETS")
    cond=CatBoostRegressor(loss_function="RMSE",**dict(shared,random_seed=20261109))
    cond.fit(X[positive],np.log1p(yc[positive]))
    return {"lightgbm_tweedie":tw,"catboost_hit_x_payout":(hit,cond)},{
        "trainingTicketRows":int(len(y)),"paidTrainingTicketRows":int(len(positive)),
        "rawTargetAverage":float(np.mean(y)),"fractionPaid":float(np.mean(y>0)),
        "targetWasClippedForTrainingOnly":MAX_MULTIPLE_TRAIN}

def predict_ticket_models(models,X):
    tw=models["lightgbm_tweedie"].predict(X)
    hit,cond=models["catboost_hit_x_payout"]
    q=hit.predict_proba(X)[:,1]
    cond_mult=np.expm1(cond.predict(X))
    # conservative: positive target model capped, never use actual test payouts.
    p=np.maximum(0,cond_mult)*q
    return {"lightgbm_tweedie":np.maximum(0,np.asarray(tw,dtype=np.float64)),
      "catboost_hit_x_payout":np.asarray(p,dtype=np.float64)}

def settlement_metrics(rows):
    n=len(rows);hits=sum(int(x["returnYen"]>0) for x in rows)
    stake=n*sum(RESEARCH_STAKE)
    payouts=sum(int(x["returnYen"]) for x in rows)
    maxpay=max((x["returnYen"] for x in rows),default=0)
    return {"races":n,"hitRaces":hits,"hitRacePct":round(100*hits/n,2) if n else None,
      "stakeYen":stake,"returnYen":payouts,"netYen":payouts-stake,
      "roiPct":round(100*payouts/stake,2) if stake else None,
      "roiWithoutMaxRacePayoutPct":round(100*(payouts-maxpay)/stake,2) if stake else None,
      "passes20PctHitFloor": bool(n and 100*hits/n>=20),
      "profitable":bool(stake and payouts>stake)}

def evaluate(groups,meta,preds):
    # All 6 families are evaluated on the identical complete venue-day cohort.
    # The "same first five race numbers" metric isolates horse/ticket model gain
    # without selecting different races based on the model.
    evaluations={}
    for family in HORSE_FAMILIES:
        for value_family in TICKET_FAMILIES:
            indexed=collections.defaultdict(list)
            for i,(day,race_no,key,prob,actual) in enumerate(meta):
                if not isinstance(day,tuple) or len(day)!=2:raise AssertionError("WRONG_DATE_VENUE_KEY")
                indexed[(day,race_no)].append((key,float(preds[value_family][i]),int(actual),float(prob)))
            selected=[];fixed=[];months=collections.defaultdict(list);types=collections.Counter()
            for day,rs in sorted(groups.items()):
                possibilities=[]
                for r in rs:
                    opts=indexed.get((day,r["raceNo"]),[])
                    best={}
                    for key,score,paid,prob in opts:
                        typ=key[0]
                        existing=best.get(typ)
                        if existing is None or score>existing[0]:
                            best[typ]=(score,key,paid,prob)
                    if len(best)!=len(TYPES):
                        raise AssertionError("MISSING_TWO_DISTINCT_JRA_TYPES")
                    pair=sorted(best.values(),key=lambda x:(-x[0],-x[3]))[:2]
                    if pair[0][1][0]==pair[1][1][0]:raise AssertionError("SAME_TYPE")
                    ret=pair[0][2]*RESEARCH_STAKE[0]//100+pair[1][2]*RESEARCH_STAKE[1]//100
                    record={"date":day[0],"raceNo":r["raceNo"],"score":pair[0][0]+pair[1][0],
                      "returnYen":ret,"tickets":[{"type":a[1][0],
                          "combination":"-".join(map(str,a[1][1])),
                          "stakeYen":RESEARCH_STAKE[ii],
                          "predExpectedReturn":round(a[0],5)} for ii,a in enumerate(pair)]}
                    possibilities.append(record)
                if len(possibilities)!=12:raise AssertionError("MODEL_EVAL_RACE_COUNT_DIFFERENCE")
                picked=sorted(possibilities,key=lambda x:(-x["score"],x["raceNo"]))[:5]
                common=[x for x in possibilities if x["raceNo"] in (1,2,3,4,5)]
                assert len(common)==len(picked)==5
                selected.extend(picked);fixed.extend(common)
                months[day[0][:7]].extend(picked)
                for x in picked:types.update(t["type"] for t in x["tickets"])
            evaluations[family+"__"+value_family]={
                "horseModel":family,"ticketModel":value_family,
                "modelSelectedFive":settlement_metrics(selected),
                "fixedSameFiveRaces":settlement_metrics(fixed),
                "monthlySelectedFive":{k:settlement_metrics(v) for k,v in sorted(months.items())},
                "selectedBetTypeCounts":dict(types),
                "exampleTickets":[x["tickets"] for x in selected[:2]],
                "allVenueDaysEvaluated":len(groups)}
    return evaluations

def check():
    p=np.array([0.5,0.3,0.2],dtype=np.float64)
    assert math.isclose(combo_probability("単勝",(0,),p),0.5)
    assert math.isclose(combo_probability("ワイド",(0,1),p),1.0)
    assert math.isclose(combo_probability("馬連",(0,1),p),
        0.5*0.3/0.5+0.3*0.5/0.7)
    assert math.isclose(combo_probability("3連複",(0,1,2),p),1.0)
    assert settlement_metrics([{"returnYen":3000},{"returnYen":0}])["roiPct"]==75.0
    x=normalize([0.5,0.25,0.25])
    assert math.isclose(x.sum(),1.0)
    assert math.isclose(ranking_softmax([2,1,0]).sum(),1.0)
    print("MULTITARGET_RANKER_CATBOOST_TWEEDIE_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:
        check();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","multigoal_history")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","multigoal_d1")
    archive=hist.load_bundles(hist.load_public_archive())
    core=hist.core_module()
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,archive)
    rank_y,top3_y,meta=truth_rows(archive,counts,y)
    names=core.load_config()["runnerProbabilityModel"]["features"]
    cols=field_indices(names)
    print("MULTITARGET_CHRONO_NO_LEAK_FEATURES",json.dumps({
      "runnerRows":len(y),"races":len(counts),"firstRace":str(dates[0]),
      "lastRace":str(dates[-1]),"featureColumns":list(USED_FEATURE_NAMES)}),flush=True)
    # One read-only bounded D1 historical payout retrieval is shared between
    # every model/architecture; no independent D1 reads by candidate.
    payouts,monthCoverage=audit.payout_book()
    cohorts={};horseAudits={};exclusions={}
    for year in (2024,2025):
        hm,ha=train_horse_models(year,X,y,top3_y,rank_y,counts,dates,offsets)
        cohorts[year],excl,n=year_groups(year,hm,X,counts,dates,offsets,meta,payouts)
        if len(cohorts[year])<150:raise RuntimeError("INSUFFICIENT_FULL_JRA_VENUE_DAYS:"+str(year))
        horseAudits[str(year)]=ha
        exclusions[str(year)]={"rawRaces":n,"excluded":excl,"completeVenueDays":len(cohorts[year])}
        print("MULTITARGET_HORSE_MODELS_FITTED",json.dumps({"year":year,
          "training":ha,"completeVenueDays":len(cohorts[year])}),flush=True)
        del hm
    out={}
    for horse_family in HORSE_FAMILIES:
        trainX,trainY,_,counts24=model_ticket_rows(cohorts[2024],horse_family,cols)
        payout_models,audit24=train_ticket_models(trainX,trainY)
        testX,testY,metadata,counts25=model_ticket_rows(cohorts[2025],horse_family,cols)
        pred=predict_ticket_models(payout_models,testX)
        result=evaluate_one_family(cohorts[2025],metadata,pred,horse_family)
        out.update(result)
        print("MULTITARGET_PAYOUT_FAMILY_2025_PAIRED",json.dumps({
          "horseFamily":horse_family,"models":{k:{"selectedFive":v["modelSelectedFive"],
             "fixedSameFive":v["fixedSameFiveRaces"]} for k,v in result.items()},
             "training":audit24},ensure_ascii=False),flush=True)
        del trainX,trainY,testX,testY,pred,payout_models
    report={"status":"HISTORICAL_RESEARCH_NOT_PROSPECTIVE_T15",
      "newHorseLosses":["LambdaRank ordinal top3 NDCG","CatBoost supervised win",
        "CatBoost supervised top3","multi-target rank-win-top3 blend"],
      "newTicketLosses":["LightGBM Tweedie zero-inflated unconditional actual payout",
        "CatBoost hit log-loss x CatBoost conditional positive payout log-RMSE"],
      "modelSelectionPrincipal":"Change model objectives, feature representation, target payout; fixed 5 race count, 2 types and exactly 1000+1000 yen",
      "2025NotPristine":True,"2024Stage2OnlyUses2024ActualJraPayouts":True,
      "noFinalOddsUsedInFeatures":True,"t15Proven":False,"promotionEligible":False,
      "yearwiseHorseTrainAudit":horseAudits,"monthPayoutCoverage":monthCoverage,
      "venueDayCoverage":exclusions,"sameDateVenueCohortForAllStrategies":True,
      "year2025PairedRealJraHitAndRoi":out}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MULTITARGET_INDEPENDENT_2025_JRA_RETURN",json.dumps({
      "evaluations":{k:{"selectedFive":v["modelSelectedFive"],
          "fixedSameFive":v["fixedSameFiveRaces"]} for k,v in out.items()},
      "promotionEligible":False},ensure_ascii=False),flush=True)

def evaluate_one_family(groups,meta,preds,family):
    # Same algorithms and fixed 5 races, but metadata contains a single
    # horse-family's ticket feature rows, not other horse-family variants.
    evaluations={}
    for value_family in TICKET_FAMILIES:
        indexed=collections.defaultdict(list)
        for i,(day,race_no,key,prob,actual) in enumerate(meta):
            indexed[(day,race_no)].append((key,float(preds[value_family][i]),int(actual),float(prob)))
        selected=[];fixed=[];months=collections.defaultdict(list);types=collections.Counter()
        for day,rs in sorted(groups.items()):
            possibilities=[]
            for r in rs:
                opts=indexed[(day,r["raceNo"])]
                best={}
                for key,score,paid,prob in opts:
                    typ=key[0]
                    old=best.get(typ)
                    if old is None or score>old[0] or (score==old[0] and prob>old[3]):
                        best[typ]=(score,key,paid,prob)
                if len(best)!=len(TYPES):raise AssertionError("SIX_MARKET_CANDIDATES_INCOMPLETE")
                pair=sorted(best.values(),key=lambda x:(-x[0],-x[3]))[:2]
                if pair[0][1][0]==pair[1][1][0]:raise AssertionError("SAME_TYPE")
                ret=sum(a[2]*RESEARCH_STAKE[i]//100 for i,a in enumerate(pair))
                possibilities.append({"date":day[0],"raceNo":r["raceNo"],
                  "score":sum(a[0] for a in pair),"returnYen":ret,
                  "tickets":[{"betType":a[1][0],
                    "combination":"-".join(map(str,a[1][1])),"stakeYen":RESEARCH_STAKE[i],
                    "modelExpectedPayoutMultiple":round(a[0],4)}
                    for i,a in enumerate(pair)]})
            if len(possibilities)!=12:raise AssertionError("RACE_COUNT_MISMATCH")
            chosen=sorted(possibilities,key=lambda x:(-x["score"],x["raceNo"]))[:5]
            common=[x for x in possibilities if x["raceNo"]<=5]
            assert len(chosen)==len(common)==5
            selected.extend(chosen);fixed.extend(common)
            months[day[0][:7]].extend(chosen)
            for x in chosen:types.update(t["betType"] for t in x["tickets"])
        evaluations[family+"__"+value_family]={
          "horseModel":family,"ticketModel":value_family,
          "modelSelectedFive":settlement_metrics(selected),
          "fixedSameFiveRaces":settlement_metrics(fixed),
          "monthlySelectedFive":{k:settlement_metrics(v) for k,v in sorted(months.items())},
          "selectedBetTypeCounts":dict(types),
          "exampleTickets":[x["tickets"] for x in selected[:2]],
          "sameCompleteVenueDayCount":len(groups)}
    return evaluations

if __name__=="__main__":
    main()
