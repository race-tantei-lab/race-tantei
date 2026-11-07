#!/usr/bin/env python3
"""Read-only after-the-fact audit of pre-race shadow candidate portfolios.

Never writes to D1 and never rewrites a historical prediction. Compares ONLY
the original selected race's settled two real bets with both shadow two-bet
policies captured on that same race's pre-T-15 official odds snapshot.
All shadow payouts use the actual stored official settlement table.
"""
from __future__ import annotations
import collections
import datetime as dt
import json
import os
import sys
import urllib.request

JST=dt.timezone(dt.timedelta(hours=9))
START="2026-11-08"
COURSE="ライト"

def query(sql, params):
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    db=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
    req=urllib.request.Request(url, data=json.dumps({"sql":sql,"params":params}).encode(),method="POST",
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=55) as f: data=json.loads(f.read())
    if not data.get("success"):raise RuntimeError("D1_READ_FAILED "+str(data.get("errors"))[:300])
    return (data.get("result") or [{}])[0].get("results") or []

def deadline_ok(locked, date, start_jst):
    try:
        at=dt.datetime.fromisoformat(str(locked).replace("Z","+00:00"))
        start=dt.datetime.fromisoformat(date+"T"+str(start_jst)[:5]+":00+09:00")
        return at<=start-dt.timedelta(minutes=15)
    except (ValueError,TypeError):
        return False

def evaluate(selection_rows,final_rows,bet_rows,payout_rows,race_rows):
    selections={}
    for r in selection_rows:
        date=r["k"].removeprefix("final_daily_selection:")
        if not date.startswith("2026-"):continue
        p=json.loads(r["v"])
        for race in p.get("selected") or []:
            selections[race["raceId"]]=(date,race.get("startTimeJst"))
    final={r["k"].removeprefix("worker_live_final:"):json.loads(r["v"]) for r in final_rows}
    bets=collections.defaultdict(list)
    for b in bet_rows:bets[b["raceId"]].append(b)
    payouts={}
    for p in payout_rows:
        key=(p["raceId"],p["betType"],p["combination"])
        v=int(p["payout100"] or 0)
        if key in payouts and payouts[key]!=v:
            raise AssertionError("CONFLICTING_STORED_JRA_PAYOUT "+str(key))
        payouts[key]=v
    refunds={r["raceId"]:{int(x) for x in json.loads(r.get("refunds") or "[]")} for r in race_rows}
    # Same race, same stake, same pre-T15 selection for paired metrics.
    # Do NOT compare standalone hit rate or standalone ROI on different cohorts.
    def empty():
        return {"races":0,"stakeYen":0,"returnYen":0,"paidTickets":0,
                "hitRaces":0,"bothTicketsHitRaces":0,"profitableRaces":0,
                "largestRaceReturnYen":0}
    totals=collections.defaultdict(empty)
    dates=collections.defaultdict(lambda:collections.defaultdict(empty))
    all_groups=collections.defaultdict(lambda:collections.defaultdict(list))
    paired_race_ids=[]
    excluded=collections.Counter()
    for rid,(date,start_jst) in sorted(selections.items()):
        snap=final.get(rid)
        actual=bets.get(rid,[])
        if snap is None or len(actual)!=2 or any(x["settlement"]!="settled" for x in actual):
            excluded["no_final_or_two_settled_actual_bets"]+=1
            continue
        if len({x.get("betType") for x in actual})!=2:
            excluded["canonical_bet_types_not_distinct"]+=1
            continue
        if any(int(x.get("stakeYen") or 0)!=1000 or x.get("returnYen") is None
               or int(x["returnYen"])<0 for x in actual):
            excluded["canonical_stake_or_payout_invalid"]+=1
            continue
        if not deadline_ok(snap.get("lockedAt"),date,start_jst):
            excluded["final_not_proven_T15"]+=1
            continue
        if not all(deadline_ok(x.get("lockedAt"),date,start_jst) for x in actual):
            excluded["public_bets_not_T15"]+=1
            continue
        shadow=snap.get("shadowResearch") or []
        if not isinstance(shadow,list) or len(shadow)!=2:
            excluded["shadow_not_captured"]+=1
            continue
        if (not all(isinstance(p,dict) and len(p.get("tickets") or [])==2
                    and len({x.get("betType") for x in p["tickets"]})==2
                    and all(t.get("betType") in ("単勝","ワイド","馬連","馬単","3連複","3連単")
                            for t in p["tickets"]) for p in shadow)
                or {p.get("policy") for p in shadow} !=
                   {"market_implied_only","market_blend_30pct_model"}):
            excluded["shadow_invalid"]+=1
            continue
        # A payout without the official frozen market timestamp is not a
        # comparable proof of a T-15 counterfactual bet.
        if not all(deadline_ok(snap.get(k),date,start_jst)
                   for k in ("previewGeneratedAt","oddsFetchedAt")):
            excluded["shadow_official_odds_or_preview_not_proven_T15"]+=1
            continue
        if snap.get("oddsSource") not in ("jra-fast-official","jra-crawl-official"):
            excluded["shadow_not_from_official_JRA"]+=1
            continue
        paired_race_ids.append(rid)
        def accrue(name, ticket_returns):
            if len(ticket_returns)!=2 or any(v<0 for v in ticket_returns):
                raise AssertionError("PAIR_MUST_CONTAIN_TWO_SETTLED_TICKETS")
            returned=sum(ticket_returns)
            for target in (totals[name],dates[date][name]):
                target["races"]+=1
                target["stakeYen"]+=2000
                target["returnYen"]+=returned
                target["paidTickets"]+=sum(v>0 for v in ticket_returns)
                target["hitRaces"]+=int(any(v>0 for v in ticket_returns))
                target["bothTicketsHitRaces"]+=int(all(v>0 for v in ticket_returns))
                target["profitableRaces"]+=int(returned>2000)
                target["largestRaceReturnYen"]=max(target["largestRaceReturnYen"],returned)
            all_groups[name][date].append(int(any(v>0 for v in ticket_returns)))
        accrue("canonical",[int(x["returnYen"]) for x in actual])
        for policy in shadow:
            name=policy["policy"]
            ticket_returns=[]
            for ticket in policy["tickets"]:
                horses={int(x) for x in str(ticket["combination"]).split("-")}
                if horses & refunds.get(rid,set()):payout100=100
                else:payout100=payouts.get((rid,ticket["betType"],ticket["combination"]),0)
                ticket_returns.append(1000*int(payout100)//100)
            accrue(name,ticket_returns)
    def finish(x):
        stake=x["stakeYen"]
        n=x["races"]
        return {**x,
            "profitYen":x["returnYen"]-stake,
            "roiPct":round(100*x["returnYen"]/stake,2) if stake else None,
            "roiMinusLargestRaceReturnPct":round(100*(x["returnYen"]-x["largestRaceReturnYen"])/stake,2) if stake else None,
            "hitRacePct":round(100*x["hitRaces"]/n,2) if n else None,
            "hitTicketPct":round(100*x["paidTickets"]/(2*n),2) if n else None,
            "profitableRacePct":round(100*x["profitableRaces"]/n,2) if n else None}
    return {"basis":"strict-same-race-pre-T15-official-odds-shadow-vs-actual-no-missing-backfill",
        "total":{key:finish(val) for key,val in sorted(totals.items())},
        "byDate":{date:{key:finish(v) for key,v in sorted(choices.items())} for date,choices in sorted(dates.items())},
        "excluded":dict(excluded),
        "pairedRaceCount":len(paired_race_ids),
        "sameRaceCohortForHitAndRoi":True,
        "allRacesHitOnEachDate":{name:{
            date:int(all(hits)) for date,hits in sorted(group.items())}
            for name,group in sorted(all_groups.items())},
        "outcomesProvenOnlyForCompletePairedCohort":len(excluded)==0,
        "shadowOnlyNotActualBets":True,
        "payoutSource":"persisted JRA D1 payout table, not externally JRA-reverified"}

def self_test():
    d="2026-11-08";rid=d+"-tokyo-01"
    selection=[{"k":"final_daily_selection:"+d,"v":json.dumps({"selected":[{"raceId":rid,"startTimeJst":"11:00"}]})}]
    final=[{"k":"worker_live_final:"+rid,"v":json.dumps({"lockedAt":"2026-11-08T01:00:00Z",
        "previewGeneratedAt":"2026-11-08T01:00:00Z",
        "oddsFetchedAt":"2026-11-08T00:58:00Z",
        "oddsSource":"jra-fast-official",
        "shadowResearch":[{"policy":"market_implied_only","tickets":[{"betType":"単勝","combination":"3"},{"betType":"ワイド","combination":"1-3"}]},
        {"policy":"market_blend_30pct_model","tickets":[{"betType":"単勝","combination":"1"},{"betType":"ワイド","combination":"1-3"}]}]})}]
    bets=[{"raceId":rid,"betType":"単勝","combination":"1","stakeYen":1000,"returnYen":0,"settlement":"settled","lockedAt":"2026-11-08T01:00:00Z"},
          {"raceId":rid,"betType":"ワイド","combination":"1-2","stakeYen":1000,"returnYen":0,"settlement":"settled","lockedAt":"2026-11-08T01:00:00Z"}]
    pays=[{"raceId":rid,"betType":"単勝","combination":"3","payout100":350},
          {"raceId":rid,"betType":"ワイド","combination":"1-3","payout100":260}]
    report=evaluate(selection,final,bets,pays,[{"raceId":rid,"refunds":"[]"}])
    assert report["total"]["canonical"]["roiPct"]==0
    assert report["total"]["canonical"]["hitRacePct"]==0
    assert report["total"]["canonical"]["hitTicketPct"]==0
    assert report["total"]["market_implied_only"]["roiPct"]==305
    assert report["total"]["market_implied_only"]["hitRacePct"]==100
    assert report["total"]["market_implied_only"]["hitTicketPct"]==100
    assert report["total"]["market_implied_only"]["bothTicketsHitRaces"]==1
    assert report["total"]["market_blend_30pct_model"]["roiPct"]==130
    assert report["total"]["market_blend_30pct_model"]["hitRacePct"]==100
    assert report["total"]["market_blend_30pct_model"]["hitTicketPct"]==50
    assert report["sameRaceCohortForHitAndRoi"] is True
    assert report["pairedRaceCount"]==1
    assert all(v["roiPct"] is not None and v["hitRacePct"] is not None
               for v in report["total"].values())
    print("SHADOW_PAIRED_HIT_AND_ROI_SELFTEST_OK")

def main():
    if "--self-test" in sys.argv:
        self_test();return
    now=dt.datetime.now(JST)
    end=(now.date()-dt.timedelta(days=1))+dt.timedelta(days=1)
    if str(end)<=START:
        print("SHADOW_LIVE_ROI_WAITING_FOR_FIRST_RACE");return
    bound=str(end)
    selections=query("SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 150",["final_daily_selection:"+START,"final_daily_selection:"+bound])
    finals=query("SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 350",["worker_live_final:"+START,"worker_live_final:"+bound])
    bets=query("""SELECT race_id AS raceId,bet_type AS betType,combination,stake_yen AS stakeYen,
      return_yen AS returnYen,settlement_status AS settlement,locked_at AS lockedAt
      FROM rt_public_bets WHERE race_id>=? AND race_id<? AND course=?
        AND source_prediction_id=-2 ORDER BY race_id,id LIMIT 1000""",[START+"-",bound+"-",COURSE])
    payouts=query("""SELECT race_id AS raceId,bet_type AS betType,combination,payout_yen AS payout100
      FROM rt_payouts WHERE race_id>=? AND race_id<? ORDER BY race_id LIMIT 2500""",[START+"-",bound+"-"])
    races=query("""SELECT race_id AS raceId,refund_horse_nos_json AS refunds
      FROM rt_races WHERE race_id>=? AND race_id<? ORDER BY race_id LIMIT 500""",[START+"-",bound+"-"])
    if any((len(data)>=limit for data,limit in ((selections,150),(finals,350),(bets,1000),(payouts,2500),(races,500)))):
        raise AssertionError("SHADOW_AUDIT_QUERY_ROW_LIMIT_REACHED")
    summary=evaluate(selections,finals,bets,payouts,races)
    print("T15_LIVE_SHADOW_ROI_COMPARISON",json.dumps(summary,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":
    main()
