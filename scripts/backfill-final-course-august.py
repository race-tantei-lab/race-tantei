import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run-final-course-production.py"
OUTPUT_PATH = ROOT / "final-course-august-backfill.json"
TARGET_DATES = ("2026-08-01", "2026-08-02")


def load_runner():
    spec = importlib.util.spec_from_file_location("final_course_production_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("FINAL_BACKFILL_RUNNER_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()
policy = runner.load_policy()
prod = runner.configure_namespace(runner.load_production_namespace(), policy)
execute = prod["execute"]


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def reset_date(race_date):
    rows = execute(
        """
        SELECT p.id FROM rt_predictions p
        JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date=?
        """,
        [policy.MODEL_VERSION, race_date],
    )
    for row in rows:
        prediction_id = int(row["id"])
        execute("DELETE FROM rt_bets WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_prediction_runners WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_predictions WHERE id=?", [prediction_id])
    return len(rows)


def canonical(ticket, combination):
    values = [int(value) for value in re.findall(r"\d{1,2}", str(combination or ""))]
    if ticket in {"ワイド", "馬連", "3連複"}:
        values.sort()
    return "-".join(str(value) for value in values)


def settle_date(race_date):
    bets = execute(
        """
        SELECT b.id,b.race_id raceId,b.bet_type betType,b.combination,b.stake_yen stakeYen,
               r.refund_horse_nos_json refunds
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND p.status='locked' AND r.race_date=?
          AND b.settlement_status='pending'
        ORDER BY b.race_id,b.id
        """,
        [policy.MODEL_VERSION, race_date],
    )
    payout_cache = {}
    total_return = 0
    for bet in bets:
        race_id = bet["raceId"]
        if race_id not in payout_cache:
            payout_rows = execute(
                "SELECT bet_type betType,combination,payout_yen payoutYen FROM rt_payouts WHERE race_id=?",
                [race_id],
            )
            payout_cache[race_id] = {
                (row["betType"], canonical(row["betType"], row["combination"])): int(row["payoutYen"] or 0)
                for row in payout_rows
            }
        stored_type = str(bet["betType"] or "")
        ticket = stored_type.split("｜", 1)[1] if "｜" in stored_type else stored_type
        combination = canonical(ticket, bet["combination"])
        horses = {int(value) for value in re.findall(r"\d{1,2}", str(bet["combination"] or ""))}
        try:
            refunds = {int(value) for value in json.loads(bet.get("refunds") or "[]")}
        except (TypeError, ValueError, json.JSONDecodeError):
            refunds = set()
        stake = int(bet["stakeYen"] or 0)
        if horses & refunds:
            return_yen = stake
        else:
            payout = payout_cache[race_id].get((ticket, combination), 0)
            return_yen = round(stake / 100 * payout)
        execute(
            "UPDATE rt_bets SET settlement_status='settled',return_yen=?,settled_at=? WHERE id=?",
            [return_yen, now_iso(), int(bet["id"])],
        )
        total_return += return_yen
    return {"tickets": len(bets), "returnYen": total_return}


def metrics(where_sql="", params=None):
    params = params or []
    rows = execute(
        f"""
        SELECT CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        END course,
        COUNT(DISTINCT b.race_id) races,
        COUNT(*) tickets,
        COALESCE(SUM(b.stake_yen),0) stakeYen,
        COALESCE(SUM(b.return_yen),0) returnYen,
        COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) hitRaces
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND b.settlement_status='settled' {where_sql}
        GROUP BY course ORDER BY course
        """,
        [policy.MODEL_VERSION, *params],
    )
    result = {}
    for row in rows:
        stake = int(row["stakeYen"] or 0)
        returned = int(row["returnYen"] or 0)
        races = int(row["races"] or 0)
        result[row["course"]] = {
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
    return result


def backfill_date(all_rows, race_date):
    history_rows = [row for row in all_rows if row["raceDate"] < race_date]
    target_rows = [row for row in all_rows if row["raceDate"] == race_date]
    if not target_rows:
        raise RuntimeError(f"FINAL_BACKFILL_TARGET_ROWS_MISSING:{race_date}")
    training_races, stores = prod["build_training"](history_rows)
    target_races = prod["build_future"](target_rows, stores)
    if not target_races:
        raise RuntimeError(f"FINAL_BACKFILL_TARGET_RACES_MISSING:{race_date}")
    model = prod["fit_model"](training_races)
    prod["attach_predictions"](model, target_races)
    selected = prod["selected_race_ids"](target_races)
    removed = reset_date(race_date)
    totals = {"published": 0, "tickets": 0, "lockedSkipped": 0}
    for race in target_races:
        race["startTimeUtc"] = "2000-01-01T00:00:00Z"
        result = prod["publish_race"](race, race["raceId"] in selected)
        for key in totals:
            totals[key] += int(result[key])
    settlement = settle_date(race_date)
    return {
        "raceDate": race_date,
        "trainingCutoffExclusive": race_date,
        "trainingRaces": len(training_races),
        "targetRaces": len(target_races),
        "selectedRaces": len(selected),
        "removedExistingPredictions": removed,
        **totals,
        "settlement": settlement,
        "metrics": metrics("AND r.race_date=?", [race_date]),
    }


def save_state(summary):
    execute(
        """
        INSERT INTO rt_system_state (state_key,state_value,updated_at)
        VALUES (?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        ["final_course_model:august", json.dumps(summary, ensure_ascii=False, separators=(",", ":"))],
    )


def main():
    all_rows = prod["load_finished_rows"]()
    dates = [backfill_date(all_rows, race_date) for race_date in TARGET_DATES]
    summary = {
        "generatedAt": now_iso(),
        "modelVersion": policy.MODEL_VERSION,
        "mode": "walk-forward-august-backfill",
        "methodology": "Each date is trained only on races strictly before that date; course-specific tickets and fixed course stakes are applied before official payout settlement.",
        "courseTargetStakes": policy.COURSE_TARGET_STAKES,
        "dates": dates,
        "aggregate": metrics("AND r.race_date BETWEEN ? AND ?", [TARGET_DATES[0], TARGET_DATES[-1]]),
    }
    save_state(summary)
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
