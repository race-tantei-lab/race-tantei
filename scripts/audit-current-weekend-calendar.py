import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "current-weekend-calendar-sync.json"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def query(sql: str, params: list) -> list[dict]:
    request = urllib.request.Request(
        URL,
        data=json.dumps({"sql": sql, "params": params}).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def main() -> None:
    expected = json.loads(REPORT.read_text(encoding="utf-8"))
    checks = []
    for day in expected.get("days") or []:
        race_date = str(day["raceDate"])
        expected_races = int(day["races"])
        expected_venues = int(day["venues"])
        rows = query(
            """
            SELECT venue,COUNT(*) AS races,MIN(race_no) AS minRaceNo,MAX(race_no) AS maxRaceNo,
                   SUM(CASE WHEN start_time_utc IS NOT NULL THEN 1 ELSE 0 END) AS withStartTime
            FROM rt_races WHERE race_date=? GROUP BY venue ORDER BY venue
            """,
            [race_date],
        )
        actual_races = sum(int(row.get("races") or 0) for row in rows)
        complete = (
            len(rows) == expected_venues
            and actual_races == expected_races
            and all(
                int(row.get("races") or 0) == 12
                and int(row.get("minRaceNo") or 0) == 1
                and int(row.get("maxRaceNo") or 0) == 12
                and int(row.get("withStartTime") or 0) == 12
                for row in rows
            )
        )
        checks.append({
            "raceDate": race_date,
            "complete": complete,
            "expectedRaces": expected_races,
            "actualRaces": actual_races,
            "expectedVenues": expected_venues,
            "actualVenues": len(rows),
            "venues": rows,
        })
    output = {"ok": bool(checks) and all(row["complete"] for row in checks), "checks": checks}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output["ok"]:
        raise SystemExit("CURRENT_WEEKEND_CALENDAR_INCOMPLETE")


if __name__ == "__main__":
    main()
