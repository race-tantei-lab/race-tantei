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
OUT = ROOT / "artifacts" / "official-odds-audit.json"
START = "2024-05-04"
END_EXCLUSIVE = "2026-08-03"

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def q(sql, params=None):
    body = json.dumps({"sql": sql, "params": params or []}).encode()
    last = None
    for attempt in range(1, 6):
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("success"):
                raise RuntimeError(payload.get("errors"))
            return payload.get("result", [{}])[0].get("results", [])
        except Exception as exc:
            last = exc
            if attempt == 5:
                raise
            time.sleep(attempt)
    raise last

fixed_params = [START, END_EXCLUSIVE]
summary = q(
    """
    SELECT
      COUNT(*) AS snapshot_rows,
      COUNT(DISTINCT o.race_id) AS races,
      MIN(r.race_date) AS min_race_date,
      MAX(r.race_date) AS max_race_date,
      MIN(o.captured_at_utc) AS min_capture,
      MAX(o.captured_at_utc) AS max_capture
    FROM rt_official_odds_snapshots o
    JOIN rt_races r ON r.race_id=o.race_id
    WHERE r.race_date>=? AND r.race_date<?
      AND o.odds_source='jra_official'
    """,
    fixed_params,
)[0]

pre_summary = q(
    """
    SELECT
      COUNT(*) AS snapshot_rows,
      COUNT(DISTINCT o.race_id) AS races,
      MIN(r.race_date) AS min_race_date,
      MAX(r.race_date) AS max_race_date,
      MIN(o.seconds_to_start) AS min_seconds_to_start,
      MAX(o.seconds_to_start) AS max_seconds_to_start
    FROM rt_official_odds_snapshots o
    JOIN rt_races r ON r.race_id=o.race_id
    WHERE r.race_date>=? AND r.race_date<?
      AND o.odds_source='jra_official'
      AND o.seconds_to_start > 0
      AND o.captured_at_utc < COALESCE(o.race_start_time_utc, r.start_time_utc)
    """,
    fixed_params,
)[0]

by_type = q(
    """
    SELECT o.bet_type,
           COUNT(*) AS snapshot_rows,
           COUNT(DISTINCT o.race_id) AS races,
           COUNT(DISTINCT o.race_id || '|' || o.combination) AS combinations,
           MIN(r.race_date) AS min_race_date,
           MAX(r.race_date) AS max_race_date
    FROM rt_official_odds_snapshots o
    JOIN rt_races r ON r.race_id=o.race_id
    WHERE r.race_date>=? AND r.race_date<?
      AND o.odds_source='jra_official'
      AND o.seconds_to_start > 0
      AND o.captured_at_utc < COALESCE(o.race_start_time_utc, r.start_time_utc)
    GROUP BY o.bet_type
    ORDER BY o.bet_type
    """,
    fixed_params,
)

by_month = q(
    """
    SELECT substr(r.race_date,1,7) AS month,
           COUNT(DISTINCT o.race_id) AS races,
           COUNT(*) AS snapshot_rows
    FROM rt_official_odds_snapshots o
    JOIN rt_races r ON r.race_id=o.race_id
    WHERE r.race_date>=? AND r.race_date<?
      AND o.odds_source='jra_official'
      AND o.seconds_to_start > 0
      AND o.captured_at_utc < COALESCE(o.race_start_time_utc, r.start_time_utc)
    GROUP BY substr(r.race_date,1,7)
    ORDER BY month
    """,
    fixed_params,
)

latest_pre = q(
    """
    WITH ranked AS (
      SELECT o.race_id, o.bet_type, o.combination, o.odds_min, o.odds_max,
             o.captured_at_utc, o.seconds_to_start,
             ROW_NUMBER() OVER (
               PARTITION BY o.race_id,o.bet_type,o.combination
               ORDER BY o.captured_at_utc DESC
             ) AS rn
      FROM rt_official_odds_snapshots o
      JOIN rt_races r ON r.race_id=o.race_id
      WHERE r.race_date>=? AND r.race_date<?
        AND o.odds_source='jra_official'
        AND o.seconds_to_start > 0
        AND o.captured_at_utc < COALESCE(o.race_start_time_utc, r.start_time_utc)
    )
    SELECT bet_type,
           COUNT(*) AS latest_rows,
           COUNT(DISTINCT race_id) AS races,
           MIN(seconds_to_start) AS closest_seconds_before_start,
           MAX(seconds_to_start) AS furthest_seconds_before_start
    FROM ranked
    WHERE rn=1
    GROUP BY bet_type
    ORDER BY bet_type
    """,
    fixed_params,
)

race_total = q(
    "SELECT COUNT(*) AS n FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished'",
    fixed_params,
)[0]["n"]

payload = {
    "fixedPeriod": {"start": START, "end": "2026-08-02", "finishedRaces": race_total},
    "allOfficialSnapshots": summary,
    "strictPreRaceOfficialSnapshots": pre_summary,
    "strictPreRaceByBetType": by_type,
    "strictPreRaceByMonth": by_month,
    "latestStrictPreRaceByBetType": latest_pre,
    "rules": {
        "oddsSource": "jra_official",
        "secondsToStart": ">0",
        "captureBeforeRaceStart": True,
        "oldModelProbabilitiesUsed": False,
        "oldProjectedRoiUsed": False,
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False))
