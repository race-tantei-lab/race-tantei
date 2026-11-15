#!/usr/bin/env python3
"""Read-only ALL live race-tantei ten-year-model money from Aug 2026.

The earlier production audit sampled only the last 40 days. This
extends it through the entire real August–November operation, with
pagination and explicit missing, late or unsettled coverage instead of
implicitly treating omitted bets as losses or wins. NEVER mutate D1.
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-production-aug-nov-roi-readonly.json"


def imported():
    path=ROOT/"scripts/audit-production-live-roi-readonly.py"
    spec=importlib.util.spec_from_file_location("actual_prod_cash_audit",path)
    x=importlib.util.module_from_spec(spec);spec.loader.exec_module(x)
    return x


def all_pages(core,sql,params,limit=500,hard_cap=25000):
    out=[]
    while True:
        page=core.query(sql+" LIMIT ? OFFSET ?",[*params,str(limit),str(len(out))])
        out.extend(page)
        if len(out)>hard_cap:raise RuntimeError("PRODUCTION_READ_CAP_REACHED")
        if len(page)<limit:break
    return out


def summarize(core,states,bets):
    report=core.audit(states,bets)
    monthly={}
    for month in sorted({str(r["stateKey"])[22:29] for r in states}):
        filtered=[r for r in states if str(r["stateKey"]).startswith(
            "final_daily_selection:"+month)]
        if filtered:monthly[month]=core.audit(filtered,bets)
    report["monthly"]=monthly
    return report


def main():
    core=imported()
    now=dt.datetime.now(core.JST).date()
    end=now-dt.timedelta(days=1)
    start=dt.date(2026,8,1)
    if end<start:raise RuntimeError("NO_RECORDED_OPERATION_PERIOD")
    through=(end+dt.timedelta(days=1)).isoformat()
    states=all_pages(core,"""
        SELECT state_key AS stateKey,state_value AS stateValue
        FROM rt_system_state
        WHERE state_key>=? AND state_key<?
        ORDER BY state_key
    """,["final_daily_selection:"+start.isoformat(),
         "final_daily_selection:"+through],limit=100)
    bets=all_pages(core,"""
        SELECT race_id AS raceId,course,stake_yen AS stakeYen,
               return_yen AS returnYen,settlement_status AS settlementStatus,
               locked_at AS lockedAt
        FROM rt_public_bets
        WHERE race_id>=? AND race_id<?
              AND source_prediction_id=-2
        ORDER BY race_id,course,id
    """,[start.isoformat()+"-",through+"-"],limit=900)
    if not states:raise RuntimeError("NO_FROZEN_LIVE_SELECTION_TO_AUDIT")
    if not bets:raise RuntimeError("NO_REAL_LIVE_BETS_TO_AUDIT")
    report=summarize(core,states,bets)
    report["period"]={"start":start.isoformat(),"through":end.isoformat()}
    report["actualBetsRowsRead"]=len(bets)
    report["actualSelectionStatesRead"]=len(states)
    report["realProductionOnly"]=True
    report["researchOnly"]=True
    report["productionModified"]=False
    report["fullyVerified"]=not any(report.get(key) for key in (
       "missingCount","lateCount","unsettledCount"))
    report["profitTarget200PassedForEveryActualCourse"]=bool(
       report["fullyVerified"] and all(
           v["roiPct"] is not None and v["roiPct"]>=200
           for v in report["courses"].values()))
    report["sourceProvenance"]="D1 recorded, NOT independently reconciled with JRA external payout"
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("LIVE_AUG_NOV_PRODUCTION_CASH_READONLY_FINAL",json.dumps({
        "from":start.isoformat(),"through":end.isoformat(),
        "selectionDays":report["periodDays"],
        "selectionRaces":report["selectionRaces"],
        "missing":report["missingCount"],"late":report["lateCount"],
        "unsettled":report["unsettledCount"],
        "courseCash":report["courses"],
        "fullyVerified":report["fullyVerified"],
        "allCoursesRoi200":report["profitTarget200PassedForEveryActualCourse"]
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
