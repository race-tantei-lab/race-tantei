#!/usr/bin/env python3
import json, os, sys, urllib.request

BASE_TOTAL={"races":14410,"stakeYen":28820000,"returnYen":124401700}
BASE_VENUES={
 "札幌":[670,1340000,5330600],"函館":[600,1200000,5272100],"福島":[960,1920000,10264200],
 "新潟":[1360,2720000,12600700],"東京":[2230,4460000,17897900],"中山":[2085,4170000,16402800],
 "中京":[1515,3030000,11882300],"京都":[1705,3410000,13982100],"阪神":[2115,4230000,16787400],
 "小倉":[1170,2340000,13981600],
}
ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]; DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]; TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
D1=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"
PUBLIC="https://race-tantei-phase0.race-tantei.workers.dev/api/public/cumulative-performance"

def q(sql,params=None):
    req=urllib.request.Request(D1,data=json.dumps({"sql":sql,"params":params or []}).encode(),method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: body=json.loads(r.read().decode())
    if not body.get("success"): raise RuntimeError(body)
    z=body.get("result") or []
    return (z[0].get("results") or []) if z else []

with urllib.request.urlopen(PUBLIC+"?_exact_audit=1",timeout=60) as r:
    snap=json.loads(r.read().decode())
closed=str(snap.get("closedThroughDate") or "")
if not closed: raise RuntimeError("CLOSED_THROUGH_DATE_MISSING")

rows=q("""
WITH valid AS (
 SELECT r.venue,b.race_id,
        COUNT(*) rowCount,
        SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) settledRows,
        SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END) stakeYen,
        SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END) returnYen
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date>? AND r.race_date<=?
   AND b.course='ライト' AND b.source_prediction_id=-2
 GROUP BY r.venue,b.race_id
 HAVING COUNT(*)=2
    AND SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END)=2
    AND SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END)=2000
)
SELECT venue,COUNT(*) races,SUM(stakeYen) stakeYen,SUM(returnYen) returnYen
FROM valid GROUP BY venue ORDER BY venue
""",["2026-08-09",closed])

live={"races":0,"stakeYen":0,"returnYen":0}
expected_venues={k:list(v) for k,v in BASE_VENUES.items()}
for x in rows:
    venue=str(x["venue"]); r=int(x["races"] or 0); s=int(x["stakeYen"] or 0); ret=int(x["returnYen"] or 0)
    live["races"]+=r;live["stakeYen"]+=s;live["returnYen"]+=ret
    cur=expected_venues.setdefault(venue,[0,0,0]);cur[0]+=r;cur[1]+=s;cur[2]+=ret
expected={
 "races":BASE_TOTAL["races"]+live["races"],
 "stakeYen":BASE_TOTAL["stakeYen"]+live["stakeYen"],
 "returnYen":BASE_TOTAL["returnYen"]+live["returnYen"],
}
actual=snap["closedTotal"]
for k in ("races","stakeYen","returnYen"):
    if int(actual[k])!=int(expected[k]):
        raise AssertionError(f"TOTAL_MISMATCH:{k}:{actual[k]}:{expected[k]}")
actual_venues={str(x["venue"]):[int(x["races"]),int(x["stakeYen"]),int(x["returnYen"])] for x in snap["closedVenues"]}
if actual_venues!=expected_venues:
    diff={k:{"actual":actual_venues.get(k),"expected":expected_venues.get(k)} for k in sorted(set(actual_venues)|set(expected_venues)) if actual_venues.get(k)!=expected_venues.get(k)}
    raise AssertionError("VENUE_MISMATCH:"+json.dumps(diff,ensure_ascii=False))
roi=expected["returnYen"]/expected["stakeYen"]*100
print(json.dumps({"CUMULATIVE_EXACT_OK":True,"closedThroughDate":closed,"productionLive":live,"total":expected,"roiPct":roi,"venues":expected_venues},ensure_ascii=False))
