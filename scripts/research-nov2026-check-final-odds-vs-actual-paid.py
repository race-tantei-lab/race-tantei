#!/usr/bin/env python3
"""Audit final-win-odds monetary proxy using observed real JRA paid tickets.

Saved old-model tickets are used ONLY as an odds-vs-actual-return calibration
diagnostic, NEVER for candidate selection or direct cash model training.
For each saved 単勝 ticket that actually returned cash, compare:
  returnLightYen (archived JRA-paid actual) vs recorded officialOdds*¥1000.
Mismatch shows why archival final odds must NOT be called exact JRA payout.

This cannot establish that any odds quote existed at T-15.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import base64
import gzip
import json
import math

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-final-win-odds-vs-observed-jra-win-payout.json"

def get():
    chunks=sorted((ROOT/"src/v1/ten-year-history-data").glob("bin-*.ts"))
    if len(chunks)!=9:raise RuntimeError("ARCHIVE_INCOMPLETE")
    encoded=""
    for p in chunks:
        s=p.read_text(encoding="utf-8").strip()
        assert s.startswith("export default ") and s.endswith(";")
        encoded+=json.loads(s[len("export default "):-1])
    payload=json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert len(payload["races"])==34566
    return payload["races"]

def study():
    years={}
    for race in get():
        day=str(race[1]);tickets=race[8] or []
        y=years.setdefault(day[:4],Counter())
        for bet in tickets:
            if str(bet[0])!="単勝":continue
            y["allSingleWinSavedTickets"]+=1
            quote=float(bet[2]) if bet[2] is not None else float("nan")
            returned=int(bet[3] or 0)
            if returned<=0:continue
            y["actualSingleWinPaidTickets"]+=1
            if not 1<=quote<=9999 or not math.isfinite(quote):
                y["paidButOddsQuoteMissing"]+=1;continue
            y["paidWithUsableQuote"]+=1
            # per-ticket Light stake ¥1000, recorded public archive.
            expected=int(round(quote*1000))
            difference=returned-expected
            y["actualPaidCashYen"]+=returned
            y["oddsImpliedCashYen"]+=expected
            y["absolutePayoutDifferenceYen"]+=abs(difference)
            if difference==0:y["paidTicketsExactQuoteMatch"]+=1
            elif abs(difference)<=100:y["paidTicketsWithin100Yen"]+=1
            else:y["paidTicketsOver100YenMismatch"]+=1
    summary=Counter()
    for row in years.values():summary.update(row)
    matched=summary["paidWithUsableQuote"]
    output={
      "classification":"REAL_JRA_PAID_TICKET_VS_QUOTES_PROXY_AUDIT_ONLY",
      "actualJraPaidTicketRowsUsedOnlyForCalibration":True,
      "usedOldSavedBetChoicesForTrainingOrSelection":False,
      "2026OutcomesUsedForModelTraining":False,
      "finalOddsNotOfficialT15":True,
      "years":{y:dict(z) for y,z in sorted(years.items())},
      "allYears":dict(summary),
      "winQuoteExactMatchRatePct":round(100*summary["paidTicketsExactQuoteMatch"]/matched,4)
           if matched else None,
      "observedPaidCashRoiAuditOnlyNotCompletePortfolio":True,
      "fullSixMarketPayoutAvailable":False,
      "allowedForProductionPromotion":False
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("OBSERVED_JRA_SINGLE_WIN_PAYOUT_VS_ARCHIVED_ODDS",json.dumps({
      "actualPaidWinningWinTickets":summary["actualSingleWinPaidTickets"],
      "quotesCompared":matched,
      "exactPaidMatches":summary["paidTicketsExactQuoteMatch"],
      "within100Yen":summary["paidTicketsWithin100Yen"],
      "over100YenMismatch":summary["paidTicketsOver100YenMismatch"],
      "missing":summary["paidButOddsQuoteMissing"],
      "pctExact":output["winQuoteExactMatchRatePct"],
      "year2026":output["years"].get("2026")},ensure_ascii=False))

if __name__=="__main__":study()
