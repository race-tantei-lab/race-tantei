#!/usr/bin/env python3
"""Independent cash-first hurdle wager generator on historic JRA cash returns.

Cross-time trial (NOT an adopted model): TRAIN 2017-2021 -> select two-ticket
monetary policy strictly on 2022 -> TRAIN 2017-2022 -> TEST 2023-2026 Apr.
Generator is learnt from ALL 336 ticket candidates (7 fixed odds-ranked horses,
six market types), not fitted to/filtered through old completed-model tickets.
Predict P(ticket payout>0) * E(payout | ticket paid) with a robust conditional
cash regressor. Every rule is ranked by realized cash, robust minus-max cash,
and hit-rate floor. Paid amounts never enter candidate features.
Historical final win odds are not official T-15 market snapshots; 2026 H2
post-live is not covered, so no production promotion is authorized.
"""
from __future__ import annotations
import collections,csv,importlib.util,json,math,os,sys,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-hurdle-direct-sixmarket-cash.json"
BETS=ROOT/"analysis-results/nov2026-hurdle-direct-sixmarket-cash-bets.csv"
SEED=20261113
TRAIN=(2017,2018,2019,2020,2021)
SELECT_YEAR=2022
FINAL_TRAIN=tuple(range(2017,2023))
OOS=(2023,2024,2025,2026)
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
MARKET_MODES=("all6","base_wide_or_win","not_trifecta","two_no_win")
GAMMAS=(0.0,0.5,1.,2.,3.)
BETAS=(0.65,1.,1.35)
SLATES=(3,4,5)
SPLITS=((1000,1000),(1500,500),(1900,100))
NEG_SAMPLE=.045

def import_script(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("REQUIRED_HISTORIC_SOURCE_MISSING")
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def source():
    original=import_script("nov2026_hurdle_cash_source",
        "scripts/research-nov2026-direct-paid-yen-regime-search.py")
    races,X,paid,years=original.source_data()
    if len(races)!=len(years) or paid.shape!=(len(races),336):
        raise RuntimeError("MISALIGNED_HISTORICAL_CASH_LABELS")
    if np.any((years==2026)&np.array([r["month"] for r in races])>="202605")):
        raise RuntimeError("2026_EARLY_MONTH_BOUNDARY_DRIFT")
    return races,X,paid,years

def cash(rows):
    n=len(rows)
    stake=2000*n
    paid=int(sum(int(row["paidYen"]) for row in rows))
    mx=max((int(row["paidYen"]) for row in rows),default=0)
    hits=sum(int(row["paidYen"]>0) for row in rows)
    return {"races":n,"stakeYen":stake,"paidYen":paid,
        "roiPct":round(100*paid/stake,5) if n else None,
        "minusMaxRaceRoiPct":round(100*(paid-mx)/stake,5) if n else None,
        "hitRacePct":round(100*hits/n,5) if n else None,
        "biggestRacePaidYen":mx}

def fit_hurdle(X,paid,years,trainyears):
    rng=np.random.default_rng(SEED)
    races=np.flatnonzero(np.isin(years,trainyears))
    if len(races)<8000:raise RuntimeError("NOT_ENOUGH_TRAIN_RACES")
    sampled_indices=(races[:,None]*336+np.arange(336)[None,:]).ravel()
    cash_train=paid.ravel()[sampled_indices]
    pos=cash_train>0
    keep=pos|(rng.random(len(sampled_indices))<NEG_SAMPLE)
    selected=sampled_indices[keep]
    label=pos[keep].astype(np.int8)
    weights=np.where(label>0,1.,1./NEG_SAMPLE).astype(np.float32)
    # Each stake is a distinct ticket, and the negative subsample is corrected
    # to represent the original proportion of zero-return tickets.
    common=dict(n_estimators=160,learning_rate=.045,num_leaves=15,max_depth=6,
       min_child_samples=350,reg_alpha=1.,reg_lambda=30.,
       colsample_bytree=.88,random_state=SEED,n_jobs=3,verbosity=-1)
    win=LGBMClassifier(objective="binary",**common)
    win.fit(X[selected],label,sample_weight=weights)
    # Regression only on winning tickets. Target is real payout per ¥100,
    # capped at per-market 95th percentile to de-emphasize one lucky jackpot.
    positives=sampled_indices[pos]
    raw_y=paid.ravel()[positives].astype(np.float64)
    market=np.rint(X[positives,0:6]).astype(np.int8).argmax(axis=1)
    clipped=raw_y.copy()
    caps={}
    for i,typ in enumerate(MARKETS):
        ismarket=market==i
        if ismarket.sum()<80:raise RuntimeError("POSITIVE_PAYOUT_MARKET_TOO_THIN:"+typ)
        cap=float(np.quantile(raw_y[ismarket],.95))
        clipped[ismarket]=np.minimum(raw_y[ismarket],cap)
        caps[typ]=round(cap,2)
    # Robust conditional payout yen / 100yen stake.
    severity=LGBMRegressor(objective="poisson",**common)
    # Market type normalization prevents wide/trifecta from dominating due
    # to larger combinatorial candidate set counts.
    freq=np.bincount(market,minlength=6)
    positive_weight=np.asarray([1./math.sqrt(float(freq[int(k)])) for k in market],
                               dtype=np.float32)
    positive_weight*=len(positive_weight)/positive_weight.sum()
    severity.fit(X[positives],np.maximum(.01,clipped/100),
                 sample_weight=positive_weight)
    return win,severity,{"trainYears":list(trainyears),"trainRaces":len(races),
           "observedPositiveTickets":int(pos.sum()),
           "sampledZeroAndPaidTickets":len(selected),"payoutCapsYen":caps,
           "outputTargets":"ticket-paid-binary + capped-conditional-paid-money",
           "selectionCashLeakageIntoFeatures":False}

def predict(win,severity,X,years,year):
    i=np.flatnonzero(years==year)
    idx=(i[:,None]*336+np.arange(336)[None,:]).ravel()
    binary=win.predict_proba(X[idx])[:,1].astype(np.float32).reshape(-1,336)
    conditional=severity.predict(X[idx]).astype(np.float32).reshape(-1,336)
    if not np.all(np.isfinite(binary)) or not np.all(np.isfinite(conditional)):
        raise RuntimeError("UNSAFE_INFERENCE_VALUE")
    expected=np.clip(binary*conditional,1e-9,1e6)
    return i,np.clip(binary,1e-8,1.),expected

def pick(races,paid,race_ix,likelihood,expected,gamma,beta,mode,slate,split):
    by_day=collections.defaultdict(list)
    for k,i in enumerate(race_ix):
        r=races[int(i)]
        scores=(np.maximum(expected[k],1e-6)**beta) * \
               (np.maximum(likelihood[k],1e-8)**gamma)
        by_market=[]
        for m,(a,b) in enumerate(BOUNDS):
            idx=a+int(np.argmax(scores[a:b]))
            by_market.append((float(scores[idx]),m,idx))
        available=sorted(by_market,key=lambda x:(-x[0],x[1]))
        if mode=="all6":t1,t2=available[:2]
        elif mode=="base_wide_or_win":
            t1=max((x for x in by_market if x[1] in (0,1)),key=lambda x:(x[0],-x[1]))
            t2=max((x for x in by_market if x[1] not in (0,1)),key=lambda x:(x[0],-x[1]))
        elif mode=="not_trifecta":t1,t2=sorted((x for x in by_market if x[1]!=5),key=lambda x:(-x[0],x[1]))[:2]
        elif mode=="two_no_win":t1,t2=sorted((x for x in by_market if x[1]!=0),key=lambda x:(-x[0],x[1]))[:2]
        else:raise RuntimeError("INVALID_MARKET_MODE")
        if t1[1]==t2[1]:raise RuntimeError("NON_DISTINCT_MARKETS")
        # First gets the weight according to its cash-hurdle signal.
        # Selection is a deterministic PRE-RESULT stake plan.
        strength=t1[0]+t2[0]
        if mode=="base_wide_or_win":
            # Pair selection itself uses positive cash-hurdle signals.
            strength=(t1[0]+t2[0])
        p1=int(paid[int(i),t1[2]])*(split[0]//100)
        p2=int(paid[int(i),t2[2]])*(split[1]//100)
        by_day[r["day"]].append((strength,r["id"],r["month"],r["venue"],
             t1[1],t1[2],t2[1],t2[2],int(p1+p2),r["raceNo"]))
    ledger=[]
    complete=0
    incomplete=0
    for d,group in sorted(by_day.items()):
        if len(group)<3:
            incomplete+=1;continue
        complete+=1
        for sig,rid,month,venue,m1,k1,m2,k2,returned,rn in sorted(
            group,key=lambda x:(-x[0],x[1]))[:slate]:
            ledger.append(dict(raceId=rid,day=d,month=month,venue=venue,
                raceNo=rn,market1=MARKETS[m1],market2=MARKETS[m2],
                templateTicket1=k1,templateTicket2=k2,
                stake1Yen=split[0],stake2Yen=split[1],
                cashScore=round(float(sig),6),paidYen=returned))
    return ledger,{"eligibleVenueDays":len(by_day),
         "threePlusVenueDays":complete,"incompleteVenueDays":incomplete,
         "selectedRaces":len(ledger)}

def main():
    if "--self-test" in sys.argv:
        assert sum(b-a for a,b in BOUNDS)==336
        assert len(MARKETS)==6
        assert cash([{"paidYen":5000},{"paidYen":1000}])["minusMaxRaceRoiPct"]==25
        assert all(sum(split)==2000 and min(split)>=100 for split in SPLITS)
        assert len(MARKET_MODES)*len(GAMMAS)*len(BETAS)*len(SLATES)*len(SPLITS)==540
        print("DIRECT_HURDLE_TWO_MARKET_CASH_SELFTEST_OK",flush=True);return
    tic=time.monotonic()
    races,X,paid,year=source()
    print("HURDLE_CASH_SOURCE",json.dumps({"races":len(races),
      "candidateTickets":paid.size,
      "yearCounts":dict(sorted(collections.Counter(map(int,year)).items())),
      "lastPayoutMonth":"202604","notActualT15":True},ensure_ascii=False),flush=True)
    win,sev,train=fit_hurdle(X,paid,year,TRAIN)
    vi, vp, ve=predict(win,sev,X,year,SELECT_YEAR)
    # 2022 ONLY: all 540 ticket-type/race-choice/staking recipes.
    validation=[]
    for gamma in GAMMAS:
      for beta in BETAS:
       for mode in MARKET_MODES:
        for slate in SLATES:
         for split in SPLITS:
            cfg=(gamma,beta,mode,slate,split)
            ledger,coverage=pick(races,paid,vi,vp,ve,*cfg)
            a=cash(ledger)
            if not a["races"]:continue
            if coverage["threePlusVenueDays"]<120:continue
            # Cash ROI primary, hit is an adoption hard constraint,
            # no logloss / horse-accuracy optimization.
            hard=(a["hitRacePct"]>=20 and a["minusMaxRaceRoiPct"]>=200)
            objective=(int(hard),int(a["hitRacePct"]>=20),
                       a["minusMaxRaceRoiPct"],a["roiPct"])
            validation.append((objective,cfg,a,coverage))
    if len(validation)!=540:raise RuntimeError(
        f"EXPECTED_540_VALID_POLICIES:{len(validation)}")
    validation.sort(key=lambda x:x[0],reverse=True)
    winner=validation[0]
    gamma,beta,mode,slate,split=winner[1]
    print("DIRECT_HURDLE_CASH_YEAR2022_SELECTION",json.dumps({
        "chosen":{"gamma":gamma,"beta":beta,"mode":mode,
                   "slate":slate,"split":split},
        "cash":winner[2],"coverage":winner[3],"gridCount":len(validation),
        "passing200":sum(r[2]["minusMaxRaceRoiPct"]>=200 and
                         r[2]["hitRacePct"]>=20 for r in validation),
        "top3":[{"params":str(x[1]),"money":x[2]} for x in validation[:3]]},
        ensure_ascii=False),flush=True)
    del win,sev
    win,sev,final_train=fit_hurdle(X,paid,year,FINAL_TRAIN)
    byyear={};rowsets={};allrows=[]
    for y in OOS:
        idx,prob,ev=predict(win,sev,X,year,y)
        rows,coverage=pick(races,paid,idx,prob,ev,gamma,beta,mode,slate,split)
        byyear[str(y)]={"money":cash(rows),"coverage":coverage}
        rowsets[str(y)]=rows
        allrows.extend(rows)
        print("DIRECT_HURDLE_CASH_OUT_OF_SAMPLE",json.dumps({
             "year":y,**byyear[str(y)]},ensure_ascii=False),flush=True)
    combined=cash(allrows)
    passes=(combined["minusMaxRaceRoiPct"]>=200 and combined["hitRacePct"]>=20
        and all(byyear[str(y)]["money"]["minusMaxRaceRoiPct"]>=200 and
                byyear[str(y)]["money"]["hitRacePct"]>=20 for y in OOS)
        and all(byyear[str(y)]["coverage"]["threePlusVenueDays"]>=35 for y in OOS))
    summary={
        "researchOnly":True,"adoptedModel":False,
        "retrospectiveModelQualificationMet":bool(passes),
        "model":"LightGBM payout hurdle (p_paid times conditional-capped-cash), not horse winner classifier",
        "validationYearOnly":SELECT_YEAR,
        "trainedYears":list(FINAL_TRAIN),
        "winnerChosenBeforeTesting2023":True,
        "winAccuracyOrLoglossSelectionNeverUsed":True,
        "twoDistinctBetTypes":True,
        "cashPerRaceYen":2000,
        "allRaceDayResultsUsedOnlyForAssessment":True,
        "candidateGeneratorIndependentOfPriorProductionBets":True,
        "officialOddsT15Verified":False,
        "payoutSource":"third-party GitHub monthly JRA-result CSV pinned at f552ca8628646f39b05ffdbdc3ab8734939ffd66",
        "payoutIndependentJraReconciliation":False,
        "2025And2026PriorResearchExposure":True,
        "forwardCoverageEnds":"2026-04",
        "2026AugNovNotCoveredByMirror":True,
        "selection":{"gamma":gamma,"beta":beta,"mode":mode,
           "racesPerVenueDay":slate,"splitYen":split},
        "candidateModelFrom2022Validation":winner[2],
        "trainMetadata":final_train,"validationTrials":len(validation),
        "outOfSampleYearly":byyear,"combined":combined,
        "seconds":round(time.monotonic()-tic,2),
        "productionUnchanged":True,
        "canDeployWithoutActualT15":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    with BETS.open("w",encoding="utf8",newline="") as f:
        fields=list(allrows[0]) if allrows else []
        if fields:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(allrows)
    print("DIRECT_HURDLE_FINANCIAL_RESULT",json.dumps({
        "retrospectiveQualification":passes,
        "yearly":{y:v["money"] for y,v in byyear.items()},
        "combined":combined,"selected":summary["selection"],
        "finalCrossPeriodMoney":summary["combined"],
        "elapsed":summary["seconds"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
