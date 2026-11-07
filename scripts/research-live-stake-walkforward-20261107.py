#!/usr/bin/env python3
"""Read-only real-payoff counterfactual on T-15-locked production tickets.

This is NOT a backtest of changing horses/races: only stake splits of the
*actual identical two tickets* selected by the production model. Uses locked
assumed odds solely for the advance-known allocation decision, never payouts.
The JRA recorded payout scales linearly in 100-yen ticket units. No D1 writes.
"""
import collections
import datetime as dt
import json
import os
import random
import sys
import urllib.request

START="2026-08-10"
END="2026-11-08"
TRAIN_END="2026-10-01"
VALIDATION_END="2026-11-01"
POLICIES=(
 "equal_1000_1000",
 "nonwide_1500_500",
 "nonwide_1800_200",
 "nonwide_1900_100",
 "wide_1500_500",
 "lower_odds_1500_500",
 "lower_odds_1800_200",
 "prefer_3to10_1500_500",
)
 
def query(sql,params):
    u=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
    req=urllib.request.Request(u,data=json.dumps({"sql":sql,"params":params}).encode(),method="POST",
          headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"]})
    with urllib.request.urlopen(req,timeout=80) as response: parsed=json.load(response)
    if not parsed.get("success"): raise RuntimeError("D1_READ_FAILED:"+str(parsed.get("errors"))[:250])
    return (parsed.get("result") or [{}])[0].get("results") or []

def deadline_ok(rows,day,race):
    try:
        start=dt.datetime.fromisoformat(day+"T"+race["startTimeJst"][:5]+":00+09:00")
        for row in rows:
            stamp=dt.datetime.fromisoformat(str(row["lockedAt"]).replace("Z","+00:00"))
            if stamp > start-dt.timedelta(minutes=15):return False
        return True
    except (ValueError,KeyError,TypeError):return False

def parse(selected,bet_rows):
    ids={}
    for r in selected:
        date=str(r["stateKey"]).split(":")[-1]
        p=json.loads(r["stateValue"])
        if p.get("sourceModel")!="ten-year-completed-model":raise AssertionError("NOT_COMPLETED_MODEL_SELECTION")
        for race in p.get("selected") or []:
            rid=str(race.get("raceId") or "")
            if rid in ids:raise AssertionError("DUPLICATE_SELECTED_RACE")
            ids[rid]=(date,race)
    bets=collections.defaultdict(list)
    for b in bet_rows: bets[str(b["raceId"])].append(b)
    valid=[]
    exclusion=collections.Counter()
    for rid,(date,race) in sorted(ids.items()):
        rows=bets.get(rid,[])
        if len(rows)!=2:
            exclusion["no_exactly_two_bets"]+=1;continue
        if len({b["betType"] for b in rows})!=2:
            exclusion["duplicated_bet_type"]+=1;continue
        if not deadline_ok(rows,date,race):
            exclusion["late_or_timestamp_missing"]+=1;continue
        if any(b["settlementStatus"]!="settled" for b in rows):
            exclusion["unsettled"]+=1;continue
        if any(b["returnYen"] is None or int(b["stakeYen"] or 0)!=1000 or int(b["returnYen"])<0 or
               int(b["returnYen"])%10!=0 or float(b["assumedOdds"] or 0)<1 for b in rows):
            exclusion["invalid_stake_return_odds"]+=1;continue
        valid.append({"date":date,"raceId":rid,"rows":sorted(rows,key=lambda x:(x["betType"],x["combination"]))})
    return valid,{"selectedRaces":len(ids),"eligibleRaces":len(valid),"excluded":dict(exclusion)}

def allocate(name,race):
    b=race["rows"]
    if name=="equal_1000_1000":return (1000,1000)
    if name.startswith("nonwide"):
        heavy=0 if b[0]["betType"]!="ワイド" else 1
        first={"nonwide_1500_500":1500,"nonwide_1800_200":1800,"nonwide_1900_100":1900}[name]
    elif name=="wide_1500_500":
        heavy=0 if b[0]["betType"]=="ワイド" else 1;first=1500
    elif name.startswith("lower_odds"):
        heavy=0 if (float(b[0]["assumedOdds"]),str(b[0]["betType"]))<=(float(b[1]["assumedOdds"]),str(b[1]["betType"])) else 1
        first=1500 if name=="lower_odds_1500_500" else 1800
    elif name=="prefer_3to10_1500_500":
        o=[float(x["assumedOdds"]) for x in b]
        good=[i for i,x in enumerate(o) if 3<=x<10]
        heavy=good[0] if len(good)==1 else (0 if o[0]<=o[1] else 1)
        first=1500
    else:raise AssertionError("UNKNOWN_POLICY "+name)
    a=[2000-first,2000-first];a[heavy]=first
    if sum(a)!=2000 or min(a)<100 or any(x%100!=0 for x in a):raise AssertionError("ILLEGAL_STAKES")
    return tuple(a)

def summarize(races,policy):
    stake=0;ret=0;winners=0;daymap=collections.defaultdict(lambda:{"stakeYen":0,"returnYen":0,"races":0})
    venue=collections.defaultdict(lambda:{"stakeYen":0,"returnYen":0,"races":0})
    pays=[]
    for race in races:
        allocation=allocate(policy,race)
        returned=0
        for b,proposed in zip(race["rows"],allocation):
            # Exact JRA 100-yen payout implied by original settled 1,000-yen ticket.
            original=int(b["returnYen"])
            if (original*proposed)%1000!=0:raise AssertionError("NON_INTEGRAL_100_YEN_PAYOUT")
            returned+=original*proposed//1000
        stake+=2000;ret+=returned;winners+=int(returned>0)
        d=daymap[race["date"]];d["stakeYen"]+=2000;d["returnYen"]+=returned;d["races"]+=1
        parts=race["raceId"].split("-");key=parts[3] if len(parts)>4 else "unknown"
        v=venue[key];v["stakeYen"]+=2000;v["returnYen"]+=returned;v["races"]+=1
        pays.append((returned,race["date"],race["raceId"]))
    pays.sort(reverse=True)
    trimmed=ret-(pays[0][0] if pays else 0)
    return {"races":len(races),"stakeYen":stake,"returnYen":ret,"profitYen":ret-stake,
            "roiPct":round(100*ret/stake,2) if stake else None,
            "paidRaceCount":winners,
            "roiExcludingLargestPayoutPct":round(100*trimmed/stake,2) if stake else None,
            "bestSingleRaceReturnYen":pays[0][0] if pays else 0,
            "daily":{k:{**v,"roiPct":round(v["returnYen"]/v["stakeYen"]*100,2)} for k,v in sorted(daymap.items())},
            "venue":{k:{**v,"roiPct":round(v["returnYen"]/v["stakeYen"]*100,2)} for k,v in sorted(venue.items())}}

def difference_ci(races,policy_a,policy_b):
    """Paired date-group bootstrap; high uncertainty on small day samples."""
    days=sorted({x["date"] for x in races})
    if len(days)<4:return None
    pairs=[]
    for d in days:
        subset=[x for x in races if x["date"]==d]
        a=summarize(subset,policy_a)
        b=summarize(subset,policy_b)
        pairs.append((a["returnYen"]-b["returnYen"],a["stakeYen"]))
    rng=random.Random(20261107)
    values=[]
    for _ in range(5000):
        picked=[pairs[rng.randrange(len(pairs))] for _ in pairs]
        values.append(100*sum(x[0] for x in picked)/sum(x[1] for x in picked))
    values.sort()
    return {"days":len(days),"pairedRoiDifferencePctPoints":round(100*sum(x[0] for x in pairs)/sum(x[1] for x in pairs),2),
            "dateBootstrap95PctCI":[round(values[125],2),round(values[4874],2)]}

def full_report(races,coverage):
    train=[x for x in races if x["date"]<TRAIN_END]
    hold=[x for x in races if TRAIN_END<=x["date"]<VALIDATION_END]
    final=[x for x in races if x["date"]>=VALIDATION_END]
    if len(train)<40 or len(hold)<40:raise AssertionError("INSUFFICIENT_TEMPORAL_SPLIT")
    train_result={k:summarize(train,k) for k in POLICIES}
    selected=max(POLICIES,key=lambda x:(train_result[x]["roiExcludingLargestPayoutPct"],-POLICIES.index(x)))
    summaries={part:{k:summarize(rows,k) for k in POLICIES} for part,rows in
               (("trainAugSep",train),("holdoutOctober",hold),("untouchedNovember",final),("allEligible",races))}
    base=summaries["holdoutOctober"]["equal_1000_1000"]
    challenger=summaries["holdoutOctober"][selected]
    diff=difference_ci(hold,selected,"equal_1000_1000")
    # No positive-ROI acceptance unless the unused holdout independently clears 100%,
    # improves baseline, and is robust after removing its largest winning race.
    passed=bool(challenger["roiPct"]>100 and challenger["roiPct"]>base["roiPct"]
                and challenger["roiExcludingLargestPayoutPct"]>=100
                and diff and diff["dateBootstrap95PctCI"][0]>0)
    return {"dateRange":START+".."+END,"source":"real T15 locked and settled JRA production tickets; no data writes",
        "counterfactualScope":"same two actual tickets, same selected races, stake-only 100-yen units, no new bet selection",
        "coverage":coverage,"trainCutoff":TRAIN_END,"holdoutCutoff":VALIDATION_END,
        "allPredeclaredStrategies":list(POLICIES),"trainChosenBy":"ROI after removing the largest payout, training period only",
        "trainChosenPolicy":selected,"results":summaries,
        "holdoutChosenVsBaselineBootstrap":diff,
        "holdoutAcceptancePassed":passed,
        "decision":"qualified_for_further_forward_test" if passed else "REJECT_NO_PROVEN_POSITIVE_RETURN",
        "warnings":["Do not select best holdout policy after observing holdout payout",
                    "Missing and late races are exclusions, not zero-loss wins",
                    "This tests only stake splits of unchanged public bet types, not improvement from selecting different horses or races",
                    "Quote odds at original lock; winnings extrapolated from recorded real JRA payout in 100-yen increments."]}

def self_test():
    races=[]
    for i in range(1,5):
        d=f"2026-08-{i+9:02d}" if i<3 else f"2026-10-{i:02d}"
        races.append({"date":d,"raceId":d+"-tokyo-01","rows":[
            {"betType":"単勝","combination":"1","assumedOdds":3.2,"stakeYen":1000,"returnYen":3000 if i%2 else 0},
            {"betType":"ワイド","combination":"1-2","assumedOdds":8.4,"stakeYen":1000,"returnYen":5000 if i==2 else 0}]})
    assert summarize(races,"equal_1000_1000")["stakeYen"]==8000
    assert summarize(races,"nonwide_1500_500")["returnYen"]==1500*(6)+500*(5)
    assert allocate("nonwide_1900_100",races[0])==(1900,100)
    assert allocate("wide_1500_500",races[0])==(500,1500)
    print("LIVE_STAKE_WALKFORWARD_SELFTEST_OK")

def main():
    if "--self-test" in sys.argv:self_test();return
    states=query("""SELECT state_key AS stateKey,state_value AS stateValue
       FROM rt_system_state WHERE state_key>=? AND state_key<?
       ORDER BY state_key LIMIT 150""",["final_daily_selection:"+START,"final_daily_selection:"+END])
    bets=query("""SELECT race_id AS raceId,course,bet_type AS betType,combination,
         stake_yen AS stakeYen,return_yen AS returnYen,assumed_odds AS assumedOdds,
         settlement_status AS settlementStatus,locked_at AS lockedAt
         FROM rt_public_bets WHERE race_id>=? AND race_id<?
         AND source_prediction_id=-2 AND course='ライト'
         ORDER BY race_id,id LIMIT 1500""",[START+"-",END+"-"])
    if len(states)>=150 or len(bets)>=1500:raise AssertionError("D1_ROW_TRUNCATED")
    races,coverage=parse(states,bets)
    report=full_report(races,coverage)
    print("LIVE_STAKE_WALKFORWARD_RESULTS",json.dumps(report,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":main()
