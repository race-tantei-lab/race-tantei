#!/usr/bin/env python3
"""A NEW race-grouped settled-cash ticket RANKER; no horse win target.

Rank real paid-YEN ticket combinations jointly *within each race*, not
win/place classification and not just expected money regression. All 6 JRA
ticket markets, rank-seven combinations, two distinct types/race, 3-5
races/venue-day. Strictly chronological train 2017-21, choose cash policy
using 2022 alone, then freeze policy to eval 2023-26 Apr only on 2022 pass.

Source limitation: mirror final win odds != stored official T-15. Research
only, not live; no D1 or production main writes, never 200 claim below gates.
"""
from __future__ import annotations
import collections,csv,importlib.util,itertools,json,math,sys,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMRanker,LGBMClassifier
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-groupwise-cash-ranker.json"
LEDGER=R/"analysis-results/nov2026-groupwise-cash-ranker-bets.csv"
B=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
NAMES=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAIRS=tuple(itertools.combinations(range(6),2))
RELEVANCE=(0,100,500,2500,10000)
CASH_GAINS=[0,1,3,12,35]
PROB_POWERS=(0.,.5,1.,2.)
RANK_TEMPS=(.2,.4,.8,1.6,3.2)
BOOST=(-.6,0.,.6)
TEMPLATES=("cash_rank","rank_hit","rank_exotic")
SLATES=(3,4,5)
SPLITS=((1000,1000),(1500,500),(1900,100),(500,1500),(100,1900))
TRAIN=tuple(range(2017,2022))
FINAL_TRAIN=tuple(range(2017,2023))
EVAL=(2023,2024,2025,2026)
MARKET_TYPES=np.asarray([m for m,(lo,hi) in enumerate(B) for i in range(lo,hi)],dtype=np.int8)
SEED=20261113
def dependency():
  p=R/"scripts/research-nov2026-form-money-new-generator.py"
  spec=importlib.util.spec_from_file_location("groupwise_training_data",p)
  mod=importlib.util.module_from_spec(spec)
  sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
  return mod
def meters(p):
  arr=np.asarray(p,dtype=np.int64);n=len(arr);s=n*2000
  paid=int(arr.sum());maxrace=int(arr.max()) if n else 0
  return dict(races=n,stakeYen=s,paidYen=paid,
    roiPct=round(100*paid/s,4) if n else None,
    minusLargestRaceRoiPct=round(100*(paid-maxrace)/s,4) if n else None,
    hitRacePct=round(100*np.count_nonzero(arr)/n,4) if n else None,
    maxRacePaidYen=maxrace)
def valid(m,minr=300):
  return m["races"]>=minr and (m["roiPct"] or 0)>=200 and (
     m["minusLargestRaceRoiPct"] or 0)>=200 and (m["hitRacePct"] or 0)>=20
def training_samples(cash,year,years):
  ix=np.flatnonzero(np.isin(year,years))
  if len(ix)<10000:raise RuntimeError("NOT_ENOUGH_RACE_GROUPS")
  rng=np.random.default_rng(SEED)
  subset=[];group_sizes=[]
  for race in ix:
    payout=cash[race]
    candidates=[]
    for lo,hi in B:
      winners=np.flatnonzero(payout[lo:hi]>0)+lo
      negatives=np.flatnonzero(payout[lo:hi]==0)+lo
      if len(negatives):
        neg=rng.choice(negatives,size=min(len(negatives),13),replace=False)
        candidates.extend(map(int,neg))
      candidates.extend(map(int,winners))
    sample=np.array(sorted(set(candidates)),dtype=np.int32)
    subset.append(race*336+sample)
    group_sizes.append(len(sample))
  positions=np.concatenate(subset).astype(np.int64)
  if len(positions)<250000:raise RuntimeError("NOT_ENOUGH_CASH_RANKING_TICKETS")
  if sum(group_sizes)!=len(positions):raise RuntimeError("BROKEN_RACE_GROUPS")
  return ix,positions,group_sizes
def trained(base,cash,attrs,markets,year,fields,years):
  idx,flat,groups=training_samples(cash,year,years)
  x=base.features(attrs,markets,fields,flat)
  target=cash.ravel()[flat]
  # Rank tickets by monetary payout amount (capped relevance, not a horse
  # win/place target); minimum NDCG query is one complete race.
  labels=np.searchsorted(np.array(RELEVANCE[1:]),target,side="right").astype(np.int8)
  if labels.min()!=0 or labels.max()<3:raise RuntimeError("INVALID_PAID_YEN_RANK_LABELS")
  ranks=LGBMRanker(objective="lambdarank",n_estimators=185,learning_rate=.055,
      num_leaves=21,max_depth=6,min_child_samples=280,reg_lambda=18.,
      colsample_bytree=.82,label_gain=CASH_GAINS,
      random_state=SEED,n_jobs=3,verbosity=-1)
  ranks.fit(x,labels,group=groups)
  hit=LGBMClassifier(objective="binary",n_estimators=145,learning_rate=.052,
      num_leaves=19,max_depth=6,min_child_samples=250,reg_lambda=22.,
      colsample_bytree=.88,random_state=SEED,n_jobs=3,verbosity=-1)
  # True cash-hit sample weights adjusted by market frequency; actual
  # unit payout does NOT leak into features.
  y=(target>0).astype(np.int8)
  m=markets[flat].astype(np.int32)
  counts=np.bincount(m,minlength=6)
  weight=1./np.sqrt(np.maximum(counts[m],1))
  hit.fit(x,y,sample_weight=weight)
  return ranks,hit,dict(trainRaces=len(idx),trainTickets=len(flat),
      labelCounts=dict(enumerate(map(int,np.bincount(labels,minlength=5)))),
      positiveCashTickets=int(y.sum()))
def predict(base,estimators,attrs,markets,fields,year,y):
  idx=np.flatnonzero(year==y)
  flat=(idx[:,None]*336+np.arange(336)[None,:]).ravel()
  ranker,hit,_=estimators
  predictions=np.empty((len(flat),2),dtype=np.float32)
  for offset in range(0,len(flat),220000):
    end=min(offset+220000,len(flat))
    x=base.features(attrs,markets,fields,flat[offset:end])
    predictions[offset:end,0]=ranker.predict(x).astype(np.float32)
    predictions[offset:end,1]=np.clip(hit.predict_proba(x)[:,1],1e-9,1.).astype(np.float32)
  return idx,predictions.reshape(len(idx),336,2)
def grouping(races,idx):
  g=collections.defaultdict(list)
  for k,i in enumerate(idx):
    r=races[int(i)];g[(str(r["day"]),str(r["venue"]))].append(k)
  return [np.asarray(v,dtype=np.int32) for v in g.values()]
def choices(cash,idx,preds,temp,probpower,exotic,kind):
  # convert within-race ranking signal to dimensionless relative cash
  # preference. All transformation and nominations are pre-result.
  score=np.clip(preds[:,:,0],-20,20)
  centered=score-score.max(axis=1,keepdims=True)
  signal=np.exp(np.clip(temp*centered,-60,0))*np.maximum(preds[:,:,1],1e-9)**probpower
  if kind=="rank_hit":signal*=np.maximum(preds[:,:,1],1e-9)
  if kind=="rank_exotic":
    signal[:,49:]*=1.15
  # Positive power on exotic markets, negative on simple markets.
  for market,(lo,hi) in enumerate(B):
    signal[:,lo:hi]*=math.exp(exotic*market/5)
  sel=np.zeros((len(idx),6),dtype=np.int16)
  strength=np.zeros((len(idx),6),dtype=np.float64)
  paid=np.zeros((len(idx),6),dtype=np.int32)
  for market,(lo,hi) in enumerate(B):
    ids=np.argmax(signal[:,lo:hi],axis=1)+lo
    sel[:,market]=ids
    strength[:,market]=signal[np.arange(len(idx)),ids]
    paid[:,market]=cash[idx,ids]
  return sel,strength,paid
def select(groups,signals,slate):
  return np.concatenate([np.asarray(sorted(g.tolist(),key=lambda i:(-signals[i],i))[:slate],
                        dtype=np.int32) for g in groups])
def optimize(races,cash,idx,preds):
  groups=grouping(races,idx)
  if len(groups)<150 or any(len(g)<5 for g in groups):
    raise RuntimeError("INCOMPLETE_2022_RACE_PROGRAM_UNIVERSE")
  q=np.asarray([(int(races[int(i)]["month"][4:])-1)//3 for i in idx],dtype=np.uint8)
  checked=0;present=0;qualifiers=0;best=None
  for kind in TEMPLATES:
    for temp in RANK_TEMPS:
      for powr in PROB_POWERS:
        for exotic in BOOST:
          noms,strength,paid=choices(cash,idx,preds,temp,powr,exotic,kind)
          # Each market's uncalibrated LambdaRank score is normalized by
          # median as objective is NOT a calibrated probability of payout.
          med=np.maximum(np.median(strength,axis=0),.000001)
          s=strength/med
          for slate in SLATES:
            for stake in SPLITS:
              per_pair=[]
              for a,b in PAIRS:
                px,py=stake
                ranked=select(groups,s[:,a]+s[:,b],slate)
                ret=paid[ranked,a]*(px//100)+paid[ranked,b]*(py//100)
                per_pair.append((a,b,ranked,ret,q[ranked]))
                checked+=1
              # 15^4 season-action vectors reduced by cash additivity;
              # choose best switch on 2022 only, absolutely no test peeking.
              policy=[]
              for quarter in range(4):
                active=[r for r in per_pair if np.any(r[4]==quarter)]
                if len(active)!=15:raise RuntimeError("MISSING_QUARTER_SLATES")
                target=max(active,key=lambda r:(
                  int(r[3][r[4]==quarter].sum())-
                  int(r[3][r[4]==quarter].max()),
                  int(np.count_nonzero(r[3][r[4]==quarter]))))
                policy.append(target)
              p=np.concatenate([z[3][z[4]==qtr] for qtr,z in enumerate(policy)])
              m=meters(p);present+=1
              if valid(m,450):
                qualifiers+=1
                candidate={"kind":kind,"temperature":temp,"hitPower":powr,
                   "exoticTilt":exotic,"slate":slate,"stakeSplit":list(stake),
                   "quarterPairs":[[int(z[0]),int(z[1])] for z in policy],
                   "cash2022":m}
                if best is None or m["minusLargestRaceRoiPct"]>best["cash2022"]["minusLargestRaceRoiPct"]:
                  best=candidate
  return best,{"fixedMarketPairsEvaluated":checked,
      "quarterlyPairChoicePolicies":present,
      "equivalentDisjointQuarterPairConfigurations":present*15**4,
      "qualified2022Policies":qualifiers}
def frozen(races,cash,idx,preds,rule):
  noms,strength,paid=choices(cash,idx,preds,rule["temperature"],
    rule["hitPower"],rule["exoticTilt"],rule["kind"])
  med=np.maximum(np.median(strength,axis=0),.000001)
  strength=strength/med
  out=[]
  for g in grouping(races,idx):
    if len(g)<rule["slate"]:raise RuntimeError("FORWARD_DAY_INCOMPLETE")
    quarter=(int(races[int(idx[g[0]])]["month"][4:])-1)//3
    a,b=rule["quarterPairs"][quarter]
    order=sorted(g.tolist(),key=lambda k:(-strength[k,a]-strength[k,b],k))[:rule["slate"]]
    for k in order:
      r=races[int(idx[k])]
      pa=int(paid[k,a])*(rule["stakeSplit"][0]//100)
      pb=int(paid[k,b])*(rule["stakeSplit"][1]//100)
      out.append({"year":int(r["month"][:4]),"raceId":r["id"],"day":r["day"],
        "venue":r["venue"],"raceNo":r["raceNo"],"market1":NAMES[a],
        "market2":NAMES[b],"ticket1":int(noms[k,a]),"ticket2":int(noms[k,b]),
        "stakeYen":2000,"paidYen":pa+pb})
  return out
def main():
  if "--self-test" in sys.argv:
    assert sum(hi-lo for lo,hi in B)==336
    assert len(PAIRS)==15 and 15**4==50625
    assert not valid({"races":1000,"roiPct":250,"minusLargestRaceRoiPct":199.99,"hitRacePct":20})
    assert valid({"races":1000,"roiPct":200,"minusLargestRaceRoiPct":200,"hitRacePct":20})
    assert len(TEMPLATES)*len(RANK_TEMPS)*len(PROB_POWERS)*len(BOOST)*len(SLATES)*len(SPLITS)*len(PAIRS)==13500
    print("RACE_GROUPED_CASH_RANKER_ACCEPTANCE_SELFTEST_OK");return
  tic=time.monotonic();base=dependency()
  races,cash,attrs,types,years,keys=base.obtain()
  # True payoff-free feature block; don't use form coverage boolean as
  # a race outcome proxy. Market type and 30 pre-form features only.
  keys=tuple(k for k in keys if k!="formIdentityMatched")
  models=trained(base,cash,attrs,types,years,keys,TRAIN)
  ix,preds=predict(base,models,attrs,types,keys,years,2022)
  policy,counts=optimize(races,cash,ix,preds)
  report={"status":"REJECTED_SEARCH_FAMILY_NOT_A_MODEL",
       "productionChanged":False,"adopted":False,
       "newArchitecture":"race-grouped six-market settled-cash LambdaRank",
       "trainYears":list(TRAIN),"policySearchYear":2022,
       "pastOutcomeLeakToRankingFeatures":False,
       "archivedJraExactT15Odds":False,
       "thirdPartyPayoutNotReconciled":True,
       "2026AugNovNotCovered":True,
       "ticketCandidateCount":int(cash.size),
       "trainSampleInfo":models[2],"grid":counts,
       "acceptedPolicy":policy}
  if policy:
    del models
    future=trained(base,cash,attrs,types,years,keys,FINAL_TRAIN)
    allrows=[];byyear={}
    for y in EVAL:
      idx,ps=predict(base,future,attrs,types,keys,years,y)
      rows=frozen(races,cash,idx,ps,policy)
      m=meters([z["paidYen"] for z in rows])
      byyear[str(y)]=m
      allrows.extend(rows)
      print("RACE_GROUPED_CASH_FORWARD_MONEY",json.dumps({"year":y,"cash":m}),flush=True)
    aggregate=meters([z["paidYen"] for z in allrows])
    success=valid(aggregate,1200) and all(
      v["races"]>=30 and v["roiPct"]>=200 and
      v["minusLargestRaceRoiPct"]>=200 and v["hitRacePct"]>=20
      for v in byyear.values())
    report.update({"status":"PROVISIONAL_HISTORICAL_NUMERIC_200_REQUIRES_JRA_T15" if success
                   else "REJECTED_SEARCH_FAMILY_NOT_A_MODEL",
                   "forwardYears":byyear,"combined":aggregate,
                   "forwardCashPassAll":bool(success)})
    if allrows:
      LEDGER.parent.mkdir(parents=True,exist_ok=True)
      with LEDGER.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
  report["elapsedSec"]=round(time.monotonic()-tic,2)
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
  print("RACE_GROUPED_CASH_RANKER_FINAL",json.dumps({
    "status":report["status"],"accepted2022":bool(policy),
    "fixedPairComparisons":counts["fixedMarketPairsEvaluated"],
    "portfolioConfigurations":counts["equivalentDisjointQuarterPairConfigurations"],
    "runtimeSec":report["elapsedSec"],"productionChanged":False
  },ensure_ascii=False),flush=True)
if __name__=="__main__":main()
