#!/usr/bin/env python3
"""NEW ACTUAL CASH ACTION MODEL -- top-ten, 6 markets, multi-ticket formations.

The single learning target is the money returned by buying a whole formation,
not horse win/place probabilities and not per-ticket expected value. A ticket
action = [JRA market, concentration style, 1/2/5/10 tickets]; the price of
each action is exactly 1000 yen. Each race buys TWO different market actions,
total 2000 yen. Entire actions, racing-day selection and amounts are chosen
BEFORE opening that race's settlement. Strict 2017-21 train / 2022 validate,
2023+ untouched unless 2022 clears all 200% and 20% hard gates.

Historical quote input: third-party FINAL win odds, NOT official pre-T15.
Actual payout source: pinned third-party mirror, NOT independently verified
JRA payment record. Hence even numerical success cannot be live certified.
"""
from __future__ import annotations
import collections,importlib.util,itertools,json,sys,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMRegressor,LGBMClassifier
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-action-profit-model.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
STYLES=("popular","broad","upset","reversal")
K=(1,2,5,10)
A=len(MARKETS)*len(STYLES)*len(K)
PER_DAY=(3,4,5)
BUDGET=2000
RAND_SEED=20261113
CASH_TRAIN=(2017,2018,2019,2020,2021)
CASH_SELECT=2022
CASH_TEST=(2023,2024,2025,2026)
# Action allocation uses stakes of 1000 yen to EACH of two different
# markets. Every k divides 10: each ticket has integer >=100 yen.
assert all(1000%k==0 for k in K)
def mod(path,name):
    s=importlib.util.spec_from_file_location(name,R/path)
    x=importlib.util.module_from_spec(s);sys.modules[name]=x;s.loader.exec_module(x);return x
def metrics(paid):
    p=np.asarray(paid,dtype=np.int64);n=len(p);stake=n*BUDGET
    returned=int(np.sum(p));largest=int(np.max(p)) if n else 0
    return dict(races=n,stakeYen=stake,paidYen=returned,
      roiPct=round(100*returned/stake,4) if n else None,
      minusLargestRaceRoiPct=round(100*(returned-largest)/stake,4) if n else None,
      hitRacePct=round(100*np.count_nonzero(p)/n,4) if n else None,
      largestRacePaidYen=largest)
def eligible(m):
    return m["races"]>=300 and (m["roiPct"] or 0)>=200 and (
       m["minusLargestRaceRoiPct"] or 0)>=200 and (m["hitRacePct"] or 0)>=20
def universe():
    core=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","fullten_all_cash")
    cash_parser=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","fullten_cash_parser")
    races=core.read_all_races(cash_parser.parse_payments)
    if not (core.CACHE.is_file() and core.RACE_CACHE.is_file()):
        core.CACHE.parent.mkdir(exist_ok=True,parents=True)
        core.full_features(races)
    with np.load(core.CACHE,allow_pickle=False) as z:
        allcash=np.asarray(z["payout"],dtype=np.int32)
        if allcash.shape!=(len(races),core.N):
            raise RuntimeError("TOP10_STALE_MONEY_CACHE")
    # Train 2017 onward, keep every qualifying settled race to maintain
    # genuine 3-5 race / venue-day coverage; no form-match filtering.
    ids=[i for i,r in enumerate(races) if r["month"]>="201701"]
    cash=allcash[np.asarray(ids,dtype=np.int32)]
    races=[races[i] for i in ids]
    if len(races)<26000 or cash.shape[1]!=1030:
        raise RuntimeError("FULL_TEN_RUNNER_ARCHIVE_MISSING")
    years=np.asarray([int(r["month"][:4]) for r in races],dtype=np.int16)
    slots,market=core.fixed_template()
    slices=[np.flatnonzero(market==m) for m in range(6)]
    if any(len(x)==0 for x in slices):raise RuntimeError("EMPTY_CASH_MARKET")
    return races,cash,years,slots,slices
def make_actions(races,cash,slots,slices):
    n=len(races)
    unit_cash=np.zeros((n,A),dtype=np.float32)
    metadata=np.zeros((n,A,16),dtype=np.float32)
    # Store exact original top-10 combination template IDs. The amount
    # 1000//k is fixed before results and the outcome lookup occurs only
    # after those IDs are chosen.
    ticket_ids=np.full((n,A,max(K)),-1,dtype=np.int16)
    unit_prices=np.asarray([1000//k for m in MARKETS for st in STYLES for k in K],
                           dtype=np.int16)
    act_market=np.asarray([m for m in range(6) for st in STYLES for k in K],
                            dtype=np.int8)
    act_style=np.asarray([st for m in range(6) for st in range(4) for k in K],
                            dtype=np.int8)
    act_count=np.asarray([k for m in MARKETS for st in STYLES for k in K],
                            dtype=np.int8)
    slotranks=np.asarray([tuple(s)+(-1,)*(3-len(s)) for s in slots],dtype=np.int16)
    for i,r in enumerate(races):
        horses=r["horses"]
        odds=np.asarray([x[1] for x in horses[:10]],dtype=np.float64)
        safe=np.maximum(odds,1.0)
        p=(1/safe);p=p/p.sum()
        lw=np.log(np.maximum(p,1e-12))
        ctx=np.asarray([r["venue"]-1,(int(r["month"][4:])-1)//3,
                        (r["raceNo"]-1)//4,len(horses),
                        np.log(safe[0]),np.log(safe[1]/safe[0]),
                        np.log(safe[4]/safe[0]),
                        np.log(safe[9]/safe[0])],dtype=np.float32)
        for m,positions in enumerate(slices):
            combo=slotranks[positions]
            active=(combo>=0)
            rank=np.maximum(combo,0)
            kactive=np.maximum(np.sum(active,axis=1),1)
            logprior=np.sum(lw[rank]*active,axis=1)
            maxrank=np.max(np.where(active,rank,0),axis=1)
            meanrank=np.sum(rank*active,axis=1)/kactive
            rankspread=maxrank-np.min(np.where(active,rank,99),axis=1)
            first=rank[:,0].astype(np.float64)
            # Each nomination style is a DIFFERENT real buyable-ticket
            # formation. No payout or finishing position enters this stage.
            s0=logprior
            s1=logprior+.35*meanrank+.1*rankspread
            s2=logprior+.7*maxrank-.16*first
            s3=logprior+.62*first+.1*rankspread
            for style,sc in enumerate((s0,s1,s2,s3)):
                order=np.argsort(-sc,kind="stable")
                for z,k in enumerate(K):
                    j=(m*len(STYLES)+style)*len(K)+z
                    selected=positions[order[:k]]
                    ticket_ids[i,j,:k]=selected
                    # Actual paid money per 100 yen spent: k tickets each
                    # 1000/k yen; 1000 total. No fractional cash labels.
                    paid_jpy=int(np.sum(cash[i,selected],dtype=np.int64)*(1000//k)//100)
                    unit_cash[i,j]=paid_jpy/10.0
                    metadata[i,j,:8]=ctx
                    metadata[i,j,8]=m
                    metadata[i,j,9]=style
                    metadata[i,j,10]=np.log2(k)
                    metadata[i,j,11]=np.mean(maxrank[order[:k]])
                    metadata[i,j,12]=np.mean(meanrank[order[:k]])
                    metadata[i,j,13]=np.mean(sc[order[:k]])
                    metadata[i,j,14]=float(np.mean(np.exp(logprior[order[:k]])))
                    metadata[i,j,15]=float(np.mean(rankspread[order[:k]]))
        if i>0 and i%5000==0:
            print("DIRECT_ACTION_CASH_PREPARED",i,flush=True)
    if np.any(unit_cash<0) or np.any(ticket_ids[:,:,0]<0):
        raise RuntimeError("ACTIONS_INCOMPLETE")
    # Proof that action paid labels exactly reconcile to raw 100-yen
    # settled combination payouts, for deterministic sampled race/actions.
    for i,j in ((0,0),(0,A-1),(n//2,A//2),(n-1,A-1)):
        chosen=ticket_ids[i,j,:int(act_count[j])]
        actual=int(np.sum(cash[i,chosen])*(1000//int(act_count[j]))//100)
        if abs(unit_cash[i,j]*10-actual)>.1:
            raise RuntimeError("ACTUAL_PAID_YEN_NOT_RECONCILED")
    return metadata,unit_cash,ticket_ids,act_market,act_style,act_count
def learn(context,unitcash,years,train_years):
    n=len(years);act=A
    train_ids=np.flatnonzero(np.isin(years,train_years))
    if len(train_ids)<13000:raise RuntimeError("NOT_ENOUGH_TRAINING_RACES")
    y=unitcash[train_ids].reshape(-1)
    rng=np.random.default_rng(RAND_SEED)
    keep=(y>0)|(rng.random(y.size)<.18)
    xx=context[train_ids].reshape(-1,16)[keep]
    yy=y[keep]
    if len(xx)<130000 or np.count_nonzero(yy)<1000:
        raise RuntimeError("NOT_ENOUGH_ACTION_LABELS")
    sample_weight=np.where(yy>0,1.,1/.18).astype(np.float32)
    base=dict(n_estimators=160,num_leaves=15,learning_rate=.06,
        max_depth=6,min_child_samples=230,reg_lambda=25.,reg_alpha=.2,
        colsample_bytree=.85,random_state=RAND_SEED,n_jobs=3,verbosity=-1)
    risk=LGBMRegressor(objective="tweedie",tweedie_variance_power=1.4,**base)
    risk.fit(xx,np.maximum(yy,0)/100.,sample_weight=sample_weight)
    paid=LGBMClassifier(objective="binary",**base)
    paid.fit(xx,(yy>0).astype(np.int8),sample_weight=sample_weight)
    return risk,paid,dict(races=int(len(train_ids)),cashActions=int(len(xx)),
                           moneyPositiveActions=int(np.count_nonzero(yy)))
def infer(model,context,years,year):
    ix=np.flatnonzero(years==year)
    x=context[ix].reshape(-1,16)
    a,b,_=model;score=np.zeros((len(x),2),dtype=np.float32)
    for k in range(0,len(x),200000):
        z=x[k:k+200000]
        score[k:k+len(z),0]=a.predict(z).astype(np.float32)
        score[k:k+len(z),1]=b.predict_proba(z)[:,1].astype(np.float32)
    return ix,score.reshape(len(ix),A,2)
def racegroups(races,ix):
    g=collections.defaultdict(list)
    for j,i in enumerate(ix):
        r=races[int(i)]
        g[(r["day"],r["venue"])].append(j)
    if not g or any(len(v)<5 for v in g.values()):
        raise RuntimeError("COMPLETE_5R_VENUE_DAYS_REQUIRED")
    return [np.asarray(x,dtype=np.int32) for x in g.values()]
def decisions(races,unitcash,ix,preds,action_market,slate,hitpower,market_prior,entropy,ledger=False):
    n=len(ix)
    p=np.maximum(preds[:,:,1],1e-8)
    predicted=np.maximum(preds[:,:,0],1e-8)
    s=predicted*p**hitpower
    # Mild equity-distribution bias toward simple/high-hit markets, also
    # decided before seeing ANY 2022 / test payout.
    for m in range(6):
        s[:,action_market==m]*=np.exp(-market_prior*m)
    top_ix=np.zeros((n,6),dtype=np.int16);top_s=np.zeros((n,6),dtype=np.float64)
    for m in range(6):
        a=np.flatnonzero(action_market==m)
        j=np.argmax(s[:,a],axis=1)
        top_ix[:,m]=a[j]
        top_s[:,m]=s[np.arange(n),a[j]]
    # Confidence in 2 distinct markets penalizes policy concentration.
    a=np.argmax(top_s,axis=1)
    other=top_s.copy();other[np.arange(n),a]=-np.inf
    b=np.argmax(other,axis=1)
    if np.any(a==b):raise RuntimeError("MARKET_DIVERSITY_BROKEN")
    selection_score=(1-entropy)*top_s[np.arange(n),a]+entropy*top_s[np.arange(n),b]
    cash=unitcash[ix]
    returns=(cash[np.arange(n),top_ix[np.arange(n),a]]+
              cash[np.arange(n),top_ix[np.arange(n),b]])*10
    grp=racegroups(races,ix)
    selected=np.concatenate([np.asarray(sorted(g.tolist(),key=lambda i:(-selection_score[i],i))[:slate],dtype=np.int32) for g in grp])
    if not ledger:return np.rint(returns[selected]).astype(np.int64),None
    rows=[]
    for j in selected:
        r=races[int(ix[j])]
        rows.append(dict(year=int(r["month"][:4]),raceId=r["id"],day=r["day"],
            venue=r["venue"],raceNo=r["raceNo"],action1=int(top_ix[j,a[j]]),
            action2=int(top_ix[j,b[j]]),market1=MARKETS[int(a[j])],
            market2=MARKETS[int(b[j])],stake1Yen=1000,stake2Yen=1000,
            paidYen=int(round(float(returns[j])))))
    return np.rint(returns[selected]).astype(np.int64),rows
def main():
    if "--self-test" in sys.argv:
        assert len(MARKETS)==6 and A==96
        assert K==(1,2,5,10) and all(1000%k==0 for k in K)
        assert not eligible(dict(races=500,roiPct=400,minusLargestRaceRoiPct=199,hitRacePct=80))
        assert eligible(dict(races=500,roiPct=215,minusLargestRaceRoiPct=200,hitRacePct=20))
        print("DIRECT_ACTION_MONEY_FORMATION_UNITTEST_OK");return
    t=time.monotonic()
    races,cash,years,slots,slices=universe()
    feat,labels,tickets,act_market,act_style,act_k=make_actions(races,cash,slots,slices)
    print("REAL_CASH_ACTION_DATASET",json.dumps(dict(races=len(races),
       markets=6,formationsPerMarket=16,disjointMarketsRequired=2,
       actionsPerRace=A,examples=int(labels.size),moneyMeasured=True,
       exactTenRunnerTicketIdentifiers=True,archiveOfficialT15=False)),flush=True)
    model=learn(feat,labels,years,CASH_TRAIN)
    ix,pred=infer(model,feat,years,CASH_SELECT)
    selected=None;accepted=0;tested=0
    prior=(0.,.05,.12,.25,.5)
    entropy_weight=(0.,.25,.6,1.)
    hit_power=(0.,.25,.6,1.)
    slates=PER_DAY
    for pr in prior:
      for ew in entropy_weight:
        for hp in hit_power:
          for k in slates:
            returns,_=decisions(races,labels,ix,pred,act_market,k,hp,pr,ew)
            actual=metrics(returns);tested+=1
            if eligible(actual):
              accepted+=1
              policy=dict(marketDiversificationPenalty=pr,
                secondMarketWeight=ew,paidEventWeight=hp,
                racesPerVenueDay=k,validationMoney=actual)
              if selected is None or (actual["minusLargestRaceRoiPct"]>
                  selected["validationMoney"]["minusLargestRaceRoiPct"]):
                 selected=policy
    report=dict(status="NO_ADOPTABLE_MODEL",productionModified=False,
       architecture="full-10-runner whole-formation direct cash action learner",
       originalRawTicketCombinations=int(cash.size),
       candidateActionChoices=int(labels.size),training=model[2],
       trained2017to2021=True,policySelection2022Only=True,
       sourceOfficialJraT15=False,thirdPartyPayoutsReconciled=False,
       realPurchaseVolumeNotAsserted=True,coverageAfter2026April=False,
       policiesChecked=tested,policiesQualified=accepted,selected=selected)
    if selected:
       del model
       future=learn(feat,labels,years,tuple(range(2017,2023)))
       yr={};allrows=[]
       for y in CASH_TEST:
          v,prd=infer(future,feat,years,y)
          ret,ledger=decisions(races,labels,v,prd,act_market,
             selected["racesPerVenueDay"],selected["paidEventWeight"],
             selected["marketDiversificationPenalty"],
             selected["secondMarketWeight"],ledger=True)
          yr[str(y)]=metrics(ret);allrows+=ledger
          print("FULL_TEN_ACTION_FORWARD_CASH",json.dumps(dict(year=y,actual=yr[str(y)])),flush=True)
       agg=metrics([x["paidYen"] for x in allrows])
       report["forward"]=yr;report["aggregate"]=agg
       passall=eligible(agg) and all(
         m["races"]>=30 and m["roiPct"]>=200 and
         m["minusLargestRaceRoiPct"]>=200 and m["hitRacePct"]>=20
         for m in yr.values())
       if passall:report["status"]="HISTORICAL_NUMERICAL_CANDIDATE_ONLY_OFFICIAL_T15_UNPROVEN"
    report["seconds"]=round(time.monotonic()-t,2)
    OUT.parent.mkdir(exist_ok=True,parents=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("DIRECT_ACTION_CASH_ACCEPTANCE",json.dumps(dict(
       status=report["status"],actualMoneyPolicyCount=tested,
       qualifying2022=accepted,
       originalTicketCombinations=int(cash.size),
       elapsedSeconds=report["seconds"],mainUnchanged=True)),flush=True)
if __name__=="__main__":main()
