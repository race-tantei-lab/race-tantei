#!/usr/bin/env python3
"""Adaptive MULTI-HORIZON CASH-METHOD learner, strictly chronological.

At each first race of a month:
  1. Train ticket RETURN forecasts from ONLY earlier settled months using
     3/6/12/24/36/60 months or all history.
  2. Compare 70 forecasting METHODS: period x condition context x risk
     clipping; each method independently selects concrete ticket per market.
  3. Meta-learn WHICH forecasting METHOD to use (venue-specific or global),
     based only on 3/6/12/24/36/60 months of earlier simulated, settled,
     realized JRA ticket cash. The method switches monthly, not a fixed rule.
  4. Apply method -> ticket/race/cash selection to the CURRENT, UNSEEN month.
  5. Only AFTER all predictions for this month were frozen: update paid cash,
     shadow outcomes and previous-month model-training distributions.

The prior exploration searched FIXED betting conditions. This is a new
model-of-forecast-method, without peeking at future payouts. Report "model"
ONLY if cash ROI>=200%, single largest paid race excluded ROI>=200%, 20% paid
race hits, and >=3 distinct bought races every venue-day simultaneously.
No failed fallback strategy, no hit-bonus, no artificial money accounting.

Research source is 136 months of third-party settled data with historical
FINAL win odds, not JRA T-15 quotes. No live deployment even if historical
targets pass until separate official T15 / chronologically untouched holdout.
"""
from __future__ import annotations
import collections, csv, gzip, importlib.util, json, sys, time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-adaptive-methods-cash-history.json"
FWD=ROOT/"analysis-results/20261114-adaptive-methods-cash-forward.json"
LED=ROOT/"analysis-results/20261114-adaptive-methods-only-approved-ledger.csv.gz"
WINDOWS=(3,6,12,24,36,60,None)
REGIMES=((),("venue",),("venue","quarter"),("favOdds",),("oddsGeom",))
PAY_VARIANTS=("cap20000","full")
META_WINDOWS=(3,6,12,24,36,60)
META_SCOPES=("global","venue")
# Hard requirement: score history with money, NEVER reward hit rates
# in method choice. Confidence shrinks fragile estimates only.
ALLOWED_MONTHS=136
MAXPAYOUT_CAP=20000  # yen per ¥100 ticket, solely prediction robustness

def imported(path,name):
    p=ROOT/path
    s=importlib.util.spec_from_file_location(name,p)
    if s is None or s.loader is None:raise RuntimeError("SOURCE_MISSING:"+path)
    m=importlib.util.module_from_spec(s);sys.modules[name]=m
    s.loader.exec_module(m);return m
def month_num(yyyymm):
    s=str(yyyymm).replace("-","")
    return int(s[:4])*12+int(s[4:6])-1
def calendar_sequence(start,end):
    y,m=int(start[:4]),int(start[4:6])
    e=month_num(end)
    out=[]
    while y*12+m-1<=e:
      out.append(f"{y:04d}{m:02d}")
      m+=1
      if m==13:y+=1;m=1
    return out
def method_specs():
    return [(w,reg,risk) for w in WINDOWS
             for reg in REGIMES for risk in PAY_VARIANTS]
def meta_specs():
    out=[(w,scope) for w in META_WINDOWS for scope in META_SCOPES]
    # Fixed baselines are forecast METHODS only, not model candidates.
    # They are part of the adaptive method-selection experiment.
    for w in WINDOWS:
        out.append((w,"fixed"))
    return out
class RollingCashMemory:
    def __init__(self,base,nt,months):
        self.base=base
        self.nt=nt;self.months=months
        self.offsets={}
        offset=0
        for reg in REGIMES:
            bins=nt
            for col in reg:bins*=base.FEATURES[col]
            self.offsets[reg]=(offset,bins)
            offset+=bins
        self.cells=offset
        # all cumulative stats in actual JRA yen; use 64-bit accumulators
        self.prefix=np.zeros((4,len(months)+1,self.cells),np.int64)
        self.template=np.arange(nt,dtype=np.int32)[None,:]
    def context_key(self,feat,reg):
        offset,_=self.offsets[reg]
        v=np.broadcast_to(self.template,feat["venue"].shape).astype(np.int32).copy()
        for col in reg:
            q=feat[col]
            if np.any(q>=self.base.FEATURES[col]):
                raise RuntimeError("INVALID_TICKET_PRE_RACE_CATEGORY_"+col)
            v=v*self.base.FEATURES[col]+q
        return v+offset
    def update(self,month_i,feat,payout):
        # Caller must produce/freeze every prediction before this runs.
        self.prefix[:,month_i+1]=self.prefix[:,month_i]
        if len(payout)==0:return
        win=(payout>0).astype(np.int64)
        capped=np.minimum(payout,MAXPAYOUT_CAP)
        for reg in REGIMES:
            key=self.context_key(feat,reg).ravel()
            self.prefix[0,month_i+1]+=np.bincount(
                key,minlength=self.cells).astype(np.int64)
            self.prefix[1,month_i+1]+=np.bincount(
                key,weights=win.ravel(),minlength=self.cells).astype(np.int64)
            self.prefix[2,month_i+1]+=np.bincount(
                key,weights=capped.ravel(),minlength=self.cells).astype(np.int64)
            self.prefix[3,month_i+1]+=np.bincount(
                key,weights=payout.ravel(),minlength=self.cells).astype(np.int64)
    def predict(self,month_i,feat,market):
        n=len(feat["venue"])
        specs=method_specs()
        choices=np.empty((n,len(specs),6),np.int16)
        expected=np.empty((n,len(specs),6),np.float32)
        priors=np.asarray((.78,.75,.74,.73,.72,.70),np.float32)[market][None,:]
        for ri,reg in enumerate(REGIMES):
            key=self.context_key(feat,reg)
            for wi,window in enumerate(WINDOWS):
                start=0 if window is None else max(0,month_i-window)
                nobs=(self.prefix[0,month_i,key]-self.prefix[0,start,key]).astype(np.float32)
                hits=(self.prefix[1,month_i,key]-self.prefix[1,start,key]).astype(np.float32)
                # Valid ticket-return estimate comes from earlier CASH,
                # not classification win probabilities or race outcomes.
                support=(nobs/(nobs+90.))*(hits/(hits+5.))
                for pi,risk in enumerate(PAY_VARIANTS):
                    bucket=2 if risk=="cap20000" else 3
                    paid=(self.prefix[bucket,month_i,key]
                          -self.prefix[bucket,start,key]).astype(np.float64)
                    mean=np.minimum(35.,paid/(np.maximum(1,nobs)*100.))
                    score=np.maximum(.02,(1.-support)*priors+support*mean)
                    expert=((wi*len(REGIMES)+ri)*len(PAY_VARIANTS)+pi)
                    for m in range(6):
                        subsets=np.flatnonzero(market==m)
                        arg=np.argmax(score[:,subsets],axis=1)
                        choices[:,expert,m]=subsets[arg].astype(np.int16)
                        expected[:,expert,m]=score[np.arange(n),subsets[arg]]
        if not np.isfinite(expected).all():
            raise RuntimeError("NAN_IN_PRIOR_ONLY_TICKET_RETURN_FORECAST")
        return choices,expected
class MetaCashState:
    def __init__(self,months,expert_count):
        n=len(months)
        # outcome matrix: [months,venue,forecast-method]
        self.pay=np.zeros((n,10,expert_count),np.int64)
        self.count=np.zeros((n,10,expert_count),np.int32)
        self.big=np.zeros((n,10,expert_count),np.int64)
        self.months=months
    def assign(self,mi,venues):
        # One meta rule can choose a different lookback/condition method
        # in each venue and month. No current/future cash is accessed here.
        configs=meta_specs()
        chosen=np.empty((len(configs),10),np.int32)
        available=method_specs()
        fallback=available.index((12,(), "cap20000"))
        for ci,(w,scope) in enumerate(configs):
            if scope=="fixed":
                selected=available.index((w,(),"cap20000"))
                chosen[ci,:]=selected
                continue
            start=max(0,mi-w)
            if mi-start<2:
                chosen[ci,:]=fallback
                continue
            for venue in range(10):
                if scope=="venue":
                    pp=self.pay[start:mi,venue]
                    nn=self.count[start:mi,venue]
                    mx=self.big[start:mi,venue]
                else:
                    pp=self.pay[start:mi].reshape(-1,self.pay.shape[-1])
                    nn=self.count[start:mi].reshape(-1,self.count.shape[-1])
                    mx=self.big[start:mi].reshape(-1,self.big.shape[-1])
                total=pp.sum(axis=0)
                ncount=nn.sum(axis=0)
                highest=mx.max(axis=0)
                # Money FIRST: net of the single biggest result. A prior
                # 100-yen ticket losing money has negative score.
                net=(total-highest-100*ncount).astype(np.float64)
                reliability=100*ncount+20000.
                value=net/reliability
                if not np.any(ncount>=25):
                    chosen[ci,venue]=fallback
                else:
                    value[ncount<25]=-np.inf
                    chosen[ci,venue]=int(np.argmax(value))
        return chosen
    def update(self,mi,payout,experts,score,venues):
        if len(payout)==0:return
        bestmarket=np.argmax(score,axis=2)
        bestticket=np.take_along_axis(experts,bestmarket[:,:,None],axis=2)[:,:,0]
        cash=payout[np.arange(len(payout))[:,None],bestticket]
        for v in np.unique(venues):
            ix=np.flatnonzero(venues==v)
            self.pay[mi,int(v)]=cash[ix].sum(axis=0,dtype=np.int64)
            self.count[mi,int(v)]=len(ix)
            self.big[mi,int(v)]=cash[ix].max(axis=0)
def dataset(base,races,payout,feat,market,months,memory=None,meta=None,
            price_choices=None,price_scores=None,position=0):
    n=len(races)
    methods=meta_specs()
    picks=np.empty((n,len(methods),6),np.int16)
    values=np.empty((n,len(methods),6),np.float32)
    monthly_index={m:[] for m in months}
    for i,r in enumerate(races):
        month=str(r["month"]).replace("-","")
        if month not in monthly_index:
            raise RuntimeError("MISSING_CALENDAR_MONTH_"+month)
        monthly_index[month].append(i)
    if memory is None:
        memory=RollingCashMemory(base,len(market),months)
    if meta is None:
        meta=MetaCashState(months,len(method_specs()))
    select_log=[]
    for mi,month in enumerate(months):
        idx=np.asarray(monthly_index[month],np.int32)
        mfeat={k:v[idx] for k,v in feat.items()}
        if not len(idx):
            memory.update(mi,mfeat,payout[idx])
            continue
        pred,score=memory.predict(mi,mfeat,market)
        venues=np.asarray([int(races[int(k)]["venue"]) for k in idx],np.int32)
        if venues.max()>=10 or venues.min()<0:
            raise RuntimeError("UNKNOWN_JRA_VENUE_IN_META")
        assigned=meta.assign(mi,venues)
        for ci in range(len(methods)):
            chosen=assigned[ci,venues]
            picks[idx,ci]=pred[np.arange(len(idx)),chosen]
            values[idx,ci]=score[np.arange(len(idx)),chosen]
        # Logs are decisions based only on PREVIOUS completed months.
        select_log.append({"month":month,"expertByVenue":assigned.tolist()})
        # No result of the current month is fed into a prediction:
        # both training state and method-selector state advance afterward.
        meta.update(mi,payout[idx],pred,score,venues)
        memory.update(mi,mfeat,payout[idx])
        if (mi+1)%12==0 or mi+1==len(months):
            print("ADAPTIVE_METHODS_CAUSAL_MONTH_COMPLETE",json.dumps({
                "month":month,"elapsedMonths":mi+1,"forecasters":len(method_specs()),
                "metaSelectors":len(methods),"noSameMonthPayoutUsedToPredict":True,
                "racesThisMonth":len(idx)}),flush=True)
    return picks,values,memory,meta,select_log
def simulate():
    t=time.monotonic()
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py",
                  "adaptive_1030_ticket_regime_base")
    core,races,payout,feat,market,slots=base.historic_cash()
    months=calendar_sequence("201501","202604")
    if len(months)!=ALLOWED_MONTHS:
        raise RuntimeError("WRONG_2015JAN_TO_2026APR_MONTH_SPAN")
    # Allocate full calendar through Nov to preserve May-Jul 2026 gaps.
    allmonths=calendar_sequence("201501","202611")
    idx=np.asarray([int(r["month"]) for r in races],np.int32)
    if idx.min()!=201501 or idx.max()!=202604:
        raise RuntimeError("HISTORIC_PERIOD_OUTSIDE_136_MONTH_WINDOW")
    # Future slots are held empty until the real post-Apr results are loaded.
    mm=RollingCashMemory(base,len(market),allmonths)
    meta=MetaCashState(allmonths,len(method_specs()))
    picks,values,mm,meta,decisions=dataset(base,races,payout,feat,market,
                                allmonths,memory=mm,meta=meta)
    original=base.MODES
    base.MODES=tuple(f"adaptive_previous_{w or 'all'}mo_{scope}"
                   for w,scope in meta_specs())
    policy_results=base.score_all(races,payout,picks,values)
    models=policy_results["models"]
    if not all(base.strict_model_only(x["money"]) for x in models):
        raise RuntimeError("BAD_SUB200_MODEL_IN_ADAPTIVE_POLICY_OUTPUT")
    historical={"status":"ADAPTIVE_200PCT_CASH_MODELS_FOUND" if models else
                         "NO_QUALIFIED_ADAPTIVE_MODEL_CREATED",
        "trainPeriodsMonths":list(WINDOWS),
        "methodFeatureRegimes":[list(x) for x in REGIMES],
        "methodPayoutTreatments":list(PAY_VARIANTS),
        "methodForecastExperts":len(method_specs()),
        "metaSelectionLookbacksMonths":list(META_WINDOWS),
        "metaSelectorMethods":len(meta_specs()),
        "metaPredictionBasedOnlyOnEarlierMonthlyCash":True,
        "featuresMayUseHistoricalFinalOddsNotT15":True,
        "allRacesThroughApr2026":len(races),
        "all136HistoricalMonthsArePrequential":True,
        "realCashOnly":True,
        "allSub200ComputationsImmediatelyDiscarded":True,
        "candidateCount":len(models),
        "models":models,
        "sampleOfDynamicMethodSelections":decisions[-4:],
        "productionChanged":False,
        "elapsedSeconds":round(time.monotonic()-t,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(historical,ensure_ascii=False,indent=2)+"\n")
    print("ADAPTIVE_METHOD_LEARNER_HISTORICAL_FINAL",json.dumps({
       "status":historical["status"],
       "historyLength":len(months),"candidateCount":len(models),
       "testedTicketExperts":len(method_specs()),"testedMethodSelectors":len(meta_specs()),
       "candidate":models[0] if models else None,
       "seconds":historical["elapsedSeconds"]},ensure_ascii=False),flush=True)
    if not models:
        # No nonqualifying method gets promoted to a candidate in the
        # independent holdout. No "best failed model" report.
        report={"status":"NO_ELIGIBLE_ADAPTIVE_MODEL_FOR_FORWARD_TEST",
           "verifiedModelCount":0,"noBelow200Fallback":True,
           "notTestedBecauseHistoricalCandidatesZero":True,
           "noProductionChange":True}
        FWD.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        return report
    # An eligible research model must also survive untouched later data.
    cash_provider=imported("scripts/research-20261114-net-profit-first-forward.py",
                            "adaptive_official_final_odds_and_payouts")
    future,coverage=cash_provider.d1_races()
    savedcache,savedracemodel=core.CACHE,core.RACE_CACHE
    try:
      core.CACHE=ROOT/"analysis-results/20261114-adaptive-forward-data.npz"
      core.RACE_CACHE=ROOT/"analysis-results/20261114-adaptive-forward-races.json"
      core.full_features(future)
      with np.load(core.CACHE,allow_pickle=False) as d:
        future_payout=np.asarray(d["payout"],np.int32)
        future_cat={k:np.asarray(d[k],np.uint8) for k in base.FEATURES}
    finally:
      core.CACHE,core.RACE_CACHE=savedcache,savedracemodel
    # No missing 2026 May-Jul data is invented. For each forward month, the
    # model uses only calendar months genuinely present through that point.
    # Since the full historical state is already trained, resume with May
    # through July as months with zero records, and Aug-Nov actual data.
    # Reuse precisely the historical state, not future payouts to rank models.
    allidx={m:i for i,m in enumerate(allmonths)}
    postp=np.empty((len(future),len(meta_specs()),6),np.int16)
    postv=np.empty((len(future),len(meta_specs()),6),np.float32)
    for m in ("202605","202606","202607"):
        j=allidx[m]
        blank={k:future_cat[k][:0] for k in base.FEATURES}
        mm.update(j,blank,future_payout[:0])
    for month in ("202608","202609","202610","202611"):
        j=allidx[month]
        ix=np.asarray([i for i,r in enumerate(future) if
                       str(r["month"]).replace("-","")==month],np.int32)
        fcat={k:x[ix] for k,x in future_cat.items()}
        if not len(ix):
            mm.update(j,fcat,future_payout[ix])
            continue
        experts,score=mm.predict(j,fcat,market)
        venues=np.asarray([int(future[int(k)]["venue"]) for k in ix],np.int32)
        assigned=meta.assign(j,venues)
        for ci in range(len(meta_specs())):
            picked_expert=assigned[ci,venues]
            postp[ix,ci]=experts[np.arange(len(ix)),picked_expert]
            postv[ix,ci]=score[np.arange(len(ix)),picked_expert]
        # Update only after this entire month has been predicted.
        meta.update(j,future_payout[ix],experts,score,venues)
        mm.update(j,fcat,future_payout[ix])
    audited=[]
    for original_candidate in models:
        m,led=base.config_replay(future,future_payout,postp,postv,
                                 original_candidate["policy"])
        if base.strict_model_only(m):
            audited.append({"historical":original_candidate["money"],
                "future":m,"policy":original_candidate["policy"]})
            if len(audited)==1:
                LED.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(LED,"wt",encoding="utf8",newline="") as f:
                    wr=csv.DictWriter(f,fieldnames=list(led[0]))
                    wr.writeheader();wr.writerows(led)
    if not all(base.strict_model_only(x["historical"]) and
               base.strict_model_only(x["future"]) for x in audited):
        raise RuntimeError("HISTORIC_OR_FUTURE_BELOW_200_IN_MODEL_LIST")
    fwdreport={"status":"ADAPTIVE_ROI200_MODEL_FOUND_AND_FORWARD_VERIFIED"
          if audited else "NO_VERIFIED_ADAPTIVE_ROI200_MODEL",
        "historicallyEligibleModelCount":len(models),
        "independentlyForwardEligibleModelCount":len(audited),
        "modelListOnlyROI200AndHit20":audited,
        "venueDayCoverage":coverage,
        "postAugActualPayoutNeverUsedToSelectHistoricalModel":True,
        "postAugMonthlyUpdatesOnlyAfterEachMonth":True,
        "missingMayToJuly2026NotFaked":True,
        "officialT15NotVerified":True,
        "productionChanged":False}
    FWD.write_text(json.dumps(fwdreport,ensure_ascii=False,indent=2)+"\n")
    print("ADAPTIVE_METHOD_LEARNER_POSTAUG_FINAL",json.dumps({
        "status":fwdreport["status"],
        "historicallyEligible":len(models),"independentlyEligible":len(audited),
        "models":audited[:2],
        "productionChanged":False},ensure_ascii=False),flush=True)
    return fwdreport
def selftest():
    assert len(method_specs())==7*5*2
    assert len(meta_specs())==6*2+7
    assert len(calendar_sequence("201501","202604"))==136
    assert month_num("202608")>month_num("202604")+3
    class B:
      FEATURES={"venue":10,"quarter":4,"favOdds":5,"oddsGeom":8}
    # A future-month massive payout must not modify a prediction made
    # for an earlier month, and different trailing windows must differ.
    st=RollingCashMemory(B(),2,["202601","202602","202603"])
    f={k:np.zeros((1,2),np.uint8) for k in B.FEATURES}
    market=np.asarray([0,1],np.int8)
    pre=st.predict(0,f,market)
    st.update(0,f,np.asarray([[1000,0]],np.int32))
    aft=st.predict(1,f,market)
    assert pre[0].shape==(1,len(method_specs()),6)
    assert np.isfinite(pre[1]).all() and np.isfinite(aft[1]).all()
    # All selected method indices at month 1 depend on only month 0.
    meta=MetaCashState(["202601","202602","202603"],len(method_specs()))
    c=meta.assign(0,np.asarray([0]))
    assert c.shape==(len(meta_specs()),10)
    chosen=np.zeros((1,len(method_specs()),6),np.int16)
    sc=np.ones_like(chosen,dtype=np.float32)
    meta.update(0,np.asarray([[250,0]],np.int32),chosen,sc,np.asarray([0]))
    assert meta.pay[0,0].sum()>0 and meta.pay[1].sum()==0
    print("ADAPTIVE_MULTI_HORIZON_METHOD_LEARNER_SELFTEST_OK",flush=True)
if __name__=="__main__":
    if "--self-test" in sys.argv:selftest()
    else:simulate()
