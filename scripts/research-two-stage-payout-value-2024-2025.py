#!/usr/bin/env python3
"""Payout-aware *new* horse/ticket model, real-JRA 2025 chronological evaluation.

Frozen algorithm:
 - 2024 horse model: labels through 2023; 2025 horse model: through 2024
 - a separate payout-value learner is fitted ONLY using 2024 true JRA payouts
   and 2024 predictions from the model trained through 2023
 - 2025 tickets use only the 2025 horse model and this 2024 payout model
 - no historical final or synthetic odds; no future race labels used as features
 - one race two distinct bet types, 3/4/5 selected races per venue/day
 - identical races/tickets/stakes used for hit rate and ROI and no wager omission
 - read-only D1, writes a research JSON artifact locally, not production.
This is historical research, NOT live T-15. Any prior discussion of 2025
results makes the comparison chronologically trained but not fully blind.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations,permutations
from pathlib import Path
import importlib.util,json,math,sys
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/payout-value-stage2-2024train-2025actual-jra.json"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
N_RANK=5
PAID_STAKE=2000

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MISSING_RESEARCH_DEPENDENCY:"+str(path))
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj);return obj

def horse_model(X,y,dates,offsets,year):
    idx=np.flatnonzero(dates<f"{year}-01-01")
    if not len(idx) or idx[-1]<10000:raise ValueError("INSUFFICIENT_EARLIER_TRAIN_DATA")
    boundary=int(offsets[int(idx[-1])+1])
    if str(dates[int(idx[-1])])>=f"{year}-01-01":raise AssertionError("HORSE_LABEL_FUTURE_LEAK")
    model=ExtraTreesClassifier(n_estimators=120,max_depth=14,min_samples_leaf=35,
                              max_features=0.7,random_state=20261107,n_jobs=2)
    model.fit(X[:boundary],y[:boundary])
    return model,{"trainRunnerRows":boundary,"trainLastDate":str(dates[int(idx[-1])])}

def get_by_year(year,X,counts,dates,offsets,meta,model,payout):
    start=f"{year}-05-04" if year==2024 else f"{year}-01-01"
    ix=np.flatnonzero((dates>=start)&(dates<f"{year+1}-01-01"))
    if not len(ix):raise ValueError("NO_TARGET_YEAR")
    low=int(offsets[int(ix[0])]);high=int(offsets[int(ix[-1]+1)])
    raw=model.predict_proba(X[low:high])[:,1]
    offset=0;groups=defaultdict(list)
    for i in ix:
        i=int(i);n=int(counts[i]);m=meta[i]
        pp=np.maximum(raw[offset:offset+n],1e-12)
        p=pp/pp.sum()
        offset+=n
        groups[(m["date"],m["venue"])].append({"raceId":m["rid"],"date":m["date"],
         "venue":m["venue"],"raceNo":int(m["no"]),"horses":tuple(int(x) for x in m["horses"]),
         "probs":p,"payout":payout.get(m["rid"],{})})
    assert offset==len(raw)
    good={};rejected=Counter()
    for group,rs in groups.items():
        if len(rs)!=12 or {r["raceNo"] for r in rs}!=set(range(1,13)):
            rejected["not_full_12_race_venue_day"]+=1;continue
        if any({k[0] for k in r["payout"]}!=set(TYPES) for r in rs):
            rejected["incomplete_six_market_payouts"]+=1;continue
        good[group]=sorted(rs,key=lambda x:x["raceNo"])
    return good,dict(rejected),len(ix)

def pl_pair(p,a,b):
    return float(p[a]*p[b]/max(1e-12,1-p[a]))
def pl_triple(p,a,b,c):
    return float(p[a]*p[b]/max(1e-12,1-p[a])*p[c]/max(1e-12,1-p[a]-p[b]))
def probability(kind,idx,p):
    if kind=="単勝":return float(p[idx[0]])
    if kind=="馬単":return pl_pair(p,*idx)
    if kind=="馬連":return pl_pair(p,*idx)+pl_pair(p,*idx[::-1])
    if kind=="3連単":return pl_triple(p,*idx)
    if kind=="3連複":return sum(pl_triple(p,*perm) for perm in permutations(idx))
    if kind=="ワイド":
        a,b=idx
        return sum(sum(pl_triple(p,*perm) for perm in permutations((a,b,c)))
            for c in range(len(p)) if c not in idx)
    raise ValueError("INVALID_TYPE")

def enumerate_tickets(r):
    p=r["probs"];order=np.argsort(-p,kind="stable")
    k=min(N_RANK,len(order))
    result=[]
    ttop=tuple(int(x) for x in order[:k])
    templates={
       "単勝":[(i,) for i in ttop],
       "ワイド":list(combinations(ttop,2)),
       "馬連":list(combinations(ttop,2)),
       "馬単":list(permutations(ttop[:4],2)),
       "3連複":list(combinations(ttop,3)),
       "3連単":list(permutations(ttop[:4],3)),
    }
    for typ in TYPES:
        for ix in templates[typ]:
            nums=[r["horses"][i] for i in ix]
            if typ in UNORDERED:nums=sorted(nums)
            key=(typ,tuple(nums))
            prob=probability(typ,ix,p)
            if not np.isfinite(prob) or prob<=0:continue
            paid=int(r["payout"].get(key,0))
            if paid<0:raise ValueError("NEGATIVE_JRA_PAYOUT")
            result.append((key,ix,prob,paid))
    return result

def features(r,ticket):
    key,idx,pr,paid=ticket
    p=np.asarray(r["probs"],dtype=np.float64)
    top=sorted(p,reverse=True)
    positions=[next(i+1 for i,horse in enumerate(np.argsort(-p,kind="stable"))
                    if int(horse)==j) for j in idx]
    picks=np.asarray([p[j] for j in idx],dtype=np.float64)
    entropy=-float(np.sum(p*np.log(np.maximum(p,1e-12))))/math.log(len(p))
    pds=list(positions)+[0]*(3-len(positions))
    vals=list(picks)+[0.]*(3-len(picks))
    return [
      *[int(key[0]==kind) for kind in TYPES],
      len(p)/18,r["raceNo"]/12,
      top[0],top[1],top[2],sum(top[:3]),entropy,
      pr,math.log(max(pr,1e-9)),float(np.prod(picks)),
      sum(vals),max(vals),min([v for v in vals if v>0]),
      pds[0]/6,pds[1]/6,pds[2]/6,
      sum(positions)/16,max(positions)/6,
      vals[0],vals[1],vals[2],
      int(key[0] in ("馬単","3連単")),
      int(1 in positions),
      int(max(positions)<=3),
    ]

def summarize(rows):
    total=len(rows);hits=sum(x["hit"] for x in rows)
    stake=sum(x["stake"] for x in rows);ret=sum(x["return"] for x in rows)
    biggest=max((x["return"] for x in rows),default=0)
    return {"races":total,"hitRaces":hits,"hitRacePct":round(100*hits/total,2) if total else None,
     "stakeYen":stake,"returnYen":ret,"netYen":ret-stake,
     "roiPct":round(100*ret/stake,2) if stake else None,
     "roiMinusLargestPayoutPct":round(100*(ret-biggest)/stake,2) if stake else None}

def data_matrix(groups):
    x=[];y=[];totals=Counter();payouts=Counter()
    for rs in groups.values():
        for r in rs:
            for ticket in enumerate_tickets(r):
                x.append(features(r,ticket))
                y.append(min(100.0,ticket[3]/100.0))
                totals[ticket[0][0]]+=1
                payouts[ticket[0][0]]+=int(ticket[3]>0)
    if len(x)<10000:raise AssertionError("INSUFFICIENT_SECOND_STAGE_TICKETS")
    return np.asarray(x,dtype=np.float32),np.asarray(y,dtype=np.float32),dict(totals),dict(payouts)

def choose_race(r,value,regressor):
    tickets=enumerate_tickets(r)
    fx=np.asarray([features(r,t) for t in tickets],dtype=np.float32)
    raw=np.maximum(1e-9,regressor.predict(fx))
    bytype={}
    for i,ticket in enumerate(tickets):
        kind=ticket[0][0]
        pred=float(raw[i])
        old=bytype.get(kind)
        if old is None or pred>old[0] or (pred==old[0] and ticket[2]>old[1][2]):
            bytype[kind]=(pred,ticket)
    bets=sorted([(v[0],v[1]) for v in bytype.values()],key=lambda t:(-t[0],-t[1][2]))
    if len(bets)<2:raise AssertionError("MISSING_DISTINCT_TYPES")
    # Two options: maximize modeled unconditional return and require
    # one ticket's model event >=20%, a mathematically valid lower bound
    # for the union probability of at least one ticket hitting.
    valid=[]
    for i in range(len(bets)):
        for j in range(i+1,len(bets)):
            a,b=bets[i],bets[j]
            if max(a[1][2],b[1][2])*100+1e-8<20:continue
            s1,s2=(1900,100) if a[0]>=b[0] else (100,1900)
            score=a[0]*s1+b[0]*s2
            valid.append((score,a,b,s1,s2))
    if not valid:return None
    score,a,b,s1,s2=max(valid,key=lambda row:row[0])
    actualReturn=int(a[1][3]*s1/100+b[1][3]*s2/100)
    return {"raceId":r["raceId"],"date":r["date"],"venue":r["venue"],"raceNo":r["raceNo"],
      "predictedScore":float(score/PAID_STAKE),"stake":PAID_STAKE,"return":actualReturn,
      "hit":int(a[1][3]>0 or b[1][3]>0),
      "tickets":[{"betType":a[1][0][0],"combination":"-".join(map(str,a[1][0][1])),
          "stakeYen":s1,"modelP":a[1][2],"trainingExpectedReturnMultiple":a[0]},
         {"betType":b[1][0][0],"combination":"-".join(map(str,b[1][0][1])),
          "stakeYen":s2,"modelP":b[1][2],"trainingExpectedReturnMultiple":b[0]}]}

def evaluate(groups,model):
    results={}
    for k in (3,4,5):
        selected=[];exclusion=Counter();byMonth=defaultdict(list)
        for (date,venue),rs in sorted(groups.items()):
            ranking=[]
            for r in rs:
                pred=choose_race(r,None,model)
                if pred is not None:ranking.append(pred)
            if len(ranking)<k:
                exclusion["fewer_than_%d_races_meet_pre_predicted_hit_floor"%k]+=1
                continue
            chosen=sorted(ranking,key=lambda x:(-x["predictedScore"],x["raceNo"]))[:k]
            selected.extend(chosen);byMonth[date[:7]].extend(chosen)
        results[str(k)]={"metrics":summarize(selected),"completeVenueDays":len(selected)//k,
          "excludedVenueDays":dict(exclusion),
          "months":{m:summarize(rs) for m,rs in sorted(byMonth.items())},
          "actualSelectedRaceIds":[x["raceId"] for x in selected[:20]],
          "exampleTickets":[x["tickets"] for x in selected[:2]]}
    return results

def selftest():
    r={"probs":np.array([0.5,0.3,0.2]),"horses":(7,8,9),"raceNo":1,
       "date":"2024-06-01","venue":"東京",
       "payout":{("単勝",(7,)):230,("ワイド",(7,8)):140,("馬連",(7,8)):550}}
    a=enumerate_tickets(r)
    assert len(a)>5
    assert any(t[0]==("単勝",(7,)) and t[3]==230 for t in a)
    assert any(t[0]==("馬連",(7,8)) and t[3]==550 for t in a)
    assert abs(probability("馬連",(0,1),r["probs"])-0.5*0.3/0.5-0.3*0.5/0.7)<1e-9
    assert features(r,a[0])
    p=probability("ワイド",(0,1),r["probs"])
    assert abs(p-1.0)<1e-9  # With 3 runners, every top-two pair is also a WIDE hit.
    assert summarize([{"stake":2000,"return":4600,"hit":1}])["roiPct"]==230
    print("SECOND_STAGE_PAYOUT_VALUE_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:selftest();return
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","value_hist")
    audit=load("scripts/research-extra-trees-2024-2025-paired-jra.py","value_d1")
    arc=hist.load_bundles(hist.load_public_archive())
    X,y,counts,dates,offsets,_,_,_,_=hist.chronological_features(hist.core_module(),arc)
    meta=audit.eligible_metadata(arc)
    assert len(meta)==len(counts)
    payout,coverage=audit.payout_book() # bounded actual six JRA market payout queries
    groups={};rejected={};training={}
    for year in (2024,2025):
        horse,trainInfo=horse_model(X,y,dates,offsets,year)
        eligible,exceptions,rawRaces=get_by_year(year,X,counts,dates,offsets,meta,horse,payout)
        if len(eligible)<100:raise ValueError("HISTORIC_JRA_COHORT_TOO_SMALL")
        groups[year]=eligible;rejected[year]=exceptions;training[year]=trainInfo
        print("PAYOUT_STAGE_YEAR_FEATURES",json.dumps({"year":year,"venues":len(eligible),
            "races":rawRaces,"horseTrain":trainInfo,"excluded":exceptions}),flush=True)
        del horse
    features24,payouts24,counts24,hits24=data_matrix(groups[2024])
    learned=HistGradientBoostingRegressor(loss="poisson",max_iter=135,learning_rate=0.04,
          max_leaf_nodes=23,min_samples_leaf=120,l2_regularization=12.0,
          early_stopping=False,random_state=20261108)
    learned.fit(features24,payouts24)
    print("PAYOUT_STAGE_TWO_STAGE_FITTED",json.dumps({"rows":len(payouts24),
        "targetsActual2024Only":True,"positiveByBetType":hits24,"rowsByBetType":counts24}),flush=True)
    evaluations=evaluate(groups[2025],learned)
    report={"status":"RESEARCH_ONLY_2024_PAYOUT_LEARNER_2025_CHRONOLOGICAL_SETTLEMENT",
      "horseModel":"ExtraTrees120 each year trained through prior year",
      "ticketModel":"Poisson HistGradientBoostingRegressor on clipped JRA actual payout multiples from 2024",
      "clipForTrainingOnly":100.0,"payoffForEvaluation":"uncapped actual JRA D1 payout",
      "trainRacePeriod":"2024-05-04..2024-12-31",
      "testRacePeriod":"2025-01-01..2025-12-31",
      "noHistoricalFinalOdds":True,"requiresT15OfficialMarketValidation":True,
      "2025PreviouslySeenInOtherStudies":True,"noPromotionAllowed":True,
      "historyInputUsesOnlyPriorYearLabels":True,
      "perRaceModeledUnionHitFloor":"at least one ticket predicted >=20%: guarantees modeled union >=20%; does NOT guarantee empirical 20%",
      "raceSelection":"highest second-stage predicted 2-ticket 2000yen return",
      "payoutDataMonthCoverage":coverage,"horseTrain":training,
      "venueDaysEligible":{str(k):len(v) for k,v in groups.items()},
      "venueDaysRejected":rejected,
      "2024Stage2TrainingRows":len(payouts24),
      "2025ProspectiveStylePairedHitAndActualJraRoi":evaluations}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PAYOUT_STAGE_2025_MATCHED_HIT_AND_ROI",json.dumps({
      "strategy":report["ticketModel"],"metrics":{k:v["metrics"] for k,v in evaluations.items()},
      "eligible":report["venueDaysEligible"],"promotion":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
