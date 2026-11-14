#!/usr/bin/env python3
"""Independent audit of ORIGINAL 431% archived two-ticket cash vs D1 payouts.

NO forecasting, no reconstruction, no future outcomes used in the selection:
the old frozen archive's chosen combinations are immutable. Compare each
archived return for 2025–Aug2026 with independently stored actual six-market
JRA-derived payout amount (per 100 yen × 10 = per 1,000-yen ticket). Count
MISSING records separately and NEVER impute zero for missing races.

This is critical: a 431% return claim is not a substitute for a real cash
settlement audit. No database writes, no historical record alterations.
"""
from __future__ import annotations
import argparse
import base64
import collections
import gzip
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"src/v1/ten-year-history-data"
UNORDERED={"ワイド","馬連","3連複"}


def normalize(kind,raw):
    nums=[int(x) for x in str(raw).replace("→","-").split("-")]
    if kind in UNORDERED:nums.sort()
    return "-".join(map(str,nums))


def archived_rows():
    chunks=sorted(BASE.glob("bin-*.ts"))
    if len(chunks)!=9:raise RuntimeError("MISSING_ORIGINAL_ARCHIVED_TICKETS")
    encoded=""
    for path in chunks:
        s=path.read_text(encoding="utf8").strip()
        encoded+=json.loads(s.removeprefix("export default ").removesuffix(";"))
    payload=json.loads(gzip.decompress(base64.b64decode(encoded)))
    if len(payload["races"])!=34566:
        raise RuntimeError("MISSING_ORIGINAL_HISTORY_RACES")
    return payload["races"]


def d1_source(path):
    prizes=collections.defaultdict(lambda:collections.defaultdict(dict))
    with gzip.open(path,"rt",encoding="utf8") as src:
        for line in src:
            if not line.strip():continue
            row=json.loads(line)
            if row.get("source")!="D1_recorded_JRA_cash_unreconciled":
                raise RuntimeError("NON_JRA_D1_PAYOUT_SOURCE")
            rid=str(row["raceId"]);kind=str(row["market"])
            bet=normalize(kind,row["ticket"])
            val=int(row["payoutYenPer100"])
            if bet in prizes[rid][kind]:
                raise RuntimeError(f"DUPLICATE_JRA_PAYOUT:{rid}:{kind}:{bet}")
            prizes[rid][kind][bet]=val
    valid={rid:p for rid,p in prizes.items() if len(p)==6}
    if len(valid)<8000:raise RuntimeError("INCOMPLETE_SIXMARKET_CASH_SOURCE")
    return valid


def tally(records):
    if not records:return None
    bought=sum(x["stake"] for x in records)
    rec=sum(x["d1Paid"] for x in records)
    historic=sum(x["archivePaid"] for x in records)
    byrace=collections.defaultdict(lambda:[0,0])
    for x in records:
        byrace[x["raceId"]][0]+=x["d1Paid"]
        byrace[x["raceId"]][1]+=x["archivePaid"]
    biggest=max(x[0] for x in byrace.values())
    match=sum(x["d1Paid"]==x["archivePaid"] for x in records)
    return {
        "raceCount":len(byrace),"ticketCount":len(records),
        "d1RecordedStakeYen":bought,
        "d1RecordedPayoutYen":rec,
        "archivedPayoutYenOnSameRaces":historic,
        "d1ROI":round(100*rec/bought,6),
        "d1RoiAfterLargestRaceRemovedPct":round(100*(rec-biggest)/bought,6),
        "hitRaces":sum(v[0]>0 for v in byrace.values()),
        "hitRacePct":round(100*sum(v[0]>0 for v in byrace.values())/len(byrace),6),
        "matchingReturnTickets":match,
        "mismatchingReturnTickets":len(records)-match,
        "absoluteDifferenceInPaidYen":sum(abs(x["d1Paid"]-x["archivePaid"]) for x in records)
    }


def audit(path):
    payouts=d1_source(path)
    captured=collections.defaultdict(list)
    missing=collections.defaultdict(list)
    for row in archived_rows():
        rid,date,venue,rno,title,start,surf,distance,tickets=row
        if date<"2025-01-01" or date>"2026-08-09" or not tickets:
            continue
        if len(tickets)!=2:raise RuntimeError("ORIGINAL_TICKET_COUNT_NOT_TWO")
        year=date[:4]
        if rid not in payouts:
            missing[year].append(rid)
            continue
        for ticket in tickets:
            kind=str(ticket[0]);comb=normalize(kind,ticket[1])
            reported=int(ticket[3])
            if kind not in payouts[rid]:
                raise RuntimeError("MISSING_MARKET_FOR_SETTLED_RACE")
            d1=int(payouts[rid][kind].get(comb,0))*10
            captured[year].append({"raceId":rid,"market":kind,
                "combo":comb,"stake":1000,"d1Paid":d1,
                "archivePaid":reported})
    byyear={year:tally(rows) for year,rows in sorted(captured.items())}
    matched=[x for row in captured.values() for x in row]
    diff=[{k:x[k] for k in ("raceId","market","combo","d1Paid","archivePaid")}
          for x in matched if x["d1Paid"]!=x["archivePaid"]]
    result={
        "status":"ARCHIVED_AND_D1_MATCH" if not diff else "ARCHIVED_MONEY_DIFFERS_FROM_D1",
        "byYear":byyear,
        "combinedMatchedRaceSubset":tally(matched),
        "originalSelectedRacesWithAbsentD1Payouts":
            {year:{"count":len(races),"sampleRaceIds":races[:12]}
             for year,races in sorted(missing.items())},
        "firstPayoutMismatches":diff[:30],
        "canProveHistoricalInSampleOriginalMoney":len(diff)==0,
        "canProveRealPreT15TradableProfit":False,
        "evaluationWindow":"2025-01-01..2026-08-09",
        "D1CashIndependentlyJraWebsiteReconciled":False,
        "fullArchive2017To2026D1CashAvailable":False,
        "researchOnly":True,"productionModified":False,
    }
    return result


def selftest():
    assert normalize("3連複","9-7-16")=="7-9-16"
    assert normalize("3連単","9-7-16")=="9-7-16"
    assert tally([{"raceId":"r1","stake":1000,"d1Paid":3000,
                   "archivePaid":3000}])["d1ROI"]==300
    print("ORIGINAL_TWO_TICKET_D1_SIXMARKET_CASH_AUDIT_SELFTEST_OK",flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--payouts")
    p.add_argument("--output")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:selftest();return
    if not args.payouts or not args.output:p.error("missing inputs")
    report=audit(args.payouts)
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ORIGINAL_431_VS_D1_SIXMARKET_PAYOUT_FINAL",json.dumps({
        "status":report["status"],"byYear":report["byYear"],
        "combined":report["combinedMatchedRaceSubset"],
        "missingOriginalRaceCoverage":report["originalSelectedRacesWithAbsentD1Payouts"],
        "firstPayoutMismatches":report["firstPayoutMismatches"][:4]
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
