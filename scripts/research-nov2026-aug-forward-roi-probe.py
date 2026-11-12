#!/usr/bin/env python3
"""Read-only August-November 2026 production-historical coverage and schema audit.
Explicit date bounds. No mutations, no token logging.
"""
from __future__ import annotations
import collections,json,os,urllib.request
A=os.environ["CLOUDFLARE_ACCOUNT_ID"]
DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{DB}/query"
def query(sql,params=()):
    body=json.dumps(dict(sql=sql,params=list(params)),ensure_ascii=False).encode()
    req=urllib.request.Request(URL,data=body,method="POST",headers={
        "Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],
        "Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=50) as f:res=json.load(f)
    if not res.get("success"):raise RuntimeError(f"D1_QUERY_ERROR:{res.get('errors')}")
    return (res.get("result") or [{}])[0].get("results") or []
def main():
    schemas={}
    for table in ("rt_public_bets","rt_races","rt_system_state"):
        fields=query(f"PRAGMA table_info({table})")
        schemas[table]=[r["name"] for r in fields]
    print("FORWARD_D1_SCHEMA",json.dumps(schemas,ensure_ascii=False),flush=True)
    counts=query("""SELECT substr(race_id,1,7) AS month,
       course,source_prediction_id AS source,
       settlement_status AS status,COUNT(*) AS cnt,
       SUM(COALESCE(stake_yen,0)) AS stakes,
       SUM(CASE WHEN settlement_status='settled'
          THEN COALESCE(return_yen,0) ELSE 0 END) AS paid
       FROM rt_public_bets
       WHERE race_id>=? AND race_id<?
       GROUP BY month,course,source,status
       ORDER BY month,course,source,status LIMIT 250""",
       ["2026-08-01-","2026-11-13-"])
    print("FORWARD_D1_MONTHLY_COUNTS",json.dumps(counts,ensure_ascii=False),flush=True)
    selections=query("""SELECT state_key AS k,state_value AS v
       FROM rt_system_state WHERE state_key>=? AND state_key<?
       ORDER BY state_key LIMIT 140""",
       ["final_daily_selection:2026-08-01","final_daily_selection:2026-11-13"])
    summaries=[]
    for x in selections:
        try:doc=json.loads(x["v"])
        except (ValueError,TypeError):continue
        ss=doc.get("selected") or []
        summaries.append({"date":x["k"].split(":")[-1],
          "selected":len(ss),"source":doc.get("sourceModel"),
          "scorePresent":sum(isinstance(a.get("raceScore"),(int,float)) for a in ss),
          "venues":len(set(str(a.get("venue")) for a in ss))})
    print("FORWARD_D1_SELECTION_COVERAGE",json.dumps(summaries,ensure_ascii=False),flush=True)
    status=query("""SELECT substr(race_id,1,7) AS month,status,COUNT(*) cnt
       FROM rt_races WHERE race_id>=? AND race_id<?
       GROUP BY month,status ORDER BY month,status LIMIT 60""",
       ["2026-08-01-","2026-11-13-"])
    print("FORWARD_D1_RACE_STATUSES",json.dumps(status,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
