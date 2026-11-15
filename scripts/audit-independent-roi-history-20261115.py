#!/usr/bin/env python3
"""Read-only, exact-as-deployed cash ROI audit for immutable independent 6m/96m predictions.

Never substitute canonical tickets, post-result odds or guessed prices.
Reports null ROI unless the independent model's OWN pre-T15 finalized tickets
and genuine results are recorded. Evaluates full available historical range.
"""
import collections
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"analysis-results"/"independent-roi-actual-coverage-20261115.json"
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
def query(sql,params=None):
    req=urllib.request.Request(URL,data=json.dumps({"sql":sql,"params":params or []}).encode(),
      headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=75) as response:
        data=json.loads(response.read().decode())
    if not data.get("success"):
        raise RuntimeError("D1_READ_FAILED:"+str(data.get("errors"))[:400])
    return ((data.get("result") or [{}])[0].get("results") or [])
def one(sql,params=None):
    rows=query(sql,params)
    return rows[0] if rows else {}
def parse_dt(s):
    try:return dt.datetime.fromisoformat(str(s).replace("Z","+00:00"))
    except Exception:return None
def parse_valid(f,mode):
    try:
        if f.get("mode")!=mode or f.get("sourceModel")!="rolling-independent-cash-v1":return None
        date=f["date"]
        if date<"2016-08-10" or date>"2026-11-15":return None
        start,odds,lock=map(parse_dt,(f.get("startTimeUtc"),f.get("oddsFetchedAt"),f.get("lockedAt")))
        if not start or not odds or not lock or odds>lock or lock>start-dt.timedelta(minutes=15):return None
        bets=f["courseBets"]
        light=[b for b in bets if b.get("course")=="ライト"]
        if len(light)!=2 or len({b.get("betType") for b in light})!=2:return None
        if any(b.get("betType") not in TYPES or not b.get("combination") or int(b.get("stakeYen",0))<=0 for b in light):return None
        return {"raceId":f["raceId"],"date":date,"light":light}
    except Exception:return None
def main():
    tables=query("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    odds_tables=[]
    for table in tables:
        name=table["name"]
        if any(word in name.lower() for word in ("odds","market","ticket","bets")):
            cols=query('PRAGMA table_info("'+name.replace('"','""')+'")')
            odds_tables.append({"name":name,"columns":[x["name"] for x in cols],
               "rows":one('SELECT COUNT(*) n FROM "'+name.replace('"','""')+'"').get("n")})
    race_counts=query("SELECT substr(race_date,1,4) AS year,COUNT(*) AS races FROM rt_races WHERE status='finished' AND race_date>='2016-08-10' GROUP BY 1 ORDER BY 1")
    prestart_odds=query("SELECT substr(r.race_date,1,4) AS year, COUNT(*) AS quotes, COUNT(DISTINCT s.race_id) AS races, COUNT(DISTINCT s.bet_type) AS betTypes FROM rt_official_odds_snapshots s JOIN rt_races r ON r.race_id=s.race_id WHERE s.seconds_to_start>=900 GROUP BY 1 ORDER BY 1")
    odds_span=one("SELECT MIN(captured_at_utc) AS minCaptured,MAX(captured_at_utc) AS maxCaptured,COUNT(DISTINCT race_id) AS races,COUNT(*) AS totalRows FROM rt_official_odds_snapshots")
    full_six_markets=one("SELECT COUNT(*) AS races FROM (SELECT race_id FROM rt_official_odds_snapshots WHERE seconds_to_start>=900 GROUP BY race_id HAVING COUNT(DISTINCT bet_type)=6)")
    counts={}
    results={}
    for mode in ("cash6","cash96"):
        prefix="independent_final:"+mode+":"
        states=query("SELECT state_value AS value FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 8000",[prefix,prefix+"~"])
        records=[]
        for s in states:
            try:
                f=json.loads(s["value"])
                d=parse_valid(f,mode)
                if d:records.append(d)
            except Exception:continue
        dates=set(r["date"] for r in records)
        totals={"targetStates":len(states),"validFrozenRaces":len(records),"finishedRaces":0,
           "settledRaces":0,"stakeYen":0,"returnYen":0,"hitRaces":0,
           "roiPct":None,"hitRatePct":None,"roiWithoutLargestTicketPct":None,"roiWithoutLargestRacePct":None}
        yearly=collections.defaultdict(lambda:{"races":0,"stakeYen":0,"returnYen":0,"hitRaces":0})
        ticket_paid=[]
        race_paid=[]
        for record in records:
            race=one("SELECT status FROM rt_races WHERE race_id=? LIMIT 1",[record["raceId"]])
            if race.get("status")!="finished":continue
            totals["finishedRaces"]+=1
            payouts=query("SELECT bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?",[record["raceId"]])
            if not payouts:continue
            by_pair={(p["betType"],p["combination"]):int(p["payoutYen"]) for p in payouts}
            paid_by_ticket=[int(round(int(b["stakeYen"])*by_pair.get((b["betType"],b["combination"]),0)/100)) for b in record["light"]]
            stake=sum(int(b["stakeYen"]) for b in record["light"])
            paid=sum(paid_by_ticket)
            if stake!=2000:raise AssertionError("BAD_INDEPENDENT_LIGHT_BUDGET:"+record["raceId"])
            totals["settledRaces"]+=1
            totals["stakeYen"]+=stake
            totals["returnYen"]+=paid
            totals["hitRaces"]+=int(paid>0)
            ticket_paid.extend(paid_by_ticket)
            race_paid.append(paid)
            row=yearly[record["date"][:4]]
            row["races"]+=1
            row["stakeYen"]+=stake
            row["returnYen"]+=paid
            row["hitRaces"]+=int(paid>0)
        if totals["stakeYen"]:
            totals["roiPct"]=round(100*totals["returnYen"]/totals["stakeYen"],4)
            totals["hitRatePct"]=round(100*totals["hitRaces"]/totals["settledRaces"],4)
            totals["roiWithoutLargestTicketPct"]=round(100*(totals["returnYen"]-max(ticket_paid,default=0))/totals["stakeYen"],4)
            totals["roiWithoutLargestRacePct"]=round(100*(totals["returnYen"]-max(race_paid,default=0))/totals["stakeYen"],4)
        results[mode]={"total":totals,"years":{
          k:{**v,"roiPct":round(100*v["returnYen"]/v["stakeYen"],4) if v["stakeYen"] else None,
              "hitRatePct":round(100*v["hitRaces"]/v["races"],4) if v["races"] else None}
          for k,v in sorted(yearly.items())},
          "datesWithIndependentFinals":len(dates)}
    result={"audit":"independent-cash6-cash96-exact-frozen-bets-readonly",
      "asOf":"2026-11-15","noCanonicalFallback":True,"noHypotheticalOdds":True,
      "historicalRacesByYear":race_counts,
      "preStartOfficialOddsByYear":prestart_odds,
      "officialOddsArchiveSpan":odds_span,
      "racesWithAllSixPreStartMarketTypes":full_six_markets.get("races",0),
      "oddsRelatedTables":odds_tables,
      "models":results,
      "validatedAllHistoricalYears":all(
         set(str(y) for y in range(2017,2027)).issubset(set(results[m]["years"]))
         for m in ("cash6","cash96"))}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("INDEPENDENT_CASH_MODELS_ACTUAL_SETTLEMENT_AUDIT")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["validatedAllHistoricalYears"]:
        print("FULL_2017_2026_BACKTEST_NOT_VALIDATED: required pre-T15 model-specific archived odds/runner predictions missing")
if __name__=="__main__":main()
