#!/usr/bin/env python3
"""Read-only, prospective 3/4/5 per-venue comparison of immutable JRA T-15 shadows.

This is a research export only, never betting, model training, backfilling or
production promotion. Reuses the official immutable market-only and 30%-model
shadow candidates already recorded by the live Worker. Queries date by date
to avoid 2500-row aggregation truncation; no output can be certified if a
selected race is missing, late, unsettled, or lacks shadow provenance.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BEGIN="2026-11-08"
JST=dt.timezone(dt.timedelta(hours=9))
POLICIES=("canonical","market_implied_only","market_blend_30pct_model")
BET_TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
LIMITS={"selection":2,"finals":70,"bets":140,"payouts":1400,"races":70}

def original_audit():
    p=ROOT/"scripts/audit-live-shadow-portfolio-roi.py"
    spec=importlib.util.spec_from_file_location("original_shadow_roi",p)
    if not spec or not spec.loader:raise RuntimeError("MISSING_CANONICAL_ROI_AUDITOR")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def read_d1(sql,params,cap):
    req=urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query",
        data=json.dumps({"sql":sql,"params":params}).encode("utf-8"),method="POST",
        headers={"Authorization":f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as response:
        data=json.loads(response.read().decode("utf-8"))
    if data.get("success") is not True:raise RuntimeError("READ_ONLY_D1_FAILURE "+str(data.get("errors"))[:450])
    result=(data.get("result") or [{}])[0].get("results") or []
    if len(result)>=cap:raise RuntimeError("D1_ROW_CAP_CANNOT_PROVE_EXHAUSTIVE_QUERY")
    return result

def fetch_day(day):
    next_day=(dt.date.fromisoformat(day)+dt.timedelta(days=1)).isoformat()
    state=read_d1(
        "SELECT state_key k,state_value v FROM rt_system_state WHERE state_key=? LIMIT 2",
        ["final_daily_selection:"+day], LIMITS["selection"])
    races=read_d1(
        """SELECT race_id raceId,race_date raceDate,status,refund_horse_nos_json refunds
        FROM rt_races WHERE race_date=? ORDER BY race_id LIMIT 70""",
        [day],LIMITS["races"])
    if not state:
        return {"selection":[],"finals":[],"bets":[],"payouts":[],"races":races}
    start,end=day+"-",next_day+"-"
    finals=read_d1(
        """SELECT state_key k,state_value v FROM rt_system_state
        WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 70""",
        ["worker_live_final:"+start,"worker_live_final:"+end],LIMITS["finals"])
    bets=read_d1(
        """SELECT race_id raceId,bet_type betType,combination,
          stake_yen stakeYen,return_yen returnYen,settlement_status settlement,
          locked_at lockedAt FROM rt_public_bets
          WHERE race_id>=? AND race_id<? AND course='ライト'
          AND source_prediction_id=-2 ORDER BY race_id,id LIMIT 140""",
        [start,end],LIMITS["bets"])
    payouts=read_d1(
        """SELECT race_id raceId,bet_type betType,combination,payout_yen payout100
        FROM rt_payouts WHERE race_id>=? AND race_id<?
        ORDER BY race_id LIMIT 1400""",
        [start,end],LIMITS["payouts"])
    return {"selection":state,"finals":finals,"bets":bets,"payouts":payouts,"races":races}

def utc_before_t15(value,day,start_jst):
    try:
        at=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
        start=dt.datetime.fromisoformat(day+"T"+str(start_jst)[:5]+":00+09:00")
        return at.tzinfo is not None and at<=start-dt.timedelta(minutes=15)
    except (ValueError,TypeError):
        return False

def ranked_selected(state):
    obj=json.loads(state["v"])
    if obj.get("sourceModel")!="ten-year-completed-model" or obj.get("resultDataUsedForTargetDay") is not False:
        raise AssertionError("SELECTION_NOT_PRE_RESULT_COMPLETED_MODEL")
    races=obj.get("selected")
    if not isinstance(races,list) or not races:
        raise AssertionError("SELECTION_EMPTY")
    by_venue=collections.defaultdict(list)
    ids=set()
    for row in races:
        rid=str(row.get("raceId") or "")
        venue=str(row.get("venue") or "")
        if rid in ids or not rid or not venue:
            raise AssertionError("SELECTION_DUPLICATE_OR_MISSING_RACE_ID")
        ids.add(rid)
        try:score=float(row["raceScore"])
        except (KeyError,ValueError,TypeError):raise AssertionError("PRE_RESULT_RACE_SCORE_MISSING") from None
        if not math.isfinite(score):raise AssertionError("INVALID_SELECTION_SCORE")
        by_venue[venue].append((score,int(row["raceNo"]),row))
    if not all(len(x)==5 for x in by_venue.values()):
        raise AssertionError("ORIGINAL_FIVE_PER_VENUE_NOT_VERIFIED")
    return {venue:[z[2] for z in sorted(rows,key=lambda x:(-x[0],x[1]))]
            for venue,rows in sorted(by_venue.items())}

def guarded_final_rows(data,by_venue,day):
    """Unsafe source or missing official settlement cannot count as a valid shadow."""
    selected={r["raceId"]:r for rows in by_venue.values() for r in rows}
    races={r["raceId"]:r for r in data["races"]}
    markets=collections.defaultdict(set)
    for p in data["payouts"]:
        markets[p["raceId"]].add(p["betType"])
    valid=[]
    invalid={}
    for row in data["finals"]:
        rid=row["k"].removeprefix("worker_live_final:")
        if rid not in selected:continue
        try:
            snap=json.loads(row["v"])
            race=selected[rid]
            times=("lockedAt","oddsFetchedAt","previewGeneratedAt")
            if not all(utc_before_t15(snap.get(t),day,race.get("startTimeJst")) for t in times):
                raise ValueError("UNVERIFIED_T15_ODDS_OR_PREVIEW")
            if (snap.get("oddsSource") not in ("jra-fast-official","jra-crawl-official")
                or not re.fullmatch(r"[0-9a-f]{64}",str(snap.get("oddsSnapshotSha256") or ""))):
                raise ValueError("OFFICIAL_ODDS_PROVENANCE_MISSING")
            if (rid not in races or races[rid].get("status")!="finished"
                or not BET_TYPES.issubset(markets[rid])):
                raise ValueError("OFFICIAL_RESULT_MARKETS_INCOMPLETE")
            shadows=snap.get("shadowResearch")
            if (not isinstance(shadows,list) or len(shadows)!=2 or
                {x.get("policy") for x in shadows}!={"market_implied_only","market_blend_30pct_model"}):
                raise ValueError("TWO_SHADOW_POLICIES_NOT_PRESENT")
            for policy in shadows:
                tickets=policy.get("tickets")
                if (not isinstance(tickets,list) or len(tickets)!=2
                    or len({t.get("betType") for t in tickets})!=2
                    or any(t.get("betType") not in BET_TYPES or not t.get("combination")
                           or not math.isfinite(float(t.get("officialOdds",float("nan"))))
                           or float(t.get("officialOdds",0))<1 for t in tickets)):
                    raise ValueError("SHADOW_TICKETS_INVALID")
        except (ValueError,TypeError,KeyError,AttributeError) as e:
            invalid[rid]=str(e) or "INVALID_FINAL_SHADOW"
            continue
        valid.append(row)
    return valid,invalid

def evaluate_day(data,day,original):
    if not data["selection"]:
        if data["races"]:
            return None,{"missingSelectionForRaceDay":1}
        return None,{}
    if len(data["selection"])!=1:
        raise AssertionError("MORE_THAN_ONE_DAILY_SELECTION_ROW")
    by_venue=ranked_selected(data["selection"][0])
    finals,bad_by_race=guarded_final_rows(data,by_venue,day)
    output={}
    for k in (3,4,5):
        chosen=[r for rows in by_venue.values() for r in rows[:k]]
        state={"k":"final_daily_selection:"+day,
               "v":json.dumps({"selected":chosen},ensure_ascii=False)}
        results=original.evaluate([state],finals,data["bets"],data["payouts"],data["races"])
        expected=len(chosen)
        actual=(results["total"].get("canonical") or {}).get("races",0)
        issues=dict(results["excluded"])
        for race in chosen:
            if race["raceId"] in bad_by_race:
                reason=bad_by_race[race["raceId"]]
                issues[reason]=issues.get(reason,0)+1
        if actual!=expected:issues["MISSING_ON_TIME_COMPLETE_RACES"]=expected-actual
        output[k]={"expected":expected,"out":results,"issues":issues}
    return output,{}

def consolidate(day_reports):
    reports={}
    for k in (3,4,5):
        totals={policy:{"races":0,"stakeYen":0,"returnYen":0} for policy in POLICIES}
        by_date={}
        excluded=collections.Counter()
        expected=0
        for day,items in sorted(day_reports.items()):
            if items is None:
                excluded["MISSING_SELECTION_RACING_DAY"]+=1
                continue
            x=items[k]
            expected+=x["expected"]
            excluded.update(x["issues"])
            current={}
            for policy in POLICIES:
                row=x["out"]["total"].get(policy,{"races":0,"stakeYen":0,"returnYen":0})
                current[policy]={key:int(row.get(key) or 0) for key in ("races","stakeYen","returnYen")}
                for key in ("races","stakeYen","returnYen"):
                    totals[policy][key]+=current[policy][key]
            # A missing candidate cannot be concealed by a successful canonical.
            if len({row["races"] for row in current.values()})!=1:
                excluded["UNPAIRED_SHADOW_DATE"]+=1
            by_date[day]=current
        reports[str(k)]={
            "basis":"strict-same-race-pre-T15-official-odds-shadow-vs-actual-no-missing-backfill",
            "shadowOnlyNotActualBets":True,
            "payoutSource":"persisted JRA D1 payout table, not externally JRA-reverified",
            "originalSelectedRacesIncluded":expected,
            "total":dict(totals),"byDate":by_date,"excluded":dict(excluded),
            "excludesUnselectedRaces":True,"researchOnly":True,
            "neverProductionPromotion":True,
        }
    return reports

def selftest():
    original=original_audit()
    d="2026-11-08"
    rows=[{"raceId":d+f"-tokyo-{i:02d}","venue":"東京","raceNo":i,
           "startTimeJst":"11:00","raceScore":10-i} for i in range(1,6)]
    sel={"k":"final_daily_selection:"+d,"v":json.dumps(
        {"sourceModel":"ten-year-completed-model","resultDataUsedForTargetDay":False,"selected":rows})}
    data={"selection":[sel],"finals":[],"bets":[],"payouts":[],"races":[]}
    out,err=evaluate_day(data,d,original)
    assert not err and out[3]["expected"]==3 and out[4]["expected"]==4 and out[5]["expected"]==5
    assert out[3]["issues"]["MISSING_ON_TIME_COMPLETE_RACES"]==3
    reports=consolidate({d:out})
    assert reports["3"]["excluded"]["MISSING_ON_TIME_COMPLETE_RACES"]==3
    assert reports["5"]["originalSelectedRacesIncluded"]==5
    assert all(not r["total"]["canonical"]["races"] for r in reports.values())
    assert utc_before_t15("2026-11-08T01:44:00Z",d,"11:00")
    assert not utc_before_t15("2026-11-08T01:46:00Z",d,"11:00")
    print("FORWARD_TOPK_SHADOW_RESEARCH_SELFTEST_OK")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--live",action="store_true")
    p.add_argument("--start",default=BEGIN)
    p.add_argument("--end-exclusive")
    p.add_argument("--output-dir",type=Path,default=ROOT/"artifacts/research-forward-topk")
    args=p.parse_args()
    if args.self_test:
        selftest();return
    if not args.live:
        p.error("live data must be requested explicitly; no background writes")
    today=dt.datetime.now(JST).date()
    start=dt.date.fromisoformat(args.start)
    end=dt.date.fromisoformat(args.end_exclusive) if args.end_exclusive else today
    if start.isoformat()<BEGIN or end>today or start>end:
        p.error("invalid future/retrospective range (must be completed future racing dates)")
    original=original_audit()
    day_reports={};missing_dates=[]
    while start<end:
        date=start.isoformat()
        data=fetch_day(date)
        output,errors=evaluate_day(data,date,original)
        if output is not None:
            day_reports[date]=output
        elif errors:
            day_reports[date]=None;missing_dates.append(date)
        start+=dt.timedelta(days=1)
    reports=consolidate(day_reports)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for k,report in reports.items():
        target=args.output_dir/("shadow-k"+k+".json")
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FORWARD_TOPK_SHADOW_EXPORT",json.dumps({
        "status":"NO_FUTURE_FINISHED_RACES" if not day_reports else "RESEARCH_ONLY",
        "dateCount":len(day_reports),"missingSelectionRaceDates":missing_dates,
        "byTopK":{k:{"expected":r["originalSelectedRacesIncluded"],
            "pairedRaces":r["total"]["canonical"]["races"],
            "excluded":r["excluded"]} for k,r in reports.items()},
        "outputDirectory":str(args.output_dir),"productionWritten":False,
    },ensure_ascii=False))

if __name__=="__main__":
    main()
