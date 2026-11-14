#!/usr/bin/env python3
"""Broad causal, actual-cash JRA system search across every bet type and top-10 combos.

ONE research run: all 136 available months (2015Jan..2026Apr), 1030 candidate
tickets per race (win, wide, quinella, exacta, trio, trifecta) and all ten
popularity-ranked horses, at least three different races per each venue-day.
No predicted month sees the same month's or later race outcomes.

Sweeps: stationary, decayed historical cash cells, payout-robust / supported
returns, favorite / market baselines, venue/quarter/odds/field/race regimes,
all six market subsets, 3/5/8/12 races per day, single/paired distinct market
tickets and equal / moderate / cash-edge scaled stakes. The optimize score
is realized net yen, with hard ROI≥200, max-race-removed ROI≥200, hit≥20%.
A 100-yen win hedge cannot be used to camouflage a 20,000-yen longshot:
candidate cash rules must put comparable stakes (ratio at most 5:1)
across two bet types. Profitable race share separately audited.

This study is broader but NOT literally exhaustive of the infinite universe
of possible strategies and CANNOT prove a model will never exist. Historical
FINAL win odds rather than official T-minus-15 snapshots are the data limit.
"""
from __future__ import annotations
import collections, csv, gzip, importlib.util, json, math, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-broad-causal-cash-sweep.json"
LED=ROOT/"analysis-results/20261114-broad-causal-best-ledger.csv.gz"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
FEATURES={"oddsGeom":8,"favOdds":5,"fieldSize":4,"venue":10,
 "quarter":4,"raceBand":3,"favGap":4,"oddsSpread":5,
 "horseAge":5,"draw":5,"horseWeight":5}
SCHEMAS=(
 (),("oddsGeom",),("favOdds",),("fieldSize",),("venue",),("quarter",),
 ("raceBand",),("favGap",),("horseAge",),("draw",),
 ("oddsGeom","fieldSize"),("oddsGeom","venue"),("oddsGeom","quarter"),
 ("favOdds","venue"),("favOdds","quarter"),("venue","quarter"),
 ("fieldSize","venue"),("raceBand","venue"),("favGap","venue"),
 ("horseAge","fieldSize"),("oddsGeom","favOdds"),("oddsSpread","venue"),
 ("draw","venue"),("horseWeight","venue"),
 ("venue","quarter","favOdds"),("fieldSize","venue","quarter"))
# 26 fundamentally different causal cash distributions, TWO horizons each.
MODES=("stable_robust","stable_mean","stable_restrained",
       "recency_robust","recency_mean","recency_restrained",
       "ensemble_robust","ensemble_mean","ensemble_restrained",
       "stationary_template","recency_template",
       "market_baseline","rank_favorite","rank_mid","rank_wide")
MASKS={
 "all6":(0,1,2,3,4,5),"no_trifecta":(0,1,2,3,4),
 "no_triples":(0,1,2,3),"winwide":(0,1),"win":(0,),
 "wide":(1,),"pairs":(1,2,3),"quinella":(2,),"exacta":(3,),
 "trio":(4,),"trifecta":(5,),"winquinella":(0,2),
 "wintrifecta":(0,5),"wide_trio":(1,4),
 "wide_trifecta":(1,5),"nonwin":(1,2,3,4,5)}
SLATES=(3,5,8,12)
STAKEPLANS=("one100","one500","one_edge","one_capped",
            "pair100","pair200","pair500_100","pair400_200",
            "pair_edge","pair_equal_edge","pair_when_positive")
SELECT_MODES=("top_score","top_margin","top_score_plus_positive")
VENUE_DAY_MIN=3
def load(path,name):
 s=importlib.util.spec_from_file_location(name,ROOT/path)
 if s is None or s.loader is None:raise RuntimeError("MISSING_RESEARCH_DEPENDENCY:"+path)
 m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
class Stream:
 def __init__(self,n,columns,decay):
  self.fields=columns;self.decay=decay;size=n
  for x in columns:size*=FEATURES[x]
  self.n=np.zeros(size,dtype=np.float64)
  self.hits=np.zeros(size,dtype=np.float64)
  self.cash=np.zeros(size,dtype=np.float64)
  self.cap=np.zeros(size,dtype=np.float64)
  self.big=np.zeros(size,dtype=np.float64)
 def codes(self,features,template):
  out=np.broadcast_to(template,features["venue"].shape).astype(np.int32).copy()
  for k in self.fields:
   f=features[k]
   if np.any(f>=FEATURES[k]):raise RuntimeError("ILLEGAL_PRE_RACE_CONTEXT_"+k)
   out=out*FEATURES[k]+f.astype(np.int32)
  return out
 def update(self,code,pay):
  if self.decay!=1:
   for a in (self.n,self.hits,self.cash,self.cap,self.big):a*=self.decay
  flat=code.ravel();yen=pay.ravel().astype(np.float64)
  n=len(self.n)
  self.n+=np.bincount(flat,minlength=n)
  self.hits+=np.bincount(flat,weights=(yen>0),minlength=n)
  self.cash+=np.bincount(flat,weights=yen,minlength=n)
  self.cap+=np.bincount(flat,weights=np.minimum(yen,100000.),minlength=n)
  nonzero=np.flatnonzero(yen)
  if len(nonzero):np.maximum.at(self.big,flat[nonzero],yen[nonzero])
 def robust(self,code,mode):
  hits=self.hits[code];n=self.n[code]
  cash=(self.cap[code] if mode=="restrained" else self.cash[code])
  biggest=(np.minimum(self.big[code],100000.) if mode=="restrained" else self.big[code])
  if mode=="mean":biggest=0.
  pnl=np.maximum(0.,cash-biggest)/np.maximum(1.,100.*n)
  return n,hits,np.minimum(pnl,35.)
def historic_cash():
 core=load("scripts/research-nov2026-decade-roi-first-sixmarkets.py","cash_sweep_top10")
 parser=load("scripts/research-nov2026-sixmarket-real-paid-cash.py","cash_sweep_parser")
 races=core.read_all_races(parser.parse_payments)
 if len(races)<30000:raise RuntimeError("INCOMPLETE_CASH_RACES")
 if not (core.CACHE.exists() and core.RACE_CACHE.exists()):
  core.CACHE.parent.mkdir(parents=True,exist_ok=True)
  core.full_features(races)
 with np.load(core.CACHE,allow_pickle=False) as d:
  paid=np.asarray(d["payout"],np.int32)
  if paid.shape!=(len(races),1030):raise RuntimeError("WRONG_1030_TEMPLATE_PAYOUT_MATRIX")
  feat={k:np.asarray(d[k],np.uint8) for k in FEATURES}
 tpl,market=core.fixed_template()
 return core,races,paid,feat,np.asarray(market,np.int8),tpl
def month_scores(streams,features,market,tpl_id,template):
    n=len(features["venue"]);T=len(market)
    base_code=streams[0][0].codes(features,template)
    priors=np.asarray((.75,.75,.75,.75,.75,.75),np.float32)[market][None,:]
    raw1=np.empty((n,T),np.float32)
    raw2=np.empty((n,T),np.float32)
    estimates=[]
    for horizon in (0,1):
      stage=streams[horizon]
      bs=stage[0]
      key=bs.codes(features,template)
      b_n,b_hit,b_raw=bs.robust(key,"robust")
      _,_,b_mean=bs.robust(key,"mean")
      _,_,b_cap=bs.robust(key,"restrained")
      # Template must occur often; the prior is market cash net of takeout.
      wt=np.minimum(1.,b_n/(b_n+160.))*np.minimum(1.,b_hit/5.)
      base=np.maximum(.01,priors*(1-wt)+wt*np.minimum(b_raw,30.))
      estimates_h={"robust":base.copy(),"mean":base.copy(),"restrained":base.copy()}
      for st in stage[1:]:
        code=st.codes(features,template)
        for method in ("robust","mean","restrained"):
          cnt,hit,pay=st.robust(code,method)
          # Suppress highly specific zero-evidence cells.
          accepted=(cnt>=20)&(hit>=2)
          shrink=(cnt/(cnt+300.))*(hit/(hit+8.))
          reward=(pay-base)*shrink
          est=base+reward
          # Never maximize training hit count or reward hitting in objective.
          estimates_h[method]=np.where(accepted,
                            np.maximum(estimates_h[method],est),estimates_h[method])
      estimates.append((base,estimates_h))
    one,two=estimates
    matrix=np.empty((n,len(MODES),T),np.float32)
    for j,mode in enumerate(MODES):
      if mode.startswith("stable_"):
        matrix[:,j]=one[1][mode.removeprefix("stable_")]
      elif mode.startswith("recency_") and mode!="recency_template":
        matrix[:,j]=two[1][mode.removeprefix("recency_")]
      elif mode.startswith("ensemble_"):
        v=mode.removeprefix("ensemble_")
        matrix[:,j]=.5*(one[1][v]+two[1][v])
      elif mode=="stationary_template":matrix[:,j]=one[0]
      elif mode=="recency_template":matrix[:,j]=two[0]
      elif mode=="market_baseline":
        matrix[:,j]=np.broadcast_to(priors,(n,T))
      elif mode=="rank_favorite":
        # Conservative favorite/rank structural prior, NO result.
        r=np.asarray([max(s) for s in tpl_id],np.float32)
        rank_bonus=np.broadcast_to((7.-np.minimum(r,7.))/8.,(n,T))
        matrix[:,j]=np.broadcast_to(priors,(n,T))+.5*rank_bonus
      elif mode=="rank_mid":
        r=np.asarray([max(s) for s in tpl_id],np.float32)
        rank_bonus=np.broadcast_to(1.-np.abs(r-3.)/6.,(n,T))
        matrix[:,j]=np.broadcast_to(priors,(n,T))+.4*rank_bonus
      elif mode=="rank_wide":
        m=market.astype(np.float32)
        matrix[:,j]=np.broadcast_to(priors,(n,T))+(market[None,:]==1)*.5
      else:raise RuntimeError("UNKNOWN_FORECAST_FAMILY")
    return matrix
def monthly_frozen_predictions(races,pay,features,market,slots):
    template=np.arange(len(market),dtype=np.int32)[None,:]
    streams=[[Stream(len(market),sch,decay) for sch in SCHEMAS]
             for decay in (1.,.95)]
    n=len(races)
    # Per-race per-model only selected ticket per market retained: no result
    # leakage while reducing huge 1030-ticket matrices to six choices.
    best=np.empty((n,len(MODES),6),np.int16)
    scores=np.empty((n,len(MODES),6),np.float32)
    indexes={month:np.flatnonzero(np.asarray([r["month"]==month for r in races]))
             for month in sorted({r["month"] for r in races})}
    if len(indexes)!=136:raise RuntimeError("MISSING_MONTHS_FROM_2015_THROUGH_2026APR")
    first_year={}
    for mi,(mon,ii) in enumerate(indexes.items()):
       z={k:v[ii] for k,v in features.items()}
       candidate=month_scores(streams,z,market,slots,template)
       for m in range(6):
         picks=np.flatnonzero(market==m)
         ix=np.argmax(candidate[:,:,picks],axis=2)
         best[ii,:,m]=picks[ix]
         scores[ii,:,m]=np.take_along_axis(candidate[:,:,picks],ix[:,:,None],axis=2)[:,:,0]
       # Payout of this month is inserted ONLY AFTER entire month prediction.
       for horizon in streams:
         for st in horizon:st.update(st.codes(z,template),pay[ii])
       first_year[mon]=len(ii)
       if (mi+1)%12==0 or mi+1==len(indexes):
        print("BROAD_CAUSAL_MONTHS_COMPUTED",json.dumps({
          "month":mon,"months":mi+1,"races":sum(first_year.values()),
          "modelTypes":len(MODES),"all1030Tickets":True,
          "usedCurrentMonthPayoutForForecast":False}),flush=True)
    return best,scores,streams,first_year
_group_memory={}
def get_venue_day_groups(races):
  key=id(races)
  if key not in _group_memory:
    codes={};v=np.empty(len(races),np.int32)
    for i,r in enumerate(races):
      k=(r["day"],int(r["venue"]))
      if k not in codes:codes[k]=len(codes)
      v[i]=codes[k]
    counts=np.bincount(v)
    if counts.min()<3:raise RuntimeError("INELIGIBLE_VENUE_DAY_LESS_THAN_THREE_RACES")
    _group_memory[key]=(v,len(codes))
  return _group_memory[key]
def policy_arrays(races,paid,chosen,forecast,market_keys,plan,slate,ranking,select_mode,ledger=False,cellbreakdown=False):
    # chosen has shape [N,6], score [N,6], returns one best ticket per market.
    n=len(races)
    allowed=np.asarray(market_keys,dtype=np.int32)
    m=np.argmax(forecast[:,allowed],axis=1)
    m1=allowed[m]
    s1=forecast[np.arange(n),m1]
    t1=chosen[np.arange(n),m1]
    backup=forecast[:,allowed].copy()
    backup[np.arange(n),m]=-1e9
    m2=allowed[np.argmax(backup,axis=1)] if len(allowed)>1 else m1
    s2=forecast[np.arange(n),m2]
    t2=chosen[np.arange(n),m2]
    if plan.startswith("pair") and len(allowed)<2:return None,None
    # Purchase 100-yen units. NO tiny 100-yen hedge paired with a huge ticket.
    extra=np.maximum(0.,s1-1.)
    u1=np.ones(n,dtype=np.int32)
    u2=np.zeros(n,dtype=np.int32)
    if plan=="one500":u1[:]=5
    elif plan=="one_edge":u1+=np.minimum(9,np.floor(extra/.45).astype(np.int32))
    elif plan=="one_capped":u1+=np.minimum(19,np.floor(extra/.3).astype(np.int32))
    elif plan=="pair100":u2[:]=1
    elif plan=="pair200":u1[:]=2;u2[:]=2
    elif plan=="pair500_100":u1[:]=5;u2[:]=1
    elif plan=="pair400_200":u1[:]=4;u2[:]=2
    elif plan=="pair_edge":
      u1=1+np.minimum(9,np.floor(extra/.6).astype(np.int32))
      u2=np.maximum(1,((u1+2)//3))
    elif plan=="pair_equal_edge":
      u1=1+np.minimum(9,np.floor(extra/.6).astype(np.int32))
      u2=u1.copy()
    elif plan=="pair_when_positive":
      u1=1+np.minimum(9,np.floor(extra/.6).astype(np.int32))
      u2=np.where(s2>=1.03,np.maximum(1,u1//2),0)
    elif plan!="one100":raise RuntimeError("UNKNOWN_STAKE_PLAN")
    # All pair tickets from different types, never same-market duplication.
    if np.any((u2>0)&(m1==m2)):raise RuntimeError("PAIRED_SAME_MARKET")
    if np.any((u2>0)&(u1>5*u2)) or np.any((u2>0)&(u2>5*u1)):
      raise RuntimeError("GROSSLY_DISPROPORTIONATE_HEDGE_STAKING")
    if ranking=="top_score":
       signal=(s1-1.)*u1+np.maximum(0,s2-1.)*u2
    elif ranking=="top_margin":
       signal=s1-1.
    else:raise RuntimeError("UNKNOWN_SELECTION_RANKING")
    groupid,groups=get_venue_day_groups(races)
    # Venue-day grouped sort is entirely vectorized: thousands of strategies,
    # no 3000-day Python loop for each combination.
    ordered=np.lexsort((np.arange(n,dtype=np.int32),-signal,groupid))
    sorted_groups=groupid[ordered]
    beginnings=np.r_[True,sorted_groups[1:]!=sorted_groups[:-1]]
    beginindex=np.maximum.accumulate(np.where(beginnings,np.arange(n),0))
    place=np.arange(n)-beginindex
    take=place<slate
    if select_mode=="top_score_plus_positive":
      take=take & ((place<3)|(signal[ordered]>0))
    ix=ordered[take]
    if len(ix)<3*groups:raise RuntimeError("THREE_RACE_MIN_NOT_ENFORCED")
    cost=100*(u1[ix]+u2[ix])
    ret=paid[ix,t1[ix]].astype(np.int64)*u1[ix].astype(np.int64)+paid[ix,t2[ix]].astype(np.int64)*u2[ix].astype(np.int64)
    money=int(ret.sum(dtype=np.int64))
    spend=int(cost.sum(dtype=np.int64))
    maxr=int(ret.max())
    hits=int(np.count_nonzero(ret))
    nr=len(ix)
    positives=int(np.count_nonzero(ret>cost))
    result={"purchaseRaces":nr,"venueDays":groups,
       "stakeYen":spend,"paidYen":money,
       "profitYen":money-spend,
       "cashRoiPct":round(100*money/spend,4),
       "minusLargestRaceCashRoiPct":round(100*(money-maxr)/spend,4),
       "largestPaidRaceYen":maxr,"hitRaces":hits,
       "hitRacePct":round(100*hits/nr,4),
       "profitableRaces":positives,
       "profitableRacePct":round(100*positives/nr,4)}
    if cellbreakdown:
        # A cell is a venue x quarter-of-year; every individual venue-day
        # still receives >=3 selected races under the frozen pre-result rule.
        if not hasattr(policy_arrays,"_cells") or policy_arrays._cells[0]!=id(races):
           cells=np.asarray([(int(z["venue"]), (int(z["month"][4:])-1)//3)
                             for z in races],np.int32)
           k=cells[:,0]*4+cells[:,1]
           keys=np.unique(k)
           policy_arrays._cells=(id(races),k,keys)
        _,key_arr,keys=policy_arrays._cells
        group=key_arr[ix]
        bins=int(max(keys))+1
        cnt=np.bincount(group,minlength=bins)
        stake_by=np.bincount(group,weights=cost,minlength=bins)
        pay_by=np.bincount(group,weights=ret,minlength=bins)
        hits_by=np.bincount(group,weights=(ret>0),minlength=bins)
        max_by=np.zeros(bins,np.int64)
        np.maximum.at(max_by,group,ret)
        stats={int(k):{"races":int(cnt[k]),"stakeYen":int(stake_by[k]),
              "paidYen":int(pay_by[k]),"hitRaces":int(hits_by[k]),
              "maxRacePayoutYen":int(max_by[k])} for k in keys}
        if sum(x["stakeYen"] for x in stats.values())!=spend or sum(x["paidYen"] for x in stats.values())!=money:
            raise RuntimeError("VENUE_QUARTER_CASH_ACCOUNTING_DISAGREES")
        return result,stats
    if not ledger:return result,None
    records=[]
    for j,k in enumerate(ix):
      k=int(k);r=races[k]
      records.append({"raceId":r["id"],"date":r["day"],
        "venue":r["venue"],"raceNo":r["raceNo"],
        "market1":MARKETS[int(m1[k])],"template1":int(t1[k]),
        "market2":MARKETS[int(m2[k])] if u2[k] else "",
        "template2":int(t2[k]) if u2[k] else "",
        "stake1Yen":100*int(u1[k]),"stake2Yen":100*int(u2[k]),
        "costYen":int(cost[j]),"paidYen":int(ret[j]),
        "netProfitYen":int(ret[j]-cost[j]),
        "hit":int(ret[j]>0),"profitable":int(ret[j]>cost[j])})
    return result,records
def hits_ok(m):
 return m["purchaseRaces"]>=3*m["venueDays"] and m["hitRaces"]*5>=m["purchaseRaces"]
def full_ok(m):
 return (hits_ok(m) and m["paidYen"]>=2*m["stakeYen"]
   and m["paidYen"]-m["largestPaidRaceYen"]>=2*m["stakeYen"])
def strict_model_only(m):
    """A returned MODEL must satisfy EVERY actual-money condition.

    A low-ROI or low-hit calculation can be an internal pruning value;
    it must never receive a policy/model/candidate record or be serialized.
    """
    if not m:return False
    spend=int(m["stakeYen"]);paid=int(m["paidYen"])
    maxpay=int(m["largestPaidRaceYen"])
    nr=int(m["purchaseRaces"]);days=int(m["venueDays"])
    return (spend>0 and nr>=3*days and
            paid>=2*spend and
            paid-maxpay>=2*spend and
            int(m["hitRaces"])*5>=nr)

def score_all(races,paid,picks,forecast,verbose=True):
    """Explore the universe but INSTANTLY DISCARD non-200% calculations.

    No fallback, no "best failed policy", no model names below the ROI gate.
    Only cash200 + robust200 + hit20 + 3 venues are returned.
    """
    start=time.monotonic()
    discovered=[]
    num=0
    roi200_math_checks=0
    for v,method in enumerate(MODES):
      for maskname,market_ids in MASKS.items():
        for select in SELECT_MODES:
          ranking="top_margin" if select=="top_margin" else "top_score"
          how="top_score_plus_positive" if select=="top_score_plus_positive" else "top_score"
          for slate in SLATES:
            for plan in STAKEPLANS:
              if plan.startswith("pair") and len(market_ids)<2:continue
              mm,_=policy_arrays(races,paid,picks[:,v],forecast[:,v],
                            market_ids,plan,slate,ranking,how)
              if mm is None:continue
              num+=1
              # ROI >= 200 is checked BEFORE a candidate/model/policy
              # record is constructed. Every rejection is thrown away.
              spend=int(mm["stakeYen"]);paid_yen=int(mm["paidYen"])
              if paid_yen<2*spend:continue
              roi200_math_checks+=1
              if paid_yen-int(mm["largestPaidRaceYen"])<2*spend:continue
              if int(mm["hitRaces"])*5<int(mm["purchaseRaces"]):continue
              if int(mm["purchaseRaces"])<3*int(mm["venueDays"]):continue
              if not strict_model_only(mm):
                  raise RuntimeError("INVALID_MODEL_ESCAPED_ROI200_GATE")
              discovered.append({"policy":{
                 "forecast":method,"marketSubset":maskname,"raceSlate":slate,
                 "stakePlan":plan,"selection":select},"money":mm})
          if verbose and num%3000<20:
             print("ROI200_ONLY_EXPLORATION_PROGRESS",json.dumps({
               "calculations":num,
               "modelsMeetingAllCashAndHitLimits":len(discovered)}),flush=True)
    discovered.sort(key=lambda x:(x["money"]["profitYen"],
                                  x["money"]["minusLargestRaceCashRoiPct"]),reverse=True)
    if not all(strict_model_only(x["money"]) for x in discovered):
        raise RuntimeError("BELOW_200_MODEL_SERIALIZATION_BLOCKED")
    summary={"methods":len(MODES),"marketMasks":len(MASKS),
       "raceSelectionVariants":len(SELECT_MODES),"daySlates":len(SLATES),
       "stakePlans":len(STAKEPLANS),"cashCalculations":num,
       "fullPeriodCash200Hit20Qualified":len(discovered),
       "models":discovered[:30],
       "status":"ONLY_ROI200_MODELS" if discovered else "NO_MODEL_CREATED",
       "seconds":round(time.monotonic()-start,2)}
    print("ROI200_ONLY_DISCOVERY_FINISHED",json.dumps({
       "calculations":num,"createdModelCount":len(discovered),
       "serializedModelCount":len(summary["models"]),
       "status":summary["status"],
       "seconds":summary["seconds"]},ensure_ascii=False),flush=True)
    return summary

def config_replay(races,pay,chosen,roi,policy):
    iv=MODES.index(policy["forecast"])
    return policy_arrays(races,pay,chosen[:,iv],roi[:,iv],
       MASKS[policy["marketSubset"]],policy["stakePlan"],
       int(policy["raceSlate"]),
       "top_margin" if policy["selection"]=="top_margin" else "top_score",
       "top_score_plus_positive" if policy["selection"]=="top_score_plus_positive" else "top_score",
       ledger=True)
def run():
    t=time.monotonic()
    core,races,paid,features,market,slots=historic_cash()
    best,roi,states,months=monthly_frozen_predictions(races,paid,features,market,slots)
    result=score_all(races,paid,best,roi)
    models=result["models"]
    venue_days=get_venue_day_groups(races)[1]
    # NO below-200 fallback model. No historical ticket ledger generated
    # unless it can independently pass all four purchase/cash rules.
    frozen=models[0] if models else None
    ledger_path=None
    if frozen:
        m,ledger=config_replay(races,paid,best,roi,frozen["policy"])
        if m!=frozen["money"] or not strict_model_only(m):
            raise RuntimeError("STRICT_CASH200_MODEL_LEDGER_FAILED")
        LED.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(LED,"wt",newline="",encoding="utf8") as f:
          writer=csv.DictWriter(f,fieldnames=list(ledger[0]))
          writer.writeheader()
          writer.writerows(sorted(ledger,key=lambda x:x["raceId"]))
        ledger_path=str(LED.relative_to(ROOT))
    report={"status":"ONLY_CASH200_HIT20_MODELS_FOUND" if frozen else
            "NO_MODEL_CREATED",
      "candidateContract":{
         "roiPctMin":200,"largestRaceRemovedRoiPctMin":200,
         "hitRatePctMin":20,"minDistinctRacesPerVenueDay":3,
         "objective":"maximize actual paidYen minus stakeYen",
         "noModelUnderRoi200":True,"noFailedModelFallback":True},
      "all136MonthPredictionsBeforeSameMonthOutcome":True,
      "sixActualJraSettledMarketTypes":list(MARKETS),
      "fullRankedTicketUniversePerRace":1030,
      "fullHistoryRaces":len(races),"fullHistoryVenueDays":venue_days,
      "datePeriod":"2015-Jan through 2026-Apr",
      "dataLimit":"Historical final win odds only, not verified pre-start-15 official odds; payouts from pinned third-party archive",
      "scopeIsNotMathematicallyAllPossibleStrategies":True,
      "search":result,
      "forwardFrozenModel":frozen,
      "selectedExactLedger":ledger_path,
      "productionModified":False,
      "seconds":round(time.monotonic()-t,2)}
    if any(not strict_model_only(x["money"]) for x in report["search"]["models"]):
        raise RuntimeError("OUTPUT_CONTAINS_BELOW200_MODEL")
    if frozen is not None and not strict_model_only(frozen["money"]):
        raise RuntimeError("FROZEN_MODEL_BELOW200")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("ROI200_ONLY_FULL_ARCHIVE_FINAL",json.dumps({
      "status":report["status"],
      "full136Months":len(months),
      "calculations":result["cashCalculations"],
      "modelsFound":result["fullPeriodCash200Hit20Qualified"],
      "qualifiedModel":frozen,
      "no200FailureFallback":True,
      "productionModified":False},ensure_ascii=False),flush=True)
    return report

def selftest():
    dummy={"purchaseRaces":10,"venueDays":3,"stakeYen":1000,
      "paidYen":4000,"largestPaidRaceYen":500,"hitRaces":2}
    assert full_ok(dummy)
    assert not full_ok(dict(dummy,hitRaces=1))
    assert not full_ok(dict(dummy,paidYen=2400,largestPaidRaceYen=500))
    assert not full_ok(dict(dummy,purchaseRaces=8))
    assert len(SCHEMAS)>=24 and len(MASKS)>=16 and len(SLATES)==4
    assert len(STAKEPLANS)>=10 and len(MODES)>=15
    # Exercise all 15 forecast families (including recency_template) before
    # downloading / materializing the 136-month data in CI.
    mock={k:np.zeros((1,6),dtype=np.uint8) for k in FEATURES}
    mocktpl=np.arange(6,dtype=np.int32)[None,:]
    mocks=[[Stream(6,sc,decay) for sc in SCHEMAS] for decay in (1.,.95)]
    forecast=month_scores(mocks,mock,np.arange(6,dtype=np.int8),
                          [(0,)]*6,mocktpl)
    assert forecast.shape==(1,len(MODES),6) and np.isfinite(forecast).all()
    test_races=[{"id":str(j),"day":"2026-11-14","venue":1,"raceNo":j+1} for j in range(3)]
    test_paid=np.asarray([[300,0,0,0,0,0]]*3,dtype=np.int32)
    picked=np.tile(np.arange(6,dtype=np.int16),(3,1))
    roi=np.tile(np.asarray([2.,1.,.8,.7,.6,.5],dtype=np.float32),(3,1))
    ledger,_=policy_arrays(test_races,test_paid,picked,roi,tuple(range(6)),
                 "one100",3,"top_margin","top_score",False)
    assert ledger["purchaseRaces"]==3 and ledger["venueDays"]==1
    assert ledger["hitRaces"]==3 and ledger["cashRoiPct"]==300.
    # The essential contractual invariant: 199.99% is NEVER a model.
    baseline={"purchaseRaces":10,"venueDays":3,"stakeYen":1000,
              "paidYen":2000,"largestPaidRaceYen":0,"hitRaces":2}
    assert strict_model_only(baseline)
    assert not strict_model_only(dict(baseline,paidYen=1999))
    assert not strict_model_only(dict(baseline,largestPaidRaceYen=1))
    assert not strict_model_only(dict(baseline,hitRaces=1))
    assert not strict_model_only(dict(baseline,purchaseRaces=8))
    print("ROI200_ONLY_CANDIDATE_CONTRACT_SELFTEST_OK",flush=True)
if __name__=="__main__":
    if "--self-test" in sys.argv:selftest()
    else:run()
