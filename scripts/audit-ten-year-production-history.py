#!/usr/bin/env python3
import json
import os
import time
import urllib.request
from pathlib import Path

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "ten-year-production-history-audit.json"
START = "2015-01-04"
END = "2026-08-09"
EXPECTED_RACES = 40155
EXPECTED_RUNNERS = 559546

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def sql(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    for attempt in range(1, 6):
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("success"):
                raise RuntimeError(payload.get("errors"))
            return payload.get("result", [{}])[0].get("results", [])
        except Exception:
            if attempt == 5:
                raise
            time.sleep(attempt)


def one(query, params=None):
    rows = sql(query, params)
    return rows[0] if rows else {}


race = one(
    "SELECT COUNT(*) AS n, MIN(race_date) AS minDate, MAX(race_date) AS maxDate, "
    "COUNT(DISTINCT race_date) AS dates FROM rt_races WHERE race_date BETWEEN ? AND ?",
    [START, END],
)
runner = one(
    "SELECT COUNT(*) AS n FROM rt_runners x JOIN rt_races r ON r.race_id=x.race_id "
    "WHERE r.race_date BETWEEN ? AND ?",
    [START, END],
)
result = one(
    "SELECT COUNT(*) AS n, SUM(CASE WHEN x.finish_position IS NOT NULL THEN 1 ELSE 0 END) AS withFinish, "
    "SUM(CASE WHEN x.final3f IS NOT NULL THEN 1 ELSE 0 END) AS withFinal3f "
    "FROM rt_results x JOIN rt_races r ON r.race_id=x.race_id WHERE r.race_date BETWEEN ? AND ?",
    [START, END],
)
payout = one(
    "SELECT COUNT(*) AS n FROM rt_payouts x JOIN rt_races r ON r.race_id=x.race_id "
    "WHERE r.race_date BETWEEN ? AND ?",
    [START, END],
)

report = {
    "requiredStart": START,
    "requiredEnd": END,
    "expectedRaces": EXPECTED_RACES,
    "expectedRunners": EXPECTED_RUNNERS,
    "races": race,
    "runners": runner,
    "results": result,
    "payouts": payout,
}
report["canonicalHistoryReady"] = (
    int(race.get("n") or 0) == EXPECTED_RACES
    and int(runner.get("n") or 0) == EXPECTED_RUNNERS
    and str(race.get("minDate") or "") == START
    and str(race.get("maxDate") or "") == END
)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
