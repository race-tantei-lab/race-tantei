#!/usr/bin/env python3
"""Audit only: saved official JRA before-T15 quotes vs payout labels. No writes."""
import json,os,urllib.request
from pathlib import Path
def q(sql,params):
  if not sql.lstrip().upper().startswith("SELECT "):raise RuntimeError("READ_ONLY")
  endpoint=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
  req=urllib.request.Request(endpoint,data=json.dumps({"sql":sql,"params":params}).encode(),method="POST",headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"})
  with urllib.request.urlopen(req,timeout=55) as r:z=json.loads(r.read())
  if not z.get("success"):raise RuntimeError(str(z.get("errors"))[:400])
  return (z.get("result") or [{}])[0].get("results") or []
def main():
  if "--self-test" in os.sys.argv:
    try:q("DELETE FROM rt_public_bets",[])
    except RuntimeError:pass
    else:raise RuntimeError("READ_ONLY_CHECK_FAIL")
    print("TRUE_T15_ONLY_QUERY_SELFTEST_OK");return
  lo,hi="2026-08-15-","2026-11-09-"
  sqls={
    "quotes": """SELECT substr(race_id,1,7) month,bet_type market, count(*) quoteRows,
              count(DISTINCT race_id) raceCount FROM rt_official_odds_snapshots
              WHERE race_id>=? AND race_id<? AND seconds_to_start>=900 AND odds_source='jra_official'
              GROUP BY substr(race_id,1,7),bet_type ORDER BY month,market""",
    "payouts": """SELECT substr(race_id,1,7) month,bet_type market, count(*) paidCombinationRows,
              count(DISTINCT race_id) raceCount FROM rt_payouts
              WHERE race_id>=? AND race_id<? GROUP BY substr(race_id,1,7),bet_type ORDER BY month,market""",
    "valueCandidates": """SELECT substr(race_id,1,7) month,bet_type market,count(*) ticketRows,
              count(DISTINCT race_id) raceCount FROM rt_official_value_candidates
              WHERE race_id>=? AND race_id<? GROUP BY substr(race_id,1,7),bet_type ORDER BY month,market""",
    "races":"""SELECT substr(race_id,1,7) month,count(*) finishedRaces,
              count(DISTINCT race_date||':'||venue) venueDays FROM rt_races
              WHERE race_id>=? AND race_id<? AND status='finished'
              GROUP BY substr(race_id,1,7) ORDER BY month"""
  }
  report={"source":"production D1 fixed official JRA T15 quote and payout labels",
          "noWrites":True,"researchOnly":True,"dateStart":lo,"dateEndExclusive":hi,
          "byMonth":{k:q(sql,[lo,hi]) for k,sql in sqls.items()}}
  out=Path("analysis-results/nov2026-real-t15-money-coverage.json")
  out.parent.mkdir(exist_ok=True,parents=True)
  out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
  print("REAL_T15_MONEY_COVERAGE",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
