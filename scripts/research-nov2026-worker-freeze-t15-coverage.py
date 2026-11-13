#!/usr/bin/env python3
"""Read-only cohort coverage of real original pre-race Worker final snapshots.

ONLY aggregate indexed bounded SQL and seven redacted metadata fields.
No outcome, no D1 writes. Fails on missing schema, never fabricates odds.
"""
from __future__ import annotations
import json,os,urllib.request
from pathlib import Path
def q(sql,params):
    if not sql.lstrip().upper().startswith("SELECT "):raise RuntimeError("ONLY_SELECT_ALLOWED")
    url=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
    req=urllib.request.Request(url,data=json.dumps({"sql":sql,"params":params}).encode(),method="POST",headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=55) as r:d=json.loads(r.read())
    if not d.get("success"):raise RuntimeError("READ_ONLY_QUERY_FAILED:"+str(d.get("errors"))[:300])
    return (d.get("result") or [{}])[0].get("results") or []
def main():
    if "--self-test" in os.sys.argv:
        assert len("worker_live_final:")==18
        print("WORKER_T15_D1_READ_ONLY_SELFTEST_OK");return
    params=["worker_live_final:2026-08-15-","worker_live_final:2026-11-09-"]
    totals=q("""SELECT substr(state_key,19,7) AS month,count(*) AS frozenRaces,
         sum(CASE WHEN json_extract(state_value,'$.sourceModel')='ten-year-completed-model' THEN 1 ELSE 0 END) AS canonicalModel,
         sum(CASE WHEN json_extract(state_value,'$.oddsFetchedAt') IS NOT NULL THEN 1 ELSE 0 END) AS storedOfficialOddsFetchTime,
         sum(CASE WHEN json_extract(state_value,'$.oddsSnapshotSha256') IS NOT NULL THEN 1 ELSE 0 END) AS storedOddsHash,
         sum(CASE WHEN json_type(state_value,'$.shadowResearch')='array' THEN 1 ELSE 0 END) AS hasSixMarketShadowResearch,
         sum(CASE WHEN json_type(state_value,'$.roiFirstResearch')='object' THEN 1 ELSE 0 END) AS hasRoiFirstResearch,
         sum(CASE WHEN json_extract(state_value,'$.lockedAt') IS NOT NULL THEN 1 ELSE 0 END) AS hasLockTimestamp
       FROM rt_system_state
       WHERE state_key>=? AND state_key<?
       GROUP BY substr(state_key,19,7) ORDER BY month""",params)
    first=q("""SELECT state_key AS stateKey,
             json_extract(state_value,'$.sourceModel') AS sourceModel,
             json_extract(state_value,'$.oddsSource') AS oddsSource,
             json_extract(state_value,'$.oddsFetchedAt') AS oddsFetchedAt,
             json_extract(state_value,'$.lockedAt') AS lockedAt,
             json_extract(state_value,'$.oddsSnapshotSha256') AS oddsSha256,
             json_type(state_value,'$.shadowResearch') AS shadowType,
             json_type(state_value,'$.roiFirstResearch') AS roiType
             FROM rt_system_state WHERE state_key>=? AND state_key<?
             ORDER BY state_key DESC LIMIT 4""",params)
    report={"source":"Worker preserved pre-final race bet record metadata 2026 Aug-Nov",
       "noDbWrites":True,"snapshotCountByMonth":totals,"sampleMetadata":first,
       "notAValidatedModel":True}
    out=Path("analysis-results/nov2026-worker-frozen-t15-coverage.json")
    out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("WORKER_FROZEN_ODDS_EVIDENCE",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
