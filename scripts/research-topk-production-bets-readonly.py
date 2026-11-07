#!/usr/bin/env python3
"""Research-only read-only 3/4/5 races per venue counterfactual.

Evaluate a predeclared top-k *subset* of historical immutable, already-locked
production bets, ranked ONLY by the original pre-race raceScore. No historical
bets are changed, no candidate odds are invented, no D1 writes. The original
model and two ticket types per race remain unchanged.

This diagnostic CANNOT establish a deployable policy: historical score
timestamps and all counterfactual pre-T15 odds still need independent proof.
The 2026 selected dates are no longer untouched for choosing k, so final
selection must use prospective unseen race dates.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import os
from pathlib import Path
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
TOP_KS = (3, 4, 5)
START = "2026-08-10"
END_EXCLUSIVE = "2026-11-08"
MAX_SELECTION_ROWS = 60
MAX_BET_ROWS = 1500

def time_ok(locked, race_date, race_start):
    if not isinstance(locked,str) or not isinstance(race_start,str):
        return False
    try:
        at=dt.datetime.fromisoformat(locked.replace("Z","+00:00"))
        st=dt.datetime.fromisoformat(race_date+"T"+race_start[:5]+":00+09:00")
        return at.tzinfo is not None and at<=st-dt.timedelta(minutes=15)
    except (ValueError,TypeError):
        return False

def read_d1(sql,params):
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    db=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
    request=urllib.request.Request(url,data=json.dumps({"sql":sql,"params":params}).encode(),
        method="POST",headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=35) as response:
        data=json.loads(response.read())
    if not data.get("success"):
        raise RuntimeError("READ_ONLY_D1_ERROR: "+str(data.get("errors"))[:600])
    return (data.get("result") or [{}])[0].get("results") or []

def fetch_readonly(start=START,end_exclusive=END_EXCLUSIVE):
    # Bounded indexed key/date predicates; no unbounded LIKE or mutation.
    selections=read_d1("""SELECT state_key AS stateKey,state_value AS stateValue
        FROM rt_system_state WHERE state_key>=? AND state_key<?
        ORDER BY state_key LIMIT 60""",
        ["final_daily_selection:"+start,"final_daily_selection:"+end_exclusive])
    bets=read_d1("""SELECT b.race_id AS raceId,b.course,b.bet_type AS betType,
        b.combination,b.stake_yen AS stakeYen,b.return_yen AS returnYen,
        b.settlement_status AS settlementStatus,b.locked_at AS lockedAt
        FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date>=? AND r.race_date<? AND b.source_prediction_id=-2
          AND b.course='ライト'
        ORDER BY r.race_date,b.race_id,b.id LIMIT 1500""",
        [start,end_exclusive])
    if len(selections)>=MAX_SELECTION_ROWS or len(bets)>=MAX_BET_ROWS:
        raise RuntimeError("D1_READ_LIMIT_REACHED_REPORT_INVALID")
    return {"selectionStates":selections,"bets":bets}

def evaluate(source):
    states=source["selectionStates"]
    bets=source["bets"]
    by_bet=collections.defaultdict(list)
    for x in bets:
        if x.get("course")=="ライト":
            by_bet[str(x.get("raceId"))].append(x)
    compiled=[]
    rejected=collections.Counter()
    for state in states:
        key=str(state.get("stateKey") or "")
        date=key.removeprefix("final_daily_selection:")
        if len(date)!=10 or not date.startswith("2026-"):
            raise ValueError("BAD_SELECTION_DATE:"+date)
        payload=json.loads(state["stateValue"])
        if payload.get("sourceModel")!="ten-year-completed-model" or payload.get("resultDataUsedForTargetDay") is not False:
            raise AssertionError("SELECTION_PROVENANCE_NOT_CONFIRMED:"+date)
        selected=payload.get("selected")
        if not isinstance(selected,list) or not selected:
            raise AssertionError("SELECTION_SET_EMPTY:"+date)
        by_venue=collections.defaultdict(list)
        for race in selected:
            rid=str(race.get("raceId") or "")
            venue=str(race.get("venue") or "")
            raw=race.get("raceScore")
            try:
                score=float(raw)
            except (ValueError,TypeError):
                raise AssertionError("ORIGINAL_PRE_RACE_SCORE_MISSING:"+rid)
            if not rid or not venue or not math.isfinite(score):
                raise AssertionError("ORIGINAL_SELECTION_SCORE_INVALID:"+rid)
            by_venue[venue].append((score,int(race.get("raceNo") or 0),rid,race))
        for venue,rows in by_venue.items():
            if len(rows)!=5 or len({r[2] for r in rows})!=5:
                raise AssertionError("FIVE_ORIGINAL_RACES_NOT_PRESENT:"+date+":"+venue)
            # The historical model ranked DESC by raceScore, ties by raceNo ASC.
            rows.sort(key=lambda r:(-r[0],r[1]))
            for rank,(_,_,rid,race) in enumerate(rows,1):
                actual=by_bet.get(rid,[])
                reason=None
                stake=refund=0
                if len(actual)!=2:
                    reason="missing_two_bets"
                elif len({x.get("betType") for x in actual})!=2:
                    reason="not_two_distinct_bet_types"
                elif not all(time_ok(x.get("lockedAt"),date,race.get("startTimeJst")) for x in actual):
                    reason="late_or_unverifiable_lock"
                elif not all(x.get("settlementStatus")=="settled" for x in actual):
                    reason="unsettled"
                elif any(x.get("returnYen") is None for x in actual):
                    reason="missing_return"
                else:
                    stake=sum(int(x.get("stakeYen") or 0) for x in actual)
                    refund=sum(int(x.get("returnYen") or 0) for x in actual)
                    if stake!=2000 or refund<0:
                        reason="invalid_stake_or_return"
                if reason:
                    rejected[reason]+=1
                compiled.append({"date":date,"venue":venue,"raceId":rid,
                    "rank":rank,"score":rows[rank-1][0],"valid":reason is None,
                    "failure":reason,"stake":stake if reason is None else 0,
                    "return":refund if reason is None else 0})
    summaries={}
    by_month={}
    for k in TOP_KS:
        subset=[x for x in compiled if x["rank"]<=k]
        valid=[x for x in subset if x["valid"]]
        stake=sum(x["stake"] for x in valid)
        payout=sum(x["return"] for x in valid)
        total_days=len({(x["date"],x["venue"]) for x in subset})
        assert len(subset)==total_days*k,(k,len(subset),total_days)
        summary={"plannedRaces":len(subset),"venueDays":total_days,
            "validRaces":len(valid),"missingOrInvalidRaces":len(subset)-len(valid),
            "completeVenueDays":sum(all(x["valid"] for x in subset if x["date"]==d and x["venue"]==v)
                                    for d,v in {(x["date"],x["venue"]) for x in subset}),
            "stakeYen":stake,"returnYen":payout,
            "roiOnValidBetsPct":round(payout*100/stake,2) if stake else None,
            "allPlannedBetsVerified":len(subset)==len(valid)}
        summaries[str(k)]=summary
        for month in sorted({x["date"][:7] for x in subset}):
            v=[x for x in valid if x["date"].startswith(month)]
            s=sum(x["stake"] for x in v)
            p=sum(x["return"] for x in v)
            by_month.setdefault(month,{})[str(k)]={"validRaces":len(v),
                "plannedRaces":sum(x["date"].startswith(month) for x in subset),
                "roiOnValidBetsPct":round(p*100/s,2) if s else None}
    return {"status":"RETROSPECTIVE_RESEARCH_NOT_PROMOTION","basis":"actual immutable locked bets, ranked by original persisted raceScore", "dateFrom":min((x["date"] for x in compiled),default=None),
        "dateThrough":max((x["date"] for x in compiled),default=None),
        "strategies":summaries,"byMonth":by_month,"invalidReasons":dict(rejected),
        "limitations":["Only the five previously selected races can be compared; never a model that selected different races",
            "Historical pre-race score capture timestamps are not independently verified here",
            "Missing or late bets are counted, not silently erased",
            "ROI denominator is placed valid bets only; incompleteness separately prohibits promotion",
            "Past performance can select a hypothesis only; future unseen race-day comparison is mandatory",
            "No official payout independently compared with JRA"],"promotionEligible":False}

def selftest():
    day="2026-10-17"
    races=[{"raceId":f"{day}-tokyo-{i:02d}","raceNo":i,
            "venue":"東京","raceScore":float(10-i),"startTimeJst":"12:00"} for i in range(1,6)]
    bets=[]
    payouts=[3000,0,6000,0,0]
    for i in range(1,6):
        rid=races[i-1]["raceId"]
        for typ in ["単勝","ワイド"]:
            bets.append({"course":"ライト","raceId":rid,"betType":typ,
                "lockedAt":day+"T01:00:00Z","settlementStatus":"settled",
                "stakeYen":1000,"returnYen":payouts[i-1] if typ=="単勝" else 0})
    states=[{"stateKey":"final_daily_selection:"+day,"stateValue":json.dumps(
        {"sourceModel":"ten-year-completed-model","resultDataUsedForTargetDay":False,"selected":races})}]
    outcome=evaluate({"selectionStates":states,"bets":bets})
    assert outcome["strategies"]["3"]["roiOnValidBetsPct"]==150.0,outcome
    assert outcome["strategies"]["4"]["roiOnValidBetsPct"]==112.5,outcome
    assert outcome["strategies"]["5"]["roiOnValidBetsPct"]==90.0,outcome
    bets[0]["lockedAt"]=day+"T04:30:00Z" # Misses T-15
    out=evaluate({"selectionStates":states,"bets":bets})
    assert out["strategies"]["3"]["validRaces"]==2
    assert out["strategies"]["3"]["missingOrInvalidRaces"]==1
    assert out["strategies"]["5"]["allPlannedBetsVerified"] is False
    print("TOPK_RESEARCH_COUNTERFACTUAL_SELFTEST_OK",json.dumps({
        "3R":outcome["strategies"]["3"]["roiOnValidBetsPct"],
        "4R":outcome["strategies"]["4"]["roiOnValidBetsPct"],
        "5R":outcome["strategies"]["5"]["roiOnValidBetsPct"]},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--live",action="store_true",
                        help="bounded read-only D1. Only run when quota is available")
    parser.add_argument("--fixture",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.self_test:
        selftest()
        return
    if args.live == bool(args.fixture):
        parser.error("choose exactly one of --fixture or --live")
    source=fetch_readonly() if args.live else json.loads(args.fixture.read_text(encoding="utf-8"))
    result=evaluate(source)
    data=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(data+"\n",encoding="utf-8")
    print("TOPK_RESEARCH_READONLY",data)
    if not all(x["allPlannedBetsVerified"] for x in result["strategies"].values()):
        print("WARNING: INCOMPLETE LIVE BET HISTORY. NOT CERTIFIABLE.")

if __name__=="__main__":
    main()
