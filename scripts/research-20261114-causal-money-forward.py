#!/usr/bin/env python3
"""Read-only independent Aug-Nov cash replay for causal prior-month-only engine.

No policy or cash learning may read 2026 Aug+ results. 2026-Aug-Nov official
historical FINAL win odds are NOT proven available 15 minutes before start.
Historical 2015-Jan..2026-Apr data freezes all cash models and policy first.
"""
from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"analysis-results/20261114-causal-money-only-full-history.json"
OUT=ROOT/"analysis-results/20261114-causal-money-2026-aug-nov-forward.json"
def imp(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path)
    if s is None or s.loader is None:raise RuntimeError("MODULE_MISSING:"+path)
    m=importlib.util.module_from_spec(s);sys.modules[name]=m
    s.loader.exec_module(m);return m
def main():
    core=imp("scripts/research-20261114-causal-money-engine.py","actual_causal_prior_month_cash")
    if "--self-test" in sys.argv:
        core.selftest()
        print("CAUSAL_FORWARD_NO_POST_AUG_TRAINING_SELFTEST_OK",flush=True)
        return
    history=json.loads(HIST.read_text(encoding="utf8"))
    candidate_list=history["realMoneyQualifyingCandidates"]
    selection=(candidate_list[0] if candidate_list else history["bestCashDiagnosticOnly"])
    if not selection:raise RuntimeError("NOTHING_TO_FORWARD_AUDIT")
    chosen=selection["configuration"]
    # This is a diagnostic when there is no 200%-ROI + hit20 candidate.
    approved_historical=bool(candidate_list)
    module,races,payout,cat,tpl,market=core.load_historical()
    _,_,states,months=core.predict_past_months(races,payout,cat,tpl,market)
    if "2026-08" in months or any(str(k)>="2026-08" for k in months):
        raise RuntimeError("POST_AUGUST_OUTCOME_ENTERED_MODEL")
    # JRA odds and settlements are retrieved solely to calculate the
    # OTHER period's decisions & realized cash. NOT training or tuning.
    source=imp("scripts/research-20261114-net-profit-first-forward.py","cash_jra_readonly_recovery")
    live,coverage=source.d1_races()
    old_cache,old_race_cache=module.CACHE,module.RACE_CACHE
    try:
        module.CACHE=ROOT/"analysis-results/20261114-causal-money-forward-matrix.npz"
        module.RACE_CACHE=ROOT/"analysis-results/20261114-causal-money-forward-races.json"
        module.CACHE.parent.mkdir(parents=True,exist_ok=True)
        module.full_features(live)
        with np.load(module.CACHE,allow_pickle=False) as z:
            forward_pay=np.asarray(z["payout"][:,tpl],dtype=np.int32)
            forward_cat={k:np.asarray(z[k][:,tpl],dtype=np.uint8) for k in core.CARD}
    finally:
        module.CACHE,module.RACE_CACHE=old_cache,old_race_cache
    scores=core.calculate_month_scores(states,forward_cat,
        np.arange(len(tpl),dtype=np.int32)[None,:],market,core.VARIANTS)
    bids,roi=core.choose_markets(scores,market,tpl)
    audit,ledger=core.digest_policy(live,bids,roi,forward_pay,tpl,market,chosen,True)
    bymonth={}
    for row in ledger:
        month=str(row["raceId"])[:7] if row["raceId"].startswith("2026-") else str(row["group"][0])[:7]
        m=bymonth.setdefault(month,{"races":0,"hits":0,"profitableRaces":0,"stakeYen":0,"paidYen":0})
        m["races"]+=1;m["hits"]+=row["hit"];m["profitableRaces"]+=row["profitableRace"]
        m["stakeYen"]+=row["stakeYen"];m["paidYen"]+=row["paidYen"]
    for m in bymonth.values():
        m["profitYen"]=m["paidYen"]-m["stakeYen"]
        m["roiPct"]=round(100*m["paidYen"]/m["stakeYen"],4)
        m["hitPct"]=round(100*m["hits"]/m["races"],4)
        m["profitableRacePct"]=round(100*m["profitableRaces"]/m["races"],4)
    result={"status":"PREVIOUS_MONTH_ONLY_FORWARD_DIAGNOSTIC",
      "historicalQualifiesCash200Hit20":approved_historical,
      "historyCash":selection["money"],
      "historicalMonthsUsedForTraining":len(months),
      "policyChosenWithoutLookingAtAugustResults":True,
      "netProfitOnlyPriority":True,
      "hitRateBonus":False,
      "policy":chosen,
      "forwardPeriod":"2026-08-01 to 2026-11-13 (as available)",
      "forwardCash":audit,"byMonth":bymonth,"dataCoverage":coverage,
      "forwardQualifiesCash200Hit20":core.qualifies(audit),
      "provenPreStart15MinuteOfficialOdds":False,
      "cashOutcomesUsedAsForwardFeature":False,
      "productionChanged":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("CAUSAL_MONEY_FORWARD_FINAL",json.dumps({
      "historyPassed":approved_historical,
      "historic":selection["money"],
      "forward":audit,"forwardMeetsAllGates":result["forwardQualifiesCash200Hit20"],
      "months":bymonth,"coverageVenueDays":coverage["fullVenueDaysWithMinimumThreeEligibleRaces"],
      "productionChanged":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
