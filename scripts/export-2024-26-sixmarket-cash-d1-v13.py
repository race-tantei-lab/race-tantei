#!/usr/bin/env python3
"""Read-only export of ALL SIX real JRA-type winning cash settlements in D1.

For each race, losing unlisted combinations can be assigned zero cash ONLY
when the race has a recorded winning payout in EACH of the six markets.
Absent races are never represented as known zero-payout races. Payouts
are D1 stored, not externally reconciled to JRA. No write SQL.
"""
from __future__ import annotations
import argparse
import collections
import gzip
import json
import os
from pathlib import Path
import urllib.request

MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
PAGE=1800
MAX_RECORDS=100000


def normalize(kind,combo):
    text=str(combo).strip().replace("→","-").replace("－","-")
    components=text.split("-")
    if not components or any(not x.isdigit() for x in components):
        raise ValueError(f"NON_NUMERIC_COMBO:{kind}:{text}")
    nums=[int(x) for x in components]
    if kind in UNORDERED:
        nums.sort()
    want=1 if kind=="単勝" else (3 if kind.startswith("3連") else 2)
    if len(nums)!=want or len(set(nums))!=len(nums):
        raise ValueError(f"INVALID_MARKET_COMBO:{kind}:{text}")
    return "-".join(map(str,nums))


def query(sql,params):
    if not sql.upper().lstrip().startswith("SELECT "):
        raise RuntimeError("D1_READ_ONLY_ONLY")
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    db=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    u=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
    req=urllib.request.Request(u,method="POST",
        data=json.dumps({"sql":sql,"params":params}).encode("utf8"),
        headers={"Content-Type":"application/json",
                 "Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"]})
    with urllib.request.urlopen(req,timeout=75) as fh:
        obj=json.load(fh)
    if not obj.get("success"):
        raise RuntimeError("D1_FAILED:"+str(obj.get("errors"))[:300])
    return (obj.get("result") or [{}])[0].get("results",[])


def export(outfile,metafile):
    dest=Path(outfile)
    dest.parent.mkdir(parents=True,exist_ok=True)
    total=0
    by_race=collections.defaultdict(set)
    market_counts=collections.Counter()
    duplicates=collections.Counter()
    current=set()
    with gzip.open(dest,"wt",encoding="utf8") as stream:
        while True:
            page=query("""
                SELECT race_id AS raceId,bet_type AS betType,
                       combination,payout_yen AS payoutYen
                FROM rt_payouts
                WHERE bet_type IN ('単勝','ワイド','馬連','馬単','3連複','3連単')
                ORDER BY race_id, bet_type, combination
                LIMIT ? OFFSET ?
            """,[PAGE,total])
            for rec in page:
                rid=str(rec.get("raceId") or "")
                kind=str(rec.get("betType") or "")
                val=int(rec.get("payoutYen") or 0)
                if kind not in MARKETS or not rid or val<=0:
                    raise RuntimeError("INVALID_PAYOUT_ROW")
                canon=normalize(kind,rec.get("combination"))
                key=(rid,kind,canon)
                if key in current:
                    duplicates[kind]+=1
                    raise RuntimeError("DUPLICATE_WINNING_TICKET")
                current.add(key)
                by_race[rid].add(kind)
                market_counts[kind]+=1
                stream.write(json.dumps({
                    "raceId":rid,"market":kind,"ticket":canon,
                    "payoutYenPer100":val,
                    "source":"D1_recorded_JRA_cash_unreconciled"
                },ensure_ascii=False)+"\n")
            total+=len(page)
            if total>MAX_RECORDS:raise RuntimeError("EXCESSIVE_PAYOUT_QUERY")
            if total%9000<PAGE:
                print("SIX_MARKET_CASH_EXPORT_PROGRESS",json.dumps({
                    "payoutRows":total,"raceIds":len(by_race)},ensure_ascii=False),
                    flush=True)
            if len(page)<PAGE:break
    full=sum(len(types)==len(MARKETS) for types in by_race.values())
    record={
        "recordedPayoutRows":total,
        "distinctRacesWithAnyMarketPayout":len(by_race),
        "distinctRacesWithAllSixMarkets":full,
        "marketPayoutEntryCounts":dict(sorted(market_counts.items())),
        "onlyFullyCoveredRacesMayAssignZeroToNonwinningCombos":True,
        "historicalCoverageFrom":"2024-05",
        "officialSource":"D1_JRA-derived_stored_payout_not_externally_reconciled",
        "preT15MarketOddsVerified":False,
        "productionModified":False,
    }
    if full<8000:
        raise RuntimeError("SIX_MARKET_CASH_RACE_COVERAGE_INCOMPLETE")
    Path(metafile).write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",
                              encoding="utf8")
    print("SIX_MARKET_CASH_DATA_EXPORT_FINAL",
          json.dumps(record,ensure_ascii=False),flush=True)


def selftest():
    assert normalize("馬連","9-7")=="7-9"
    assert normalize("ワイド","9-7")=="7-9"
    assert normalize("3連複","16-7-9")=="7-9-16"
    assert normalize("3連単","16-7-9")=="16-7-9"
    assert normalize("馬単","9-7")=="9-7"
    print("SIX_MARKET_PAYOUT_CANONICALIZATION_SELFTEST_OK",flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--meta")
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:selftest()
    else:
        if not a.out or not a.meta:ap.error("output and meta required")
        export(a.out,a.meta)
