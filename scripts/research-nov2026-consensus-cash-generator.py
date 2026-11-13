#!/usr/bin/env python3
"""Cash-first 2-head CONSENSUS + chance-of-payment hedge, immutable holdout.

Distinct from single payout head, ruleset cells, ticket box and flat
2-market pair routing: each ticket is valued by disagreement between TWO
independently fitted paid-yen heads, with an option to hedge one head by
conditional probability of any cash payout. A 2-market portfolio is selected
from six official JRA bet categories and evaluated in actual paid yen.
2022 policy selection ONLY, 2023-2026 pre-registered holdout.
This archive uses third-party payout, and win odds are final, not T15.
No promotion, no production writes, no historical backfilling.
"""
from __future__ import annotations
import collections,csv,importlib.util,itertools,json,math,os,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-consensus-hedged-cash.json"
LEDGER=R/"analysis-results/nov2026-consensus-hedged-cash-ledger.csv"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
B=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
PAIRS=tuple(itertools.combinations(range(6),2))
ALPHAS=(0.,.25,.5,.75,1.)
DOWNSIDE=(0.,.3,.8,1.5)
HITS=(0.,.25,.75)
FRONTIERS=("highest_ev","balanced_ev_hit","highest_hit","min_head_ev")
PER_DAY=(3,4,5)
SPLITS=((1000,1000),(1500,500),(1900,100),(500,1500),(100,1900))
TRAIN=tuple(range(2017,2022))
FINAL_TRAIN=tuple(range(2017,2023))
TEST=(2023,2024,2025,2026)
def mod():
  p=R/"scripts/research-nov2026-form-money-new-generator.py"
  spec=importlib.util.spec_from_file_location("historical_form_cash_generator",p)
  a=importlib.util.module_from_spec(spec)
  sys.modules[spec.name]=a;spec.loader.exec_module(a);return a
def money(cash):
  arr=np.asarray(cash,dtype=np.int64)
  n=len(arr)
  stake=n*2000;paid=int(arr.sum());top=int(arr.max()) if n else 0
  return {"races":n,"stakeYen":stake,"paidYen":paid,
    "roiPct":round(100*paid/stake,4) if stake else None,
    "minusLargestRaceRoiPct":round(100*(paid-top)/stake,4) if stake else None,
    "hitRacePct":round(100*np.count_nonzero(arr)/n,4) if n else None,
    "largestRacePayoutYen":top}
def qualifies(x,minimum=300):
  return x["races"]>=minimum and (x["roiPct"] or 0)>=200 and (
    x["minusLargestRaceRoiPct"] or 0)>=200 and (x["hitRacePct"] or 0)>=20
def consensus(pred,alpha,downside,hit_power):
  # p payout-event times clipped conditional-money, independently fitted
  # versus Tweedie direct cash, both in yen per 100 unit.
  l=np.log(np.maximum(pred[:,:,0],1e-8))
  r=np.log(np.maximum(pred[:,:,1],1e-8))
  p=np.maximum(pred[:,:,2],1e-8)
  diff=np.abs(l-r)
  fused=np.exp((1-alpha)*l+alpha*r)
  return fused*np.exp(-downside*diff)*np.power(p,hit_power),\
         np.minimum(np.exp(l),np.exp(r))
def max_by_market(cash,idx,pred,alpha,downside,hit_power,frontier):
  fused,minimum=consensus(pred,alpha,downside,hit_power)
  n=len(idx);vals=np.zeros((n,6),np.float64)
  prob=np.maximum(pred[:,:,2],1e-9)
  ids=np.zeros((n,6),np.int16)
  outcomes=np.zeros((n,6),np.int32)
  for m,(lo,hi) in enumerate(B):
    if frontier=="highest_ev":s=fused[:,lo:hi]
    elif frontier=="highest_hit":s=prob[:,lo:hi]
    elif frontier=="balanced_ev_hit":s=np.sqrt(fused[:,lo:hi]*prob[:,lo:hi])
    elif frontier=="min_head_ev":s=minimum[:,lo:hi]
    else:raise RuntimeError("UNKNOWN_FRONTIER")
    j=np.argmax(s,axis=1)+lo
    ids[:,m]=j.astype(np.int16)
    # All market priorities normalized relative to their sample median
    # on training-forward predictions, preventing rare payout units from
    # dominating every slate simply by scale. No paid labels used.
    vals[:,m]=fused[np.arange(n),j]
    outcomes[:,m]=cash[idx,j]
  return ids,vals,outcomes
def group(races,idx):
  by=collections.defaultdict(list)
  for k,i in enumerate(idx):
    r=races[int(i)]
    by[(r["day"],str(r["venue"]))].append(k)
  return [np.asarray(v,dtype=np.int32) for v in by.values()]
def select(grouping,scores,k):
  return np.concatenate([np.asarray(sorted(g.tolist(),key=lambda i:(-scores[i],i))[:k],
                              dtype=np.int32) for g in grouping])
def apply(races,cash,idx,pred,rule):
  ids,score,paid=max_by_market(cash,idx,pred,rule["alpha"],rule["downside"],
    rule["hitPower"],rule["frontier"])
  grp=group(races,idx);quarts=np.asarray([(int(races[int(i)]["month"][4:])-1)//3
       for i in idx],dtype=np.int8)
  if any(len(g)<rule["racesPerVenueDay"] for g in grp):
    raise RuntimeError("FORWARD_VENUE_DAY_NOT_COMPLETE")
  picks=[];ret=[]
  for g in grp:
    quarter=int(quarts[g[0]])
    a,b=rule["pairPerQuarter"][quarter]
    x,y=rule["stakeSplit"]
    priority=score[:,a]+score[:,b]
    for t in sorted(g.tolist(),key=lambda i:(-priority[i],i))[:rule["racesPerVenueDay"]]:
      row=races[int(idx[t])]
      pa=int(paid[t,a])*(x//100)+int(paid[t,b])*(y//100)
      ret.append(pa)
      picks.append({"raceId":row["id"],"year":int(row["month"][:4]),
        "quarter":quarter+1,"day":row["day"],"venue":row["venue"],"raceNo":row["raceNo"],
        "marketA":TYPES[a],"marketB":TYPES[b],"ticketA":int(ids[t,a]),
        "ticketB":int(ids[t,b]),"stakeA":x,"stakeB":y,
        "paidYen":pa})
  return picks,money(ret)
def grid(races,cash,idx,pred):
  grp=group(races,idx);quarts=np.asarray([(int(races[int(i)]["month"][4:])-1)//3
       for i in idx],dtype=np.int8)
  if len(grp)<120 or any(len(g)<5 for g in grp):
    raise RuntimeError("NOT_ALL_2022_RACE_PROGRAMS_AVAILABLE")
  seen=0;frozen=0;best=None;qual=0
  # Five ALPHAS x four downside x three hit weighting
  # x four within-market nomination policies x three slate sizes
  # x five splits x 15 pair action choices. Regime vector among 15^4
  # represented EXACTLY by disjoint seasonal payout maximization.
  for alpha in ALPHAS:
   for down in DOWNSIDE:
    for h in HITS:
     for frontier in FRONTIERS:
      ids,score,paid=max_by_market(cash,idx,pred,alpha,down,h,frontier)
      # Scale per market by median positive expected cash to avoid market
      # payout magnitude being a proxy for confidence in selection.
      med=np.maximum(np.median(score,axis=0),1e-6)
      normalized=score/med
      for count in PER_DAY:
       for x,y in SPLITS:
        evaluated=[]
        for a,b in PAIRS:
          signals=normalized[:,a]+normalized[:,b]
          take=select(grp,signals,count)
          ret=paid[take,a]*(x//100)+paid[take,b]*(y//100)
          qs=quarts[take]
          evaluated.append((a,b,take,ret,qs))
          seen+=1
        # Quarter-specific market pair switching, but stable parameters
        # across all quarters. Labels from 2023+ are never inspected.
        chosen=[]
        for q in range(4):
          candidates=[z for z in evaluated if np.count_nonzero(z[4]==q)>=100]
          if not candidates:break
          bestq=max(candidates,key=lambda z:(
             int(z[3][z[4]==q].sum())-int(z[3][z[4]==q].max()),
             np.count_nonzero(z[3][z[4]==q])))
          chosen.append(bestq)
        if len(chosen)!=4:continue
        returns=np.concatenate([z[3][z[4]==q] for q,z in enumerate(chosen)])
        result=money(returns);frozen+=1
        if qualifies(result):
          qual+=1
          candidate={"alpha":alpha,"downside":down,"hitPower":h,
             "frontier":frontier,"racesPerVenueDay":count,
             "stakeSplit":[x,y],
             "pairPerQuarter":[[int(z[0]),int(z[1])] for z in chosen],
             "validation":result,"quality":result["minusLargestRaceRoiPct"]}
          if best is None or candidate["quality"]>best["quality"]:
             best=candidate
  return best,{"singleMarketPairEvaluations":seen,"quarterlyPortfolioStrategies":frozen,
     "representedQuarterlyPairSchedules":frozen*15**4,
     "eligibleWithAll200AndHit20":qual,
     "selectedWithoutLookingAt2023Plus":True}
def main():
  if "--self-test" in sys.argv:
    assert sum(hi-lo for lo,hi in B)==336
    assert len(PAIRS)==15
    assert len(ALPHAS)*len(DOWNSIDE)*len(HITS)*len(FRONTIERS)*len(PER_DAY)*len(SPLITS)*len(PAIRS)==54000
    assert not qualifies({"races":350,"roiPct":700,"minusLargestRaceRoiPct":199,"hitRacePct":50})
    assert qualifies({"races":350,"roiPct":210,"minusLargestRaceRoiPct":200,"hitRacePct":20})
    print("CONSENSUS_CASH_GATE_AND_ACTION_GRID_TEST_OK");return
  start=time.monotonic()
  base=mod()
  races,cash,attrs,types,years,keys=base.obtain()
  if "formIdentityMatched" in keys:
    keys=tuple(k for k in keys if k!="formIdentityMatched")
  print("CONSENSUS_CASH_FAMILY",json.dumps({"races":len(races),
       "unrestrictedRank7Tickets":int(cash.size),
       "preRaceFormFeatures":len(keys),
       "missingHistoricalOfficialT15":True},ensure_ascii=False),flush=True)
  models=base.train(cash,attrs,types,years,keys,TRAIN)
  idx,pred=base.infer(models,attrs,types,keys,years,2022)
  candidate,counts=grid(races,cash,idx,pred)
  report={"status":"SEARCH_FAMILY_REJECTED_NOT_A_MODEL","adoptedModel":False,
    "productionUnchanged":True,
    "generator":"two-independent-cash-head disagreement and payout-event hedge",
    "trainingYears":list(TRAIN),"validationYear":2022,
    "officialT15OddsVerified":False,
    "payoutOfficiallyJraReconciled":False,
    "exposedLaterDataFromEarlierResearch":True,
    "coverageOnlyThrough2026April":True,
    "validationDesigns":counts,
    "acceptedCandidate":None}
  if candidate is not None:
    report["acceptedCandidate"]=candidate
    del models
    full=base.train(cash,attrs,types,years,keys,FINAL_TRAIN)
    cash_rows=[];by_year={}
    for y in TEST:
      ix,p=base.infer(full,attrs,types,keys,years,y)
      rows,m=apply(races,cash,ix,p,candidate)
      cash_rows+=rows;by_year[str(y)]=m
      print("CONSENSUS_CASH_HELDOUT_YEAR",json.dumps({"year":y,"cash":m}),flush=True)
    total=money([z["paidYen"] for z in cash_rows])
    # All 4 test periods and aggregate must pass; 2026 is Jan-Apr.
    ok=qualifies(total) and all(
      v["races"]>=30 and v["roiPct"]>=200 and
      v["minusLargestRaceRoiPct"]>=200 and v["hitRacePct"]>=20
      for v in by_year.values())
    report.update({"status":"NUMERIC_PASS_NOT_JRA_T15" if ok
        else "SEARCH_FAMILY_REJECTED_NOT_A_MODEL",
       "frozenHoldoutMoney":total,"frozenHoldoutYears":by_year,
       "numericIndependentYearsPassed":bool(ok)})
    if cash_rows:
       LEDGER.parent.mkdir(parents=True,exist_ok=True)
       with LEDGER.open("w",encoding="utf8",newline="") as f:
          w=csv.DictWriter(f,fieldnames=list(cash_rows[0]));w.writeheader();w.writerows(cash_rows)
  report["seconds"]=round(time.monotonic()-start,3)
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
  print("CONSENSUS_CASH_FINAL",json.dumps({
    "status":report["status"],"200Qualified":candidate is not None,
    "gridSize":counts["singleMarketPairEvaluations"],
    "representedSwitches":counts["representedQuarterlyPairSchedules"],
    "productionUnchanged":True,"elapsed":report["seconds"]},
    ensure_ascii=False),flush=True)
if __name__=="__main__":main()
