#!/usr/bin/env python3
"""Read-only D1 export of official-recorded WIN payouts (2024-2026 only).

Production D1 holds only May 2024 onwards, NOT 2016-2024 full history.
This export is research-only and never fills missing prior payout periods
with estimates or post-race final odds. No updates, creates, deletes or
changes to bets/production. Winning JRA yen per 100 yen ticket are copied
from the recorded settlement table, and only for actual win tickets.
"""
from __future__ import annotations
import collections
import json
import os
from pathlib import Path
import urllib.request


def read(sql,params):
    if not sql.strip().upper().startswith("SELECT "):
        raise ValueError("D1_READ_ONLY_SELECT_REQUIRED")
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    db=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
    req=urllib.request.Request(url,method="POST",data=json.dumps({"sql":sql,"params":params}).encode(),
      headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
    with urllib.request.urlopen(req,timeout=60) as stream:reply=json.load(stream)
    if reply.get("success") is not True:
        raise RuntimeError("D1_QUERY_REJECTED:"+str(reply.get("errors"))[:250])
    return (reply.get("result") or [{}])[0].get("results",[])


def export(path,meta):
    out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
    total=0
    races=set()
    unique=set()
    with out.open("w",encoding="utf-8") as stream:
        offset=0
        while True:
            rows=read("""
                SELECT p.race_id AS raceId,p.bet_type AS betType,
                       p.combination,p.payout_yen AS payoutYen
                FROM rt_payouts p
                WHERE p.bet_type='単勝'
                ORDER BY p.race_id,p.combination
                LIMIT ? OFFSET ?""",[2000,offset])
            for r in rows:
                rid=str(r.get("raceId") or "")
                combination=str(r.get("combination") or "")
                payout=int(r.get("payoutYen") or 0)
                if not rid or not combination.isdigit() or payout<=0:
                    raise RuntimeError("INVALID_OFFICIAL_D1_WIN_PAYOUT")
                key=(rid,combination)
                if key in unique:raise RuntimeError("DUPLICATE_WIN_PAYOUT")
                unique.add(key);races.add(rid);total+=1
                stream.write(json.dumps({"raceId":rid,"betType":"単勝",
                    "combination":combination,"payoutYenPer100":payout,
                    "source":"D1_stored_JRA_return_not_independently_verified"},
                    ensure_ascii=False)+"\n")
            offset+=len(rows)
            print("D1_READ_ONLY_WIN_PAYOUT_BATCH",json.dumps({"total":total,"races":len(races)}),flush=True)
            if len(rows)<2000:break
    summary={
        "source":"D1-recorded JRA WIN payout, independent JRA web reconciliation not performed",
        "winPayoutRows":total,
        "uniqueRacesWithWinPayout":len(races),
        "completeTenYearPayoutHistoryAvailable":False,
        "historicalDatabaseCoverageBegins":"2024-05-04",
        "researchOnly":True,
        "productionModified":False,
    }
    if len(races)<5000:raise RuntimeError("WIN_PAYOUT_COVERAGE_BELOW_EXPECTED_2024_2026")
    Path(meta).write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("D1_READ_ONLY_WIN_PAYOUT_EXPORT_FINAL",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True)
    p.add_argument("--meta",required=True)
    a=p.parse_args()
    export(a.out,a.meta)
