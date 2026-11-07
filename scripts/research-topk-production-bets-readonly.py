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
import random
from pathlib import Path
import urllib.request
import urllib.error

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
    try:
        with urllib.request.urlopen(request,timeout=35) as response:
            data=json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body=exc.read(1200).decode("utf-8","replace")
        # Cloudflare quota errors and invalid SQL both return 400; expose
        # sanitized response so they are not incorrectly conflated.
        raise RuntimeError(f"READ_ONLY_D1_HTTP_{exc.code}: {body}") from None
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
        b.assumed_odds AS assumedOdds,r.refunds AS refunds,
        b.settlement_status AS settlementStatus,b.locked_at AS lockedAt
        FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date>=? AND r.race_date<? AND b.source_prediction_id=-2
          AND b.course='ライト'
        ORDER BY r.race_date,b.race_id,b.id LIMIT 1500""",
        [start,end_exclusive])
    if len(selections)>=MAX_SELECTION_ROWS or len(bets)>=MAX_BET_ROWS:
        raise RuntimeError("D1_READ_LIMIT_REACHED_REPORT_INVALID")
    return {"selectionStates":selections,"bets":bets}

def ticket_is_real_hit(ticket):
    """Return/repaid stake is ROI cash but NEVER an actual hit."""
    value=int(ticket.get("returnYen") or 0)
    if value<=0:return False
    try:
        refunds=set(int(n) for n in json.loads(ticket.get("refunds") or "[]"))
        numbers=set(int(n) for n in str(ticket.get("combination") or "").split("-"))
    except (ValueError,TypeError):
        raise ValueError("BAD_REFUND_OR_COMBINATION_IN_SETTLED_BET") from None
    if numbers & refunds:return False
    return True


def hit_coverage(rows):
    """Hit coverage on ORIGINAL two distinct locked tickets; never infer odds."""
    n=len(rows)
    if not n:return {"races":0,"hitRaces":0,"hitRacePct":None,
        "winningTickets":0,"tickets":0,"hitTicketPct":None,"bothTicketsHitRaces":0,
        "profitableRaces":0,"profitableRacePct":None}
    if any(not x["valid"] for x in rows):
        raise AssertionError("HIT_COVERAGE_MUST_EXCLUDE_INVALID_RACES")
    paid=sum(x["hitTickets"] for x in rows)
    hit=sum(x["hitTickets"]>0 for x in rows)
    both=sum(x["hitTickets"]==2 for x in rows)
    profit=sum(x["return"]>x["stake"] for x in rows)
    return {"races":n,"hitRaces":hit,
        "hitRacePct":round(100*hit/n,2),"winningTickets":paid,
        "tickets":2*n,"hitTicketPct":round(100*paid/(2*n),2),
        "bothTicketsHitRaces":both,"profitableRaces":profit,
        "profitableRacePct":round(100*profit/n,2)}


def venue_day_hit_sweeps(complete,k):
    """Only count fully complete k-ticket races per venue/day."""
    if k not in TOP_KS:raise ValueError("COUNT_BELOW_3_FORBIDDEN")
    cohorts=[rows[:k] for rows in complete.values()]
    if any(len(rows)!=k or any(not x["valid"] for x in rows) for rows in cohorts):
        raise AssertionError("INCOMPLETE_VENUE_DAY")
    full=sum(all(x["hitTickets"]>0 for x in rows) for rows in cohorts)
    zero=sum(all(x["hitTickets"]==0 for x in rows) for rows in cohorts)
    eighty=sum(sum(x["hitTickets"]>0 for x in rows)>=math.ceil(0.8*k)
               for rows in cohorts)
    return {"completeVenueDays":len(cohorts),"allRacesHitVenueDays":full,
        "noRacesHitVenueDays":zero,"atLeast80PctRacesHitVenueDays":eighty,
        "allRacesHitVenueDayPct":round(100*full/len(cohorts),2) if cohorts else None,
        "atLeast80PctRacesHitVenueDayPct":round(100*eighty/len(cohorts),2) if cohorts else None}


def matched_complete_days(compiled):
    """Paired fair comparison: identical date+venue cohorts with all five T-15 bets."""
    by_venue=collections.defaultdict(list)
    for row in compiled:
        by_venue[(row["date"],row["venue"])].append(row)
    complete={key:sorted(rows,key=lambda x:x["rank"]) for key,rows in by_venue.items()
              if len(rows)==5 and all(x["valid"] for x in rows)}
    by_date=collections.defaultdict(list)
    for (day,venue),rows in complete.items():
        by_date[day].append(rows)
    summary={"matchedCompleteVenueDays":len(complete),"matchedRaceDates":len(by_date),
             "topKs":{},"rankOutcomes":{}}
    for k in TOP_KS:
        subset=[r for rows in complete.values() for r in rows[:k]]
        stake=sum(x["stake"] for x in subset)
        payout=sum(x["return"] for x in subset)
        monthly={}
        for m in sorted({x["date"][:7] for x in subset}):
            x=[r for r in subset if r["date"].startswith(m)]
            s=sum(r["stake"] for r in x)
            monthly[m]=round(100*sum(r["return"] for r in x)/s,2) if s else None
        max_r=max((x["return"] for x in subset),default=0)
        summary["topKs"][str(k)]={
          "races":len(subset),"stakeYen":stake,"returnYen":payout,
          "roiPct":round(100*payout/stake,2) if stake else None,
          "roiWithoutLargestRacePayoutPct":round(100*(payout-max_r)/stake,2) if stake else None,
          "largestRacePayoutSharePct":round(100*max_r/payout,2) if payout else None,
          "hitCoverage":hit_coverage(subset),
          "venueDayCoverage":venue_day_hit_sweeps(complete,k),
          "months":monthly
        }
    for rank in range(1,6):
        xs=[r for rows in complete.values() for r in rows if r["rank"]==rank]
        s=sum(r["stake"] for r in xs)
        summary["rankOutcomes"][str(rank)]={
            "races":len(xs),"roiPct":round(100*sum(r["return"] for r in xs)/s,2) if s else None
        }
    # Cluster bootstrap by race DATE (not individual race), to preserve same-day dependence.
    rng=random.Random(20261107)
    dates=sorted(by_date)
    differences={("3","5"):[],("4","5"):[],("3","4"):[]}
    if dates:
        day_totals={}
        for day in dates:
            day_totals[day]={k:(
                sum(r["stake"] for rows in by_date[day] for r in rows[:k]),
                sum(r["return"] for rows in by_date[day] for r in rows[:k]))
                for k in TOP_KS}
        for _ in range(10000):
            sample=[dates[rng.randrange(len(dates))] for __ in dates]
            roi={}
            for k in TOP_KS:
                stake=sum(day_totals[d][k][0] for d in sample)
                ret=sum(day_totals[d][k][1] for d in sample)
                roi[str(k)]=100*ret/stake
            for (a,b),vec in differences.items():
                vec.append(roi[a]-roi[b])
        paired={}
        for key,x in differences.items():
            x.sort()
            paired["vs".join(key)]={
               "observedDiffPctPoints":round(summary["topKs"][key[0]]["roiPct"]-
                                             summary["topKs"][key[1]]["roiPct"],2),
               "dayClusterBootstrap95PctInterval":[round(x[250],2),round(x[9750],2)],
               "positiveDifferenceSamplesPct":round(100*sum(v>0 for v in x)/len(x),2)}
        summary["pairedDifferences"]=paired
    summary["bootstrapCaveat"]="resampling dates describes this historical cohort only; not a future guarantee"
    return summary


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
                    "return":refund if reason is None else 0,
                    "hitTickets":sum(ticket_is_real_hit(x) for x in actual)
                      if reason is None else 0,
                    "ticketRows":actual if reason is None else []})
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
            "roiWithoutLargestRacePayoutPct":round(100*(payout-max((r["return"] for r in valid),default=0))/stake,2) if stake else None,
            "hitCoverageOnValidRaces":hit_coverage(valid),
            "allPlannedBetsVerified":len(subset)==len(valid)}
        summaries[str(k)]=summary
        for month in sorted({x["date"][:7] for x in subset}):
            v=[x for x in valid if x["date"].startswith(month)]
            s=sum(x["stake"] for x in v)
            p=sum(x["return"] for x in v)
            by_month.setdefault(month,{})[str(k)]={"validRaces":len(v),
                "plannedRaces":sum(x["date"].startswith(month) for x in subset),
                "roiOnValidBetsPct":round(p*100/s,2) if s else None,
                "hitCoverageOnValidRaces":hit_coverage(v)}
    return {"status":"RETROSPECTIVE_RESEARCH_NOT_PROMOTION","basis":"actual immutable locked bets, ranked by original persisted raceScore", "dateFrom":min((x["date"] for x in compiled),default=None),
        "dateThrough":max((x["date"] for x in compiled),default=None),
        "strategies":summaries,"byMonth":by_month,"invalidReasons":dict(rejected),
        "fairPairedCompleteDays":matched_complete_days(compiled),
        "pairedStakeGrid":paired_stake_grid(compiled),
        "limitations":["Only the five previously selected races can be compared; never a model that selected different races",
            "Historical pre-race score capture timestamps are not independently verified here",
            "Missing or late bets are counted, not silently erased",
            "ROI denominator is placed valid bets only; incompleteness separately prohibits promotion",
            "Past performance can select a hypothesis only; future unseen race-day comparison is mandatory",
            "No official payout independently compared with JRA"],"promotionEligible":False}


STAKES_GRID={
    "equal_1000_1000":(1000,1000,"equal"),
    "nonwide_1500_500":(1500,500,"nonwide"),
    "nonwide_1800_200":(1800,200,"nonwide"),
    "nonwide_1900_100":(1900,100,"nonwide"),
    "wide_1500_500":(1500,500,"wide"),
    "lower_odds_1500_500":(1500,500,"lower_odds"),
    "lower_odds_1800_200":(1800,200,"lower_odds"),
    "prefer_3to10_1500_500":(1500,500,"prefer_3to10"),
}

def allocate_stakes(policy, ticket_rows):
    if len(ticket_rows)!=2:raise ValueError("NEED_EXACTLY_TWO_TICKETS")
    heavy,small,kind=STAKES_GRID[policy]
    rows=sorted(ticket_rows,key=lambda x:(str(x["betType"]),str(x["combination"])))
    if kind=="equal":return [(rows[0],1000),(rows[1],1000)]
    if kind=="nonwide":
        selected=0 if rows[0]["betType"]!="ワイド" else 1
    elif kind=="wide":
        selected=0 if rows[0]["betType"]=="ワイド" else 1
    else:
        try:odds=[float(x["assumedOdds"]) for x in rows]
        except (ValueError,TypeError,KeyError):raise ValueError("NO_PRE_LOCK_ODDS") from None
        if any(not math.isfinite(x) or x<1 for x in odds):raise ValueError("INVALID_PRE_LOCK_ODDS")
        if kind=="lower_odds":
            selected=0 if (odds[0],str(rows[0]["betType"]))<=(odds[1],str(rows[1]["betType"])) else 1
        elif kind=="prefer_3to10":
            matches=[i for i,x in enumerate(odds) if 3<=x<10]
            selected=matches[0] if len(matches)==1 else (0 if odds[0]<=odds[1] else 1)
        else:raise ValueError("UNKNOWN_STAKE_KIND")
    result=[(rows[0],small),(rows[1],small)]
    result[selected]=(rows[selected],heavy)
    if sum(x[1] for x in result)!=2000 or min(x[1] for x in result)<100:
        raise AssertionError("INCORRECT_STAKE_ALLOCATION")
    return result

def candidate_summary(rows,policy):
    cash=0;hits=0;hit_tickets=0;win_races=0;returns=[]
    for row in rows:
        real_bets=row.get("ticketRows") or []
        if not row["valid"] or len(real_bets)!=2:raise ValueError("UNPAIRED_OR_INCOMPLETE_RACE")
        amount=0
        for bet,stake in allocate_stakes(policy,real_bets):
            actual_stake=int(bet["stakeYen"])
            original_return=int(bet["returnYen"])
            if actual_stake!=1000 or original_return<0:
                raise ValueError("INCONSISTENT_ORIGINAL_STAKE_RETURN")
            if (original_return*stake)%actual_stake:
                raise ValueError("NON_INTEGRAL_ACTUAL_PAYOFF")
            amount+=original_return*stake//actual_stake
        cash+=amount
        hits+=int(row["hitTickets"]>0)
        hit_tickets+=row["hitTickets"]
        win_races+=int(amount>2000)
        returns.append(amount)
    n=len(rows);investment=2000*n
    return {
        "races":n,"hitRaces":hits,"hitRacePct":round(100*hits/n,2) if n else None,
        "hitTicketPct":round(100*hit_tickets/(2*n),2) if n else None,
        "stakeYen":investment,"returnYen":cash,"profitYen":cash-investment,
        "roiPct":round(100*cash/investment,2) if investment else None,
        "roiWithoutLargestRacePayoutPct":round(100*(cash-max(returns,default=0))/investment,2) if investment else None,
        "profitableRacePct":round(100*win_races/n,2) if n else None,
    }

def paired_stake_grid(compiled):
    """Same 5-complete venue-days for every K and stake split: 24 strict paired trials.

    2026 data were inspected before this search. This is descriptive,
    NEVER a future holdout, or a proof that any rule is profitable.
    """
    groups=collections.defaultdict(list)
    for row in compiled:groups[(row["date"],row["venue"])].append(row)
    complete={k:sorted(v,key=lambda x:x["rank"]) for k,v in groups.items()
              if len(v)==5 and all(x["valid"] for x in v)}
    if not complete:
        return {"status":"NO_COMPLETE_DAYS","promotionEligible":False}
    periods={
       "full":lambda day:True,
       "trainAugSep":lambda day:day<"2026-10-01",
       "holdoutOctober":lambda day:"2026-10-01"<=day<"2026-11-01",
       "November":lambda day:day>="2026-11-01",
    }
    output={}
    for period,valid_date in periods.items():
        by_period={key:rows for key,rows in complete.items() if valid_date(key[0])}
        matrix={}
        for k in TOP_KS:
            subset=[r for group in by_period.values() for r in group[:k]]
            matrix[str(k)]={policy:candidate_summary(subset,policy) for policy in STAKES_GRID}
        output[period]={"venueDays":len(by_period),"raceDates":len({key[0] for key in by_period}),
                        "sameOriginalFiveRaceCohort":True,"strategies":matrix}
    full=output["full"]["strategies"]
    baseline=full["5"]["equal_1000_1000"]
    pareto=[]
    for k,portfolio in full.items():
        for policy,stats in portfolio.items():
            if stats["hitRacePct"] is None:continue
            is_dominated=any(
                (other["hitRacePct"]>=stats["hitRacePct"] and other["roiPct"]>=stats["roiPct"]
                  and (other["hitRacePct"]>stats["hitRacePct"] or other["roiPct"]>stats["roiPct"]))
                for b in full.values() for other in b.values() if other["hitRacePct"] is not None)
            if not is_dominated:
                pareto.append({"racesPerVenue":int(k),"stakePolicy":policy,
                              "hitRacePct":stats["hitRacePct"],"roiPct":stats["roiPct"],
                              "stakeYen":stats["stakeYen"],"returnYen":stats["returnYen"]})
    dominating=[x for x in pareto if x["hitRacePct"]>baseline["hitRacePct"] and x["roiPct"]>baseline["roiPct"]]
    return {"status":"RETROSPECTIVE_2026_PAIRED_HIT_AND_ROI",
        "source":"original immutable production bets, verified T-15 and 5 complete selected races",
        "totalVariants":len(STAKES_GRID)*len(TOP_KS),
        "testedStakePolicies":list(STAKES_GRID),
        "coverageNote":"Do not hide missing/late bets outside complete venue-days",
        "periods":output,
        "paretoHistoricalCandidates":pareto,
        "dominatesEqualFiveRaceHistory":dominating,
        "promotionEligible":False,
        "forwardROIValidated":False,
        "limitations":[
            "Same past original horse/ticket predictions only, not a new horse probability model",
            "Original recorded returns still require independent official JRA payout verification",
            "Past 2026 months were already examined; optimizing against them is hindsight",
            "All races with absent or late original tickets are excluded only from equal matched complete venue-days",
            "An observed Pareto frontier does not establish future profitability"]}


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
                "combination":"1" if typ=="単勝" else "1-2",
                "stakeYen":1000,"returnYen":payouts[i-1] if typ=="単勝" else 0,
                "assumedOdds":3.0 if typ=="単勝" else 8.0,"refunds":"[]"})
    states=[{"stateKey":"final_daily_selection:"+day,"stateValue":json.dumps(
        {"sourceModel":"ten-year-completed-model","resultDataUsedForTargetDay":False,"selected":races})}]
    outcome=evaluate({"selectionStates":states,"bets":bets})
    assert outcome["strategies"]["3"]["roiOnValidBetsPct"]==150.0,outcome
    assert outcome["strategies"]["4"]["roiOnValidBetsPct"]==112.5,outcome
    assert outcome["strategies"]["5"]["roiOnValidBetsPct"]==90.0,outcome
    assert outcome["strategies"]["3"]["hitCoverageOnValidRaces"]["hitRacePct"]==66.67
    assert outcome["strategies"]["5"]["hitCoverageOnValidRaces"]["hitRacePct"]==40.0
    assert outcome["strategies"]["5"]["hitCoverageOnValidRaces"]["hitTicketPct"]==20.0
    assert outcome["strategies"]["5"]["hitCoverageOnValidRaces"]["profitableRaces"]==2
    complete=outcome["fairPairedCompleteDays"]["topKs"]
    assert complete["3"]["venueDayCoverage"]["allRacesHitVenueDays"]==0
    assert complete["5"]["venueDayCoverage"]["allRacesHitVenueDays"]==0
    assert complete["5"]["venueDayCoverage"]["completeVenueDays"]==1
    assert complete["5"]["hitCoverage"]["hitRaces"]==2
    grid=outcome["pairedStakeGrid"]
    assert grid["totalVariants"]==24
    assert grid["periods"]["full"]["strategies"]["3"]["equal_1000_1000"]["hitRacePct"]==66.67
    assert grid["periods"]["full"]["strategies"]["3"]["nonwide_1900_100"]["returnYen"]==17100
    assert grid["periods"]["full"]["strategies"]["5"]["equal_1000_1000"]["roiPct"]==90.0
    assert grid["promotionEligible"] is False
    refunded={"betType":"単勝","combination":"1","returnYen":1000,"refunds":"[1]"}
    assert not ticket_is_real_hit(refunded)
    assert ticket_is_real_hit({**refunded,"refunds":"[]"})
    assert all(int(k)>=3 for k in TOP_KS)
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
