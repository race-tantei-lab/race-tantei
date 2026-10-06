#!/usr/bin/env python3
import json, os, re, urllib.request
from collections import defaultdict

ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]; DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]; TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"
KEY="public_daily_performance_history:v1"; COURSES=("ライト","スタンダード","プレミアム")

def q(sql,params=None):
    req=urllib.request.Request(URL,data=json.dumps({"sql":sql,"params":params or []},ensure_ascii=False).encode(),method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read().decode())
    if not out.get("success"): raise RuntimeError(out)
    z=out.get("result") or []
    return (z[0].get("results") or []) if z else []

state=q("SELECT state_value value FROM rt_system_state WHERE state_key=? LIMIT 1",[KEY])
assert state and state[0].get("value"), "DAILY_HISTORY_STATE_MISSING"
p=json.loads(state[0]["value"])
assert p.get("version")=="daily-performance-history-v1"
days=p.get("days") or []
assert days
dates=[str(x["date"]) for x in days]
marks=",".join("?" for _ in dates)
rows=q(f"""SELECT r.race_date raceDate,b.race_id raceId,b.course,
 COUNT(*) rowCount,
 SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) settledRows,
 SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END) settledStakeYen,
 SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END) returnYen
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date IN ({marks}) AND b.source_prediction_id=-2
 GROUP BY r.race_date,b.race_id,b.course ORDER BY r.race_date,b.race_id,b.course""",dates)
agg=defaultdict(lambda:defaultdict(lambda:{"settledRaces":0,"settledStakeYen":0,"returnYen":0}))
for x in rows:
    if int(x["rowCount"] or 0)==2 and int(x["settledRows"] or 0)==2:
        z=agg[str(x["raceDate"])][str(x["course"])]
        z["settledRaces"]+=1;z["settledStakeYen"]+=int(x["settledStakeYen"] or 0);z["returnYen"]+=int(x["returnYen"] or 0)
for day in days:
    date=str(day["date"])
    for c in day.get("courses") or []:
        course=str(c["course"]); expected=agg[date][course]
        assert int(c.get("settledRaces") or 0)==expected["settledRaces"], (date,course,"settledRaces",c.get("settledRaces"),expected)
        assert int(c.get("settledStakeYen") or 0)==expected["settledStakeYen"], (date,course,"stake",c.get("settledStakeYen"),expected)
        assert int(c.get("returnYen") or 0)==expected["returnYen"], (date,course,"return",c.get("returnYen"),expected)
        if expected["settledStakeYen"]:
            roi=expected["returnYen"]/expected["settledStakeYen"]*100
            assert abs(float(c["roiPct"])-roi)<1e-9, (date,course,"roi",c.get("roiPct"),roi)
print(json.dumps({"DAILY_PERFORMANCE_D1_EXACT_OK":True,"throughDate":p.get("throughDate"),"days":dates,"unresolvedDates":p.get("unresolvedDates")},ensure_ascii=False))
