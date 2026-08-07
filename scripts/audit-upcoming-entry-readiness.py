import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "upcoming-entry-readiness.json"
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


def main() -> None:
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
    total_races = sum(int(row.get("storedRaces") or 0) for row in rows)
    entry_ready = sum(int(row.get("racesWithEntries") or 0) for row in rows)
    odds_ready = sum(int(row.get("racesWithWinOdds") or 0) for row in rows)
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "totalStoredFutureRaces": total_races,
        "racesWithAtLeastThreeEntries": entry_ready,
        "racesWithAtLeastThreeOfficialWinOdds": odds_ready,
        "minimumFiveEntryReadyByVenueDay": all(int(row.get("racesWithEntries") or 0) >= 5 for row in rows) if rows else False,
        "minimumFiveOddsReadyByVenueDay": all(int(row.get("racesWithWinOdds") or 0) >= 5 for row in rows) if rows else False,
        "groups": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
