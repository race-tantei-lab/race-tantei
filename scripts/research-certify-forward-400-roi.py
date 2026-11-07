#!/usr/bin/env python3
"""Research-only 400%-ROI gate on *future*, immutable, T-15 shadow results.

No model fitting, no historical backfills, no D1 writes, no Worker deployment.
Takes a JSON report from audit-live-shadow-portfolio-roi.py. That upstream
auditor already checks pre-T-15 lock times, two distinct ticket types,
immutable live tickets, stored JRA settlement and no backfill.

This additional gate rejects small samples, missing races, incomplete
comparison, one-off winners and an in-sample policy selection. It can return
RESEARCH_GATE_PASSED, but NEVER performs or authorizes production promotion.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

EARLIEST_PREDECLARED_DATE = "2026-11-08"
EXPECTED_STAKE_PER_RACE = 2000
TARGET_ROI_PCT = 400.0
MIN_DATES = 24
MIN_RACES = 300
MIN_QUARTILE_DATES = 6
MAX_SINGLE_RACE_PAYOUT_SHARE = 0.20
POLICIES = ("market_implied_only", "market_blend_30pct_model")

def reject_reasons(report, policy):
    reasons = []
    if report.get("basis") != "strict-same-race-pre-T15-official-odds-shadow-vs-actual-no-missing-backfill":
        reasons.append("UNVERIFIED_SOURCE_PROVENANCE")
    if report.get("shadowOnlyNotActualBets") is not True:
        reasons.append("SHADOW_PUBLIC_BET_INTEGRITY_UNVERIFIED")
    if report.get("payoutSource") != "persisted JRA D1 payout table, not externally JRA-reverified":
        reasons.append("UNEXPECTED_PAYOUT_PROVENANCE")
    excluded = report.get("excluded")
    if not isinstance(excluded, dict) or any(type(v) is not int or v < 0 for v in excluded.values()):
        reasons.append("INVALID_EXCLUSION_COUNTERS")
    elif sum(excluded.values()):
        reasons.append("ANY_MISSING_LATE_UNSETTLED_OR_INVALID_RACE")
    totals = report.get("total")
    daily = report.get("byDate")
    if not isinstance(totals,dict) or not isinstance(daily,dict):
        return reasons+["MISSING_TOTALS_OR_DAILY_BREAKDOWN"], None
    candidate = totals.get(policy)
    current = totals.get("canonical")
    if not isinstance(candidate,dict) or not isinstance(current,dict):
        return reasons+["MISSING_CANDIDATE_OR_CANONICAL"], None
    dates=sorted(daily)
    if len(dates)<MIN_DATES:
        reasons.append("TOO_FEW_INDEPENDENT_RACE_DATES")
    if any(not (len(d)==10 and EARLIEST_PREDECLARED_DATE<=d) for d in dates):
        reasons.append("HISTORICAL_OR_INVALID_DATE")
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    if any(d>=now.isoformat() for d in dates):
        reasons.append("UNFINISHED_CURRENT_OR_FUTURE_RACE_DATE")
    if int(candidate.get("races") or 0)<MIN_RACES:
        reasons.append("INSUFFICIENT_FUTURE_RACES")
    n=int(candidate.get("races") or 0)
    stake=int(candidate.get("stakeYen") or 0)
    payout=int(candidate.get("returnYen") or 0)
    if stake != EXPECTED_STAKE_PER_RACE*n or payout<0:
        reasons.append("INVALID_FROZEN_STAKE_OR_PAYOUT")
    if int(current.get("races") or -1)!=n:
        reasons.append("ACTUAL_AND_SHADOW_RACE_SET_NOT_MATCHED")
    if not dates or any(not isinstance(daily[d],dict) or policy not in daily[d] or "canonical" not in daily[d] for d in dates):
        return reasons+["MISSING_PAIRED_DAILY_RECORD"], None
    # Reconstruct and reconcile all money rather than accepting a stated ROI.
    rows=[]
    for date in dates:
        p=daily[date][policy]
        base=daily[date]["canonical"]
        try:
            count=int(p["races"])
            s=int(p["stakeYen"])
            ret=int(p["returnYen"])
            bc=int(base["races"])
        except (KeyError, ValueError, TypeError):
            return reasons+["INVALID_DAILY_ROI"], None
        if count != bc or count<1 or s!=count*EXPECTED_STAKE_PER_RACE or ret<0:
            reasons.append("UNPAIRED_OR_INVALID_DAILY_STAKE")
        rows.append((date,count,s,ret))
    if (sum(x[1] for x in rows)!=n or sum(x[2] for x in rows)!=stake
            or sum(x[3] for x in rows)!=payout):
        reasons.append("TOTAL_DAILY_RECONCILIATION_FAILED")
    roi=round(100*payout/stake,4) if stake>0 else 0.0
    if roi<TARGET_ROI_PCT:
        reasons.append("ROI_BELOW_400_PCT")
    # Fixed 4 equal-duration-by-racing-day intervals, no hindsight dates.
    groups=[rows[i*len(rows)//4:(i+1)*len(rows)//4] for i in range(4)]
    group_roi=[]
    for group in groups:
        if len(group)<MIN_QUARTILE_DATES:
            reasons.append("INSUFFICIENT_TIME_BLOCK")
        s=sum(x[2] for x in group)
        r=sum(x[3] for x in group)
        v=round(100*r/s,4) if s else 0.0
        group_roi.append(v)
        if v<TARGET_ROI_PCT:
            reasons.append("ONE_OR_MORE_CHRONOLOGICAL_QUARTERS_BELOW_400")
    # A single 24-day block cannot independently identify largest race payout.
    # Upstream daily data can still guard against a single racing date
    # explaining the full gain. Stronger per-ticket checks remain mandatory.
    positive=sum(max(0,x[3]-x[2]) for x in rows)
    largest=max((max(0,x[3]-x[2]) for x in rows),default=0)
    if positive==0 or largest/positive>MAX_SINGLE_RACE_PAYOUT_SHARE:
        reasons.append("PROFIT_CONCENTRATED_IN_ONE_DAY")
    summary={"policy":policy, "observedRoiPct":roi,
        "raceDates":len(dates),"races":n,
        "quartileRoiPct":group_roi,"largestPositiveDayShare":round(largest/positive,6) if positive else 1.0,
        "researchGatePassed":not bool(reasons),
        "productionPromotionAuthorized":False,
        "notMarketOrFutureGuarantee":True}
    return sorted(set(reasons)),summary

def evaluate(report):
    results={}
    for policy in POLICIES:
        reasons,summary=reject_reasons(report,policy)
        results[policy]={"passed":not reasons,"reasons":reasons,"metrics":summary}
    return {"status":"RESEARCH_ONLY_400_ROI_GATE",
        "researchPassAnyPolicy":any(x["passed"] for x in results.values()),
        "policies":results,"productionPromotionAuthorized":False,
        "note":"A historical gate alone cannot guarantee any future profit or permit deployment."}

def self_test():
    days=[str(dt.date(2026,11,8)+dt.timedelta(days=i)) for i in range(24)]
    # Deterministic synthetic fixture tests only; not historical evidence.
    # To ensure all dates are before NOW, use date checker separately.
    report={"basis":"strict-same-race-pre-T15-official-odds-shadow-vs-actual-no-missing-backfill",
        "shadowOnlyNotActualBets":True,
        "payoutSource":"persisted JRA D1 payout table, not externally JRA-reverified",
        "excluded":{"shadow_not_captured":2},
        "total":{"canonical":{"races":300,"stakeYen":600000,"returnYen":200000},
           "market_implied_only":{"races":300,"stakeYen":600000,"returnYen":3050000},
           "market_blend_30pct_model":{"races":300,"stakeYen":600000,"returnYen":3000000}},
        "byDate":{d:{
            "canonical":{"races":12 if i!=23 else 24,"stakeYen":24000 if i!=23 else 48000,"returnYen":0},
            "market_implied_only":{"races":12 if i!=23 else 24,"stakeYen":24000 if i!=23 else 48000,
                 "returnYen":120000 if i!=23 else 240000},
            "market_blend_30pct_model":{"races":12 if i!=23 else 24,"stakeYen":24000 if i!=23 else 48000,
                 "returnYen":120000 if i!=23 else 240000}
        } for i,d in enumerate(days)}}
    # The synthetic fixture is intentionally not completable today and has
    # invalid totals/exclusions. The gate MUST block it.
    result=evaluate(report)
    assert not result["researchPassAnyPolicy"]
    for name in POLICIES:
        assert "ANY_MISSING_LATE_UNSETTLED_OR_INVALID_RACE" in result["policies"][name]["reasons"]
        assert "UNFINISHED_CURRENT_OR_FUTURE_RACE_DATE" in result["policies"][name]["reasons"]
    assert "TOTAL_DAILY_RECONCILIATION_FAILED" in result["policies"]["market_implied_only"]["reasons"]
    assert "TOTAL_DAILY_RECONCILIATION_FAILED" not in result["policies"]["market_blend_30pct_model"]["reasons"]
    # A forged high stated ROI without any evidence must also fail.
    assert not evaluate({"total":{"market_implied_only":{"roiPct":10000}}})["researchPassAnyPolicy"]
    print("STRICT_400_ROI_RESEARCH_GATE_SELFTEST_OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.self_test:
        self_test();return
    if args.input is None:
        parser.error("--input JSON report is required")
    result=evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+"\n",encoding="utf-8")
    print("STRICT_400_ROI_RESEARCH_GATE",text)
    if not result["researchPassAnyPolicy"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
