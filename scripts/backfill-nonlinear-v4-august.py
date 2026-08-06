import json
import re
from datetime import datetime, timezone
from pathlib import Path

PRODUCTION_SOURCE = Path(__file__).with_name("publish-nonlinear-v4-production.py")
TARGET_DATES = ["2026-08-01", "2026-08-02"]


def load_production_namespace():
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")
    needle = "v4 = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(v4)"
    replacement = (
        "v4 = importlib.util.module_from_spec(spec)\n"
        "import sys\n"
        "sys.modules[spec.name] = v4\n"
        "spec.loader.exec_module(v4)"
    )
    if needle not in source:
        raise RuntimeError("AUGUST_BACKFILL_PRODUCTION_IMPORT_PATCH_TARGET_MISSING")
    source = source.replace(needle, replacement, 1)
    namespace = {"__name__": "production_v4_backfill_module", "__file__": str(PRODUCTION_SOURCE)}
    exec(compile(source, str(PRODUCTION_SOURCE), "exec"), namespace, namespace)
    return namespace


prod = load_production_namespace()
MODEL_VERSION = prod["MODEL_VERSION"]
execute = prod["execute"]


def d1_safe_insert_many(table_sql, rows, columns_per_row):
    """Keep each D1 request below the bound-parameter ceiling."""
    if not rows:
        return
    chunk_size = max(1, 80 // columns_per_row)
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        placeholders = ",".join(
            ["(" + ",".join(["?"] * columns_per_row) + ")"] * len(chunk)
        )
        params = [value for row in chunk for value in row]
        execute(table_sql.format(values=placeholders), params)


# publish_race resolves globals dynamically from this namespace.
prod["insert_many"] = d1_safe_insert_many


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def reset_date(race_date):
    rows = execute(
        """
        SELECT p.id
        FROM rt_predictions p
        JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date=?
        """,
        [MODEL_VERSION, race_date],
    )
    for row in rows:
        prediction_id = int(row["id"])
        execute("DELETE FROM rt_bets WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_prediction_runners WHERE prediction_id=?", [prediction_id])
        execute("DELETE FROM rt_predictions WHERE id=?", [prediction_id])
    return len(rows)


def canonical_combination(ticket, combination):
    numbers = [int(value) for value in re.findall(r"\d{1,2}", combination or "")]
    if ticket in {"ワイド", "馬連", "3連複"}:
        numbers.sort()
    return "-".join(str(value) for value in numbers)


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
        [MODEL_VERSION, race_date],
    )
    payout_cache = {}
    settled = 0
    returned = 0
    for bet in bets:
        race_id = bet["raceId"]
        if race_id not in payout_cache:
            payout_rows = execute(
                "SELECT bet_type betType,combination,payout_yen payoutYen FROM rt_payouts WHERE race_id=?",
                [race_id],
            )
            payout_cache[race_id] = {
                (row["betType"], canonical_combination(row["betType"], row["combination"])): int(row["payoutYen"] or 0)
                for row in payout_rows
            }
        stored_type = str(bet["betType"] or "")
        ticket = stored_type.split("｜", 1)[1] if "｜" in stored_type else stored_type
        combination = canonical_combination(ticket, str(bet["combination"] or ""))
        horses = {int(value) for value in re.findall(r"\d{1,2}", str(bet["combination"] or ""))}
        try:
            refunds = {int(value) for value in json.loads(bet.get("refunds") or "[]")}
        except (TypeError, ValueError):
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
        settled += 1
        returned += return_yen
    return {"tickets": settled, "returnYen": returned}


def date_metrics(race_date):
    rows = execute(
        """
        SELECT CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        END course,
        COUNT(DISTINCT b.race_id) races,
        COUNT(*) tickets,
        COALESCE(SUM(b.stake_yen),0) stakeYen,
        COALESCE(SUM(b.return_yen),0) returnYen,
        COALESCE(SUM(CASE WHEN b.return_yen>0 THEN 1 ELSE 0 END),0) hits
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND r.race_date=? AND b.settlement_status='settled'
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
        GROUP BY course
        ORDER BY course
        """,
        [MODEL_VERSION, race_date],
    )
    result = []
    for row in rows:
        stake = int(row["stakeYen"] or 0)
        returns = int(row["returnYen"] or 0)
        result.append({
            "course": row["course"],
            "races": int(row["races"] or 0),
            "tickets": int(row["tickets"] or 0),
            "stakeYen": stake,
            "returnYen": returns,
            "profitYen": returns - stake,
            "roiPct": returns / stake * 100 if stake else None,
            "ticketHitRatePct": int(row["hits"] or 0) / int(row["tickets"] or 1) * 100,
        })
    return result


def backfill_date(all_rows, race_date):
    history_rows = [row for row in all_rows if row["raceDate"] < race_date]
    target_rows = [row for row in all_rows if row["raceDate"] == race_date]
    if not target_rows:
        raise RuntimeError(f"AUGUST_BACKFILL_TARGET_ROWS_MISSING:{race_date}")

    training_races, stores = prod["build_training"](history_rows)
    target_races = prod["build_future"](target_rows, stores)
    if not target_races:
        raise RuntimeError(f"AUGUST_BACKFILL_TARGET_RACES_MISSING:{race_date}")
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
        "metrics": date_metrics(race_date),
    }


def save_state(summary):
    key = f"production_model:{MODEL_VERSION}:august_backfill"
    execute(
        """
        INSERT INTO rt_system_state (state_key,state_value,updated_at)
        VALUES (?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        [key, json.dumps(summary, ensure_ascii=False, separators=(",", ":"))],
    )


def main():
    all_rows = prod["load_finished_rows"]()
    results = [backfill_date(all_rows, race_date) for race_date in TARGET_DATES]
    summary = {
        "modelVersion": MODEL_VERSION,
        "mode": "retrospective-v4-backfill",
        "methodology": "Each date is trained only on races strictly before that date; final stored market odds are used for the historical replay.",
        "includedInAugustAggregate": True,
        "generatedAt": now_iso(),
        "dates": results,
    }
    save_state(summary)
    Path("production-nonlinear-v4-august-backfill.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
