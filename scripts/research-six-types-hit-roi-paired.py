#!/usr/bin/env python3
"""Research-only: evaluate hit rate AND ROI together over all 15 distinct
JRA bet-type pairs, four PREDECLARED ticket-ranking rules, two stake policies,
and 3/4/5 races per venue day (360 rule combinations).

Requires externally furnished FULL pre-T15 OFFICIAL JRA six-market odds
candidate snapshots, immutable pre-result race scores, and complete actual JRA
payouts. Does not retrain/change model, access D1, write public bets, backfill
snapshots or authorize deployment. Missing one of those sources => NO RESULTS.

Only supports existing 56-feature model outputs, and same locked candidate
dataset for every paired hit/return metric. Do NOT apply it retrospectively
using final market odds and claim actual pre-T15 ROI.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import itertools
import json
import math
from pathlib import Path
import re
from typing import Any

JST=dt.timezone(dt.timedelta(hours=9))
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
RANKERS=("probability","canonical_score","expected_value","shortest_official_odds")
STAKE_SPLITS=((1000,1000),(1400,600))
KS=(3,4,5)
BEGIN="2026-11-08"
SOURCE_MODEL="ten-year-completed-model"
ODDS_SOURCES=("jra-fast-official","jra-crawl-official")
DAYS_REQUIRED=24
RACES_REQUIRED=300
PAIRS=tuple(itertools.combinations(TYPES,2))
assert len(PAIRS)==15
REPORT_SCHEMA="all_15_pairs_hit_plus_roi_same_race_cohort_v1"

def is_pre_t15(value:str,date:str,start_time:str)->bool:
    try:
        at=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
        start=dt.datetime.fromisoformat(date+"T"+str(start_time)[:5]+":00+09:00")
        return at.tzinfo is not None and at<=start-dt.timedelta(minutes=15)
    except (TypeError,ValueError):return False

def verify_race(race:dict,day:str)->dict:
    rid=str(race.get("raceId") or "")
    if not rid.startswith(day+"-") or race.get("date")!=day:
        raise ValueError("RACE_ID_DATE_INVALID")
    if race.get("sourceModel")!=SOURCE_MODEL:
        raise ValueError("CURRENT_MODEL_IDENTITY_MISSING")
    if not re.fullmatch(r"[0-9a-f]{64}",str(race.get("modelSha256") or "")):
        raise ValueError("CURRENT_MODEL_HASH_MISSING")
    if race.get("oddsSource") not in ODDS_SOURCES or not re.fullmatch(
            r"[0-9a-f]{64}",str(race.get("officialOddsSha256") or "")):
        raise ValueError("OFFICIAL_ODDS_SNAPSHOT_NOT_VERIFIED")
    if not all(is_pre_t15(race.get(key),day,race.get("startTimeJst"))
               for key in ("oddsFetchedAt","lockedAt","candidateGeneratedAt")):
        raise ValueError("T15_DEADLINE_OR_PRE_RESULT_CANDIDATES_NOT_VERIFIED")
    if race.get("resultStatus")!="finished" or race.get("payoutsCompleteForSixTypes") is not True:
        raise ValueError("ALL_SIX_MARKETS_NOT_SETTLED")
    try:score=float(race["raceScore"])
    except (TypeError,ValueError,KeyError):raise ValueError("PRE_RESULT_RACE_SCORE_MISSING") from None
    if not math.isfinite(score):raise ValueError("PRE_RESULT_RACE_SCORE_INVALID")
    raw=race.get("candidates")
    if not isinstance(raw,list) or len(raw)<6 or len(raw)>12000:
        raise ValueError("CANDIDATE_ROWS_MISSING_OR_TOO_MANY")
    by_type=collections.defaultdict(list)
    seen=set()
    for x in raw:
        if not isinstance(x,dict) or x.get("betType") not in TYPES:
            raise ValueError("INVALID_BET_TYPE")
        typ=x["betType"]
        combo=str(x.get("combination") or "")
        expected=1 if typ=="単勝" else 2 if typ in ("ワイド","馬連","馬単") else 3
        parts=combo.split("-")
        try:numbers=tuple(int(v) for v in parts)
        except (TypeError,ValueError):raise ValueError("INVALID_COMBINATION") from None
        if len(numbers)!=expected or len(set(numbers))!=expected or any(not 1<=v<=18 for v in numbers):
            raise ValueError("INVALID_COMBINATION")
        if typ in ("ワイド","馬連","3連複") and tuple(sorted(numbers))!=numbers:
            raise ValueError("UNORDERED_COMBINATION_NOT_CANONICAL")
        try:
            p=float(x["predictedProbability"])
            odds=float(x["officialOdds"])
        except (TypeError,ValueError,KeyError):
            raise ValueError("CANDIDATE_PROBABILITY_OR_ODDS_MISSING") from None
        if not (math.isfinite(p) and 0<p<=1 and math.isfinite(odds) and odds>=1):
            raise ValueError("INVALID_CANDIDATE_PROBABILITY_OR_OFFICIAL_ODDS")
        if (typ,combo) in seen:raise ValueError("DUPLICATE_OFFICIAL_COMBINATION")
        seen.add((typ,combo))
        by_type[typ].append({"betType":typ,"combination":combo,
            "predictedProbability":p,"officialOdds":odds})
    if set(by_type)!=set(TYPES):
        raise ValueError("ALL_SIX_OFFICIAL_ODDS_MARKETS_REQUIRED")
    if not isinstance(race.get("refundHorses"),list):
        raise ValueError("REFUND_HORSE_LIST_MISSING")
    try:refunds={int(v) for v in race["refundHorses"]}
    except (TypeError,ValueError):raise ValueError("INVALID_REFUND_LIST") from None
    if not all(1<=v<=18 for v in refunds):raise ValueError("INVALID_REFUND_LIST")
    payouts={}
    pay_rows=race.get("payouts")
    if not isinstance(pay_rows,list):raise ValueError("ACTUAL_JRA_PAYOUT_ROWS_MISSING")
    for item in pay_rows:
        key=(str(item.get("betType") or ""),str(item.get("combination") or ""))
        if key[0] not in TYPES:raise ValueError("INVALID_SETTLEMENT_TYPE")
        try:money=int(item["payout100"])
        except (KeyError,TypeError,ValueError):raise ValueError("INVALID_ACTUAL_JRA_PAYOUT") from None
        if money<0 or money%10!=0:raise ValueError("INVALID_JRA_PAYOUT_UNIT")
        if key in payouts and payouts[key]!=money:
            raise ValueError("CONFLICTING_JRA_PAYOUTS")
        payouts[key]=money
    return {"raceId":rid,"score":score,"raceNo":int(race["raceNo"]),
            "byType":by_type,"payouts":payouts,"refunds":refunds}

def ranked_ticket(items:list,policy:str):
    if policy=="probability":
        score=lambda x:x["predictedProbability"]
    elif policy=="canonical_score":
        score=lambda x:math.log(x["predictedProbability"])+0.2*math.log(x["officialOdds"])
    elif policy=="expected_value":
        score=lambda x:x["predictedProbability"]*x["officialOdds"]
    elif policy=="shortest_official_odds":
        score=lambda x:-x["officialOdds"]
    else:raise ValueError("UNKNOWN_RANKER")
    return sorted(items,key=lambda x:(-score(x),x["combination"]))[0]

def actual_return_yen(r, ticket,stake):
    if set(map(int,ticket["combination"].split("-"))) & r["refunds"]:
        payout100=100
    else:payout100=r["payouts"].get((ticket["betType"],ticket["combination"]),0)
    return payout100*stake//100

def choose(r,ranker,pair,split):
    left=ranked_ticket(r["byType"][pair[0]],ranker)
    right=ranked_ticket(r["byType"][pair[1]],ranker)
    assert left["betType"]!=right["betType"] and sum(split)==2000
    ret=[actual_return_yen(r,t,s) for t,s in zip((left,right),split)]
    return {"stake":2000,"return":sum(ret),"hitRace":int(any(x>0 for x in ret)),
        "hitTickets":sum(x>0 for x in ret),"bothHit":int(all(x>0 for x in ret)),
        "profitableRace":int(sum(ret)>2000)}

def report_stats(rows:list):
    stake=sum(x["stake"] for x in rows);returned=sum(x["return"] for x in rows)
    n=len(rows);largest=max((x["return"] for x in rows),default=0)
    return {
        "races":n,"stakeYen":stake,"returnYen":returned,
        "profitYen":returned-stake,
        "hitRaces":sum(x["hitRace"] for x in rows),
        "hitRacePct":round(100*sum(x["hitRace"] for x in rows)/n,2) if n else None,
        "winningTickets":sum(x["hitTickets"] for x in rows),
        "tickets":2*n,
        "hitTicketPct":round(100*sum(x["hitTickets"] for x in rows)/(2*n),2) if n else None,
        "roiPct":round(100*returned/stake,2) if stake else None,
        "roiMinusLargestRacePct":round(100*(returned-largest)/stake,2) if stake else None,
        "profitableRaces":sum(x["profitableRace"] for x in rows),
        "bothTicketsHitRaces":sum(x["bothHit"] for x in rows),
    }

def evaluate(source:dict):
    if source.get("oddsMoment")!="JRA_OFFICIAL_PRE_T15" or source.get("candidateGenerationMoment")!="PRE_RESULT":
        raise ValueError("HISTORICAL_FINAL_ODDS_NOT_ELIGIBLE")
    if source.get("payoutProvenance")!="JRA_ACTUAL_SETTLED":
        raise ValueError("JRA_ACTUAL_PAYOUT_NOT_VERIFIED")
    days=source.get("days")
    if not isinstance(days,list) or not days:raise ValueError("NO_COMPLETED_RACE_DAYS")
    cohorts={}
    for day in days:
        date=str(day.get("date") or "")
        venue=str(day.get("venue") or "")
        if date<BEGIN or len(date)!=10 or not venue:raise ValueError("INVALID_FUTURE_DATE_OR_VENUE")
        if (date,venue) in cohorts:raise ValueError("DUPLICATE_VENUE_DAY")
        races=day.get("races")
        if not isinstance(races,list) or len(races)!=5:
            raise ValueError("EXACTLY_FIVE_ORIGINAL_PRE_SELECTED_RACES_REQUIRED")
        checked=[verify_race(r,date) for r in races]
        if len({r["raceId"] for r in checked})!=5 or len({r["raceNo"] for r in checked})!=5:
            raise ValueError("DUPLICATE_OR_INCOMPLETE_FIVE_RACES")
        cohorts[(date,venue)]=sorted(checked,key=lambda r:(-r["score"],r["raceNo"]))
    outputs=[]
    for k in KS:
        for ranker in RANKERS:
            for pair in PAIRS:
                for split in STAKE_SPLITS:
                    flat=[];by_month=collections.defaultdict(list)
                    by_venue=collections.defaultdict(list)
                    full_hit=0
                    for (date,venue),races in sorted(cohorts.items()):
                        rr=[choose(r,ranker,pair,split) for r in races[:k]]
                        flat.extend(rr)
                        by_month[date[:7]].extend(rr)
                        by_venue[venue].extend(rr)
                        full_hit+=int(all(r["hitRace"] for r in rr))
                    res=report_stats(flat)
                    monthly={month:report_stats(rows) for month,rows in sorted(by_month.items())}
                    # Every period includes *both* metrics on one identical cohort.
                    if any(v["hitRacePct"] is None or v["roiPct"] is None for v in monthly.values()):
                        raise AssertionError("UNPAIRED_METRICS")
                    outputs.append({"racesPerVenueDay":k,"policy":ranker,
                        "distinctTypes":list(pair),"stakesYen":list(split),
                        "venueDays":len(cohorts),"allRacesHitVenueDays":full_hit,
                        "total":res,"monthly":monthly,
                        "byVenue":{venue:report_stats(rows) for venue,rows in sorted(by_venue.items())}})
    return {"schema":REPORT_SCHEMA,"originalModelChanged":False,
        "productionChanged":False,"releaseAuthorized":False,
        "provenance":"prospective T15 official six-type quotes and settled JRA payouts",
        "all15PairsTested":True,"minRacesPerVenueDay":3,"preferredRacesPerVenueDay":5,
        "cohorts":len(cohorts),"configurations":len(outputs),
        "reportOnlyWhenHitAndRoiBothKnown":True,"strategies":outputs,
        "certificationEligible":len({d for d,_ in cohorts})>=DAYS_REQUIRED
                                 and len(cohorts)*5>=RACES_REQUIRED,
        "roi400Proven":False,
        "notes":"No production promotion. Historical selection bias/complete future holdout must be audited separately."}

def selftest():
    date="2026-11-08"
    combos={"単勝":"1","ワイド":"1-2","馬連":"1-2","馬単":"1-2",
            "3連複":"1-2-3","3連単":"1-2-3"}
    rows=[]
    for i in range(5):
        c=[{"betType":k,"combination":v,"predictedProbability":0.5,"officialOdds":3.0}
           for k,v in combos.items()]
        pays=[{"betType":key,"combination":combo,"payout100":400}
              for key,combo in combos.items()] if i==0 else []
        rows.append({"raceId":date+"-tokyo-"+str(i+1),"date":date,"raceNo":i+1,
            "sourceModel":SOURCE_MODEL,"modelSha256":"a"*64,
            "oddsSource":"jra-fast-official","officialOddsSha256":"b"*64,
            "lockedAt":"2026-11-08T01:00:00Z",
            "oddsFetchedAt":"2026-11-08T00:59:00Z",
            "candidateGeneratedAt":"2026-11-08T01:00:00Z",
            "startTimeJst":"11:00","raceScore":5-i,
            "resultStatus":"finished","payoutsCompleteForSixTypes":True,
            "refundHorses":[],"candidates":c,"payouts":pays})
    source={"oddsMoment":"JRA_OFFICIAL_PRE_T15","candidateGenerationMoment":"PRE_RESULT",
      "payoutProvenance":"JRA_ACTUAL_SETTLED",
      "days":[{"date":date,"venue":"東京","races":rows}]}
    rep=evaluate(source)
    assert rep["configurations"]==len(KS)*len(RANKERS)*15*len(STAKE_SPLITS)==360
    assert all(3<=x["racesPerVenueDay"]<=5 for x in rep["strategies"])
    assert all(len(set(x["distinctTypes"]))==2 for x in rep["strategies"])
    assert all(x["total"]["hitRacePct"] is not None and x["total"]["roiPct"] is not None for x in rep["strategies"])
    first=rep["strategies"][0]
    assert first["total"]["hitRaces"]==1
    assert first["total"]["roiPct"]==133.33
    assert first["total"]["hitRacePct"]==33.33
    assert rep["roi400Proven"] is False
    rows[0]["oddsFetchedAt"]="2026-11-08T01:46:00Z"
    try:evaluate(source)
    except ValueError as e:assert "T15" in str(e)
    else:raise AssertionError("LATE_OFFICIAL_ODDS_ACCEPTED")
    print("ALL15_BET_PAIRS_PAIRED_HIT_ROI_SELFTEST_OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.self_test:selftest();return
    if not args.input:parser.error("Only immutable pre-T15 six-market snapshots may be evaluated")
    report=evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    payload=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload+"\n",encoding="utf-8")
    print("RESEARCH_ALL15_PAIRED_METRICS",json.dumps({
        "configurations":report["configurations"],"cohorts":report["cohorts"],
        "certificationEligible":report["certificationEligible"],
        "productionChanged":False,
    },ensure_ascii=False))
if __name__=="__main__":main()
