#!/usr/bin/env python3
"""Independent cash recomputation of stored 2016-26 in-sample baseline.

The existing 431.65% historical claim is a full-archive-trained LightGBM
backtest. This auditor merely sums ORIGINAL frozen public ticket returns;
it is not an OOS result and must not be used as forward profitability proof.
No production or historical data are altered.
"""
import base64,collections,datetime as dt,gzip,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-original-frozen-model-cash-reconciliation.json"


def rows():
    chunks=sorted((ROOT/"src/v1/ten-year-history-data").glob("bin-*.ts"))
    if len(chunks)!=9:raise RuntimeError("INCOMPLETE_ARCHIVED_HISTORY")
    encoded=""
    for p in chunks:
        s=p.read_text(encoding="utf8").strip()
        encoded+=json.loads(s.removeprefix("export default ").removesuffix(";"))
    b=json.loads(gzip.decompress(base64.b64decode(encoded)))
    data=b["races"]
    if len(data)!=34566:raise RuntimeError("NOT_FULL_TEN_YEAR_ARCHIVE")
    return data


def report(items):
    stake=sum(row["stakeYen"] for row in items)
    paid=sum(row["returnYen"] for row in items)
    largest=max((row["returnYen"] for row in items),default=0)
    hit=sum(row["returnYen"]>0 for row in items)
    days=collections.Counter((row["date"],row["venue"]) for row in items)
    if not items or stake<=0:raise ValueError("NO_ACTUAL_ARCHIVED_BETS")
    return {
        "races":len(items),"venueDays":len(days),
        "minRacesPerVenueDay":min(days.values()),
        "stakeYen":stake,"paidYen":paid,"profitYen":paid-stake,
        "roiPct":round(100*paid/stake,7),
        "roiAfterSingleLargestRaceRemovedPct":round(100*(paid-largest)/stake,7),
        "hitRacePct":round(100*hit/len(items),7),
        "largestSingleRacePaidYen":largest,
    }


def audit():
    out=[]
    for rr in rows():
        rid,date,venue,no,title,start,surf,dist,tickets=rr
        if not tickets:continue
        if len(tickets)!=2:raise RuntimeError(f"NOT_TWO_FROZEN_TICKETS:{rid}")
        actual_receipts=sum(int(t[3]) for t in tickets)
        if len({t[0] for t in tickets})!=2:
            raise RuntimeError(f"DUPLICATE_MARKET_IN_FROZEN_POLICY:{rid}")
        out.append({"raceId":str(rid),"date":date,"venue":venue,
                    "stakeYen":2000,"returnYen":actual_receipts,
                    "tickets":[t[:2] for t in tickets]})
    if len(out)!=14410:raise RuntimeError(f"NOT_FULL_FROZEN_BASELINE:{len(out)}")
    full=report(out)
    if full["paidYen"]!=124401700 or full["stakeYen"]!=28820000:
        raise RuntimeError(f"ORIGINAL_BASELINE_CASH_MISMATCH:{full}")
    years={}
    for yr in range(2016,2027):
        subset=[x for x in out if x["date"].startswith(str(yr))]
        if subset:years[str(yr)]=report(subset)
    return {
        "source":"frozen selected actual race-ticket payouts in public history assets",
        "policy":"frozen 56-feature whole-archive-trained LightGBM as deployed 2026-08",
        "outOfSampleIndependentForward":False,
        "fullHistorical":full,
        "byYear":years,
        "allYears2017To2026":report([x for x in out if x["date"]>="2017-01-01"]),
        "researchOnly":True,"productionChanged":False,
    }


if __name__=="__main__":
    result=audit()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ORIGINAL_56_MODEL_FROZEN_CASH_RECONCILIATION",
          json.dumps({"full":result["fullHistorical"],
                      "2017plus":result["allYears2017To2026"],
                      "2025":result["byYear"]["2025"],
                      "2026ThroughAug09":result["byYear"]["2026"],
                      "outOfSample":False},ensure_ascii=False),flush=True)
