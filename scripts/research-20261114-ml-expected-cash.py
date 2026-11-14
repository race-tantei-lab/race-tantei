#!/usr/bin/env python3
"""Independent chronological LightGBM REAL-MONEY payout learner + broad policy sweep.

Unlike horse win prediction, target is ACTUAL JRA 100-yen payout per ticket.
10 models train on expanding PAST YEARS ONLY (2015-2017, then through 2019,
2021, 2023 and 2025), predict the next 2 years, and are audited for ACTUAL
money profit. 2015-17 uses a no-label baseline. For Aug-Nov 2026, training may
also include 2026Apr, but no 2026Aug+ result.

All 1,030 win/wide/quinella/exacta/trio/trifecta ticket types are evaluated.
Cash portfolio search combines market subsets, 3-12 different races per venue
day, market diversification, budget allocations, ranked cash edges, and
does not reward high hit rate: hit20 is a hard eligibility floor.

This is independent of the preceding-month empirical cell-regime model but
has the same data limitations: historical FINAL win odds, NOT JRA T-15 odds.
"""
from __future__ import annotations
import collections,importlib.util,json,sys,time
from pathlib import Path
import numpy as np
import lightgbm as lgb
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-ml-cash-full-history.json"
OUT_FWD=ROOT/"analysis-results/20261114-ml-cash-aug-nov-forward.json"
FEATURES=("market","rankMin","rankMax","rankSum","rankGap","rankFirst",
 "rankSecond","favCount","oddsGeom","oddsSpread","favOdds","favGap",
 "fieldSize","venue","quarter","raceBand","horseAge","draw","horseWeight")
MODE_NAMES=("ml_robust_cash","ml_full_cash","ml_ensemble_cash",
 "ml_conservative_cash","ml_favorite_aware_cash","ml_winwide_prior")
def imp(path,name):
 s=importlib.util.spec_from_file_location(name,ROOT/path)
 if s is None or s.loader is None:raise RuntimeError("ML_MODULE_NOT_FOUND:"+path)
 m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
def feat_rows(cat,market,r,t):
 return np.column_stack([market[t] if x=="market" else cat[x][r,t]
                          for x in FEATURES]).astype(np.float32)
def sample_ticket_cash(paid,years):
 rng=np.random.default_rng(20261114)
 records=[]
 for i in range(len(paid)):
    success=np.flatnonzero(paid[i]>0)
    negative=np.flatnonzero(paid[i]==0)
    k=min(40,len(negative))
    chosen=rng.choice(negative,size=k,replace=False)
    records.append((i,success,chosen,len(negative)/max(k,1)))
 rows=[];tickets=[];weights=[]
 for i,pos,neg,neg_w in records:
    rows.extend([i]*(len(pos)+len(neg)))
    tickets.extend(pos.tolist()+neg.tolist())
    weights.extend([1.]*len(pos)+[neg_w]*len(neg))
 rr=np.asarray(rows,np.int32)
 tt=np.asarray(tickets,np.int32)
 ww=np.asarray(weights,np.float32)
 if len(rr)<1_000_000 or int(np.count_nonzero(paid[rr,tt]))<100000:
    raise RuntimeError("CASH_ML_SAMPLE_INCOMPLETE")
 print("FULL_CASH_LIGHTGBM_IMPORTANCE_SAMPLER",json.dumps({
  "all1030CashTickets":int(paid.shape[0]*paid.shape[1]),
  "sampledTickets":len(rr),"actualWinningSampleTickets":int(np.count_nonzero(paid[rr,tt])),
  "maxZeroImportanceWeight":float(ww.max()),
  "zeroTicketSubsampleCorrected":True}),flush=True)
 return rr,tt,ww
def prediction_models(X,y,w,train_years):
 trained={}
 for key,params in (
   ("robust",{"objective":"tweedie","tweedie_variance_power":1.35,"maxcap":100000.}),
   ("full",{"objective":"poisson","maxcap":1000000.})):
    capped=np.minimum(y,params["maxcap"])/100.
    ds=lgb.Dataset(X,label=capped,weight=w,free_raw_data=True)
    parameters={"objective":params["objective"],"verbosity":-1,"learning_rate":0.06,
      "num_leaves":23,"min_data_in_leaf":350,"num_threads":4,
      "feature_fraction":.9,"lambda_l2":10.,
      "max_bin":63,"min_sum_hessian_in_leaf":10.,
      "seed":20261114,"force_col_wise":True}
    if "tweedie" in parameters["objective"]:
      parameters["tweedie_variance_power"]=params["tweedie_variance_power"]
    model=lgb.train(parameters,ds,num_boost_round=100)
    trained[key]=model
 print("CAUSAL_LIGHTGBM_PAYOUT_MODELS_TRAINED",json.dumps({
   "latestTrainingYear":train_years,"modelFamilies":list(trained),
   "trainingExamples":len(y),"notHorseWinAccuracyObjective":True}),flush=True)
 return trained
def best_by_market(cat,paid,market,models,indices=None):
    if indices is None:indices=np.arange(len(cat["venue"]),dtype=np.int32)
    n=len(indices)
    chosen=np.empty((n,len(MODE_NAMES),6),dtype=np.int16)
    value=np.empty((n,len(MODE_NAMES),6),dtype=np.float32)
    tmpl_groups=[np.flatnonzero(market==m) for m in range(6)]
    for a in range(0,n,180):
      end=min(n,a+180)
      rr=np.arange(a,end,dtype=np.int32)
      mn=len(rr)
      all_t=np.tile(np.arange(len(market),dtype=np.int32),mn)
      all_r=np.repeat(indices[rr],len(market))
      X=feat_rows(cat,market,all_r,all_t)
      lo=np.maximum(0.,models["robust"].predict(X,num_threads=4).reshape(mn,len(market)))
      hi=np.maximum(0.,models["full"].predict(X,num_threads=4).reshape(mn,len(market)))
      score=np.empty((mn,len(MODE_NAMES),len(market)),np.float32)
      score[:,0]=np.minimum(25.,lo)
      score[:,1]=np.minimum(35.,hi)
      score[:,2]=.75*score[:,0]+.25*score[:,1]
      score[:,3]=.75*score[:,0]+.25*.72
      score[:,4]=score[:,2] # boost to first popularity horses in ALL market types
      for m in range(6):
        cells=tmpl_groups[m]
        score[:,4,cells]*=(1.+.15*(1.-cat["rankMin"][indices[rr]][:,cells]/9.))
      score[:,5]=score[:,3]
      score[:,5,market!=0]=np.minimum(score[:,5,market!=0],1.)
      score[:,5,market==1]*=1.02
      for m in range(6):
        tpl=tmpl_groups[m]
        z=np.argmax(score[:,:,tpl],axis=2)
        chosen[a:end,:,m]=tpl[z]
        value[a:end,:,m]=np.take_along_axis(score[:,:,tpl],z[:,:,None],axis=2)[:,:,0]
      if a and a%2700==0:
        print("FULL_CASH_ML_RACE_INFERENCE_PROGRESS",json.dumps({
          "processed":end,"total":n,"marketTemplates":len(market)}),flush=True)
    return chosen,value
def fixed_baseline(races,market):
 n=len(races)
 chosen=np.zeros((n,len(MODE_NAMES),6),np.int16)
 value=np.empty((n,len(MODE_NAMES),6),np.float32)
 for m in range(6):
   t=int(np.flatnonzero(market==m)[0])
   chosen[:,:,m]=t
   value[:,:,m]=.74 if m==0 else .72
 value[:,4,0]=1.
 value[:,5,0]=1.1
 value[:,5,1]=1.
 return chosen,value
def historical_crossfit():
 broad=imp("scripts/research-20261114-broad-causal-cash-sweep.py","ml_eval_shared_cash")
 core,races,payout,feat,market,slots=broad.historic_cash()
 n=len(races)
 years=np.asarray([int(r["month"][:4]) for r in races],np.int16)
 if years.min()!=2015 or years.max()!=2026:raise RuntimeError("YEARLY_ML_CASH_ARCHIVE_INCOMPLETE")
 rr,tt,importance=sample_ticket_cash(payout,years)
 X=feat_rows({**feat,**{k:np.zeros_like(payout,dtype=np.uint8) for k in FEATURES if k not in feat and k!="market"}},market,rr,tt)
 yy=payout[rr,tt].astype(np.float64)
 yyears=years[rr]
 output_idx=np.empty((n,len(MODE_NAMES),6),np.int16)
 output_val=np.empty((n,len(MODE_NAMES),6),np.float32)
 early=np.flatnonzero(years<2018)
 output_idx[early],output_val[early]=fixed_baseline([races[int(i)] for i in early],market)
 trained_last=None
 for first in (2018,2020,2022,2024,2026):
   train=np.flatnonzero(yyears<first)
   if len(train)<300000:raise RuntimeError("TOO_FEW_OLDER_CASH_TICKETS")
   models=prediction_models(X[train],yy[train],importance[train],first-1)
   idx=np.flatnonzero((years>=first)&(years<=min(first+1,2026)))
   if len(idx):
     pred,score=best_by_market(feat,payout,market,models,idx)
     output_idx[idx]=pred;output_val[idx]=score
   trained_last=models
 return broad,core,races,payout,feat,market,output_idx,output_val,trained_last,years
def main():
 if "--self-test" in sys.argv:
   assert len(FEATURES)==19 and len(MODE_NAMES)==6
   assert np.isfinite(feat_rows(
     {"venue":np.zeros((1,6),np.uint8),**{k:np.zeros((1,6),np.uint8) for k in FEATURES if k not in ("venue","market")}},
     np.arange(6),np.arange(6)*0,np.arange(6))).all()
   print("EXPANDING_YEAR_REAL_JRA_CASH_LIGHTGBM_SELFTEST_OK",flush=True)
   return
 start=time.monotonic()
 broad,core,races,payout,feat,market,picks,forecast,trained,years=historical_crossfit()
 original=broad.MODES
 broad.MODES=MODE_NAMES
 summary=broad.score_all(races,payout,picks,forecast)
 chosen=(summary["qualified"][0] if summary["qualified"] else summary["bestProfitDiagnostic"])
 report={"status":"ML_HISTORICAL_CASH200_HIT20_FOUND" if summary["qualified"] else
    "ML_NO_CASH200_HIT20_FOUND_IN_TESTED_POLICY_SPACE",
   "policyChosenWithoutAnyAug-Nov2026Results":True,
   "historicalActualCash":summary,
   "historicalRaces":len(races),
   "all136MonthRecords":True,
   "crossFitTraining":"2015-2017 base, 2018-2019 using up to 2017, 2020-2021 using up to 2019, 2022-2023 using up to 2021, 2024-2025 using up to 2023, 2026Jan-Apr using up to 2025",
   "objective":"actual yen payouts per 100 yen ticket; payout capped and importance weighted",
   "winnerFrozenPolicy":chosen,"productionChanged":False,
   "notOfficialT15":True}
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 print("FULL_CASH_LIGHTGBM_HISTORICAL_FINAL",json.dumps({
   "qualified":summary["fullPeriodCash200Hit20Qualified"],
   "policies":summary["cashVariantsMeasured"],
   "bestProfit":summary["bestProfitDiagnostic"],
   "topWithHit20":summary["bestWith20PercentHits"],
   "seconds":round(time.monotonic()-start,1)}),flush=True)
 if "--no-forward" in sys.argv:return
 source=imp("scripts/research-20261114-net-profit-first-forward.py","ml_jra_aug_nov_cash_provider")
 fwd,coverage=source.d1_races()
 old_cache,old_rcache=core.CACHE,core.RACE_CACHE
 try:
   core.CACHE=ROOT/"analysis-results/20261114-ml-forward-cash.npz"
   core.RACE_CACHE=ROOT/"analysis-results/20261114-ml-forward-races.json"
   core.full_features(fwd)
   with np.load(core.CACHE,allow_pickle=False) as d:
      cash=np.asarray(d["payout"],np.int32)
      context={k:np.asarray(d[k],np.uint8) for k in FEATURES if k!="market"}
 finally:
   core.CACHE,core.RACE_CACHE=old_cache,old_rcache
 # Fit final model on ALL 2015..2026-Apr records, then evaluate August-Nov.
 # Unlike cross-fit historical 2026, Aug+ genuinely can use Apr as past.
 # Retrain on only past history even if new data were downloaded.
 rr,tt,weights=sample_ticket_cash(payout,years)
 X=feat_rows(feat,market,rr,tt)
 model=prediction_models(X,payout[rr,tt].astype(np.float64),weights,2026)
 win,score=best_by_market(context,cash,market,model)
 audited,ledger=broad.config_replay(fwd,cash,win,score,chosen["policy"])
 res={"status":"CASH_EXPECTED_RETURN_MODEL_FULL_FORWARD_AUDIT",
   "historicallyQualified":summary["fullPeriodCash200Hit20Qualified"],
   "frozenPolicyFromHistoryOnly":chosen["policy"],
   "forwardActualCash":audited,"forwardMeetsStrictGates":broad.full_ok(audited),
   "venueDayCoverage":coverage,
   "noAugustOrLaterActualPayoutUsedForTraining":True,
   "dataCaveat":"Final odds, not pre-start official T15; incomplete public payout rows",
   "productionModified":False}
 OUT_FWD.write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n")
 print("FULL_CASH_LIGHTGBM_FORWARD_FINAL",json.dumps({
    "frozen":chosen["policy"],"historical":chosen["money"],"forward":audited,
    "forwardQualified":res["forwardMeetsStrictGates"],
    "completeVenueDays":coverage["fullVenueDaysWithMinimumThreeEligibleRaces"],
    "seconds":round(time.monotonic()-start,1)},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
