#!/usr/bin/env python3
"""REPLAY two already-chosen v16 new cash-method recipes on 2026 Aug-Nov LIVE data.

No claims of fully proven real-world profitability. Underlying horse picks are
the production ten-year-completed-model; no newly trained horse selector.

Retrospective LIVE scenario:
- read anonymous frozen public selections, actual Light course tickets
  and settled returns, pre-T15 timestamps, recorded assumed odds and races
  exclusively via D1 SELECT statements; no operational mutations.
- insist on exactly TWO DISTINCT markets with positive actual stakes,
  pre-T15 lock and fully settled payout for EACH of FIVE original
  selected races on a venue-day. Incomplete venue-days are EXCLUDED
  as a unit; never select only known winners.
- rescale recorded true returns to yen per 1000, and apply the TWO frozen
  v16 winner rules with fixed per-race 2000 yen.
- refit the new monetary forecast for each target MONTH using only
  settled cash from earlier months: original pre-2026-Aug archive and
  eligible prior LIVE tickets. NO same-month target cash enters training.
- report 2026 Aug15-Nov14 original baseline vs cash 6mo 5r method
  and cash 96mo 3r method on EXACTLY MATCHED venue-days.
- assumed odds are not independently verified JRA T-minus-15 quotes.
- missing live records, late-locked races and venue-days are reported.
- no production changes; payout results are D1 stored and not
  independently reconciled with official JRA web.

THE OLD MODEL'S ORIGINAL HORSE SELECTOR FIT 2016-Aug to 2026-Aug09;
the Aug15 onward source selections are outside that target date range.
The new "best method" hyperparameters were selected using original
2017-2026 in-sample history; this is a retrospective evaluation, not
a prespecified or independently deployed real-time experiment.
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
import sys

ROOT=Path(__file__).resolve().parents[1]
LAST="2026-11-14"
FIRST="2026-08-10"
VENUES=("東京","中山","京都","阪神","中京","新潟","福島","小倉","札幌","函館")
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
JST=dt.timezone(dt.timedelta(hours=9))


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m


def d1(sql,params):
    if not sql.strip().upper().startswith("SELECT "):
        raise RuntimeError("NON_READ_ONLY_SQL_REJECTED")
    import urllib.request
    u=("https://api.cloudflare.com/client/v4/accounts/"+
       os.environ["CLOUDFLARE_ACCOUNT_ID"]+"/d1/database/"+
       os.environ["CLOUDFLARE_D1_DATABASE_ID"]+"/query")
    req=urllib.request.Request(u,method="POST",
       data=json.dumps({"sql":sql,"params":params}).encode(),
       headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],
                "Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=75) as f:
        data=json.load(f)
    if not data.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{data.get('errors')}")
    return (data.get("result") or [{}])[0].get("results",[])


def pages(sql,args,limit=350,hard_max=10000):
    out=[]
    while True:
        fetched=d1(sql+" LIMIT ? OFFSET ?",[ *args,limit,len(out)])
        out.extend(fetched)
        if len(out)>hard_max:
            raise RuntimeError("READ_ONLY_QUERY_HARD_PAGE_LIMIT")
        if len(fetched)<limit:
            break
    return out


def get_records():
    begin=FIRST
    end=(dt.date.fromisoformat(LAST)+dt.timedelta(days=1)).isoformat()
    states=pages("""
       SELECT state_key AS stateKey,state_value AS stateValue
       FROM rt_system_state
       WHERE state_key>=? AND state_key<?
       ORDER BY state_key
    """,["final_daily_selection:"+begin,"final_daily_selection:"+end],limit=65)
    bets=pages("""
       SELECT race_id AS raceId,course,bet_type AS betType,
              combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,
              return_yen AS returnYen,settlement_status AS settlementStatus,
              locked_at AS lockedAt
       FROM rt_public_bets
       WHERE race_id>=? AND race_id<?
         AND source_prediction_id=-2 AND course='ライト'
       ORDER BY race_id, id
    """,[begin+"-",end+"-"],limit=350)
    races=pages("""
       SELECT race_id AS raceId,race_date AS raceDate,venue,
              race_no AS raceNo,surface,
              distance_m AS distanceM,start_time_jst AS startTimeJst
       FROM rt_races
       WHERE race_id>=? AND race_id<?
       ORDER BY race_id
    """,[begin+"-",end+"-"],limit=350)
    if len(states)<20 or len(bets)<400 or len(races)<200:
        raise RuntimeError(f"INSUFFICIENT_LIVE_SOURCE_DATA:{len(states)},{len(bets)},{len(races)}")
    return states,bets,{str(r["raceId"]):r for r in races}


def locked_on_time(rows,start_date,start_time):
    if not start_time or len(start_time)<5:
        return False
    begin=dt.datetime.fromisoformat(start_date+"T"+start_time[:5]+":00+09:00")
    cutoff=begin-dt.timedelta(minutes=15)
    for row in rows:
        at=str(row.get("lockedAt") or "")
        try:
            d=dt.datetime.fromisoformat(at.replace("Z","+00:00"))
        except ValueError:
            return False
        if d.tzinfo is None or d>cutoff:
            return False
    return True


def create_live_rows(states,bets,races):
    by_bet=collections.defaultdict(list)
    for bet in bets:
        by_bet[str(bet["raceId"])].append(bet)
    byday=collections.defaultdict(list)
    diagnostics=collections.Counter()
    previously=[]
    seen=set()
    for s in states:
        key=str(s.get("stateKey") or "")
        date=key.removeprefix("final_daily_selection:")
        if not(FIRST<=date<=LAST):
            continue
        payload=json.loads(str(s.get("stateValue") or "{}"))
        if payload.get("sourceModel")!="ten-year-completed-model":
            raise RuntimeError(f"WRONG_PRODUCTION_SOURCE_MODEL:{date}")
        selected=payload.get("selected")
        if not isinstance(selected,list):
            raise RuntimeError(f"NO_FROZEN_SELECTION_LIST:{date}")
        for chosen in selected:
            rid=str(chosen.get("raceId") or "")
            if rid in seen:raise RuntimeError(f"DUPLICATE_SELECTION:{rid}")
            seen.add(rid)
            v=str(chosen.get("venue") or "")
            if v not in VENUES:raise RuntimeError(f"UNRECOGNIZED_VENUE:{v}")
            diagnostics["originalSelectedRaces"]+=1
            if rid not in races:
                diagnostics["missingRaceMetadata"]+=1
                byday[(date,v)].append(None)
                continue
            meta=races[rid]
            raw=by_bet.get(rid,[])
            if len(raw)!=2:
                diagnostics["notTwoRealMoneyTickets"]+=1
                byday[(date,v)].append(None)
                continue
            if not all(str(x.get("betType") or "") in MARKETS for x in raw):
                diagnostics["unexpectedMarket"]+=1
                byday[(date,v)].append(None)
                continue
            if len({str(x["betType"]) for x in raw})!=2:
                diagnostics["sameMarketTwice"]+=1
                byday[(date,v)].append(None)
                continue
            if any(int(x.get("stakeYen") or 0)<100 or
                   int(x.get("stakeYen") or 0)%100!=0 for x in raw):
                diagnostics["invalidRealStake"]+=1
                byday[(date,v)].append(None)
                continue
            if not locked_on_time(raw,date,str(chosen.get("startTimeJst") or meta.get("startTimeJst") or "")):
                diagnostics["lateOrMissingT15Lock"]+=1
                byday[(date,v)].append(None)
                continue
            if any(x.get("settlementStatus")!="settled" or x.get("returnYen") is None for x in raw):
                diagnostics["unsettledTickets"]+=1
                byday[(date,v)].append(None)
                continue
            if any(not math.isfinite(float(x.get("assumedOdds") or 0)) or
                   float(x.get("assumedOdds") or 0)<=0 for x in raw):
                diagnostics["missingPriceAssumption"]+=1
                byday[(date,v)].append(None)
                continue
            norm=[]
            for x in raw:
                stake=int(x["stakeYen"]);paid=int(x["returnYen"])
                per_thousand=(paid*1000)/stake
                if int(per_thousand)!=per_thousand:
                    raise RuntimeError(f"NON_INTEGER_RECONSTRUCTED_YEN:{rid}")
                norm.append((str(x["betType"]),str(x["combination"]),
                             float(x["assumedOdds"]),int(per_thousand)))
            row={
                "id":rid,
                "date":date,"month":date[:7],"venue":v,
                "race_no":int(meta["raceNo"]),
                "surface":str(meta.get("surface") or "障害"),
                "distance":int(meta.get("distanceM") or 0),
                "ticket":tuple(norm),
                "realOriginalStakeYen":sum(int(x["stakeYen"]) for x in raw),
                "realOriginalReturnYen":sum(int(x["returnYen"]) for x in raw),
            }
            byday[(date,v)].append(row)
            previously.append(row)
            diagnostics["eligibleIndividualRaces"]+=1
    if not byday:
        raise RuntimeError("NO_REAL_SELECTION_VENUE_DAYS")
    ready={}
    for datevenue,rr in byday.items():
        if len(rr)!=5:
            raise RuntimeError(f"NOT_FIVE_FROZEN_PICKS_PER_VENUE_DAY:{datevenue},{len(rr)}")
        if any(x is None for x in rr):
            diagnostics["excludedVenueDaysDueToIncompleteTicketPair"]+=1
            continue
        diagnostics["fullFiveRaceVenueDays"]+=1
        ready[datevenue]=rr
    return ready,previously,dict(diagnostics),len(byday)


def define_methods(v16):
    return {
        "profit_max_6month":{
            "horizon":6,"lag":0,"objective":"hit_cash",
            "stakeMode":"favour_predicted_90",
            "racesPerVenueDay":5,"racePriority":"expected_cash",
        },
        "roi_max_96month":{
            "horizon":96,"lag":0,"objective":"cash80",
            "stakeMode":"favour_predicted_90",
            "racesPerVenueDay":3,"racePriority":"expected_cash",
        },
    }


def monthly_sums(rows):
    if not rows:
        return None
    stake=sum(x["stake"] for x in rows)
    ret=sum(x["paid"] for x in rows)
    hit=sum(x["paid"]>0 for x in rows)
    return {
        "venueDays":len({(x["date"],x["venue"]) for x in rows}),
        "boughtRaces":len(rows),
        "stakeYen":stake,"receivedYen":ret,"profitYen":ret-stake,
        "roiPct":round(100*ret/stake,5) if stake else None,
        "afterLargestSingleRaceRoiPct":round(100*(ret-max(x["paid"] for x in rows))/stake,5) if stake else None,
        "hitRacePct":round(100*hit/len(rows),5),
        "qualifiedPastCash200":bool(ret>=2*stake+max(x["paid"] for x in rows) and hit*5>=len(rows) and len(rows)>=3*len({(x["date"],x["venue"]) for x in rows})),
    }


def replay(v16,archived,eligible,ready):
    by_month=collections.defaultdict(list)
    for row in archived:
        by_month[row["month"]].append(row)
    for row in eligible:
        if row["date"]<FIRST:
            raise RuntimeError("BAD_LIVE_DATE")
        if row["id"] in {x["id"] for x in by_month[row["month"]]}:
            raise RuntimeError("ARCHIVE_LIVE_RACE_OVERLAP")
        by_month[row["month"]].append(row)
    features={(r["id"],j):v16.ticket_features(r,j)
              for month in by_month for r in by_month[month] for j in (0,1)}
    months=sorted({date[:7] for date,venue in ready})
    out=collections.defaultdict(list)
    methodparams=define_methods(v16)
    for target in months:
        fits={}
        for name,m in methodparams.items():
            fits[name]=v16.fit_money_model(target,m["horizon"],m["lag"],
                     m["objective"],by_month,features)
        for (date,venue),rows in sorted(ready.items()):
            if not date.startswith(target):
                continue
            for name,m in methodparams.items():
                score=[]
                for row in rows:
                    a=v16.score_ticket(features[(row["id"],0)],fits[name],m["objective"])
                    b=v16.score_ticket(features[(row["id"],1)],fits[name],m["objective"])
                    rank,paid,stake=v16.model_prediction_for_race(
                        row,a,b,m["stakeMode"],m["racePriority"])
                    score.append((rank,row,paid,stake))
                score.sort(key=lambda x:(-x[0],x[1]["race_no"],x[1]["id"]))
                chosen=score[:m["racesPerVenueDay"]]
                if len(chosen)<3:raise RuntimeError("LESS_THAN_THREE_CASH_SELECTS")
                out[name].extend({
                    "date":row["date"],"venue":row["venue"],
                    "paid":paid,"stake":stake,
                } for _,row,paid,stake in chosen)
            for row in rows:
                out["equal_stake_baseline"].append({
                    "date":date,"venue":venue,"paid":sum(x[3] for x in row["ticket"]),
                    "stake":2000})
                out["actual_light_original_money"].append({
                    "date":date,"venue":venue,
                    "paid":row["realOriginalReturnYen"],
                    "stake":row["realOriginalStakeYen"]})
    return out,methodparams


def selftest():
    assert monthly_sums([{"date":"2026-11-14","venue":"東京","paid":2000,"stake":2000},
                         {"date":"2026-11-14","venue":"東京","paid":0,"stake":2000},
                         {"date":"2026-11-14","venue":"東京","paid":0,"stake":2000}])["roiPct"]==33.33333
    assert not locked_on_time([{"lockedAt":"2026-11-14T01:00:00Z"}],"2026-11-14","10:05")
    assert locked_on_time([{"lockedAt":"2026-11-14T00:30:00Z"}],"2026-11-14","10:05")
    print("LIVE_AUGNOV_STRICT_V16_CASH_REPLAY_SELFTEST_OK",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--self-test",action="store_true")
    a=parser.parse_args()
    if a.self_test:return selftest()
    if not a.out:parser.error("missing --out")
    v16=module("scripts/research-20261115-baseline-inclusive-rolling-money-v16.py",
               "original_new_rollcash_v16")
    archived,_=v16.archived_races()
    states,bets,races=get_records()
    full,elig,diagnostics,days=create_live_rows(states,bets,races)
    if not full:
        report={"status":"NO_FULL_FIVE_RACE_ON_TIME_VENUE_DAYS",
                "data":diagnostics,"period":[FIRST,LAST],"evaluated":False,
                "productionModified":False}
    else:
        datasets,methods=replay(v16,archived,elig,full)
        totals={name:monthly_sums(rows) for name,rows in datasets.items()}
        monthly={name:{month:monthly_sums([x for x in rows if x["date"][:7]==month])
                       for month in sorted({x["date"][:7] for x in rows})}
                 for name,rows in datasets.items()}
        report={
            "status":"STRICT_LIVE_AUGNOV_V16_REWEIGHTING_RESEARCH_COMPLETED",
            "evaluationPeriod":"2026-08-10..2026-11-14",
            "firstRecordedLiveSelectionDate":min(d for d,_ in full),
            "lastRecordedLiveSelectionDate":max(d for d,_ in full),
            "totalFrozenSelectedVenueDays":days,
            "fullyCompletableFiveRaceVenueDays":len(full),
            "ignoredAllIncompleteVenueDays":True,
            "sourceCoverageDiagnostics":diagnostics,
            "methods":methods,
            "comparisonAllOnIdenticalEligibleVenueDays":totals,
            "monthlyOnIdenticalVenueDays":monthly,
            "T15LockTimestampVerifiedForAllIncludedTickets":True,
            "allPriceAssumptionsVerifiedJRAOfficialPreT15":False,
            "historicalHorseModelTrainingIncludesPreAug2026":True,
            "v16MethodFamilySelectionWasOptimizedOn2017to2026Archive":True,
            "newMethodNotDeployed":True,
            "notFullOperationalCumulativeROI":True,
            "D1CashNotIndependentlyReconciledExternalJRA":True,
            "productionModified":False,
        }
    out=Path(a.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("LIVE_AUGNOV_V16_TWO_METHOD_STRICT_CASH_FINAL",json.dumps({
        "status":report["status"],
        "period":[FIRST,LAST],
        "selectedVenueDays":report.get("totalFrozenSelectedVenueDays"),
        "strictlyCompleteVenueDays":report.get("fullyCompletableFiveRaceVenueDays"),
        "coverage":report.get("sourceCoverageDiagnostics",report.get("data")),
        "comparableCash":report.get("comparisonAllOnIdenticalEligibleVenueDays"),
        "monthlyCash":report.get("monthlyOnIdenticalVenueDays"),
        "newModelIsLiveDeployed":False,
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
