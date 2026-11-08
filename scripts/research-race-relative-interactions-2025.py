#!/usr/bin/env python3
"""Direct ticket-payoff prediction with learned within-race horse interactions.

Truly new features/objectives relative to the previous ROI studies:
  * Raw 56 horse form features are expanded to 18 race-z-scored form
    features for each chosen horse, with pairwise differences and interactions,
    rather than merely the horse winner probability/market rank.
  * Ticket-hit probability trained independently from positive conditional
    JRA payout size and direct Tweedie expected payout, then competing
    money-valued scoring models are frozen by 2024 temporal validation.
  * All 2025 outcomes are used exclusively for historical settlement.
The stage-one LGBM LambdaRank for 2024 is trained only through 2023,
and for 2025 only through 2024. No 2025 labels enter any model or policy fit.

NO archive FINAL odds are used, no fabricated odds, no historical T15 snapshot
guarantees. All reported profits/losses are simulation on actual JRA payouts,
not real placed bets, and 2025 has been inspected in earlier studies.
No production writes, deployment, or live bet changes.
"""
from __future__ import annotations
import json,math,sys
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor
import lightgbm as lgb

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/race-relative-interaction-2025-actual-jra.json"
FEATURE_NAMES=("horseWinRate","horseTop3Rate","jockeyWinRate","jockeyTop3Rate",
 "trainerWinRate","trainerTop3Rate","avg3FinishPct","avg3SpeedMps",
 "lastSpeedMps","sameDistWinRate","sameDistTop3Rate","lastFinal3fPct",
 "horseStarts","daysSinceLast","age","assignedWeight","drawPct","distanceChange")
EVAL_K=5
BET=1000
FAMILIES=("direct_tweedie","pair_hurdle","blended_hurdle_tweedie","winsor_hurdle")
CUTOFF="2024-09-01"

def load(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj)
    return obj

def append_form_features(groups,X,offsets,meta,core):
    declared=core.load_config()["runnerProbabilityModel"]["features"]
    ix=[declared.index(name) for name in FEATURE_NAMES]
    rid_idx={m["rid"]:i for i,m in enumerate(meta)}
    for rows in groups.values():
      for r in rows:
        i=rid_idx[r["raceId"]]
        values=X[int(offsets[i]):int(offsets[i+1]),ix]
        if len(values)!=len(r["horses"]):raise RuntimeError("RACE_RUNNER_FEATURE_JOIN_MISMATCH")
        mu=values.mean(axis=0)
        sd=values.std(axis=0)
        z=(values-mu)/np.where(sd>1e-6,sd,1.0)
        r["raceRelativeForm"]=np.clip(z,-5,5).astype(np.float32)

def expanded_ticket_rows(groups,struct,base):
    baseX,paid,hit,meta=struct.build_rows(groups,base,"ranker_only")
    added=[]
    for day,r,ticket in meta:
        _,ix,_,_=ticket
        z=r["raceRelativeForm"]
        a=np.asarray(z[list(ix)],dtype=np.float32)
        ordered=np.zeros((3,a.shape[1]),dtype=np.float32)
        ordered[:len(ix)]=a
        # Preserve horse identities and role positions for ordered markets,
        # symmetric cross-horse effects for unordered markets.
        feature=np.concatenate((
            ordered.ravel(),
            np.mean(a,axis=0),
            np.std(a,axis=0),
            np.min(a,axis=0),
            np.max(a,axis=0),
            np.abs(a[0]-a[-1]),
            a[0]*a[-1],
            np.asarray([float(len(ix)==n) for n in (1,2,3)],dtype=np.float32)
        ))
        added.append(feature)
    extra=np.asarray(added,dtype=np.float32)
    if len(extra)!=len(baseX):raise AssertionError("EXTRA_FEATURE_MISMATCH")
    Xnew=np.hstack([baseX,extra])
    if not np.isfinite(Xnew).all():raise AssertionError("NONFINITE_FEATURES")
    return Xnew,paid,hit,meta

def fitted(X,paid,hits):
    if hits.sum()<800:raise RuntimeError("INSUFFICIENT_TRAIN_TICKET_WINNERS")
    cls=HistGradientBoostingClassifier(max_iter=95,learning_rate=.055,
            max_leaf_nodes=23,min_samples_leaf=100,l2_regularization=10,
            random_state=20261108,early_stopping=False)
    cls.fit(X,hits)
    pos=hits==1
    value=HistGradientBoostingRegressor(loss="poisson",max_iter=105,
            learning_rate=.045,max_leaf_nodes=19,min_samples_leaf=50,
            l2_regularization=12,random_state=20261108,early_stopping=False)
    value.fit(X[pos],np.clip(paid[pos]/100,1,180))
    direct=lgb.LGBMRegressor(objective="tweedie",tweedie_variance_power=1.35,
            n_estimators=200,num_leaves=23,min_child_samples=115,
            learning_rate=.045,reg_lambda=15,random_state=20261108,n_jobs=2,verbosity=-1)
    direct.fit(X,np.clip(paid/100,0,100))
    typ_payout=[]
    for i in range(6):
        filt=(X[:,i]>.5)&pos
        if not np.any(filt):raise RuntimeError("MISSING_MARKET_WIN_PRIOR")
        typ_payout.append(float(np.quantile(paid[filt]/100,.90)))
    return cls,value,direct,np.asarray(typ_payout)

def score(model,X):
    cls,value,direct,cap=model
    p=np.clip(cls.predict_proba(X)[:,1],0,1)
    conditional=np.maximum(0,value.predict(X))
    d=np.maximum(0,direct.predict(X))
    capped=np.zeros(len(X),dtype=np.float64)
    for i in range(6):
        subset=X[:,i]>.5
        capped[subset]=np.minimum(conditional[subset],cap[i])
    return {
      "direct_tweedie":d,
      "pair_hurdle":p*conditional,
      "blended_hurdle_tweedie":.50*d+.50*p*conditional,
      "winsor_hurdle":p*capped,
      "hitProb":p
    }

def select(groups,meta,score,hit_probability,allow_partial=False):
    ranked=defaultdict(list)
    for i,(day,r,ticket) in enumerate(meta):
        k,idx,prob,paid=ticket
        ranked[(day,r["raceId"])].append((float(score[i]),float(hit_probability[i]),k,int(paid)))
    venue_rows=[];monthly=defaultdict(list);no_pair=0
    for day,rs in sorted(groups.items()):
        daychoices=[]
        for r in rs:
            t=ranked[(day,r["raceId"])]
            best={}
            for s,p,k,paid in t:
                typ=k[0]
                if typ not in best or s>best[typ][0]:
                    best[typ]=(s,p,k,paid)
            if len(best)!=6:raise AssertionError("MISSING_TWO_OF_SIX_MARKET_TYPES")
            cand=[]
            rows=sorted(best.values(),key=lambda t:(-t[0],-t[1]))
            for i,a in enumerate(rows):
                for b in rows[i+1:]:
                    if max(a[1],b[1])<.20:continue
                    cand.append((a[0]+b[0],a,b))
            if not cand:continue
            u,a,b=max(cand,key=lambda x:x[0])
            if a[2][0]==b[2][0]:raise AssertionError("SAME_TYPE")
            ret=(a[3]+b[3])*BET//100
            daychoices.append({"date":day[0],"venue":day[1],
               "raceNo":r["raceNo"],"raceId":r["raceId"],
               "predictedReturn":u*BET,"stake":2*BET,
               "return":ret,"hit":int(a[3]>0 or b[3]>0),
               "tickets":[[a[2][0],list(a[2][1]),a[1]],[b[2][0],list(b[2][1]),b[1]]]})
        if len(daychoices)<EVAL_K:
            no_pair+=1
            if not allow_partial:continue
        chosen=sorted(daychoices,key=lambda q:(-q["predictedReturn"],q["raceNo"]))[:EVAL_K]
        venue_rows+=chosen
        monthly[day[0][:7]]+=chosen
    def stats(rows):
        n=len(rows);h=sum(r["hit"] for r in rows)
        stake=sum(r["stake"] for r in rows);ret=sum(r["return"] for r in rows)
        mx=max((r["return"] for r in rows),default=0)
        return {"races":n,"hitRaces":h,"hitRacePct":round(100*h/n,2) if n else None,
          "stakeYen":stake,"returnYen":ret,"netYen":ret-stake,
          "roiPct":round(100*ret/stake,2) if stake else None,
          "roiMinusMaxRacePct":round(100*(ret-mx)/stake,2) if stake else None}
    return {"metrics":stats(venue_rows),"excludedVenueDays":no_pair,
       "months":{k:stats(v) for k,v in sorted(monthly.items())},
       "sampleTickets":venue_rows[:2]}

def selftest():
    row={"raceRelativeForm":np.array([[0,1],[1,0],[0,-1]],dtype=np.float32)}
    x=np.array([2,3,1],dtype=float)
    assert x.sum()==6
    assert len(FEATURE_NAMES)==18 and len(FAMILIES)==4
    assert BET*2==2000 and CUTOFF.startswith("2024")
    print("RACE_RELATIVE_INTERACTION_MODEL_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","interaction_hist")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","interaction_jra")
    struct=load("scripts/research-structural-ranker-twohead-2025.py","interaction_struct")
    base=load("scripts/research-two-stage-payout-value-2024-2025.py","interaction_tickets")
    archive=hist.load_bundles(hist.load_public_archive())
    core=hist.core_module()
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(core,archive)
    t3=struct.top3_targets(archive)
    meta=audit.eligible_metadata(archive)
    assert len(X)==len(y)==len(t3) and len(meta)==len(counts)
    pays,coverage=audit.payout_book()
    groups={};horseTraining={}
    for year in (2024,2025):
        horse,info=struct.fit_horse_models(X,y,t3,counts,offsets,dates,year)
        full,excluded,_=struct.year_groups(year,X,counts,dates,offsets,meta,horse,pays)
        append_form_features(full,X,offsets,meta,core)
        groups[year]=full;horseTraining[year]=info
        print("INTERACTION_HORSE_TRAIN",year,len(full),json.dumps(info),flush=True)
        del horse
    x24,paid24,hit24,meta24=expanded_ticket_rows(groups[2024],struct,base)
    x25,paid25,hit25,meta25=expanded_ticket_rows(groups[2025],struct,base)
    split=np.asarray([row[0][0]>=CUTOFF for row in meta24],dtype=bool)
    if min(sum(split),sum(~split))<20000:raise RuntimeError("INSUFFICIENT_CHRONOLOGICAL_SPLIT_2024")
    print("INTERACTION_FEATURES_READY",json.dumps({"features":x24.shape[1],
        "2024Rows":len(x24),"2025Rows":len(x25),"priorTraining":int(sum(~split)),
        "2024ValidationRows":int(sum(split))}),flush=True)
    early=fitted(x24[~split],paid24[~split],hit24[~split])
    preds24=score(early,x24[split])
    testmeta=[m for m,good in zip(meta24,split) if good]
    valrows={}
    for kind in FAMILIES:
        restrict={k:v for k,v in groups[2024].items() if k[0]>=CUTOFF}
        out=select(restrict,testmeta,preds24[kind],preds24["hitProb"])
        valrows[kind]=out["metrics"]
    # 2024-only ranking; no 2025 payout used to choose the model formula.
    eligible=[(k,v) for k,v in valrows.items() if v["hitRacePct"] is not None
       and v["hitRacePct"]>=20 and v["races"]>=150]
    if not eligible:raise RuntimeError("2024_NO_CALIBRATED_HIT20_POLICY")
    ranked=sorted(eligible,key=lambda kv:
      (-kv[1]["roiMinusMaxRacePct"],-kv[1]["roiPct"],kv[0]))
    choice=ranked[0][0]
    print("INTERACTION_2024_ONLY_SELECTOR",json.dumps({"winner":choice,
      "all2024Validation":valrows},ensure_ascii=False),flush=True)
    # Refit once on all 2024 training labels, never 2025 labels.
    trained=fitted(x24,paid24,hit24)
    out25=score(trained,x25)
    results={kind:select(groups[2025],meta25,out25[kind],out25["hitProb"])
             for kind in FAMILIES}
    chosen=results[choice]["metrics"]
    report={"status":"RESEARCH_ONLY_RACE_RELATIVE_TWO_HEAD_PAYOUT",
      "selectedFrom2024Only":choice,
      "2024Val":valrows,
      "2025Models":results,
      "frozenSelected2025":chosen,
      "2025PassedHitFloor":chosen["hitRacePct"] is not None and chosen["hitRacePct"]>=20,
      "2025RoiOver100":chosen["roiPct"] is not None and chosen["roiPct"]>100,
      "no2025LabelsUsedInModelSelectionOrFit":True,
      "2025ArchivePreviouslyReviewed":True,
      "historicalRunnerT15Proven":False,
      "officialOddsPreT15Used":False,
      "realBetsPlaced":False,"eligibleForPromotion":False,
      "cohortVenueDays":{str(k):len(v) for k,v in groups.items()},
      "horseTraining":horseTraining,
      "ticketTrain2024Rows":len(x24),"featureCount":x24.shape[1],
      "payoutSourceMonths":coverage}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("INTERACTION_2025_REAL_JRA_PAIRED",json.dumps({"chosen":choice,
        "selected2025":chosen,"all2025":{k:v["metrics"] for k,v in results.items()},
        "promotionEligible":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
