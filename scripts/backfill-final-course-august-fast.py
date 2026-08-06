import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run-final-course-production.py"
OUTPUT_PATH = ROOT / "final-course-august-backfill.json"
SOURCE_MODEL = "v4.1.0-nonlinear-hgb-5r"
DATES = ("2026-08-01", "2026-08-02")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module("final_course_fast_runner", RUNNER_PATH)
policy = runner.load_policy()
prod = runner.configure_namespace(runner.load_production_namespace(), policy)
execute = prod["execute"]


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(ticket, combination):
    values = [int(value) for value in re.findall(r"\d{1,2}", str(combination or ""))]
    if ticket in {"ワイド", "馬連", "3連複"}:
        values.sort()
    return "-".join(str(value) for value in values)


def reset_final_predictions():
    rows = execute(
        """SELECT p.id FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?""",
        [policy.MODEL_VERSION, DATES[0], DATES[-1]],
    )
    for row in rows:
        prediction_id = int(row["id"])
        execute("DELETE FROM rt_bets WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_prediction_runners WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_predictions WHERE id=?", [prediction_id])
    return len(rows)


def load_source_races():
    rows = execute(
        """
        SELECT p.id predictionId,p.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
          r.start_time_utc startTimeUtc,pr.horse_no horseNo,pr.horse_name horseName,
          pr.predicted_order predictedOrder,pr.win_probability probability,
          COALESCE(pr.current_odds,rr.win_odds) winOdds,
          EXISTS(SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id) selected
        FROM rt_predictions p
        JOIN rt_races r ON r.race_id=p.race_id
        JOIN rt_prediction_runners pr ON pr.prediction_id=p.id
        LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
        WHERE p.model_version=? AND p.status='locked' AND r.race_date BETWEEN ? AND ?
        ORDER BY r.race_date,r.venue,r.race_no,pr.predicted_order
        """,
        [SOURCE_MODEL, DATES[0], DATES[-1]],
    )
    grouped = {}
    for row in rows:
        race_id = row["raceId"]
        race = grouped.setdefault(race_id, {
            "raceId": race_id,
            "raceDate": row["raceDate"],
            "venue": row["venue"],
            "raceNo": int(row["raceNo"] or 0),
            "startTimeUtc": "2000-01-01T00:00:00Z",
            "selected": bool(row["selected"]),
            "runners": [],
        })
        race["runners"].append({
            "horseNo": int(row["horseNo"]),
            "horseName": row["horseName"] or "",
            "predictedOrder": int(row["predictedOrder"] or 99),
            "probability": float(row["probability"] or 0),
            "winOdds": float(row["winOdds"] or 0),
        })
    races = sorted(grouped.values(), key=lambda race: (race["raceDate"], race["venue"], race["raceNo"]))
    if len(races) != 72:
        raise RuntimeError(f"FINAL_FAST_SOURCE_RACE_COUNT:{len(races)}")
    selected_counts = defaultdict(int)
    for race in races:
        if race["selected"]:
            selected_counts[race["raceDate"]] += 1
    for race_date in DATES:
        if selected_counts[race_date] != 15:
            raise RuntimeError(f"FINAL_FAST_SELECTED_COUNT:{race_date}:{selected_counts[race_date]}")
    return races


def settle():
    bets = execute(
        """
        SELECT b.id,b.race_id raceId,b.bet_type betType,b.combination,b.stake_yen stakeYen,
               r.refund_horse_nos_json refunds
        FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ? AND b.settlement_status='pending'
        ORDER BY b.race_id,b.id
        """,
        [policy.MODEL_VERSION, DATES[0], DATES[-1]],
    )
    payout_cache = {}
    for bet in bets:
        race_id = bet["raceId"]
        if race_id not in payout_cache:
            payout_cache[race_id] = {
                (row["betType"], canonical(row["betType"], row["combination"])): int(row["payoutYen"] or 0)
                for row in execute("SELECT bet_type betType,combination,payout_yen payoutYen FROM rt_payouts WHERE race_id=?", [race_id])
            }
        ticket = str(bet["betType"]).split("｜", 1)[-1]
        horses = {int(value) for value in re.findall(r"\d{1,2}", str(bet["combination"] or ""))}
        try:
            refunds = {int(value) for value in json.loads(bet.get("refunds") or "[]")}
        except Exception:
            refunds = set()
        stake = int(bet["stakeYen"] or 0)
        payout = 100 if horses & refunds else payout_cache[race_id].get((ticket, canonical(ticket, bet["combination"])), 0)
        returned = round(stake / 100 * payout)
        execute("UPDATE rt_bets SET settlement_status='settled',return_yen=?,settled_at=? WHERE id=?", [returned, now_iso(), int(bet["id"])])
    return len(bets)


def metrics(extra_where="", params=None):
    params = params or []
    rows = execute(
        f"""
        SELECT CASE WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム' END course,
          COUNT(DISTINCT b.race_id) races,COUNT(*) tickets,
          COALESCE(SUM(b.stake_yen),0) stakeYen,COALESCE(SUM(b.return_yen),0) returnYen,
          COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) hitRaces
        FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND b.settlement_status='settled' {extra_where}
        GROUP BY course ORDER BY course
        """,
        [policy.MODEL_VERSION, *params],
    )
    output = {}
    for row in rows:
        stake = int(row["stakeYen"] or 0)
        returned = int(row["returnYen"] or 0)
        races = int(row["races"] or 0)
        output[row["course"]] = {
            "races": races,
            "tickets": int(row["tickets"] or 0),
            "stakeYen": stake,
            "returnYen": returned,
            "profitYen": returned - stake,
            "roiPct": round(returned / stake * 100, 4) if stake else None,
            "hitRaces": int(row["hitRaces"] or 0),
            "hitRatePct": round(int(row["hitRaces"] or 0) / races * 100, 4) if races else None,
            "targetStakePerRace": policy.COURSE_TARGET_STAKES[row["course"]],
        }
    return output


def main():
    races = load_source_races()
    removed = reset_final_predictions()
    totals = {"published": 0, "tickets": 0, "lockedSkipped": 0}
    for race in races:
        result = prod["publish_race"](race, race["selected"])
        for key in totals:
            totals[key] += int(result[key])
    settled = settle()
    summary = {
        "generatedAt": now_iso(),
        "modelVersion": policy.MODEL_VERSION,
        "sourcePredictionModel": SOURCE_MODEL,
        "mode": "saved-walk-forward-ranking-plus-final-course-policy",
        "methodology": "The saved Aug 1-2 walk-forward v4 rankings and identical 5R selections are reused; only the final distinct course ticket policies are generated and settled against official payouts.",
        "courseTargetStakes": policy.COURSE_TARGET_STAKES,
        "sourceRaces": len(races),
        "selectedRaces": sum(1 for race in races if race["selected"]),
        "removedExistingFinalPredictions": removed,
        **totals,
        "settledTickets": settled,
        "dates": {date: metrics("AND r.race_date=?", [date]) for date in DATES},
        "aggregate": metrics("AND r.race_date BETWEEN ? AND ?", [DATES[0], DATES[-1]]),
    }
    execute(
        """INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP""",
        ["final_course_model:august", json.dumps(summary, ensure_ascii=False, separators=(",", ":"))],
    )
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
