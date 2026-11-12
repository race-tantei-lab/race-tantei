#!/usr/bin/env python3
"""NEW CASH-FIRST RESEARCH: predict paid yen directly, not winners.

A cash-conditioned candidate policy is trained ONLY on historical JRA settled
ticket yen. It is NEVER a deployable 'model' unless the whole fixed out-of-time
ledger meets 200% ROI, minus-largest-race 200%, hit >=20%, venue-day 3-5 races,
and verified official T-15 odds & official settlement are subsequently proven.

Source currently is a third-party payout mirror with final WIN odds. Never
call this prospective JRA T-15 betting or live ROI200.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import csv,importlib.util,json,math,sys,time
import numpy as np
from lightgbm import LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-direct-paid-yen-regime-search.json"
BETS=ROOT/"analysis-results/nov2026-direct-paid-yen-frozen-test-bets.csv"
FIELDS=("market","rankMin","rankMax","rankSum","rankGap","rankFirst",
        "rankSecond","favCount","oddsGeom","oddsSpread","horseAge",
        "draw","horseWeight","favOdds","favGap","venue","fieldSize",
        "raceBand","quarter")
STEPS=(((0,7),(7,28),(28,49),(49,91),(91,126),(126,336)))
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
SEED=20261112
CAPS=(20000.,60000.,180000.)
MODES=("top_all_markets","base_win_or_wide_plus_overlay","two_robust_nonwin_markets")
TRAIN=tuple(range(2017,2022))
PSEUDO=2022
OOS=tuple(range(2023,2027))
NEGATIVE_KEEP=0.045

def get_module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_SHARED_CASH_SOURCE:"+path)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def indices_top7(src):
    from itertools import combinations,permutations
    slots,markets=src.fixed_template()
    dictionary={(int(markets[i]),tuple(slots[i])):i for i in range(len(slots))}
    rows=[]
    for m in range(6):
        if m==0:items=[(i,) for i in range(7)]
        elif m in (1,2):items=list(combinations(range(7),2))
        elif m==3:items=list(permutations(range(7),2))
        elif m==4:items=list(combinations(range(7),3))
        else:items=list(permutations(range(7),3))
        rows.extend(dictionary[(m,t)] for t in items)
    if len(rows)!=336 or len(set(rows))!=336:raise RuntimeError("BAD_336_TICKET_PROJECTION")
    return np.array(rows,dtype=np.int32)

def source_data():
    src=get_module("scripts/research-nov2026-decade-roi-first-sixmarkets.py","sixpaid_source")
    pay=get_module("scripts/research-nov2026-sixmarket-real-paid-cash.py","sixpaid_parse")
    allraces=src.read_all_races(pay.parse_payments)
    if src.CACHE.exists() and src.RACE_CACHE.exists():
        saved=json.loads(src.RACE_CACHE.read_text(encoding="utf-8"))["races"]
        if len(saved)!=len(allraces) or any(a["id"]!=b["id"] for a,b in zip(saved,allraces)):
            raise RuntimeError("HISTORIC_SIX_MARKET_CASH_CACHE_RACE_ORDER_INVALID")
    else:
        src.CACHE.parent.mkdir(parents=True,exist_ok=True)
        src.full_features(allraces)
    proj=indices_top7(src)
    keep=np.flatnonzero(np.array([int(r["month"][:4])>=2017 for r in allraces]))
    races=[allraces[int(i)] for i in keep]
    n=len(races)
    # Cash data is the supervised TARGET only. No current/test payout is
    # part of ANY predictor feature, racing-time decision, or ticket ranking.
    with np.load(src.CACHE,allow_pickle=False) as z:
        paid=z["payout"][keep[:,None],proj[None,:]].astype(np.int32)
        if paid.shape!=(n,336):raise RuntimeError("FAILED_RACE_TICKET_MATRIX")
        X=np.empty((n*336,len(FIELDS)),dtype=np.float32)
        for j,field in enumerate(FIELDS):
            a=z[field][keep[:,None],proj[None,:]]
            X[:,j]=a.ravel().astype(np.float32)
    year=np.array([int(r["month"][:4]) for r in races],dtype=np.int16)
    print("DIRECT_CASH_SUPERVISED_UNIVERSE",json.dumps({
        "races":n,"candidateTickets":int(paid.size),
        "years":dict(sorted(Counter(map(int,year)).items())),
        "nonzeroCashTickets":int((paid>0).sum()),
        "featuresAllPreOutcome":True,"sixRealCashMarkets":True,
        "officialT15Odds":False,"officialPayoutReconciled":False
    },ensure_ascii=False),flush=True)
    return races,X,paid,year

def money(rows):
    stake=200*len(rows)
    paid=sum(r["paidYen"] for r in rows)
    maxrace=max((r["paidYen"] for r in rows),default=0)
    hits=sum(r["paidYen"]>0 for r in rows)
    return {"races":len(rows),"tickets":2*len(rows),
            "stakeYen":stake,"paidYen":paid,
            "profitYen":paid-stake,
            "roiPct":round(100*paid/stake,4) if stake else None,
            "minusMaxRaceRoiPct":round(100*(paid-maxrace)/stake,4) if stake else None,
            "maxRacePaidYen":maxrace,"hitRaces":hits,
            "hitRacePct":round(100*hits/len(rows),4) if rows else None}

def train_cash_estimator(X,paid,year,training,cap):
    n=paid.shape[0]
    train_races=np.flatnonzero(np.isin(year,training))
    if not len(train_races):raise RuntimeError("NO_TRAIN_YEARS")
    # Keep ALL paid tickets; zero-payout controls uniformly sampled,
    # with inverse-sampling weight so the cash expectation is unbiased.
    first=train_races[:,None]*336+np.arange(336,dtype=np.int32)[None,:]
    tr=first.ravel()
    label=paid.ravel()[tr]
    rg=np.random.default_rng(SEED+int(cap))
    select=(label>0)|(rg.random(len(tr))<NEGATIVE_KEEP)
    tr=tr[select];v=label[select]
    weight=np.where(v>0,1.,1./NEGATIVE_KEEP).astype(np.float32)
    # Capped training PAYOUT protects against maximizing one jackpot race.
    cash_target=np.minimum(v.astype(np.float32),cap)/100.
    est=LGBMRegressor(objective="tweedie",tweedie_variance_power=1.35,
       n_estimators=160,num_leaves=15,max_depth=6,
       min_child_samples=550,learning_rate=0.055,reg_lambda=30.,
       colsample_bytree=.88,subsample=1.,n_jobs=3,verbosity=-1,
       random_state=SEED)
    est.fit(X[tr],cash_target,sample_weight=weight)
    return est,{"trainingRaces":len(train_races),"sampleTickets":len(tr),
                "allTrainingPaidTickets":int((label>0).sum()),
                "payoutCapYen":cap,
                "oversamplingCorrection":True}

def choose(races,paid,year,score,target,mode):
    ix=np.flatnonzero(year==target)
    if not len(ix):return [],{}
    scores=score.reshape(len(ix),336)
    actual=paid[ix]
    groups=defaultdict(list)
    for k,i in enumerate(ix):
        r=races[int(i)]
        best=[]
        for m,(a,b) in enumerate(STEPS):
            v=scores[k,a:b]
            j=int(np.argmax(v))+a
            best.append((float(scores[k,j]),m,j))
        if mode=="top_all_markets":
            ranked=sorted(best,key=lambda z:(-z[0],z[1]))[:2]
        elif mode=="base_win_or_wide_plus_overlay":
            # More than 20% hit-rate requires stable low-paying base hits.
            a=max((z for z in best if z[1] in (0,1)),key=lambda z:(z[0],-z[1]))
            b=max((z for z in best if z[1] not in (0,1)),key=lambda z:(z[0],-z[1]))
            ranked=[a,b]
        elif mode=="two_robust_nonwin_markets":
            ranked=sorted((z for z in best if z[1]!=0),key=lambda z:(-z[0],z[1]))[:2]
        else:raise RuntimeError("UNKNOWN_CHOICE_MODE")
        if len(set(z[1] for z in ranked))!=2:
            raise RuntimeError("REPEATED_BET_MARKET")
        pred=sum(z[0] for z in ranked)
        ticket1,ticket2=ranked[0][2],ranked[1][2]
        entry={
          "year":target,"raceId":r["id"],"day":r["day"],
          "venue":r["venue"],"raceNo":r["raceNo"],"choiceMode":mode,
          "market1":MARKETS[ranked[0][1]],"market2":MARKETS[ranked[1][1]],
          "ticket1":int(ticket1),"ticket2":int(ticket2),
          "scorePreRace":round(pred,4),
          "paidYen":int(actual[k,ticket1])+int(actual[k,ticket2])}
        groups[(r["day"],r["venue"])].append(entry)
    result=[]
    for d,rows in groups.items():
        rows.sort(key=lambda r:(-r["scorePreRace"],r["raceId"]))
        result.extend(rows[:5])
    coverage={
      "candidateProgramDays":len(groups),
      "fiveRProgramDays":sum(len(v)>=5 for v in groups.values()),
      "threeRProgramDays":sum(len(v)>=3 for v in groups.values()),
      "selectedRaces":len(result),
      "allJraProgramDaysVerified":False}
    return result,coverage

def score_for(est,X,year,target):
    idx=np.flatnonzero(year==target)
    block=X[(idx[:,None]*336+np.arange(336)[None,:]).ravel()]
    yhat=est.predict(block).astype(np.float32)
    if not np.all(np.isfinite(yhat)):raise RuntimeError("CASH_PREDICTION_NONFINITE")
    if np.any(yhat<0):raise RuntimeError("CASH_PREDICTION_NEGATIVE")
    return yhat

def main():
    if "--self-test" in sys.argv:
        assert len(STEPS)==6 and sum(b-a for a,b in STEPS)==336
        assert money([{"paidYen":300},{"paidYen":100}])["minusMaxRaceRoiPct"]==25.
        assert len(FIELDS)==19
        print("DIRECT_PAID_YEN_POLICY_SELFTEST_OK",flush=True);return
    start=time.monotonic()
    races,X,paid,year=source_data()
    # Candidate choices are decided by 2022 ONLY. 2023 onward is held
    # out of ALL hyperparameter choice and ALL training/selection.
    pseudo={}
    for cap in CAPS:
        est,metadata=train_cash_estimator(X,paid,year,TRAIN,cap)
        predictions=score_for(est,X,year,PSEUDO)
        for mode in MODES:
            decisions,coverage=choose(races,paid,year,predictions,PSEUDO,mode)
            cash=money(decisions)
            # Conservative aggregate ROI is primary; avoid win-only objectives.
            # Empty or thin portfolios always fail. Per-year minimum 20% hits
            # is counted but NOT weighted ahead of cash.
            sample_support=(coverage["fiveRProgramDays"]/max(coverage["candidateProgramDays"],1))
            cash_score=((cash["minusMaxRaceRoiPct"] or 0)-100)*sample_support
            pseudo[(cap,mode)]={"trainingMetadata":metadata,
                "cash":cash,"coverage":coverage,"score":round(cash_score,5)}
        print("DIRECT_CASH_PSEUDO_2022",json.dumps({
          "capYen":cap,"modes":{m:pseudo[(cap,m)]["cash"] for m in MODES}
        },ensure_ascii=False),flush=True)
    winner=max(pseudo,key=lambda key:(pseudo[key]["score"],-key[0],key[1]))
    cap,mode=winner
    # Fit again using pre-2023 cash, completely blind to later outcome.
    est,finaltrain=train_cash_estimator(X,paid,year,tuple(range(2017,2023)),cap)
    yearsets={};allrows=[];coverage={}
    for y in OOS:
        predictions=score_for(est,X,year,y)
        picks,counts=choose(races,paid,year,predictions,y,mode)
        yearsets[str(y)]=money(picks)
        coverage[str(y)]=counts
        allrows.extend(picks)
        print("DIRECT_CASH_FORWARD_YEAR",json.dumps({
            "year":y,"metrics":yearsets[str(y)],"coverage":counts
        },ensure_ascii=False),flush=True)
    combined=money(allrows)
    all200=(combined["minusMaxRaceRoiPct"] is not None
            and combined["minusMaxRaceRoiPct"]>=200
            and combined["hitRacePct"] is not None
            and combined["hitRacePct"]>=20
            and all(yearsets[str(y)]["minusMaxRaceRoiPct"] is not None
                    and yearsets[str(y)]["minusMaxRaceRoiPct"]>=200
                    for y in OOS))
    report={"researchOnly":True,
      "isAdoptedModel":False,"retrospectiveCriteriaReached":bool(all200),
      "notOfficialT15":True,"notOfficialPayoutReconciled":True,
      "2025And2026HavePriorResearchExposure":True,
      "fixedRuleSelectionBasedOnlyOn2017To2022":True,
      "payoutOnlyModelTargetNotWinnerOrLogloss":True,
      "negativeTicketSamplingInverseWeighted":True,
      "candidateCashMethods":len(CAPS)*len(MODES),
      "selectionMethod":"2022 cash minus-max ROI with 5R coverage",
      "trainYears2017To2022":True,
      "winnerPreselectedUsing2022Only":{"capYen":cap,"mode":mode},
      "validation2022AllPseudoModels":
       {str(c)+"_"+m:pseudo[(c,m)] for c,m in pseudo},
      "fitParameters":finaltrain,
      "year":yearsets,"combined":combined,"coverage":coverage,
      "allFourForwardYears200Robust":all200,
      "seconds":round(time.monotonic()-start,3),
      "followupRequired":"independent official JRA payout and official pre-race T15 odds / 2026 Aug-Nov"};
    OUT.parent.mkdir(exist_ok=True,parents=True)
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    fields=("year","raceId","day","venue","raceNo","choiceMode",
            "market1","market2","ticket1","ticket2",
            "scorePreRace","paidYen")
    with BETS.open("w",encoding="utf8",newline="") as handle:
        csvout=csv.DictWriter(handle,fieldnames=fields)
        csvout.writeheader();csvout.writerows(allrows)
    print("DIRECT_CASH_YEN_FINAL",json.dumps({
      "preSelectedCap":cap,"preSelectedMode":mode,
      "forwardCash":combined,"year":yearsets,
      "retrospectiveCandidateCriteriaReached":all200,
      "seconds":report["seconds"],
      "researchOnly":True,"officialT15Verified":False
    },ensure_ascii=False),flush=True)

if __name__=="__main__":main()
