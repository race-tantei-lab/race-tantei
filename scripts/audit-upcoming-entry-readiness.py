import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "upcoming-entry-readiness.json"
DISCOVERY = ROOT / "jra-entry-anchor-discovery.json"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def query(sql: str) -> list[dict]:
    request = urllib.request.Request(
        URL,
        data=json.dumps({"sql": sql, "params": []}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def expected_groups() -> list[tuple[str, str]]:
    if not DISCOVERY.exists():
        raise RuntimeError("JRA_ENTRY_DISCOVERY_REPORT_MISSING")
    payload = json.loads(DISCOVERY.read_text(encoding="utf-8"))
    meetings = payload.get("calendarMeetings") or []
    groups = sorted({(str(row.get("date") or ""), str(row.get("venue") or "")) for row in meetings if row.get("date") and row.get("venue")})
    if not groups:
        raise RuntimeError("JRA_EXPECTED_WEEKEND_GROUPS_EMPTY")
    return groups


def main() -> None:
    expected = expected_groups()
    rows = query(
        """
        WITH per_race AS (
          SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue,
                 r.race_no AS raceNo, r.start_time_utc AS startTimeUtc,
                 SUM(CASE WHEN rr.runner_status='active' THEN 1 ELSE 0 END) AS activeRunners,
                 SUM(CASE WHEN rr.runner_status='active' AND rr.win_odds>1 THEN 1 ELSE 0 END) AS runnersWithOfficialWinOdds
          FROM rt_races r
          LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
          WHERE r.status!='finished'
            AND r.race_date>=date('now')
            AND r.race_date<=date('now','+14 days')
          GROUP BY r.race_id,r.race_date,r.venue,r.race_no,r.start_time_utc
        )
        SELECT raceDate, venue,
               COUNT(*) AS storedRaces,
               SUM(CASE WHEN activeRunners>=3 THEN 1 ELSE 0 END) AS racesWithEntries,
               SUM(CASE WHEN runnersWithOfficialWinOdds>=3 THEN 1 ELSE 0 END) AS racesWithWinOdds,
               MIN(activeRunners) AS minimumActiveRunners,
               MAX(activeRunners) AS maximumActiveRunners,
               MIN(raceNo) AS minimumRaceNo,
               MAX(raceNo) AS maximumRaceNo
        FROM per_race
        GROUP BY raceDate,venue
        ORDER BY raceDate,venue
        """
    )
    by_group = {(str(row.get("raceDate")), str(row.get("venue"))): row for row in rows}
    checks = []
    for race_date, venue in expected:
        row = by_group.get((race_date, venue))
        complete = bool(
            row
            and int(row.get("storedRaces") or 0) == 12
            and int(row.get("racesWithEntries") or 0) == 12
            and int(row.get("minimumRaceNo") or 0) == 1
            and int(row.get("maximumRaceNo") or 0) == 12
            and int(row.get("minimumActiveRunners") or 0) >= 3
        )
        checks.append({
            "raceDate": race_date,
            "venue": venue,
            "complete": complete,
            "storedRaces": int((row or {}).get("storedRaces") or 0),
            "racesWithEntries": int((row or {}).get("racesWithEntries") or 0),
            "minimumRaceNo": int((row or {}).get("minimumRaceNo") or 0),
            "maximumRaceNo": int((row or {}).get("maximumRaceNo") or 0),
            "minimumActiveRunners": int((row or {}).get("minimumActiveRunners") or 0),
        })

    total_races = sum(int(row.get("storedRaces") or 0) for row in rows)
    entry_ready = sum(int(row.get("racesWithEntries") or 0) for row in rows)
    odds_ready = sum(int(row.get("racesWithWinOdds") or 0) for row in rows)
    weekend_complete = bool(checks) and all(item["complete"] for item in checks)
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "weekendComplete": weekend_complete,
        "expectedVenueDays": len(expected),
        "expectedRaces": len(expected) * 12,
        "totalStoredFutureRaces": total_races,
        "racesWithAtLeastThreeEntries": entry_ready,
        "racesWithAtLeastThreeOfficialWinOdds": odds_ready,
        "checks": checks,
        "groups": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not weekend_complete:
        raise SystemExit("UPCOMING_WEEKEND_INCOMPLETE")


if __name__ == "__main__":
    main()
