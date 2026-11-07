#!/usr/bin/env python3
"""Read-only research-only D1 coverage audit. Does not train or deploy any model."""
import json,os,urllib.request

A=os.environ["CLOUDFLARE_ACCOUNT_ID"]
D=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
T=os.environ["CLOUDFLARE_API_TOKEN"]
U=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"

def query(sql,params=()):
    request=urllib.request.Request(U,data=json.dumps({"sql":sql,"params":list(params)}).encode(),method="POST",headers={"Authorization":"Bearer "+T,"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=60) as response: x=json.load(response)
    if not x.get("success"):raise RuntimeError(str(x.get("errors"))[:450])
    return (x.get("result") or [{}])[0].get("results") or []

def main():
    out={}
    table_cols={
        "rt_official_value_candidates":"captured_at_utc",
        "rt_official_odds_snapshots":"captured_at_utc",
    }
    for table,col in table_cols.items():
        out[table]={}
        for start,end in (("2024-01-01","2025-01-01"),("2025-01-01","2026-01-01"),
                          ("2026-01-01","2026-08-10"),("2026-08-10","2026-11-08")):
            try:
                result=query(f"""SELECT COUNT(*) AS rows, COUNT(DISTINCT race_id) AS races,
                    MIN({col}) AS oldestCapture, MAX({col}) AS latestCapture
                    FROM {table} WHERE race_id>=? AND race_id<?""",(start+"-",end+"-"))
                out[table][start+".."+end]=result[0] if result else {}
            except Exception as e:
                out[table][start+".."+end]={"error":str(e)[:350]}
    for table in ("rt_races","rt_payouts"):
        out[table]={}
        for start,end in (("2024-01-01","2025-01-01"),("2025-01-01","2026-01-01"),
                          ("2026-01-01","2026-08-10"),("2026-08-10","2026-11-08")):
            try:
                result=query(f"""SELECT COUNT(*) AS rows,COUNT(DISTINCT race_id) AS races
                  FROM {table} WHERE race_id>=? AND race_id<?""",(start+"-",end+"-"))
                out[table][start+".."+end]=result[0] if result else {}
            except Exception as e:
                out[table][start+".."+end]={"error":str(e)[:350]}
    print("RESEARCH_HISTORICAL_TICKET_OFFICIAL_ODDS_COVERAGE",json.dumps(out,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":main()
