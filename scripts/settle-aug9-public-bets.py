import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "collect-jra-official-odds.py"
spec = importlib.util.spec_from_file_location("settle_collector", COLLECTOR)
if spec is None or spec.loader is None:
    raise RuntimeError("COLLECTOR_IMPORT_FAILED")
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

REPORT = ROOT / "analysis-results" / "aug9-public-settlement.json"
UNORDERED = {"ワイド", "馬連", "3連複"}


def canonical(bet_type: str, combination: str) -> str:
    nums = [int(x) for x in combination.replace("→", "-").replace("、", "-").split("-") if x.strip().isdigit()]
    if bet_type in UNORDERED:
        nums.sort()
    return "-".join(str(x) for x in nums)


def main() -> None:
    rows = collector.d1_query(
        """
        SELECT b.id,b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
               b.stake_yen AS stakeYen,r.refund_horse_nos_json AS refunds
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE b.race_id LIKE '2026-08-09-%'
          AND b.settlement_status='pending'
          AND r.status='finished'
        ORDER BY b.race_id,b.course,b.id
        """
    )
    by_race = {}
    for row in rows:
        by_race.setdefault(str(row["raceId"]), []).append(row)

    settled_rows = 0
    settled_races = []
    hit_races = []
    race_summaries = []
    now = datetime.now(timezone.utc).isoformat()

    for race_id, bets in by_race.items():
        payouts = collector.d1_query(
            "SELECT bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?",
            [race_id],
        )
        if not payouts:
            raise RuntimeError(f"PAYOUTS_MISSING:{race_id}")
        payout_map = {
            f"{p['betType']}:{canonical(str(p['betType']), str(p['combination']))}": int(p['payoutYen'])
            for p in payouts
        }
        refunds = set()
        try:
            refunds = {int(x) for x in json.loads(bets[0].get("refunds") or "[]")}
        except Exception:
            refunds = set()

        course_returns = {"ライト": 0, "スタンダード": 0, "プレミアム": 0}
        course_stakes = {"ライト": 0, "スタンダード": 0, "プレミアム": 0}
        for bet in bets:
            horses = [int(x) for x in str(bet["combination"]).split("-") if x.isdigit()]
            stake = int(bet["stakeYen"])
            if any(h in refunds for h in horses):
                return_yen = stake
            else:
                key = f"{bet['betType']}:{canonical(str(bet['betType']), str(bet['combination']))}"
                return_yen = round(stake / 100 * payout_map.get(key, 0))
            collector.d1_query(
                "UPDATE rt_public_bets SET settlement_status='settled',return_yen=? WHERE id=?",
                [return_yen, int(bet["id"])],
            )
            course = str(bet["course"])
            course_returns[course] = course_returns.get(course, 0) + return_yen
            course_stakes[course] = course_stakes.get(course, 0) + stake
            settled_rows += 1

        settled_races.append(race_id)
        if any(v > 0 for v in course_returns.values()):
            hit_races.append(race_id)
        race_summaries.append({
            "raceId": race_id,
            "stakeYen": course_stakes,
            "returnYen": course_returns,
            "hit": any(v > 0 for v in course_returns.values()),
        })

    audit = collector.d1_query(
        """
        SELECT course,COUNT(DISTINCT race_id) AS settledRaces,
               COALESCE(SUM(stake_yen),0) AS stakeYen,
               COALESCE(SUM(return_yen),0) AS returnYen
        FROM rt_public_bets
        WHERE race_id LIKE '2026-08-09-%' AND settlement_status='settled'
        GROUP BY course ORDER BY course
        """
    )
    payload = {
        "settledAt": now,
        "newlySettledRaceCount": len(settled_races),
        "newlySettledBetRows": settled_rows,
        "newlySettledRaces": settled_races,
        "newlyHitRaces": hit_races,
        "races": race_summaries,
        "aug9Totals": audit,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
