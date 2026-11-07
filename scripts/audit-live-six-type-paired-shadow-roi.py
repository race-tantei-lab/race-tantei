#!/usr/bin/env python3
"""Research-only JRA pre-T15 frozen 6-market, all-15 two-type pair audit.

This NEVER modifies the completed LightGBM or public predictions.
Uses compact \`candidatesByType\` captured by the LIVE Worker from the exact
pre-T15 official odds request and model probabilities (same as public bets).
Every published/light bet is independently compared against persisted actual
JRA payout. Research pairs are 100% read-only, settled after the race.
Missing odds, late locks, missing six type payouts, refund inconsistencies,
or incomplete 5-race venue-days invalidate the entire venue-day.

Use --self-test on CI. --date YYYY-MM-DD is an explicit manual-only D1
read with small indexed date-bounded queries. NO schedule, NO D1 writes.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import itertools
import json
import math
import os
import re
import sys
import urllib.request

JST=dt.timezone(dt.timedelta(hours=9))
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAIRS=tuple(itertools.combinations(TYPES,2))
POLICIES=("market_implied_only","market_blend_30pct_model")
STAKE_SPLITS=((1000,1000),(1400,600))
TOP_K=(3,4,5)
CURRENT_MODEL="ten-year-completed-model"
# sha256 of the deployed frozen model. This is NOT a new model or refit.
MODEL_SHA256="63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5"
SOURCES=("jra-fast-official","jra-crawl-official")
MAX_RACES_PER_DAY=36

def t15_ok(value,date,start):
    try:
        generated=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
        begin=dt.datetime.fromisoformat(date+"T"+str(start)[:5]+":00+09:00")
        return generated.tzinfo is not None and generated<=begin-dt.timedelta(minutes=15)
    except (TypeError,ValueError):return False

def parse_types(rows,require_complete):
    by_id=collections.defaultdict(dict)
    for r in rows:
        rid=str(r["raceId"])
        key=(r["betType"],r["combination"])
        payout=int(r["payout100"])
        if r["betType"] not in TYPES or payout<0 or payout%10:
            raise ValueError("INVALID_JRA_PAYOUT")
        if key in by_id[rid] and by_id[rid][key]!=payout:
            raise ValueError("CONFLICTING_JRA_PAYOUT")
        by_id[rid][key]=payout
    if require_complete:
        for rid,values in by_id.items():
            if {x[0] for x in values}!=set(TYPES):
                raise ValueError("INCOMPLETE_SIX_MARKET_PAYOUT:"+rid)
    return by_id

def horse_numbers(typ,combo):
    if typ not in TYPES:raise ValueError("INVALID_BET_TYPE")
    required=1 if typ=="単勝" else 2 if typ in ("ワイド","馬連","馬単") else 3
    try:horses=tuple(int(n) for n in str(combo).split("-"))
    except ValueError:raise ValueError("NON_NUMERIC_HORSE_COMBO") from None
    if len(horses)!=required or len(set(horses))!=required or not all(1<=n<=18 for n in horses):
        raise ValueError("INVALID_HORSE_COMBO")
    if typ in ("ワイド","馬連","3連複") and horses!=tuple(sorted(horses)):
        raise ValueError("UNORDERED_BET_NOT_CANONICAL")
    return horses

def settle(rid,typ,combo,stake,payout,refunds):
    horses=horse_numbers(typ,combo)
    if set(horses)&refunds:
        return {"returnYen":stake,"winning":False,"refunded":True}
    p=payout.get((typ,combo),0)
    return {"returnYen":p*stake//100,"winning":p>0,"refunded":False}

def valid_six(snapshot,date,start):
    if (snapshot.get("sourceModel")!=CURRENT_MODEL or
        snapshot.get("modelSha256")!=MODEL_SHA256 or
        snapshot.get("oddsSource") not in SOURCES or
        not re.fullmatch("[0-9a-f]{64}",str(snapshot.get("oddsSnapshotSha256") or ""))):
        raise ValueError("NOT_FROZEN_MODEL_AND_OFFICIAL_ODDS")
    if not all(t15_ok(snapshot.get(field),date,start) for field in
               ("lockedAt","previewGeneratedAt","generationStartedAt","oddsFetchedAt")):
        raise ValueError("LATE_OR_UNVERIFIED_FINAL_ODDS")
    policies=snapshot.get("shadowResearch")
    if not isinstance(policies,list) or len(policies)!=2:
        raise ValueError("MISSING_TWO_SHADOW_POLICIES")
    results={}
    for policy in policies:
        name=policy.get("policy")
        if name not in POLICIES or name in results:
            raise ValueError("INVALID_SHADOW_POLICY")
        selected=policy.get("tickets")
        by_type=policy.get("candidatesByType")
        if not isinstance(selected,list) or len(selected)!=2:
            raise ValueError("INVALID_SHADOW_SELECTION")
        if not isinstance(by_type,list) or len(by_type)!=6:
            raise ValueError("MISSING_SIX_OFFICIAL_TYPE_CANDIDATES")
        types=[x.get("betType") for x in by_type]
        if tuple(types)!=TYPES:
            raise ValueError("SIX_CANDIDATE_TYPE_ORDER_CHANGED")
        if len({x.get("betType") for x in selected})!=2:
            raise ValueError("SHADOW_PUBLIC_PAIR_NOT_DISTINCT")
        by_map={}
        for x in by_type:
            typ=x["betType"];combo=str(x["combination"])
            horse_numbers(typ,combo)
            for field in ("officialOdds","rawModelProbability","blendedProbability","score"):
                if not isinstance(x.get(field),(float,int)) or not math.isfinite(x[field]):
                    raise ValueError("SHADOW_VALUE_MISSING:"+field)
            if x["officialOdds"]<1 or not 0<x["rawModelProbability"]<=1 or not 0<x["blendedProbability"]<=1:
                raise ValueError("SHADOW_PROBABILITY_OR_OFFICIAL_ODDS_INVALID")
            by_map[typ]=x
        for ticket in selected:
            candidate=by_map.get(ticket.get("betType"))
            if not candidate or candidate.get("combination")!=ticket.get("combination"):
                raise ValueError("SHADOW_SELECTION_MISMATCH_WITH_SIX_CANDIDATES")
        results[name]=by_map
    if set(results)!=set(POLICIES):
        raise ValueError("SHADOW_POLICIES_NOT_COMPLETE")
    return results

def metrics(records):
    count=len(records)
    if not count:return {"races":0,"hitRacePct":None,"roiPct":None}
    stakes=sum(r["stake"] for r in records)
    payouts=sum(r["returned"] for r in records)
    hit=sum(r["wins"]>0 for r in records)
    largest=max(r["returned"] for r in records)
    return {"races":count,"bets":count*2,"hitRaces":hit,
        "hitRacePct":round(100*hit/count,2),
        "winningTickets":sum(r["wins"] for r in records),
        "hitTicketPct":round(100*sum(r["wins"] for r in records)/(count*2),2),
        "refundedTickets":sum(r["refunds"] for r in records),
        "bothTicketsHitRaces":sum(r["wins"]==2 for r in records),
        "profitableRaces":sum(r["returned"]>r["stake"] for r in records),
        "stakeYen":stakes,"returnYen":payouts,
        "profitYen":payouts-stakes,
        "roiPct":round(100*payouts/stakes,2),
        "roiWithoutLargestRaceReturnPct":round(100*(payouts-largest)/stakes,2)}

def evaluate(selections,finals,bets,payouts,races,date):
    if not re.fullmatch(r"20[2-9][0-9]-[01][0-9]-[0-3][0-9]",date) or date<"2026-11-08":
        raise ValueError("FUTURE_FORWARD_SHADOW_STARTS_NOV8")
    selected=collections.defaultdict(list)
    ids=set()
    for race in selections:
        rid=race["raceId"]
        if rid in ids:raise ValueError("DUPLICATE_SELECTED_RACE")
        ids.add(rid)
        if not rid.startswith(date+"-") or not race.get("venue"):
            raise ValueError("SELECTION_RACE_ID_AND_VENUE_INCONSISTENT")
        if not isinstance(race.get("raceScore"),(float,int)) or not math.isfinite(race["raceScore"]):
            raise ValueError("ORIGINAL_FROZEN_RACE_SCORE_MISSING")
        selected[race["venue"]].append(race)
    if not selected or any(len(rows)!=5 for rows in selected.values()):
        raise ValueError("FIVE_ORIGINAL_LOCKED_RACES_PER_VENUE_REQUIRED")
    if len(ids)>MAX_RACES_PER_DAY:raise ValueError("TOO_MANY_SELECTED_RACES")
    final_map={x["raceId"]:x["snapshot"] for x in finals}
    race_map={r["raceId"]:r for r in races}
    actual_by_id=collections.defaultdict(list)
    for b in bets:actual_by_id[b["raceId"]].append(b)
    payout_map=parse_types(payouts,False)
    invalid={}
    complete={}
    for venue,rows in selected.items():
        try:
            collected=[]
            for row in rows:
                rid=row["raceId"]
                race=race_map.get(rid)
                if not race or race.get("status")!="finished":
                    raise ValueError("OFFICIAL_RACE_RESULT_NOT_FINISHED:"+rid)
                payout=payout_map.get(rid,{})
                if {k[0] for k in payout}!=set(TYPES):
                    raise ValueError("INCOMPLETE_SIX_MARKET_PAYOUT:"+rid)
                if not isinstance(race.get("refunds"),list):
                    raise ValueError("MISSING_OFFICIAL_REFUND_LIST:"+rid)
                refunds={int(n) for n in race["refunds"]}
                p=valid_six(final_map.get(rid,{}),date,row.get("startTimeJst"))
                actual=actual_by_id.get(rid,[])
                if len(actual)!=2 or len({r["betType"] for r in actual})!=2:
                    raise ValueError("MISSING_TWO_REAL_PUBLIC_BETS:"+rid)
                if any(r.get("settlement")!="settled" or r.get("stakeYen")!=1000 or
                       r.get("returnYen") is None or not t15_ok(r.get("lockedAt"),date,row.get("startTimeJst"))
                       for r in actual):
                    raise ValueError("REAL_PUBLIC_BETS_NOT_VERIFIED_T15_SETTLED:"+rid)
                baseline=[settle(rid,r["betType"],r["combination"],1000,payout,refunds) for r in actual]
                if any(entry["returnYen"]!=int(rowbet["returnYen"])
                       for entry,rowbet in zip(baseline,actual)):
                    raise ValueError("ACTUAL_RETURN_DISAGREES_WITH_JRA_PAYOUT:"+rid)
                collected.append({"row":row,"real":baseline,"shadow":p,
                                  "payout":payout,"refunds":refunds})
            complete[venue]=sorted(collected,key=lambda r:(-r["row"]["raceScore"],r["row"]["raceNo"]))
        except (ValueError,KeyError,TypeError) as error:
            invalid[venue]=str(error)
    result={}
    for k in TOP_K:
        for policy in ("canonical",)+POLICIES:
            for pair in (("actual","actual"),) if policy=="canonical" else PAIRS:
                for split in ((1000,1000),) if policy=="canonical" else STAKE_SPLITS:
                    if policy=="canonical" and k<3:raise AssertionError("MIN_3")
                    records=[];complete_days=0
                    for venue,group in complete.items():
                        current=group[:k]
                        if len(current)!=k:raise AssertionError("PARTIAL_VENUE_GROUP")
                        complete_days+=int(all(True for _ in current)) # not "all hit"
                        for x in current:
                            if policy=="canonical":
                                tickets=x["real"]
                            else:
                                tickets=[
                                    settle(x["row"]["raceId"],typ,
                                           x["shadow"][policy][typ]["combination"],stake,
                                           x["payout"],x["refunds"])
                                    for typ,stake in zip(pair,split)]
                            records.append({"stake":sum(split),
                                "returned":sum(t["returnYen"] for t in tickets),
                                "wins":sum(t["winning"] for t in tickets),
                                "refunds":sum(t["refunded"] for t in tickets)})
                    key=(str(k)+"|"+policy+"|"+"+".join(pair)+"|"+",".join(map(str,split)))
                    stat=metrics(records)
                    full=sum(
                        all(row["wins"]>0 for row in records[i:i+k])
                        for i in range(0,len(records),k))
                    result[key]={**stat,"completeVenueDays":len(complete),
                                 "allSelectedRacesHitVenueDays":full,
                                 "selectedK":k,
                                 "pairTypes":list(pair) if policy!="canonical" else None,
                                 "policy":policy}
    # All strategies have the SAME original 5-per-venue preselected races
    # and exactly the SAME (complete) venue-day cohort per K, with paired
    # ticket success and real payout ROI from the same records.
    count5=len(complete)*5
    return {"date":date,"source":"original T15 56-feature model and live official odds",
        "productionModelChanged":False,"productionTicketsChanged":False,
        "allSixTypesCompared":True,"all15DistinctPairs":len(PAIRS)==15,
        "missingOrInvalidVenueDays":invalid,
        "completeVenueDays":len(complete),
        "completedFiveRaceCohortRaces":count5,
        "sameRaceCohortForHitRateAndROI":True,
        "refundsNeverCountAsHits":True,
        "actualJraPayoutSource":"D1 stored JRA official, not independently externally rechecked",
        "strategies":result,"promotionAuthorized":False}

def selftest():
    date="2026-11-08"
    f=lambda i:date+"-東京-"+str(i)
    selected=[{"raceId":f(i),"venue":"東京","raceNo":i,
               "startTimeJst":"11:00","raceScore":10-i} for i in range(1,6)]
    ptypes=["単勝","ワイド","馬連","馬単","3連複","3連単"]
    combos=["1","1-2","1-2","1-2","1-2-3","1-2-3"]
    candidates=[{"betType":a,"combination":b,"officialOdds":3.0,
                 "rawModelProbability":0.2,"blendedProbability":0.3,
                 "score":0.1} for a,b in zip(ptypes,combos)]
    finals=[]
    realbets=[]
    payout=[]
    race_rows=[]
    for i in range(1,6):
        rid=f(i)
        snap={"sourceModel":CURRENT_MODEL,"modelSha256":MODEL_SHA256,
              "oddsSource":"jra-fast-official",
              "oddsSnapshotSha256":"a"*64,
              "lockedAt":"2026-11-08T01:00:00Z",
              "previewGeneratedAt":"2026-11-08T00:59:00Z",
              "generationStartedAt":"2026-11-08T00:58:00Z",
              "oddsFetchedAt":"2026-11-08T00:58:50Z",
              "shadowResearch":[{"policy":pol,
                 "tickets":candidates[:2],"candidatesByType":candidates} for pol in POLICIES]}
        finals.append({"raceId":rid,"snapshot":snap})
        realbets.extend({"raceId":rid,"betType":t,"combination":c,"stakeYen":1000,
                         "returnYen":4000 if i==1 else 0,
                         "lockedAt":"2026-11-08T01:00:00Z","settlement":"settled"}
                         for t,c in (("単勝","1"),("ワイド","1-2")))
        payout.extend({"raceId":rid,"betType":t,"combination":c,
                       "payout100":400 if i==1 else 0} for t,c in zip(ptypes,combos))
        race_rows.append({"raceId":rid,"status":"finished","refunds":[]})
    report=evaluate(selected,finals,realbets,payout,race_rows,date)
    assert len(report["strategies"])==3*(1+len(PAIRS)*len(POLICIES)*len(STAKE_SPLITS))
    assert report["completeVenueDays"]==1
    assert report["strategies"]["5|canonical|actual+actual|1000,1000"]["hitRacePct"]==20.0
    assert report["strategies"]["5|canonical|actual+actual|1000,1000"]["roiPct"]==80.0
    assert report["strategies"]["5|market_implied_only|単勝+ワイド|1000,1000"]["roiPct"]==80.0
    assert report["strategies"]["5|market_implied_only|単勝+ワイド|1000,1000"]["hitRacePct"]==20.0
    assert report["strategies"]["5|market_implied_only|単勝+ワイド|1000,1000"]["allSelectedRacesHitVenueDays"]==0
    # Late final invalidates entire venue-day, not one losing race.
    finals[1]["snapshot"]["lockedAt"]="2026-11-08T01:47:00Z"
    missed=evaluate(selected,finals,realbets,payout,race_rows,date)
    assert missed["completeVenueDays"]==0
    assert "東京" in missed["missingOrInvalidVenueDays"]
    assert missed["strategies"]["5|canonical|actual+actual|1000,1000"]["roiPct"] is None
    finals[1]["snapshot"]["lockedAt"]="2026-11-08T01:00:00Z"
    # 100% stake refund changes ROI, but cannot be counted as a winning ticket.
    realbets[0]["returnYen"]=1000
    realbets[1]["returnYen"]=1000
    race_rows[0]["refunds"]=[1,2]
    refunded=evaluate(selected,finals,realbets,payout,race_rows,date)
    assert refunded["strategies"]["5|canonical|actual+actual|1000,1000"]["hitRacePct"]==0
    assert refunded["strategies"]["5|canonical|actual+actual|1000,1000"]["roiPct"]==20.0
    print("SIX_TYPE_T15_SHADOW_PAIRED_HIT_ROI_SELFTEST_OK",flush=True)

def query(sql,params):
    base=(f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
        f"/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query")
    req=urllib.request.Request(base,data=json.dumps({"sql":sql,"params":params}).encode(),
        method="POST",headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],
        "Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=55) as response:
        doc=json.loads(response.read())
    if not doc.get("success"):
        raise RuntimeError("D1_READ_FAILED "+str(doc.get("errors"))[:300])
    return (doc.get("result") or [{}])[0].get("results") or []

def fetch_date(date):
    end=(dt.date.fromisoformat(date)+dt.timedelta(days=1)).isoformat()
    sel=query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
               ["final_daily_selection:"+date])
    if len(sel)!=1:raise RuntimeError("NO_IMMUTABLE_PRE_SELECTED_RACE_LIST")
    payload=json.loads(sel[0]["value"])
    if payload.get("sourceModel")!=CURRENT_MODEL or payload.get("resultDataUsedForTargetDay") is not False:
        raise RuntimeError("SELECTION_NOT_VERIFIED_PRE_RESULT_CANONICAL_MODEL")
    selected=payload.get("selected") or []
    finals=query("SELECT state_key AS k,state_value AS v FROM rt_system_state "
                 "WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 40",
                 ["worker_live_final:"+date+"-","worker_live_final:"+end+"-"])
    if len(finals)>=40:raise RuntimeError("FINAL_ROW_LIMIT_REACHED")
    final_rows=[{"raceId":r["k"].removeprefix("worker_live_final:"),
                 "snapshot":json.loads(r["v"])} for r in finals]
    bets=query("SELECT race_id AS raceId,bet_type AS betType,combination,"
        "stake_yen AS stakeYen,return_yen AS returnYen,"
        "settlement_status AS settlement,locked_at AS lockedAt FROM rt_public_bets "
        "WHERE race_id>=? AND race_id<? AND course='ライト' AND source_prediction_id=-2 "
        "ORDER BY race_id,id LIMIT 80",[date+"-",end+"-"])
    pays=query("SELECT race_id AS raceId,bet_type AS betType,combination,"
       "payout_yen AS payout100 FROM rt_payouts WHERE race_id>=? AND race_id<? "
       "ORDER BY race_id LIMIT 900",[date+"-",end+"-"])
    races=query("SELECT race_id AS raceId,status,refund_horse_nos_json AS refundJson "
        "FROM rt_races WHERE race_id>=? AND race_id<? ORDER BY race_id LIMIT 40",
        [date+"-",end+"-"])
    if any(len(rows)>=limit for rows,limit in ((bets,80),(pays,900),(races,40))):
        raise RuntimeError("INDEXED_DATE_QUERY_ROW_CAP_REACHED")
    records=[{"raceId":r["raceId"],"status":r["status"],
              "refunds":json.loads(r["refundJson"] or "[]")} for r in races]
    return selected,final_rows,bets,pays,records

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--date",help="Explicit finished JST race date; manual and read-only")
    args=p.parse_args()
    if args.self_test:selftest();return
    if not args.date:p.error("Specify --date for one completed racing day")
    date=dt.date.fromisoformat(args.date)
    if date>=dt.datetime.now(JST).date():
        raise RuntimeError("CANNOT_AUDIT_FUTURE_OR_STILL_RUNNING_JRA_DAY")
    result=evaluate(*fetch_date(args.date),args.date)
    print("SIX_MARKET_T15_PAIRED_HIT_AND_ROI",json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
