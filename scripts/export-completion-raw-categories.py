import gzip
import json
import os
import pickle
import time
import urllib.request
from pathlib import Path

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "completion-raw-categories.pkl.gz"
META = ROOT / "artifacts" / "completion-raw-categories-meta.json"

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def sql(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    last_error = None
    for attempt in range(1, 7):
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("success"):
                raise RuntimeError(f"D1_ERROR:{payload.get('errors')}")
            return payload.get("result", [{}])[0].get("results", [])
        except Exception as error:
            last_error = error
            if attempt == 6:
                raise
            time.sleep(attempt * 1.5)
    raise last_error


def month_ranges(start, end):
    year, month = map(int, start[:7].split("-"))
    end_year, end_month = map(int, end[:7].split("-"))
    while (year, month) <= (end_year, end_month):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        yield f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"
        year, month = next_year, next_month


rows = []
for start, end in month_ranges("2024-05-01", "2026-08-01"):
    rows.extend(
        sql(
            """
            SELECT
              r.race_id raceId, r.race_date raceDate, r.venue, r.race_no raceNo,
              r.race_name raceName, r.conditions, r.surface, r.distance_m distanceM,
              r.direction, r.weather, r.track_condition trackCondition,
              rr.horse_no horseNo, rr.frame_no frameNo, rr.horse_name horseName,
              rr.sex_age sexAge, rr.horse_weight horseWeight, rr.weight_change weightChange,
              rr.jockey, rr.assigned_weight assignedWeight, rr.trainer, rr.stable,
              rr.win_odds winOdds, rr.popularity, rr.runner_status runnerStatus
            FROM rt_races r
            JOIN rt_runners rr ON rr.race_id = r.race_id
            WHERE r.race_date >= ? AND r.race_date < ? AND r.status = 'finished'
            ORDER BY r.race_date, r.venue, r.race_no, rr.horse_no
            """,
            [start, end],
        )
    )

race_ids = sorted({row["raceId"] for row in rows})
if len(race_ids) != 7695:
    raise RuntimeError(f"COMPLETION_RACE_COUNT_MISMATCH:{len(race_ids)}")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(OUTPUT, "wb", compresslevel=5) as handle:
    pickle.dump({"schema": 1, "source": "existing D1 only; no new race ingestion", "rows": rows}, handle, protocol=5)

meta = {
    "races": len(race_ids),
    "runners": len(rows),
    "start": min(row["raceDate"] for row in rows),
    "end": max(row["raceDate"] for row in rows),
    "bytes": OUTPUT.stat().st_size,
    "fields": sorted(rows[0].keys()) if rows else [],
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
