#!/usr/bin/env python3
import json, os, urllib.request
from collections import defaultdict

ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]
DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"
START="2026-08-10"
END="2026-10-03"

def q(sql,params=None):
    body=json.dumps({"sql":sql,"params":params or []},ensure_ascii=False).encode()
    req=urllib.request.Request(URL,data=body,method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read().decode())
    if not out.get("success"): raise RuntimeError(out)
    z=out.get("result") or []
    return (z[0].get("results") or []) if z else []

states=q("SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key LIKE 'final_daily_selection:%' ORDER BY state_key")
selected=[]
dates=[]
for row in states:
    date=str(row["k"]).split(":")[-1]
    if not (START<=date<=END): continue
    try: p=json.loads(row["v"])
    except Exception: continue
    ids=[str(x.get("raceId") or "") for x in p.get("selected",[]) if x.get("raceId")]
    if not ids: continue
    dates.append((date,len(ids),p.get("sourceModel"),p.get("resultDataUsedForTargetDay")))
    selected.extend(ids)
selected=list(dict.fromkeys(selected))

coverage={}
for off in range(0,len(selected),40):
    ids=selected[off:off+40]; ph=",".join("?" for _ in ids)
    odds=q(f"""SELECT race_id AS raceId,
      COUNT(DISTINCT bet_type) AS betTypes,
      COUNT(DISTINCT captured_at_utc) AS snapshotTimes,
      MAX(CASE WHEN seconds_to_start>=900 THEN captured_at_utc END) AS latestPreT15,
      COUNT(CASE WHEN seconds_to_start>=900 THEN 1 END) AS preT15Rows
      FROM rt_official_odds_snapshots WHERE race_id IN ({ph}) GROUP BY race_id""",ids)
    res=q(f"""SELECT r.race_id AS raceId,
      COUNT(DISTINCT rr.horse_no) AS resultHorses,
      COUNT(DISTINCT p.bet_type||':'||p.combination) AS payouts
      FROM rt_races r
      LEFT JOIN rt_results rr ON rr.race_id=r.race_id AND rr.finish_position IS NOT NULL
      LEFT JOIN rt_payouts p ON p.race_id=r.race_id
      WHERE r.race_id IN ({ph}) GROUP BY r.race_id""",ids)
    for x in odds: coverage.setdefault(x["raceId"],{}).update(x)
    for x in res: coverage.setdefault(x["raceId"],{}).update(x)

full=[rid for rid in selected if coverage.get(rid,{}).get("latestPreT15") and int(coverage.get(rid,{}).get("betTypes") or 0)>=6 and int(coverage.get(rid,{}).get("resultHorses") or 0)>=3 and int(coverage.get(rid,{}).get("payouts") or 0)>0]
bydate=defaultdict(lambda:{"selected":0,"comparable":0})
for rid in selected:
    date=rid[:10];bydate[date]["selected"]+=1
    if rid in full:bydate[date]["comparable"]+=1
report={"start":START,"end":END,"selectionDates":dates,"selectedRaces":len(selected),"comparableRaces":len(full),"byDate":dict(sorted(bydate.items())),"missing":[{"raceId":rid,**coverage.get(rid,{})} for rid in selected if rid not in full]}
print(json.dumps(report,ensure_ascii=False))
