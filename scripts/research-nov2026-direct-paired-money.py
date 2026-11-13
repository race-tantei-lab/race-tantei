#!/usr/bin/env python3
"""FULL PAIR-PORTFOLIO CASH LEARNER, NOT A HORSE WIN-PROB MODEL.

Directly learn cash returned by each purchasable *two-market formation*
jointly (JPY 2,000), rather than combining two standalone ticket predictions.
Action identity: first market, second market, ticket count, style, field context
and correlated odds structure. In each 12-race venue-day choose 3/4/5 ranked
races, the pair and two market formations BEFORE reading their settlements.
Historical payout is ONLY a supervised label, not an inference input.
Train 2017-21; approve parameters on 2022 alone; 2023+ disjoint evaluation
only if 2022 ROI>=200%, ROI-minus-largest>=200%, hit-rate>=20%, 3R/venue.
The archived horse win odds are closing odds, not official pre-T15 quote
history, so numeric qualification alone cannot certify live adoption.
"""
from __future__ import annotations
import csv,importlib.util,json,sys,collections,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMRegressor,LGBMClassifier
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-direct-pair-money-model.json"
LED=R/"analysis-results/nov2026-direct-pair-money-bets.csv"
SEED=20261113
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
TRAIN=tuple(range(2017,2022))
HOLDOUT=(2023,2024,2025,2026)
# 3 independently-generated ticket sets per market, each with 10 x 100 JPY,
# (popular 1-point, broad 5 points, upset 10 points), therefore all actions
# cost 1000 JPY per market. Whole paired stake = 2000 JPY.
KIND_ACTIONS=(0,6,11)  # [popular/1, broad/5, upset/10]
MARKET_ACTIONS=np.asarray([[m*16+a for a in KIND_ACTIONS] for m in range(6)],dtype=np.int16)
PAIR_ACTIONS=np.asarray([(int(u),int(v)) for m in range(6)
    for n in range(m+1,6) for u in MARKET_ACTIONS[m] for v in MARKET_ACTIONS[n]],dtype=np.int16)
PAIRS=len(PAIR_ACTIONS)
assert PAIRS==135 and np.all(PAIR_ACTIONS[:,0]//16!=PAIR_ACTIONS[:,1]//16)
YEARS_SAMPLE=tuple(range(2017,2022))
CASH_APPROVAL=2022
SLATES=(3,4,5)
CASH_POWERS=(0.,0.5,1.)
DISAGREE=(0.,.5)
SCOREMODES=("joint_ev","joint_ev_hit","joint_hit","joint_conservative")
def dep():
    p=R/"scripts/research-nov2026-direct-action-money.py"
    x=importlib.util.spec_from_file_location("raw96_money_formation",p)
    v=importlib.util.module_from_spec(x);sys.modules[x.name]=v;x.loader.exec_module(v)
    return v
def stats(a):
    a=np.asarray(a,dtype=np.int64);n=len(a);cost=2000*n
    paid=int(a.sum());maxp=int(a.max()) if n else 0
    return {"races":n,"stakeYen":cost,"paidYen":paid,
        "roiPct":round(100*paid/cost,4) if n else None,
        "minusLargestRaceRoiPct":round(100*(paid-maxp)/cost,4) if n else None,
        "hitRacePct":round(100*np.count_nonzero(a)/n,4) if n else None,
        "maximumRacePayoutYen":maxp}
def acceptable(q,min_races=400):
    return q["races"]>=min_races and (q["roiPct"] or 0)>=200 and (
        q["minusLargestRaceRoiPct"] or 0)>=200 and (q["hitRacePct"] or 0)>=20
def pair_features(x,y,pairs=PAIR_ACTIONS):
    # x: [race_count,96,16], y: (optional) [race_count,96]
    n=x.shape[0]
    a=x[:,pairs[:,0],:]
    b=x[:,pairs[:,1],:]
    # On-source pooled group: actions jointly evaluated, no payout features.
    result=np.empty((n,len(pairs),38),dtype=np.float32)
    result[:,:,:16]=a
    # Share early 8 race-level fields only once, with both 8 action-specific
    # features embedded to avoid labeling correlated quote context twice.
    result[:,:,16:24]=b[:,:,8:16]
    result[:,:,24:32]=a[:,:,8:16]-b[:,:,8:16]
    result[:,:,32:36]=a[:,:,8:12]+b[:,:,8:12]
    result[:,:,36]=np.maximum(a[:,:,14],b[:,:,14])
    result[:,:,37]=np.abs(a[:,:,14]-b[:,:,14])
    return result
def paid_arrays(label,ids):
    # label is monetary payout per market action in units of JPY/10.
    # Multiply by 10 to obtain full JPY 1,000 each. No payout changes
    # based on future outcome used to generate action IDs.
    la=label[ids]
    return np.rint((la[:,PAIR_ACTIONS[:,0]]+la[:,PAIR_ACTIONS[:,1]])*10).astype(np.int64)
def learn(x,pay,year,train):
    indexes=np.flatnonzero(np.isin(year,train))
    if len(indexes)<13000:raise RuntimeError("INSUFFICIENT_CASH_TRAIN_RACES")
    rng=np.random.default_rng(SEED)
    training_data=[]
    target=[]
    # Sample complete real-money two-market actions. Keep all paid
    # winners; sample losing pairs with inverse propensity weights.
    for start in range(0,len(indexes),400):
        sel=indexes[start:start+400]
        labels=paid_arrays(pay,sel).reshape(-1)
        keep=(labels>0)|(rng.random(len(labels))<.16)
        features=pair_features(x[sel],None).reshape(-1,38)
        training_data.append(features[keep])
        target.append(labels[keep])
    features=np.concatenate(training_data)
    paid=np.concatenate(target)
    if len(features)<260000 or int(np.count_nonzero(paid))<18000:
        raise RuntimeError("INSUFFICIENT_JOINT_PAYING_PORTFOLIOS")
    weights=np.where(paid>0,1.,1/.16).astype(np.float32)
    y=np.minimum(paid,250000).astype(np.float32)/2000.
    opts=dict(n_estimators=160,learning_rate=.055,num_leaves=17,
        max_depth=6,min_child_samples=280,reg_lambda=23.,
        colsample_bytree=.8,random_state=SEED,n_jobs=3,verbosity=-1)
    cash=LGBMRegressor(objective="tweedie",tweedie_variance_power=1.25,**opts)
    cash.fit(features,y,sample_weight=weights)
    pos=LGBMClassifier(objective="binary",**opts)
    pos.fit(features,(paid>0).astype(np.int8),sample_weight=weights)
    # Outlier dampening by a separately trained capped conditional model,
    # not by an ex post largest-winner removal in ticket selection.
    capped=LGBMRegressor(objective="poisson",**{
        **opts,"n_estimators":115,"num_leaves":11,"min_child_samples":360})
    capped.fit(features,np.minimum(paid,15000).astype(np.float32)/2000.,
        sample_weight=weights)
    info={"races":int(len(indexes)),"twoMarketPortfolios":int(len(features)),
       "paidPairLabels":int(np.count_nonzero(paid)),
       "separateNetMoneyTarget":True}
    return cash,pos,capped,info
def predict(models,x,years,yr):
    ind=np.flatnonzero(years==yr)
    n=len(ind)
    out=np.zeros((n,PAIRS,3),dtype=np.float32)
    for start in range(0,n,300):
        ix=ind[start:start+300]
        a=pair_features(x[ix],None).reshape(-1,38)
        cash,pos,cap,_=models
        z=np.empty((len(a),3),dtype=np.float32)
        for j in range(0,len(a),50000):
            xx=a[j:j+50000]
            z[j:j+len(xx),0]=cash.predict(xx).astype(np.float32)
            z[j:j+len(xx),1]=pos.predict_proba(xx)[:,1].astype(np.float32)
            z[j:j+len(xx),2]=cap.predict(xx).astype(np.float32)
        out[start:start+len(ix)]=z.reshape(len(ix),PAIRS,3)
    return ind,out
def venue_groups(races,idx):
    by=collections.defaultdict(list)
    for k,i in enumerate(idx):
        r=races[int(i)]
        by[(r["day"],r["venue"])].append(k)
    if not by or any(len(g)<5 for g in by.values()):
        raise RuntimeError("VENUE_DAY_LACKS_MINIMUM_5_RACES")
    return [np.asarray(g,dtype=np.int32) for g in by.values()]
def decisions(races,labels,idx,pred,slate,power,penalty,mode,ledger=False):
    pure=np.maximum(pred[:,:,0],1e-7)
    clip=np.maximum(pred[:,:,2],1e-7)
    prob=np.maximum(pred[:,:,1],1e-7)
    if mode=="joint_ev":score=pure
    elif mode=="joint_hit":score=prob
    elif mode=="joint_conservative":score=clip
    elif mode=="joint_ev_hit":score=np.sqrt(pure*clip)
    else:raise RuntimeError("BAD_JOINT_POLICY")
    score=score*np.power(prob,power)*np.power(1+np.maximum(pure-clip,0),-penalty)
    nominated=np.argmax(score,axis=1)
    priority=score[np.arange(len(idx)),nominated]
    grouping=venue_groups(races,idx)
    paid=paid_arrays(labels,idx)
    chosen=np.concatenate([np.asarray(sorted(g.tolist(),
        key=lambda j:(-float(priority[j]),int(j)))[:slate],
        dtype=np.int32) for g in grouping])
    winnings=paid[chosen,nominated[chosen]]
    if not ledger:return winnings,None
    bets=[]
    for j in chosen:
        r=races[int(idx[j])]
        a,b=PAIR_ACTIONS[nominated[j]]
        bets.append({"year":int(r["month"][:4]),"raceId":r["id"],
          "venue":r["venue"],"day":r["day"],"raceNo":r["raceNo"],
          "market1":TYPES[int(a)//16],"market2":TYPES[int(b)//16],
          "action1":int(a),"action2":int(b),
          "stake1Yen":1000,"stake2Yen":1000,
          "paidYen":int(paid[j,nominated[j]])})
    return winnings,bets
def main():
    if "--self-test" in sys.argv:
        assert PAIRS==135
        assert pair_features(np.zeros((2,96,16),dtype=np.float32),None).shape==(2,135,38)
        assert len(SLATES)*len(CASH_POWERS)*len(DISAGREE)*len(SCOREMODES)==72
        assert not acceptable({"races":500,"roiPct":200,"minusLargestRaceRoiPct":199,"hitRacePct":30})
        assert acceptable({"races":500,"roiPct":200,"minusLargestRaceRoiPct":200,"hitRacePct":20})
        print("JOINT_REAL_CASH_PORTFOLIO_SELFTEST_OK");return
    start=time.monotonic()
    d=dep()
    races,cash,year,slots,slices=d.universe()
    features,labels,ticketids,markets,styles,ticket_counts=d.make_actions(
        races,cash,slots,slices)
    print("JOINT_CASH_ACTION_GENERATOR",json.dumps({
       "races":len(races),"perRaceTwoMarketFormations":PAIRS,
       "allCandidateCombinations":int(len(races)*PAIRS),
       "cashSettlementOnlyTargets":True,
       "pastFinalOddsNotOfficialT15":True}),flush=True)
    models=learn(features,labels,year,TRAIN)
    ix,pred=predict(models,features,year,CASH_APPROVAL)
    best=None;tested=0;qualifiers=0
    for slate in SLATES:
     for power in CASH_POWERS:
      for penalty in DISAGREE:
       for mode in SCOREMODES:
        pay,_=decisions(races,labels,ix,pred,slate,power,penalty,mode)
        m=stats(pay);tested+=1
        if acceptable(m):
          qualifiers+=1
          rule={"slate":slate,"power":power,"penalty":penalty,
             "mode":mode,"verified2022Cash":m}
          if best is None or m["minusLargestRaceRoiPct"]>best["verified2022Cash"]["minusLargestRaceRoiPct"]:
             best=rule
    report={"status":"REJECTED_NOT_A_MODEL","mainChanged":False,
       "newAlgorithm":"two-market JOINT portfolio money forecaster",
       "actionsPerRace":PAIRS,"sourceRaces":len(races),
       "trainYearStart":2017,"trainYearEnd":2021,
       "approvalYear":2022,"trainData":models[3],
       "portfoliosChecked":tested,"qualifyingPortfolios":qualifiers,
       "gate200Pct":True,"largestPayoutExcluded200Pct":True,
       "hitRateFloor20Pct":True,"mustSelectAtLeast3VenueRaces":True,
       "pre15OfficialOddsProven":False,"officialPayoutReconciled":False,
       "historicalInspected2023PlusPreviously":True,
       "chosen":best}
    if best:
        del models
        nextmodels=learn(features,labels,year,tuple(range(2017,2023)))
        final=[];years={}
        for y in HOLDOUT:
            ids,pred=predict(nextmodels,features,year,y)
            amounts,details=decisions(races,labels,ids,pred,best["slate"],
                best["power"],best["penalty"],best["mode"],True)
            years[str(y)]=stats(amounts);final.extend(details)
            print("JOINT_PORTFOLIO_FORWARD_YEN",json.dumps({"year":y,
              "settledCash":years[str(y)]}),flush=True)
        whole=stats([v["paidYen"] for v in final])
        passed=acceptable(whole) and all(
            m["races"]>=30 and m["roiPct"]>=200 and
            m["minusLargestRaceRoiPct"]>=200 and m["hitRacePct"]>=20
            for m in years.values())
        report.update({"status":"PROVISIONAL_UNVERIFIED_T15_NUMERIC200"
                 if passed else "REJECTED_NOT_A_MODEL",
            "forwardMoney":whole,"independentYears":years,
            "forwardNumericQualified":passed})
        if final:
            LED.parent.mkdir(parents=True,exist_ok=True)
            with LED.open("w",encoding="utf-8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=list(final[0]))
                w.writeheader();w.writerows(final)
    report["elapsedSec"]=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("JOINT_REAL_CASH_MODEL_RESULT",json.dumps({
       "status":report["status"],"qualified2022":bool(best),
       "policiesChecked":tested,"pairedActionCandidates":int(len(races)*PAIRS),
       "durationSec":report["elapsedSec"],"mainChanged":False}),flush=True)
if __name__=="__main__":main()
