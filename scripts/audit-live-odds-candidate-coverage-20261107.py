#!/usr/bin/env python3
"""Read-only availability probe for real pre-T15 counterfactual ticket candidates."""
import json,os,urllib.request
u=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
t=os.environ["CLOUDFLARE_API_TOKEN"]
def q(sql):
    request=urllib.request.Request(u,method="POST",headers={"Authorization":"Bearer "+t,"Content-Type":"application/json"},data=json.dumps({"sql":sql,"params":[]}).encode())
    with urllib.request.urlopen(request,timeout=50) as f:r=json.loads(f.read())
    if not r.get("success"):raise RuntimeError(str(r.get("errors"))[:300])
    return (r.get("result") or [{}])[0].get("results") or []
for table in ("rt_official_value_candidates","rt_official_odds_snapshots"):
    try:
        result=q(f"""SELECT COUNT(*) AS n, MIN(substr(captured_at_utc,1,10)) AS firstDay,
        MAX(substr(captured_at_utc,1,10)) AS lastDay,
        COUNT(DISTINCT race_id) AS races
        FROM {table} WHERE race_id >= '2026-08-10-' AND race_id < '2026-11-08-'""")
        print("CANDIDATE_SOURCE_COVERAGE",json.dumps({"table":table,"summary":result},separators=(",",":")))
    except Exception as e:
        print("CANDIDATE_SOURCE_ERROR",json.dumps({"table":table,"error":str(e)[:600]}))
