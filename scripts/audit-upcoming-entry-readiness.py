import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "upcoming-entry-readiness.json"
DISCOVERY = ROOT / "jra-entry-anchor-discovery.json"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
JST = timezone(timedelta(hours=9))


def query(sql: str) -> list[dict]:
    request = urllib.request.Request(
        URL,
        data=json.dumps({"sql": sql, "params": []}).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def discovery_payload() -> dict:
    if not DISCOVERY.exists():
        raise RuntimeError("JRA_ENTRY_DISCOVERY_REPORT_MISSING")
    return json.loads(DISCOVERY.read_text(encoding="utf-8"))


def expected_groups(payload: dict) -> list[tuple[str, str]]:
    meetings = payload.get("calendarMeetings") or []
    groups = sorted({(str(row.get("date") or ""), str(row.get("venue") or "")) for row in meetings if row.get("date") and row.get("venue")})
    if not groups:
        raise RuntimeError("JRA_EXPECTED_WEEKEND_GROUPS_EMPTY")
    return groups


def required_entry_dates(target_dates: list[str], now_jst: datetime) -> list[str]:
    dates = sorted(set(target_dates))
    if not dates:
        return []
    weekday = now_jst.weekday()  # Mon=0 ... Sun=6
    if weekday == 4 and now_jst.hour >= 10:  # Friday: Saturday numbers are available
        return dates[:1]
    if weekday == 5 and now_jst.hour >= 10:  # Saturday: Sunday numbers are available too
        return dates
    if weekday == 6:  # Sunday: current day must be entry-ready
        return dates
    return []


def main() -> None:
    payload = discovery_payload()
    expected = expected_groups(payload)
    target_dates = [str(value) for value in (payload.get("targetDates") or []) if value]
    now_jst = datetime.now(JST)
    entry_dates = required_entry_dates(target_dates, now_jst)

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
               MAX(raceNo) AS maximumRaceNo,
               SUM(CASE WHEN startTimeUtc IS NOT NULL THEN 1 ELSE 0 END) AS racesWithStartTime
        FROM per_race
        GROUP BY raceDate,venue
        ORDER BY raceDate,venue
        """
    )
    by_group = {(str(row.get("raceDate")), str(row.get("venue"))): row for row in rows}
    checks = []
    for race_date, venue in expected:
        row = by_group.get((race_date, venue)) or {}
        stored = int(row.get("storedRaces") or 0)
        entries = int(row.get("racesWithEntries") or 0)
        min_no = int(row.get("minimumRaceNo") or 0)
        max_no = int(row.get("maximumRaceNo") or 0)
        starts = int(row.get("racesWithStartTime") or 0)
        schedule_complete = stored == 12 and min_no == 1 and max_no == 12 and starts == 12
        entry_required = race_date in entry_dates
        entry_complete = entries == 12
        checks.append({
            "raceDate": race_date,
            "venue": venue,
            "scheduleComplete": schedule_complete,
            "entryRequiredNow": entry_required,
            "entryComplete": entry_complete,
            "storedRaces": stored,
            "racesWithEntries": entries,
            "racesWithWinOdds": int(row.get("racesWithWinOdds") or 0),
            "minimumRaceNo": min_no,
            "maximumRaceNo": max_no,
            "racesWithStartTime": starts,
            "minimumActiveRunners": int(row.get("minimumActiveRunners") or 0),
        })

    schedule_complete = bool(checks) and all(item["scheduleComplete"] for item in checks)
    required_entries_complete = all(item["entryComplete"] for item in checks if item["entryRequiredNow"])
    weekend_ready = schedule_complete and required_entries_complete
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "generatedAtJst": now_jst.isoformat(),
        "weekendReady": weekend_ready,
        "scheduleComplete": schedule_complete,
        "requiredEntriesComplete": required_entries_complete,
        "targetDates": target_dates,
        "requiredEntryDatesNow": entry_dates,
        "expectedVenueDays": len(expected),
        "expectedRaces": len(expected) * 12,
        "checks": checks,
        "groups": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not weekend_ready:
        raise SystemExit("UPCOMING_WEEKEND_NOT_READY")


if __name__ == "__main__":
    main()
