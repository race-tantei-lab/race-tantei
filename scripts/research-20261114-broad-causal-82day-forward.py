#!/usr/bin/env python3
"""Independently apply full-136-month frozen cash-sweep policies to 2026 Aug-Nov.

All training uses ONLY 2015-Jan..2026-Apr actual payouts. 2026 Aug-Nov JRA
official historical FINAL win odds and actual settled payout data are loaded
AFTER the 136-month historical policy has been selected. No retraining on
August-Nov results and NO D1/production writes.

IMPORTANT: 82 venue-days means >=3 eligible races per venue-day; it is not a
claim that every 2026 individual payout/result row is complete.
"""
from __future__ import annotations
import importlib.util,json,sys,collections
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"analysis-results/20261114-broad-causal-cash-sweep.json"
OUT=ROOT/"analysis-results/20261114-broad-causal-cash-forward-82day.json"
def load(path,name):
    m=importlib.util.spec_from_file_location(name,ROOT/path)
    if m is None or m.loader is None:raise RuntimeError("MODULE_MISSING:"+path)
    obj=importlib.util.module_from_spec(m);sys.modules[name]=obj
    m.loader.exec_module(obj);return obj
def main():
    broad=load("scripts/research-20261114-broad-causal-cash-sweep.py","frozen_comprehensive_cash_search")
    if "--self-test" in sys.argv:
       broad.selftest()
       print("BROAD_CAUSAL_82DAY_FORWARD_INDEPENDENCE_SELFTEST_OK",flush=True)
       return
    prior=json.loads(SOURCE.read_text(encoding="utf8"))
    chosen=prior["forwardFrozenPolicy"]
    if not chosen or chosen["policy"] is None:raise RuntimeError("HISTORICAL_CASH_POLICY_NOT_FROZEN")
    if not prior["all136MonthPredictionsBeforeSameMonthOutcome"]:
       raise RuntimeError("INVALID_PRIOR_HISTORY_LEAK_GUARD")
    core,hist,payout,feat,market,slots=broad.historic_cash()
    _,_,states,months=broad.monthly_frozen_predictions(hist,payout,feat,market,slots)
    if len(months)!=136 or any(int(x)>=202608 for x in months):
       raise RuntimeError("FUTURE_SETTLEMENT_ENTERED_TRAINING")
    # Fetch real six-market payouts and official JRA full-field final win odds
    # only AFTER history states and policy freeze.
    provider=load("scripts/research-20261114-net-profit-first-forward.py","jra_completed_actual_cash_readonly")
    fwd,coverage=provider.d1_races()
    saved_cache,saved_racecache=core.CACHE,core.RACE_CACHE
    try:
      core.CACHE=ROOT/"analysis-results/20261114-broad-forward-feature-matrix.npz"
      core.RACE_CACHE=ROOT/"analysis-results/20261114-broad-forward-races.json"
      core.CACHE.parent.mkdir(parents=True,exist_ok=True)
      core.full_features(fwd)
      with np.load(core.CACHE,allow_pickle=False) as data:
         forward_cash=np.asarray(data["payout"],dtype=np.int32)
         forward_features={k:np.asarray(data[k],dtype=np.uint8) for k in broad.FEATURES}
    finally:
      core.CACHE=saved_cache
      core.RACE_CACHE=saved_racecache
    if len(fwd)!=forward_cash.shape[0] or forward_cash.shape[1]!=1030:
       raise RuntimeError("FORWARD_PAYOUT_ALIGNMENT_FAILED")
    n=len(fwd)
    sc=broad.month_scores(states,forward_features,market,slots,
           np.arange(1030,dtype=np.int32)[None,:])
    winners=np.empty((n,len(broad.MODES),6),dtype=np.int16)
    scores=np.empty((n,len(broad.MODES),6),dtype=np.float32)
    for m in range(6):
        templates=np.flatnonzero(market==m)
        k=np.argmax(sc[:,:,templates],axis=2)
        winners[:,:,m]=templates[k]
        scores[:,:,m]=np.take_along_axis(sc[:,:,templates],k[:,:,None],axis=2)[:,:,0]
    track=prior["realMoneySearch"]
    review=[chosen]
    # Audit every historical all-gate candidate individually, without
    # selecting based on forward outcome; additionally inspect a few
    # diverse cash/hit benchmarks as diagnostics (NOT adopted models).
    seen={json.dumps(chosen["policy"],sort_keys=True)}
    for x in (track.get("qualified") or [])[:30]+[
          track.get("bestProfitDiagnostic"),track.get("bestWith20PercentHits")]:
       if not x:continue
       fingerprint=json.dumps(x["policy"],sort_keys=True)
       if fingerprint in seen:continue
       seen.add(fingerprint);review.append(x)
    result=[]
    for i,x in enumerate(review):
      cash,ledger=broad.config_replay(fwd,forward_cash,winners,scores,x["policy"])
      bymonth=collections.defaultdict(lambda:{"races":0,"hit":0,"profitable":0,"stakeYen":0,"paidYen":0})
      for bet in ledger:
          month=str(bet["date"])[:7]
          item=bymonth[month]
          item["races"]+=1;item["hit"]+=bet["hit"];item["profitable"]+=bet["profitable"]
          item["stakeYen"]+=bet["costYen"];item["paidYen"]+=bet["paidYen"]
      for q in bymonth.values():
          q["roiPct"]=round(100*q["paidYen"]/q["stakeYen"],4)
          q["hitPct"]=round(100*q["hit"]/q["races"],4)
          q["profitYen"]=q["paidYen"]-q["stakeYen"]
      result.append({"frozenPolicy":x["policy"],
         "historicalActualCash":x["money"],
         "forwardActualCash":cash,
         "forwardCash200Hit20Qualified":broad.full_ok(cash),
         "monthly":dict(sorted(bymonth.items()))})
      print("COMPREHENSIVE_FROZEN_POLICY_FORWARD",json.dumps({
        "i":i+1,"past":x["money"],"postAugust":cash,
        "allCashGatesMet":broad.full_ok(cash)},ensure_ascii=False),flush=True)
    report={"status":"COMPLETE_CROSS_PERIOD_READ_ONLY_AUDIT",
       "period":"2026-08-01..2026-11-13",
       "all136MonthsOfEarlierHistoryTrained":True,
       "selectionFrozenBeforeReading2026AugOnwardOutcome":True,
       "dataCoverage":coverage,
       "officialHistoricalFinalWinOddsNotTminus15":True,
       "noD1Writes":True,"noProductionChange":True,
       "candidatePoliciesInHistoricalResearch":track["fullPeriodCash200Hit20Qualified"],
       "forwardCash200Hit20QualifiedCount":sum(x["forwardCash200Hit20Qualified"] for x in result),
       "reviewed":result}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("BROAD_CASH_FORWARD_FINAL",json.dumps({
      "reviewed":len(result),
      "historicallyQualified":track["fullPeriodCash200Hit20Qualified"],
      "forward200Qualified":report["forwardCash200Hit20QualifiedCount"],
      "forwardCashTop":result[0]["forwardActualCash"],
      "venueDays":coverage["fullVenueDaysWithMinimumThreeEligibleRaces"],
      "remainingMissingResults":coverage["stillMissingActualResultOrCash"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
