#!/usr/bin/env python3
"""True chronological out-of-period audit of the historical joint ROI200 claim.

The other MILP program selects 31 venue-quarter actions using the payout
outcomes of ALL years, hence its 501% apparent return is in-sample selection.
Here:
 - Generate base ticket experts with prior-month outcomes only.
 - Limit joint MILP selection to historical races through 2024-12.
 - Freeze the policy switches before seeing 2025 or 2026 payouts.
 - Replay every 2025-Jan..2026-Apr venue-day and calculate true cash return,
   minus the largest payout, hit percentage and coverage.
 - Never use holdout money in selection or retrain the switch based on holdout.
 - Never claim production readiness from POST-RACE FINAL odds; T-15 still needed.
This is one 2025/2026 time split, not a pristine prospective future proof.
"""
from __future__ import annotations
import collections
import csv
import gzip
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"analysis-results/20261114-chronological-joint-oos-2025-2026.json"
LEDGER = ROOT/"analysis-results/20261114-chronological-joint-oos-2025-2026-ledger.csv.gz"
TRAIN_THROUGH = "202412"
TEST_FROM = "202501"
TEST_THROUGH = "202604"


def imported(path, name):
    f = ROOT / path
    spec = importlib.util.spec_from_file_location(name, f)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def replay(base, races, payouts, picked, scores, rules):
    # Never call the optimizer inside this routine. Frozen research rules only.
    by_cell = collections.defaultdict(list)
    for i,race in enumerate(races):
        cell = int(race["venue"])*4+(int(race["month"][4:])-1)//3
        by_cell[cell].append(i)
    if not by_cell:
        raise RuntimeError("HOLDOUT_EMPTY")
    if not set(by_cell) <= set(rules):
        raise RuntimeError(f"HOLDOUT_VENUE_QUARTER_MISSING_FROZEN_RULE:{set(by_cell)-set(rules)}")
    ledger=[]
    for cell, indices in sorted(by_cell.items()):
        config = rules[cell]["policy"]
        mode = base.MODES.index(config["forecast"])
        ix = np.asarray(indices,dtype=np.int32)
        rr = [races[int(i)] for i in ix]
        base._group_memory.clear()
        if hasattr(base.policy_arrays, "_cells"):
            delattr(base.policy_arrays, "_cells")
        money, rows = base.policy_arrays(
            rr, payouts[ix], picked[ix,mode], scores[ix,mode],
            base.MASKS[config["marketSubset"]], config["stakePlan"],
            config["raceSlate"],
            "top_margin" if config["selection"]=="top_margin" else "top_score",
            "top_score_plus_positive" if config["selection"]=="top_score_plus_positive" else "top_score",
            ledger=True)
        if money is None or not rows or len(rows) < 3*money["venueDays"]:
            raise RuntimeError(f"INCOMPLETE_FROZEN_HOLDOUT_CELL:{cell}")
        ledger.extend(rows)
    if len({r["raceId"] for r in ledger}) != len(ledger):
        raise RuntimeError("DUPLICATE_HELDOUT_RACE")
    return ledger


def metrics(ledger):
    if not ledger:
        return {"status": "NO_CASH_LEDGER"}
    stake = sum(int(r["costYen"]) for r in ledger)
    paid = sum(int(r["paidYen"]) for r in ledger)
    max_payout = max(int(r["paidYen"]) for r in ledger)
    hit = sum(int(r["hit"]) for r in ledger)
    days = collections.Counter((r["date"],str(r["venue"])) for r in ledger)
    if min(days.values()) < 3:
        raise RuntimeError("FEWER_THAN_THREE_RACES_PER_VENUE_DAY")
    out = {
        "races":len(ledger),"venueDays":len(days),
        "stakeYen":stake,"paidYen":paid,
        "profitYen":paid-stake,
        "largestPaidRaceYen":max_payout,
        "cashRoiPct":round(100*paid/stake,5),
        "minusLargestRaceCashRoiPct":round(100*(paid-max_payout)/stake,5),
        "hitRaces":hit,"hitRacePct":round(100*hit/len(ledger),5),
        "minimumRacesPerVenueDay":min(days.values()),
    }
    out["passesCash200Hit20"] = (out["cashRoiPct"]>=200 and
                                out["minusLargestRaceCashRoiPct"]>=200 and
                                hit*5>=len(ledger))
    return out


def self_test():
    # The holdout gate must reject 501% aggregate if any chronological
    # holdout underperforms, regardless of training optimization.
    led = []
    for y, pay in (("2025", 0), ("2026", 2000)):
        for i in range(3):
            led.append({"raceId":f"{y}{i}","date":y+"01-"+str(i//3),
                        "venue":"tokyo","costYen":100,
                        "paidYen":pay if i==0 else 0,
                        "hit":int(pay>0 and i==0)})
    s=metrics(led)
    assert s["cashRoiPct"]>200
    assert not s["passesCash200Hit20"]
    assert s["minimumRacesPerVenueDay"]==3
    print("CHRONOLOGICAL_JOINT_HOLDOUT_GATE_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    t0=time.monotonic()
    milp=imported("scripts/research-20261114-joint-all-history-money-milp.py", "old_joint_milp")
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py","cash_base_for_chronological_holdout")
    core,races,payout,features,market,slots=base.historic_cash()
    picks,score,_,months=base.monthly_frozen_predictions(races,payout,features,market,slots)
    if len(months)!=136:
        raise RuntimeError("NOT_FULL_136_MONTH_DATA")
    train_ix=np.asarray([i for i,r in enumerate(races) if str(r["month"])<=TRAIN_THROUGH],dtype=np.int32)
    test_ix=np.asarray([i for i,r in enumerate(races) if TEST_FROM<=str(r["month"])<=TEST_THROUGH],dtype=np.int32)
    if len(train_ix)<25000 or len(test_ix)<2500 or len(set(train_ix)&set(test_ix)):
        raise RuntimeError(f"INVALID_TRAIN_TEST_SPLIT:{len(train_ix)}:{len(test_ix)}")
    rr=[races[int(i)] for i in train_ix]
    rs=[races[int(i)] for i in test_ix]
    base._group_memory.clear()
    if hasattr(base.policy_arrays,"_cells"):
        delattr(base.policy_arrays,"_cells")
    options, scanned=milp.build_options(base,rr,payout[train_ix],picks[train_ix],score[train_ix])
    audits=[]
    bestledger=None
    for alpha in (1.,1.2,2.):
        frozen,solver = milp.solve(options,alpha)
        if not frozen:
            audits.append({"trainObjective":alpha,"noQualifiedTrainingPolicy":True,
                           "solver":solver})
            continue
        # ONLY frozen training policies go into the target evaluation.
        led=replay(base,rs,payout[test_ix],picks[test_ix],score[test_ix],frozen)
        metrics_all=metrics(led)
        yr={y:metrics([r for r in led if str(r["date"])[:4]==y])
            for y in ("2025","2026")}
        accepted=(metrics_all["passesCash200Hit20"]
                  and all(m.get("passesCash200Hit20",False) for m in yr.values()))
        audits.append({
            "trainObjective":alpha,
            "historicalTraining":solver.get("qualifiedActualMoney"),
            "chronologicalHoldout":metrics_all,
            "holdoutYears":yr,
            "acceptAsIndependentlyValidatedCashModel":accepted,
            "historicalFinalOddsNotT15":True,
        })
        if bestledger is None:
            bestledger=led
        print("FROZEN_JOINT_CASH_2025_2026_HOLDOUT",json.dumps(audits[-1],ensure_ascii=False),flush=True)
    result={
        "researchOnly":True,"productionChanged":False,
        "timeSplit":{"trainThrough":TRAIN_THROUGH,"holdoutFrom":TEST_FROM,
                     "holdoutThrough":TEST_THROUGH,
                     "trainRaces":len(train_ix),"holdoutRaces":len(test_ix)},
        "policyChosenWithHoldoutOutcomes":False,
        "monthlyTicketExpertUsesPreviousMonthsOnly":True,
        "currentAndFutureMonthPayoutUsedForExperts":False,
        "officialT15OddsReconciled":False,
        "source":"THIRD_PARTY_RETROSPECTIVE_FINAL_ODDS_UNRECONCILED",
        "baseCalculations":scanned,"runs":audits,
        "productionPromotionAllowed":False,
        "elapsedSeconds":round(time.monotonic()-t0,2),
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if bestledger:
        with gzip.open(LEDGER,"wt",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(bestledger[0]))
            writer.writeheader()
            writer.writerows(sorted(bestledger,key=lambda x:x["raceId"]))
    print("FROZEN_JOINT_CASH_OOS_FINAL",json.dumps({
        "status":"TESTED_WITH_HOLDOUT",
        "trainingPolicies":sum(bool(r.get("historicalTraining")) for r in audits),
        "holdoutCash200Candidates":sum(bool(r.get("acceptAsIndependentlyValidatedCashModel")) for r in audits),
        "historicalFinalOddsNotT15":True,"productionPromotionAllowed":False,
        "seconds":result["elapsedSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
