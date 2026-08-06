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


runner = load_module("final_course_bulk_runner", RUNNER_PATH)
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


def chunks(rows, size):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def insert_values(sql_prefix, rows, columns, chunk_size):
    for batch in chunks(rows, chunk_size):
        placeholders = ",".join(["(" + ",".join(["?"] * columns) + ")"] * len(batch))
        execute(sql_prefix + placeholders, [value for row in batch for value in row])


def load_source():
    runner_rows = execute(
        """
        SELECT p.id predictionId,p.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
          pr.horse_no horseNo,pr.horse_name horseName,pr.predicted_order predictedOrder,
          pr.win_probability probability,pr.place_probability placeProbability,pr.fair_odds fairOdds,
          COALESCE(pr.current_odds,rr.win_odds) winOdds,pr.expected_value_pct expectedValuePct,
          EXISTS(SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id) selected,
          r.refund_horse_nos_json refunds
        FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id
        JOIN rt_prediction_runners pr ON pr.prediction_id=p.id
        LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
        WHERE p.model_version=? AND p.status='locked' AND r.race_date BETWEEN ? AND ?
        ORDER BY r.race_date,r.venue,r.race_no,pr.predicted_order
        """,
        [SOURCE_MODEL, DATES[0], DATES[-1]],
    )
    payout_rows = execute(
        """SELECT p.race_id raceId,p.bet_type betType,p.combination,p.payout_yen payoutYen
        FROM rt_payouts p JOIN rt_races r ON r.race_id=p.race_id
        WHERE r.race_date BETWEEN ? AND ?""",
        [DATES[0], DATES[-1]],
    )
    payout_maps = defaultdict(dict)
    for row in payout_rows:
        payout_maps[row["raceId"]][(row["betType"], canonical(row["betType"], row["combination"]))] = int(row["payoutYen"] or 0)
    grouped = {}
    for row in runner_rows:
        race = grouped.setdefault(row["raceId"], {
            "raceId": row["raceId"], "raceDate": row["raceDate"], "venue": row["venue"],
            "raceNo": int(row["raceNo"] or 0), "selected": bool(row["selected"]),
            "refunds": set(json.loads(row.get("refunds") or "[]")), "payouts": payout_maps[row["raceId"]], "runners": []
        })
        race["runners"].append({
            "horseNo": int(row["horseNo"]), "horseName": row["horseName"] or "",
            "predictedOrder": int(row["predictedOrder"] or 99),
            "probability": float(row["probability"] or 0), "placeProbability": float(row["placeProbability"] or 0),
            "fairOdds": float(row["fairOdds"] or 0), "winOdds": float(row["winOdds"] or 0),
            "expectedValuePct": float(row["expectedValuePct"] or 0),
        })
    races = sorted(grouped.values(), key=lambda row: (row["raceDate"], row["venue"], row["raceNo"]))
    selected = defaultdict(int)
    for race in races:
        selected[race["raceDate"]] += int(race["selected"])
    if len(races) != 72 or any(selected[date] != 15 for date in DATES):
        raise RuntimeError(f"FINAL_BULK_SOURCE_COUNTS:races={len(races)}:selected={dict(selected)}")
    return races


def reset_existing():
    execute("DELETE FROM rt_bets WHERE prediction_id IN (SELECT p.id FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?)", [policy.MODEL_VERSION, *DATES])
    execute("DELETE FROM rt_prediction_runners WHERE prediction_id IN (SELECT p.id FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?)", [policy.MODEL_VERSION, *DATES])
    execute("DELETE FROM rt_predictions WHERE id IN (SELECT p.id FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?)", [policy.MODEL_VERSION, *DATES])


def save_predictions(races):
    timestamp = now_iso()
    prediction_rows = [(race["raceId"], policy.MODEL_VERSION, "locked", timestamp, timestamp, timestamp, timestamp) for race in races]
    insert_values("INSERT INTO rt_predictions(race_id,model_version,status,generated_at,locked_at,source_odds_at,updated_at) VALUES ", prediction_rows, 7, 10)
    ids = {row["raceId"]: int(row["id"]) for row in execute("SELECT p.id,p.race_id raceId FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?", [policy.MODEL_VERSION, *DATES])}
    if len(ids) != 72:
        raise RuntimeError(f"FINAL_BULK_PREDICTION_IDS:{len(ids)}")
    runner_values = []
    for race in races:
        prediction_id = ids[race["raceId"]]
        for runner_row in race["runners"]:
            runner_values.append((prediction_id, runner_row["horseNo"], runner_row["horseName"], runner_row["predictedOrder"], runner_row["probability"], runner_row["placeProbability"], runner_row["fairOdds"], runner_row["winOdds"], runner_row["expectedValuePct"], "final-v5：非線形順位＋コース別買い目"))
    insert_values("INSERT INTO rt_prediction_runners(prediction_id,horse_no,horse_name,predicted_order,win_probability,place_probability,fair_odds,current_odds,expected_value_pct,explanation) VALUES ", runner_values, 10, 8)
    return ids


def save_settled_bets(races, ids):
    timestamp = now_iso()
    bet_values = []
    for race in races:
        if not race["selected"]:
            continue
        for bet in policy.build_bets(race):
            course, ticket = bet["betType"].split("｜", 1)
            horses = {int(value) for value in bet["combination"].split("-") if value}
            payout = 100 if horses & race["refunds"] else race["payouts"].get((ticket, canonical(ticket, bet["combination"])), 0)
            stake = int(bet["stakeYen"])
            returned = round(stake / 100 * payout)
            bet_values.append((ids[race["raceId"]], race["raceId"], bet["betType"], bet["combination"], stake, bet["assumedOdds"], bet["hitProbability"], bet["expectedValuePct"], "settled", returned, timestamp))
    insert_values("INSERT INTO rt_bets(prediction_id,race_id,bet_type,combination,stake_yen,assumed_odds,hit_probability,expected_value_pct,settlement_status,return_yen,settled_at) VALUES ", bet_values, 11, 7)
    return len(bet_values)


def metrics(where_sql="", params=None):
    rows = execute(f"""SELECT CASE WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト' WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード' WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム' END course,COUNT(DISTINCT b.race_id) races,COUNT(*) tickets,COALESCE(SUM(b.stake_yen),0) stakeYen,COALESCE(SUM(b.return_yen),0) returnYen,COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) hitRaces FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id JOIN rt_races r ON r.race_id=b.race_id WHERE p.model_version=? AND b.settlement_status='settled' {where_sql} GROUP BY course ORDER BY course""", [policy.MODEL_VERSION, *(params or [])])
    output = {}
    for row in rows:
        stake, returned, races = int(row["stakeYen"] or 0), int(row["returnYen"] or 0), int(row["races"] or 0)
        output[row["course"]] = {"races": races, "tickets": int(row["tickets"] or 0), "stakeYen": stake, "returnYen": returned, "profitYen": returned-stake, "roiPct": round(returned/stake*100,4) if stake else None, "hitRaces": int(row["hitRaces"] or 0), "hitRatePct": round(int(row["hitRaces"] or 0)/races*100,4) if races else None, "targetStakePerRace": policy.COURSE_TARGET_STAKES[row["course"]]}
    return output


def main():
    races = load_source()
    reset_existing()
    ids = save_predictions(races)
    ticket_count = save_settled_bets(races, ids)
    summary = {"generatedAt": now_iso(), "modelVersion": policy.MODEL_VERSION, "sourcePredictionModel": SOURCE_MODEL, "mode": "bulk-saved-ranking-final-course-policy", "courseTargetStakes": policy.COURSE_TARGET_STAKES, "sourceRaces": len(races), "selectedRaces": sum(int(race["selected"]) for race in races), "settledTickets": ticket_count, "dates": {date: metrics("AND r.race_date=?", [date]) for date in DATES}, "aggregate": metrics("AND r.race_date BETWEEN ? AND ?", list(DATES))}
    execute("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP", ["final_course_model:august", json.dumps(summary, ensure_ascii=False, separators=(",", ":"))])
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
