import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "train-nonlinear-market-blend-v4.py"
OUTPUT = ROOT / "final-v5-august-audit.json"
MODEL = "v5.0.0-nonlinear-course-policy"
START = "2026-08-01"
END = "2026-08-02"

spec = importlib.util.spec_from_file_location("final_v5_audit_sql", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("AUDIT_SQL_MODULE_LOAD_FAILED")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
sql = module.sql


def n(value):
    return int(value or 0)


def main():
    summary = sql(
        """
        SELECT
          COUNT(DISTINCT p.id) predictions,
          COUNT(DISTINCT p.race_id) predictionRaces,
          COUNT(DISTINCT CASE WHEN b.id IS NOT NULL THEN b.race_id END) selectedRaces,
          COUNT(DISTINCT pr.id) runnerRows,
          COUNT(DISTINCT b.id) bets,
          COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END),0) settledBets,
          COALESCE(SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END),0) unsettledBets
        FROM rt_predictions p
        JOIN rt_races r ON r.race_id=p.race_id
        LEFT JOIN rt_prediction_runners pr ON pr.prediction_id=p.id
        LEFT JOIN rt_bets b ON b.prediction_id=p.id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?
        """,
        [MODEL, START, END],
    )[0]
    rows = sql(
        """
        SELECT r.race_date raceDate,
          CASE WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
               WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
               WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム' END course,
          COUNT(DISTINCT b.race_id) races,
          COUNT(*) tickets,
          COALESCE(SUM(b.stake_yen),0) stakeYen,
          COALESCE(SUM(b.return_yen),0) returnYen,
          COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) hitRaces,
          COALESCE(SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END),0) unsettledTickets
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?
        GROUP BY r.race_date,course
        ORDER BY r.race_date,course
        """,
        [MODEL, START, END],
    )
    dates = {}
    aggregate = {}
    for row in rows:
        date = row["raceDate"]
        course = row["course"]
        stake = n(row["stakeYen"])
        returned = n(row["returnYen"])
        races = n(row["races"])
        item = {
            "races": races,
            "tickets": n(row["tickets"]),
            "stakeYen": stake,
            "returnYen": returned,
            "profitYen": returned - stake,
            "roiPct": round(returned / stake * 100, 4) if stake else None,
            "hitRaces": n(row["hitRaces"]),
            "hitRatePct": round(n(row["hitRaces"]) / races * 100, 4) if races else None,
            "unsettledTickets": n(row["unsettledTickets"]),
        }
        dates.setdefault(date, {})[course] = item
        agg = aggregate.setdefault(course, {"races": 0, "tickets": 0, "stakeYen": 0, "returnYen": 0, "hitRaces": 0, "unsettledTickets": 0})
        for key in ("races", "tickets", "stakeYen", "returnYen", "hitRaces", "unsettledTickets"):
            agg[key] += item[key]
    for course, row in aggregate.items():
        row["profitYen"] = row["returnYen"] - row["stakeYen"]
        row["roiPct"] = round(row["returnYen"] / row["stakeYen"] * 100, 4) if row["stakeYen"] else None
        row["hitRatePct"] = round(row["hitRaces"] / row["races"] * 100, 4) if row["races"] else None
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modelVersion": MODEL,
        "summary": {key: n(value) for key, value in summary.items()},
        "complete": n(summary["predictionRaces"]) == 72 and n(summary["selectedRaces"]) == 30 and n(summary["bets"]) > 0 and n(summary["unsettledBets"]) == 0,
        "dates": dates,
        "aggregate": aggregate,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
