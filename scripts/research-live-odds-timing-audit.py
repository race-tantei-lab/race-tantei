import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "analysis-results" / "research-live-odds-timing-audit.json"
ODDS_EDGES = [2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000]
DATE = "2026-08-09"

ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def d1_query(sql, params=None):
    payload = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        D1_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def odds_bin(value):
    value = float(value)
    index = 0
    while index < len(ODDS_EDGES) and value >= ODDS_EDGES[index]:
        index += 1
    return index


def main():
    rows = d1_query(
        """
        WITH selected AS (
          SELECT DISTINCT race_id FROM rt_public_bets WHERE race_id LIKE ?
        ), snaps AS (
          SELECT s.race_id,s.combination,
                 (s.odds_min+s.odds_max)/2.0 AS preOdds,
                 s.seconds_to_start AS secondsToStart,
                 s.captured_at_utc AS capturedAt,
                 ROW_NUMBER() OVER(
                   PARTITION BY s.race_id,s.combination
                   ORDER BY ABS(COALESCE(s.seconds_to_start,999999)-1800),s.captured_at_utc DESC
                 ) AS rn
          FROM rt_official_odds_snapshots s
          JOIN selected x ON x.race_id=s.race_id
          WHERE s.bet_type='単勝'
            AND s.seconds_to_start BETWEEN 900 AND 2700
        )
        SELECT r.race_id AS raceId,r.venue,r.race_no AS raceNo,
               u.horse_no AS horseNo,u.win_odds AS finalOdds,u.popularity AS finalPopularity,
               s.preOdds,s.secondsToStart,s.capturedAt
        FROM selected x
        JOIN rt_races r ON r.race_id=x.race_id
        JOIN rt_runners u ON u.race_id=x.race_id AND COALESCE(u.runner_status,'active')='active'
        LEFT JOIN snaps s ON s.race_id=x.race_id AND s.combination=CAST(u.horse_no AS TEXT) AND s.rn=1
        ORDER BY r.venue,r.race_no,u.horse_no
        """,
        [DATE + "-%"],
    )

    by_race = defaultdict(list)
    for row in rows:
        by_race[str(row["raceId"])].append(row)

    comparable = 0
    bin_changed = 0
    pct_moves = []
    rank_changed = 0
    race_reports = []
    for race_id, race_rows in by_race.items():
        pre_rows = [row for row in race_rows if row.get("preOdds") is not None and row.get("finalOdds") is not None]
        pre_order = sorted(pre_rows, key=lambda row: (float(row["preOdds"]), int(row["horseNo"])))
        pre_rank = {int(row["horseNo"]): index + 1 for index, row in enumerate(pre_order)}
        changed_here = 0
        compared_here = 0
        rank_changed_here = 0
        for row in pre_rows:
            pre = float(row["preOdds"])
            final = float(row["finalOdds"])
            if pre <= 0 or final <= 0:
                continue
            compared_here += 1
            comparable += 1
            if odds_bin(pre) != odds_bin(final):
                bin_changed += 1
                changed_here += 1
            pct_moves.append(abs(final - pre) / pre)
            final_pop = row.get("finalPopularity")
            if final_pop is not None and pre_rank.get(int(row["horseNo"])) != int(final_pop):
                rank_changed += 1
                rank_changed_here += 1
        sample = race_rows[0]
        race_reports.append({
            "raceId": race_id,
            "venue": sample.get("venue"),
            "raceNo": sample.get("raceNo"),
            "activeRunners": len(race_rows),
            "runnersWithComparableOdds": compared_here,
            "oddsBinChanges": changed_here,
            "popularityRankChanges": rank_changed_here,
        })

    pct_moves.sort()
    def quantile(q):
        if not pct_moves:
            return None
        index = min(len(pct_moves)-1, max(0, round((len(pct_moves)-1)*q)))
        return pct_moves[index]

    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "date": DATE,
        "mode": "read_only",
        "selectedRaceCount": len(by_race),
        "comparableRunnerCount": comparable,
        "oddsBinChangedCount": bin_changed,
        "oddsBinChangedPct": (100.0 * bin_changed / comparable) if comparable else None,
        "popularityRankChangedCount": rank_changed,
        "popularityRankChangedPct": (100.0 * rank_changed / comparable) if comparable else None,
        "absoluteOddsMovePct": {
            "median": 100.0 * quantile(0.5) if quantile(0.5) is not None else None,
            "p75": 100.0 * quantile(0.75) if quantile(0.75) is not None else None,
            "p90": 100.0 * quantile(0.9) if quantile(0.9) is not None else None,
        },
        "races": race_reports,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
