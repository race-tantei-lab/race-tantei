#!/usr/bin/env python3
"""Read-only forward settlement of *actually frozen* pre-T15 ROI-first shadows.

Do not run on race day before results have all finished. Same venue-days and
identical race IDs, two ticket types, 2,000 yen per race on both strategies.
No synthetic final odds, retro-created predictions, re-scoring after result,
D1 writes, public bet modifications or new model promotion.
"""
import argparse
import collections
import datetime as dt
import importlib.util
import json
import pathlib

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/audit-live-six-type-paired-shadow-roi.py"
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}

def source():
    spec=importlib.util.spec_from_file_location("six_market_actual_audit",SOURCE)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def validate_shadow(audit,snapshot,pre,date,start):
    if not isinstance(pre,dict) or pre.get("policy")!="roi_first_jra_official_model_ev_v1":
        raise ValueError("MISSING_OR_WRONG_ROI_FIRST_POLICY")
    if pre.get("researchOnly") is not True or pre.get("notActualJraRoi") is not True:
        raise ValueError("RESEARCH_NOT_LABELED_AS_UNVALIDATED")
    if pre.get("minimumModeledHitPct")!=20 or float(pre.get("modeledTwoTicketHitPct",0))<20:
        raise ValueError("MODELED_HIT_FLOOR_NOT_MET")
    if pre.get("stakeYen")!=2000 or pre.get("oddsFetchedAt")!=snapshot.get("oddsFetchedAt"):
        raise ValueError("SHADOW_NOT_SAME_T15_OFFICIAL_ODDS")
    if not audit.t15_ok(pre.get("oddsFetchedAt"),date,start):
        raise ValueError("SHADOW_POST_T15_OFFICIAL_ODDS")
    tickets=pre.get("tickets")
    if not isinstance(tickets,list) or len(tickets)!=2:
        raise ValueError("SHADOW_TWO_TICKETS_REQUIRED")
    if len({r.get("betType") for r in tickets})!=2:
        raise ValueError("SHADOW_TWO_DIFFERENT_TYPES_REQUIRED")
    stakes=[]
    for ticket in tickets:
        bettype=ticket.get("betType")
        if bettype not in TYPES:raise ValueError("INVALID_SHADOW_TYPE")
        audit.horse_numbers(bettype,ticket.get("combination"))
        stake=ticket.get("stakeYen")
        if not isinstance(stake,int) or stake<100 or stake%100:
            raise ValueError("SHADOW_INVALID_STAKE")
        if float(ticket.get("conservativeOfficialOdds",0))<1:
            raise ValueError("NOT_OFFICIAL_ODDS")
        if not 0<float(ticket.get("modelProbability",0))<=1:
            raise ValueError("INVALID_PRE_RESULT_PROBABILITY")
        stakes.append(stake)
    if sum(stakes)!=2000:raise ValueError("SHADOW_BUDGET_MISMATCH")
    return tickets

def compare(date,selection,finals,bets,payouts,races):
    audit=source()
    canonical=audit.evaluate(selection,finals,bets,payouts,races,date)
    allowed={x["venue"] for x in selection}-set(canonical["missingOrInvalidVenueDays"])
    finals_by_id={r["raceId"]:r["snapshot"] for r in finals}
    race_map={r["raceId"]:r for r in races}
    bets_by_id=collections.defaultdict(list)
    for b in bets:bets_by_id[b["raceId"]].append(b)
    payout_by_id=audit.parse_types(payouts,False)
    groups=collections.defaultdict(list)
    for row in selection:
        if row["venue"] in allowed:groups[row["venue"]].append(row)
    complete={}
    excluded=dict(canonical["missingOrInvalidVenueDays"])
    for venue,chosen in groups.items():
        try:
            if len(chosen)!=5:raise ValueError("MISSING_FIVE_SELECTED_RACES")
            settled=[]
            for row in chosen:
                rid=row["raceId"]
                snap=finals_by_id.get(rid,{})
                tickets=validate_shadow(audit,snap,snap.get("roiFirstResearch"),
                    date,row["startTimeJst"])
                race=race_map.get(rid)
                if not race or race.get("status")!="finished":
                    raise ValueError("RESULT_NOT_FINISHED")
                if len(bets_by_id.get(rid,[]))!=2:
                    raise ValueError("CANONICAL_TWO_PUBLIC_BETS_MISSING")
                if {k[0] for k in payout_by_id.get(rid,{})}!=TYPES:
                    raise ValueError("SIX_ACTUAL_JRA_PAYOUTS_INCOMPLETE")
                if not isinstance(race.get("refunds"),list):
                    raise ValueError("MISSING_OFFICIAL_REFUND_LIST")
                refunds={int(n) for n in race["refunds"]}
                two=[]
                for ticket in tickets:
                    two.append(audit.settle(rid,ticket["betType"],ticket["combination"],
                        ticket["stakeYen"],payout_by_id[rid],refunds))
                baseline=[]
                for ticket in bets_by_id[rid]:
                    if not audit.t15_ok(ticket.get("lockedAt"),date,row["startTimeJst"]):
                        raise ValueError("CANONICAL_LATE_LOCK")
                    if int(ticket["stakeYen"])!=1000 or ticket.get("settlement")!="settled":
                        raise ValueError("CANONICAL_NOT_VALID_SETTLED")
                    result=audit.settle(rid,ticket["betType"],ticket["combination"],
                        1000,payout_by_id[rid],refunds)
                    if result["returnYen"]!=int(ticket["returnYen"]):
                        raise ValueError("PUBLIC_BET_MISMATCH_JRA")
                    baseline.append(result)
                settled.append({"raceId":rid,"score":row["raceScore"],
                    "roiFirst":{"stake":2000,"returned":sum(x["returnYen"] for x in two),
                        "wins":sum(x["winning"] for x in two),
                        "refunds":sum(x["refunded"] for x in two)},
                    "canonical":{"stake":2000,"returned":sum(x["returnYen"] for x in baseline),
                        "wins":sum(x["winning"] for x in baseline),
                        "refunds":sum(x["refunded"] for x in baseline)}})
            complete[venue]=sorted(settled,key=lambda r:(-r["score"],r["raceId"]))
        except (ValueError,KeyError,TypeError) as e:
            excluded[venue]=str(e)
    comparisons={}
    for k in (3,4,5):
        chosen=[row for venue in sorted(complete) for row in complete[venue][:k]]
        roi=audit.metrics([x["roiFirst"] for x in chosen])
        baseline=audit.metrics([x["canonical"] for x in chosen])
        comparisons[str(k)]={"sharedRaceIds":[x["raceId"] for x in chosen],
            "sameSelectedRacesAndStakeForBoth":True,
            "roiFirstHitAndActualJraRoi":roi,"canonicalHitAndActualJraRoi":baseline}
    return {"date":date,"classification":"PROSPECTIVE_ONLY_IF_SNAPSHOT_GENUINELY_FROZEN_BEFORE_T15",
        "futureOutcomeLabelsUsedInSelection":False,"notProofOfFutureProfit":True,
        "selectedVenueDays":len(allowed),"fullyMatchedVenueDays":len(complete),
        "excludedVenueDays":excluded,"comparisons":comparisons,
        "productionBetsRewritten":False,"source":"D1 stored official JRA payouts and immutable T15 research shadow"}

def selftest():
    audit=source()
    snap={"oddsFetchedAt":"2026-11-08T00:40:00Z"}
    model={"policy":"roi_first_jra_official_model_ev_v1",
           "researchOnly":True,"notActualJraRoi":True,
           "minimumModeledHitPct":20,"modeledTwoTicketHitPct":31.2,
           "stakeYen":2000,"oddsFetchedAt":"2026-11-08T00:40:00Z",
           "tickets":[{"betType":"単勝","combination":"1","stakeYen":1900,
                       "conservativeOfficialOdds":4,"modelProbability":0.3},
                      {"betType":"ワイド","combination":"1-2","stakeYen":100,
                       "conservativeOfficialOdds":2.0,"modelProbability":0.4}]}
    assert len(validate_shadow(audit,snap,model,"2026-11-08","10:00"))==2
    late=dict(model,oddsFetchedAt="2026-11-08T01:00:00Z")
    try:validate_shadow(audit,snap,late,"2026-11-08","10:00")
    except ValueError:pass
    else:raise AssertionError("INVALID_LATE_SHADOW_NOT_REJECTED")
    missing=dict(model,tickets=[model["tickets"][0],model["tickets"][0]])
    try:validate_shadow(audit,snap,missing,"2026-11-08","10:00")
    except ValueError:pass
    else:raise AssertionError("DUPLICATE_BET_TYPES_NOT_REJECTED")
    print("ROI_FIRST_TRUE_T15_PAIRED_JRA_SETTLEMENT_SELFTEST_OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--date")
    args=parser.parse_args()
    if args.self_test:selftest();return
    if not args.date:parser.error("--date required")
    date=dt.date.fromisoformat(args.date)
    if date>=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date():
        raise RuntimeError("RACE_DAY_MUST_BE_FINISHED_BEFORE_EVALUATION")
    audit=source()
    out=compare(args.date,*audit.fetch_date(args.date))
    print("ROI_FIRST_PROSPECTIVE_TRUE_JRA_SETTLEMENT_PAIRED",
          json.dumps(out,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
