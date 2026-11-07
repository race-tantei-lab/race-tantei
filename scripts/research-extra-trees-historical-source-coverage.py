#!/usr/bin/env python3
"""Check real pre-Aug 2026 JRA payout availability without scanning or writing D1.

Zero row(s) for a year means the repository's D1 table cannot currently
support an older-than-Aug-2026 payout-consistent retrospective audit.
No synthetic payouts, postrace odds substitutions, or production alterations.
"""
import json
import os
import urllib.request

def query(sql, params):
    url=("https://api.cloudflare.com/client/v4/accounts/"
        + os.environ["CLOUDFLARE_ACCOUNT_ID"]+"/d1/database/"
        + os.environ["CLOUDFLARE_D1_DATABASE_ID"]+"/query")
    data=json.dumps({"sql":sql,"params":params}).encode()
    req=urllib.request.Request(url,method="POST",data=data,
       headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],
                "Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as f:
        out=json.load(f)
    if not out.get("success"):
        raise RuntimeError("D1_PAYOUT_AVAILABILITY_SELECT_FAILED:"+str(out.get("errors"))[:180])
    return (out.get("result") or [{}])[0].get("results") or []

def main():
    rows={}
    for year in (2023,2024,2025,2026):
        a,b=f"{year}-",f"{year+1}-"
        groups={}
        for table,datecol in (("rt_payouts","race_id"),("rt_races","race_id")):
            # An indexed prefix range and LIMIT 1: no unbounded table aggregate.
            sql=f"SELECT {datecol} raceId FROM {table} WHERE {datecol}>=? AND {datecol}<? ORDER BY {datecol} LIMIT 1"
            v=query(sql,[a,b])
            groups[table]={"hasAnyRows":bool(v),"firstRaceId":v[0].get("raceId") if v else None}
        rows[str(year)]=groups
    report={"status":"SOURCE_COVERAGE_ONLY_NOT_MODEL_PERFORMANCE",
            "source":"Cloudflare D1, bounded read-only indexed SELECT LIMIT 1 per year/table",
            "preAugIndependentExtraTrees2024_2025JraPayoutsReady":
               all(rows[y]["rt_payouts"]["hasAnyRows"] for y in ("2024","2025")),
            "requiresChronologicalYearwiseRefit":True,
            "requiresAllSixTypePayoutCoverageAndT15":True,
            "years":rows}
    print("EXTRATREES_OLDER_PERIOD_PAYOUT_SOURCE_COVERAGE",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
