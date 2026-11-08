#!/usr/bin/env python3
"""Read-only evaluation gate for payout-value model experiments.

Input is a locally saved, immutable JSON array of ticket-level historical predictions.
No D1 access. No historical final odds treated as T-15 odds. No production writes.
Each record: raceId,date,venue,policy,betType,combination,stakeYen,
returnYen,lockedBeforeT15 (true only with timestamp proof).
For historical offline research, lockedBeforeT15 must be false.
Compare only on exactly matched race IDs with two different bet types per policy.
"""
import argparse
import collections
import json
import math
import random

def summarize(rows):
    if not rows: raise ValueError("EMPTY_EVALUATION")
    races=collections.defaultdict(lambda:collections.defaultdict(list))
    for x in rows:
        for field in ("raceId","date","venue","policy","betType","combination","stakeYen","returnYen"):
            if field not in x:raise ValueError("MISSING_"+field)
        if not str(x["raceId"]).startswith(str(x["date"])):raise ValueError("DATE_RACE_MISMATCH")
        if not isinstance(x["stakeYen"],int) or x["stakeYen"]<=0 or x["stakeYen"]%100:
            raise ValueError("INVALID_STAKE")
        if not isinstance(x["returnYen"],int) or x["returnYen"]<0:
            raise ValueError("INVALID_RETURN")
        races[x["policy"]][x["raceId"]].append(x)
    policies=sorted(races)
    common=set.intersection(*(set(races[p]) for p in policies))
    if not common:raise ValueError("NO_COMMON_RACES")
    if any(set(races[p])!=common for p in policies):
        raise ValueError("COHORT_MISMATCH_DO_NOT_DROP_RACES")
    stakes={}
    data={}
    for p in policies:
        grouped=[]
        for rid in sorted(common):
            tickets=races[p][rid]
            if len(tickets)!=2 or len({t["betType"] for t in tickets})!=2:
                raise ValueError("NOT_TWO_DISTINCT_BET_TYPES:"+rid)
            if len({(t["betType"],t["combination"]) for t in tickets})!=2:
                raise ValueError("DUPLICATE_TICKET")
            if len({t["date"] for t in tickets})!=1 or len({t["venue"] for t in tickets})!=1:
                raise ValueError("INCONSISTENT_RACE_META")
            if any(t.get("lockedBeforeT15") is True and not t.get("oddsSnapshotTimestamp") for t in tickets):
                raise ValueError("UNPROVEN_T15_ODDS")
            stake=sum(t["stakeYen"] for t in tickets)
            ret=sum(t["returnYen"] for t in tickets)
            grouped.append((rid,tickets[0]["date"],tickets[0]["venue"],stake,ret))
        stakes[p]=[x[3] for x in grouped]
        data[p]=grouped
    if any(stakes[p]!=stakes[policies[0]] for p in policies[1:]):
        raise ValueError("STAKE_PER_RACE_MISMATCH")
    if any([(r[0],r[1],r[2]) for r in data[p]]!=[(r[0],r[1],r[2]) for r in data[policies[0]]] for p in policies[1:]):
        raise ValueError("DATE_OR_VENUE_MISMATCH")
    out={}
    for p,grouped in data.items():
        st=sum(r[3] for r in grouped);ret=sum(r[4] for r in grouped)
        hit=sum(r[4]>0 for r in grouped)
        largest=max(grouped,key=lambda r:r[4])
        months=collections.defaultdict(lambda:[0,0,0])
        venues=collections.defaultdict(lambda:[0,0,0])
        for rid,date,venue,s,v in grouped:
            for bucket in (months[date[:7]],venues[venue]):
                bucket[0]+=s;bucket[1]+=v;bucket[2]+=int(v>0)
        def groupsummary(g):
            return {k:{"stakeYen":v[0],"returnYen":v[1],
                        "profitYen":v[1]-v[0],"roiPct":round(100*v[1]/v[0],2),
                        "hitRaces":v[2]} for k,v in sorted(g.items())}
        robust=(ret-largest[4])/(st-largest[3]) if st>largest[3] else None
        out[p]={"races":len(grouped),"hitRaces":hit,"hitRatePct":round(100*hit/len(grouped),2),
          "stakeYen":st,"returnYen":ret,"profitYen":ret-st,"roiPct":round(100*ret/st,2),
          "largestRaceReturnYen":largest[4],
          "roiExcludingLargestRacePct":round(100*robust,2) if robust is not None else None,
          "minimum20PctHitRate":5*hit>=len(grouped),
          "positiveProfit":ret>st,"monthly":groupsummary(months),"venues":groupsummary(venues)}
    return {"cohortRaces":len(common),"policies":out,
            "historicalResultsAreNotForwardProof":True,
            "modelPromotionApproved":False}

def selftest():
    def record(policy,rid,typ,stake,ret):
        return {"policy":policy,"raceId":"2025-01-01-"+rid,"date":"2025-01-01",
                "venue":"東京","betType":typ,"combination":"1-2" if typ=="ワイド" else "1",
                "stakeYen":stake,"returnYen":ret,"lockedBeforeT15":False}
    rows=[]
    for i in range(10):
        for p in ("a","b"):
            rows.append(record(p,str(i),"単勝",1000,3000 if i<2 and p=="a" else 0))
            rows.append(record(p,str(i),"ワイド",1000,5000 if i==0 and p=="b" else 0))
    a=summarize(rows)
    assert a["policies"]["a"]["hitRatePct"]==20
    assert a["policies"]["a"]["roiPct"]==30
    assert a["policies"]["b"]["hitRatePct"]==10
    assert a["policies"]["b"]["minimum20PctHitRate"] is False
    assert a["policies"]["a"]["roiExcludingLargestRacePct"]==round(3000/18000*100,2)
    try:
        summarize(rows[:-1])
        raise AssertionError("COHORT_GATE_MISSED")
    except ValueError:pass
    print("PAYOUT_VALUE_PAIRED_EVALUATOR_SELFTEST_OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--input",help="Immutable JSON ticket-level evaluation file")
    args=parser.parse_args()
    if args.self_test:selftest();return
    if not args.input:parser.error("--input is required")
    with open(args.input,encoding="utf-8") as f: rows=json.load(f)
    print(json.dumps(summarize(rows),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
