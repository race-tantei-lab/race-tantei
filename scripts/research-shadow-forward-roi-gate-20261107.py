#!/usr/bin/env python3
"""Strict forward-only, read-only ROI gate for precommitted shadow selections.

No model/website/production bet writes. Pre-race official odds and combinations
were fixed at T-15 by production Worker; all settlements are stored JRA payouts.
Refuses incomplete snapshots, missing payout tables, and mismatched actual wins.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import os
import random
import urllib.request

JST=dt.timezone(dt.timedelta(hours=9))
START=dt.date(2026,11,8)
POLICIES=("market_implied_only","market_blend_30pct_model")
UNORDERED={"ワイド","馬連","3連複"}

def canonical(typ, combo):
    txt=str(combo).replace("→","-").replace("－","-").replace("–","-")
    parts=txt.split("-")
    if not parts or not all(p.strip().isdigit() for p in parts):
        raise ValueError("NONNUMERIC_COMBINATION:"+txt)
    nos=[int(p) for p in parts]
    expected=1 if typ=="単勝" else 2 if typ in ("ワイド","馬連","馬単") else 3
    if len(nos)!=expected or len(set(nos))!=expected:
        raise ValueError("WRONG_COMBINATION_SHAPE:"+str((typ,txt)))
    if typ in UNORDERED:
        nos.sort()
    return "-".join(map(str,nos))

def cutoff(date,start_jst):
    return dt.datetime.fromisoformat(date+"T"+str(start_jst)[:5]+":00+09:00")-dt.timedelta(minutes=15)

def before_cutoff(stamp,close):
    if not stamp:
        return False
    try:
        parsed=dt.datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
        return parsed.tzinfo is not None and parsed<=close
    except (ValueError,TypeError):
        return False

def query(sql,params):
    a=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    d=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    t=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{a}/d1/database/{d}/query"
    req=urllib.request.Request(url,method="POST",
        data=json.dumps({"sql":sql,"params":params}).encode(),
        headers={"Authorization":"Bearer "+t,"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=60) as resp:
        result=json.loads(resp.read())
    if not result.get("success"):
        raise RuntimeError("D1_READ_ONLY_QUERY_FAILED:"+str(result.get("errors"))[:350])
    return (result.get("result") or [{}])[0].get("results") or []

def paired_ci(days,policy,seed=20261107,reps=5000):
    if len(days)<4:
        return {"days":len(days),"ci95PctPoints":None}
    pairs=[]
    for day,x in sorted(days.items()):
        p=x.get(policy);b=x.get("canonical")
        if not p or not b or not p["stakeYen"] or p["stakeYen"]!=b["stakeYen"]:
            raise AssertionError("UNPAIRED_COHORT:"+day)
        pairs.append((p["returnYen"]-b["returnYen"],p["stakeYen"]))
    rng=random.Random(seed)
    sims=[]
    for _ in range(reps):
        sample=[pairs[rng.randrange(len(pairs))] for _ in pairs]
        sims.append(sum(a for a,_ in sample)*100/sum(b for _,b in sample))
    sims.sort()
    return {"days":len(days),"differencePctPoints":round(100*sum(a for a,_ in pairs)/sum(b for _,b in pairs),2),
        "ci95PctPoints":[round(sims[int(reps*0.025)],2),round(sims[int(reps*0.975)-1],2)]}

def evaluate(sel_rows,final_rows,bet_rows,pay_rows,race_rows):
    selected={}
    for item in sel_rows:
        date=str(item["k"]).removeprefix("final_daily_selection:")
        p=json.loads(item["v"] or "{}")
        if p.get("sourceModel")!="ten-year-completed-model":
            raise AssertionError("SELECTION_MODEL_MISMATCH:"+date)
        for r in p.get("selected") or []:
            rid=str(r.get("raceId") or "")
            if not rid.startswith(date+"-") or rid in selected:
                raise AssertionError("DUPLICATE_OR_WRONG_DATE_SELECTION:"+rid)
            selected[rid]=(date,str(r.get("startTimeJst") or ""))
    finals={str(x["k"]).removeprefix("worker_live_final:"):json.loads(x["v"]) for x in final_rows}
    bets=collections.defaultdict(list)
    for b in bet_rows:
        bets[str(b["raceId"])].append(b)
    payouts={}
    paid_races=set()
    for p in pay_rows:
        rid=str(p["raceId"]);paid_races.add(rid)
        key=(rid,str(p["betType"]),canonical(str(p["betType"]),p["combination"]))
        value=int(p.get("payout100") or 0)
        if key in payouts and payouts[key]!=value:
            raise AssertionError("CONFLICTING_JRA_PAYOUTS:"+str(key))
        payouts[key]=value
    race_status={str(r["raceId"]):str(r.get("status") or "") for r in race_rows}
    refunded={str(r["raceId"]):{int(x) for x in json.loads(r.get("refunds") or "[]")} for r in race_rows}
    totals=collections.defaultdict(lambda:{"races":0,"stakeYen":0,"returnYen":0,"hitRaces":0,"largestSingleRaceReturnYen":0})
    days=collections.defaultdict(lambda:collections.defaultdict(lambda:{"races":0,"stakeYen":0,"returnYen":0}))
    excluded=collections.Counter()
    included_ids=[]
    for rid,(day,start) in sorted(selected.items()):
        snap=finals.get(rid)
        actual=bets.get(rid,[])
        if snap is None:
            excluded["missing_final_snapshot"]+=1;continue
        if len(actual)!=2 or len({b["betType"] for b in actual})!=2 or any(b["settlement"]!="settled" for b in actual):
            excluded["missing_or_unsettled_actual_bets"]+=1;continue
        try: limit=cutoff(day,start)
        except (TypeError,ValueError):
            excluded["start_time_invalid"]+=1;continue
        if not (before_cutoff(snap.get("lockedAt"),limit)
                and before_cutoff(snap.get("oddsFetchedAt"),limit)
                and before_cutoff(snap.get("previewGeneratedAt"),limit)
                and all(before_cutoff(x.get("lockedAt"),limit) for x in actual)):
            excluded["not_proven_pre_T15"]+=1;continue
        if snap.get("oddsSource") not in ("jra-fast-official","jra-crawl-official") or not snap.get("oddsSnapshotSha256"):
            excluded["official_odds_provenance_missing"]+=1;continue
        if rid not in paid_races or race_status.get(rid)!="finished":
            excluded["race_not_final_or_JRA_payouts_missing"]+=1;continue
        if any(int(x["stakeYen"] or 0)!=1000 or x["returnYen"] is None or int(x["returnYen"])<0 for x in actual):
            excluded["invalid_actual_stake_or_return"]+=1;continue
        shadow=snap.get("shadowResearch")
        if not isinstance(shadow,list) or len(shadow)!=len(POLICIES) or set(x.get("policy") for x in shadow)!=set(POLICIES):
            excluded["shadow_missing_or_noncanonical"]+=1;continue
        if any(len(x.get("tickets") or [])!=2 or
               len({z.get("betType") for z in x.get("tickets") or []})!=2
               for x in shadow):
            excluded["shadow_ticket_types_invalid"]+=1;continue
        def payout_of(ticket,stake=1000):
            typ=ticket["betType"]
            comb=canonical(typ,ticket["combination"])
            if set(map(int,comb.split("-"))) & refunded.get(rid,set()):
                return stake
            return stake*int(payouts.get((rid,typ,comb),0))//100
        computed=sum(payout_of(b,int(b["stakeYen"])) for b in actual)
        recorded=sum(int(b["returnYen"]) for b in actual)
        if computed!=recorded:
            raise AssertionError("REAL_BET_VS_JRA_PAYOUT_MISMATCH:"+rid+":"+str((computed,recorded)))
        results={"canonical":recorded}
        for p in shadow:
            for ticket in p["tickets"]:
                if not (float(ticket.get("officialOdds") or 0)>=1 and
                        0<float(ticket.get("blendedProbability") or 0)<=1):
                    raise AssertionError("INVALID_SHADOW_ODDS_OR_PROBABILITY:"+rid)
            results[p["policy"]]=sum(payout_of(z) for z in p["tickets"])
        included_ids.append(rid)
        for key,ret in results.items():
            total=totals[key];total["races"]+=1;total["stakeYen"]+=2000;total["returnYen"]+=ret
            total["hitRaces"]+=int(ret>0)
            total["largestSingleRaceReturnYen"]=max(total["largestSingleRaceReturnYen"],ret)
            d=days[day][key];d["races"]+=1;d["stakeYen"]+=2000;d["returnYen"]+=ret
    def fmt(a):
        return {**a,"roiPct":round(100*a["returnYen"]/a["stakeYen"],2) if a["stakeYen"] else None,
                "roiWithoutLargestRacePct":round(100*(a["returnYen"]-a.get("largestSingleRaceReturnYen",0))/a["stakeYen"],2) if a["stakeYen"] else None}
    results={k:fmt(x) for k,x in totals.items()}
    dates={d:{k:fmt(v) for k,v in group.items()} for d,group in sorted(days.items())}
    # Predeclared: both policies remain disqualified until independent data and
    # profitability / paired superiority gates pass, without peeking at labels.
    gate={}
    for policy in POLICIES:
        paired=paired_ci(days,policy) if days else {"days":0,"ci95PctPoints":None}
        value=results.get(policy,{"races":0,"roiPct":None,"roiWithoutLargestRacePct":None})
        enough=len(days)>=10 and value["races"]>=150
        ci=paired.get("ci95PctPoints")
        passed=bool(enough and value.get("roiPct") is not None and value["roiPct"]>100
            and value["roiWithoutLargestRacePct"]>100 and ci and ci[0]>0
            and not excluded)
        gate[policy]={"days":len(days),"minimumRequiredDays":10,"races":value["races"],
            "minimumRequiredRaces":150,"pairedRoiBootstrap":paired,
            "qualifiedForReview":passed,"reason":("PASS_RESEARCH_ONLY_NO_AUTO_PROMOTION" if passed
            else "INCOMPLETE_DATA" if excluded else "INSUFFICIENT_SAMPLE" if not enough
            else "NOT_PROVEN_POSITIVE_ROI")}
    return {"status":"FORWARD_ONLY_SHADOW_RESEARCH_NO_PRODUCTION_CHANGE",
        "eligibleRaces":len(included_ids),"selectedRaces":len(selected),"skipped":dict(excluded),
        "results":results,"daily":dates,"eligibility":gate,
        "notActualShadowWagers":True,"officialPayoutSource":"D1 official JRA data; no independent JRA cross-check",
        "effect":"no public ticket/model/site or DB change"}

def self_test():
    day="2026-11-08";rid=day+"-tokyo-01"
    sel=[{"k":"final_daily_selection:"+day,"v":json.dumps({"sourceModel":"ten-year-completed-model","selected":[{"raceId":rid,"startTimeJst":"11:00"}]})}]
    meta={"lockedAt":"2026-11-08T01:10:00Z","oddsFetchedAt":"2026-11-08T01:09:00Z",
          "previewGeneratedAt":"2026-11-08T01:09:30Z","oddsSource":"jra-fast-official",
          "oddsSnapshotSha256":"0"*64,
          "shadowResearch":[
             {"policy":"market_implied_only","tickets":[{"betType":"単勝","combination":"3","officialOdds":3.5,"blendedProbability":0.2857},
                {"betType":"ワイド","combination":"3-1","officialOdds":2.6,"blendedProbability":0.3846}]},
             {"policy":"market_blend_30pct_model","tickets":[{"betType":"単勝","combination":"1","officialOdds":3.0,"blendedProbability":0.33},
                {"betType":"ワイド","combination":"1-3","officialOdds":2.6,"blendedProbability":0.37}]}
          ]}
    fin=[{"k":"worker_live_final:"+rid,"v":json.dumps(meta)}]
    bets=[
     {"raceId":rid,"betType":"単勝","combination":"1","stakeYen":1000,"returnYen":0,"settlement":"settled","lockedAt":"2026-11-08T01:10:00Z"},
     {"raceId":rid,"betType":"ワイド","combination":"1-2","stakeYen":1000,"returnYen":0,"settlement":"settled","lockedAt":"2026-11-08T01:10:00Z"}]
    pays=[{"raceId":rid,"betType":"単勝","combination":"3","payout100":350},
          {"raceId":rid,"betType":"ワイド","combination":"1-3","payout100":260}]
    races=[{"raceId":rid,"status":"finished","refunds":"[]"}]
    x=evaluate(sel,fin,bets,pays,races)
    assert x["eligibleRaces"]==1 and x["results"]["canonical"]["roiPct"]==0
    assert x["results"]["market_implied_only"]["roiPct"]==305
    assert x["results"]["market_blend_30pct_model"]["roiPct"]==130
    assert x["eligibility"]["market_implied_only"]["qualifiedForReview"] is False
    # Changing the official odds timestamp to T-14 must invalidate the sample.
    altered=json.loads(json.dumps(meta));altered["oddsFetchedAt"]="2026-11-08T01:46:00Z"
    failed=evaluate(sel,[{"k":fin[0]["k"],"v":json.dumps(altered)}],bets,pays,races)
    assert failed["eligibleRaces"]==0 and failed["skipped"]["not_proven_pre_T15"]==1
    # Positive actual return disagreeing with official JRA payouts is fatal.
    bad=json.loads(json.dumps(bets));bad[0]["returnYen"]=500
    try:
        evaluate(sel,fin,bad,pays,races)
        raise AssertionError("EXPECTED_PAYOUT_MISMATCH_NOT_DETECTED")
    except AssertionError as e:
        assert "REAL_BET_VS_JRA_PAYOUT_MISMATCH" in str(e)
    print("FORWARD_SHADOW_RESEARCH_SELFTEST_OK")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--through-date",default=None,help="Inclusive JST day only if races and settlement are complete")
    args=ap.parse_args()
    if args.self_test:
        self_test();return
    today=dt.datetime.now(JST).date()
    through=dt.date.fromisoformat(args.through_date) if args.through_date else today-dt.timedelta(days=1)
    if through>today:raise AssertionError("CANNOT_INCLUDE_FUTURE_RACE_DAY")
    if through<START:
        print("SHADOW_VALIDATION_NOT_YET_DUE",str(through));return
    exclusive=through+dt.timedelta(days=1)
    start=str(START);end=str(exclusive)
    query_defs=(
      ("selections","SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 160",
       ["final_daily_selection:"+start,"final_daily_selection:"+end],160),
      ("finals","SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 600",
       ["worker_live_final:"+start,"worker_live_final:"+end],600),
      ("bets","SELECT race_id AS raceId,bet_type AS betType,combination,stake_yen AS stakeYen,return_yen AS returnYen,settlement_status AS settlement,locked_at AS lockedAt FROM rt_public_bets WHERE race_id>=? AND race_id<? AND course='ライト' AND source_prediction_id=-2 ORDER BY race_id,id LIMIT 1000",
       [start+"-",end+"-"],1000),
      ("payouts","SELECT race_id AS raceId,bet_type AS betType,combination,payout_yen AS payout100 FROM rt_payouts WHERE race_id>=? AND race_id<? AND bet_type IN ('単勝','ワイド','馬連','馬単','3連複','3連単') ORDER BY race_id LIMIT 10000",
       [start+"-",end+"-"],10000),
      ("races","SELECT race_id AS raceId, status,refund_horse_nos_json AS refunds FROM rt_races WHERE race_id>=? AND race_id<? ORDER BY race_id LIMIT 600",
       [start+"-",end+"-"],600),
    )
    fetched={}
    for name,sql,params,limit in query_defs:
        x=query(sql,params)
        if len(x)>=limit:raise AssertionError("D1_ROW_TRUNCATION:"+name)
        fetched[name]=x
    if not fetched["selections"]:
        raise AssertionError("NO_FROZEN_RACE_SELECTIONS")
    result=evaluate(fetched["selections"],fetched["finals"],fetched["bets"],fetched["payouts"],fetched["races"])
    result["throughDateJst"]=str(through)
    print("FORWARD_SHADOW_VALIDATION",json.dumps(result,ensure_ascii=False,separators=(",",":")))
    if not result["eligibleRaces"]:
        raise AssertionError("NO_MATCHED_PRE_T15_SETTLED_SHADOW_PORTFOLIOS")

if __name__=="__main__":
    main()
