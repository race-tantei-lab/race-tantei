import importlib.util
import itertools
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

MODEL_VERSION = "v4.1.0-nonlinear-hgb-5r"
CONTEXT_START = "2024-05-01"
TRAIN_START = "2025-05-01"
COURSE_BUDGETS = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]

spec = importlib.util.spec_from_file_location(
    "nonlinear_v4_analysis",
    Path(__file__).with_name("train-nonlinear-market-blend-v4.py"),
)
if spec is None or spec.loader is None:
    raise RuntimeError("NONLINEAR_V4_MODULE_LOAD_FAILED")
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)


def month_ranges(start, end):
    year, month = map(int, start[:7].split("-"))
    end_year, end_month = map(int, end[:7].split("-"))
    while (year, month) <= (end_year, end_month):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        yield f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"
        year, month = next_year, next_month


def load_finished_rows():
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    rows = []
    for start, end in month_ranges(CONTEXT_START, tomorrow):
        rows.extend(v4.sql(
            """
            SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
                   r.surface,r.distance_m distanceM,r.track_condition trackCondition,
                   rr.horse_no horseNo,rr.frame_no frameNo,rr.horse_name horseName,
                   rr.sex_age sexAge,rr.horse_weight horseWeight,rr.weight_change weightChange,
                   rr.jockey,rr.assigned_weight assignedWeight,rr.trainer,rr.stable,
                   rr.win_odds winOdds,rr.popularity,rr.runner_status runnerStatus,
                   rs.finish_position finishPosition,rs.final3f
            FROM rt_races r
            JOIN rt_runners rr ON rr.race_id=r.race_id
            JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=rr.horse_no
            WHERE r.race_date>=? AND r.race_date<? AND r.status='finished'
            ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
            """,
            [start, end],
        ))
    return rows


def load_future_rows():
    return v4.sql(
        """
        SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
               r.surface,r.distance_m distanceM,r.track_condition trackCondition,
               r.start_time_utc startTimeUtc,
               rr.horse_no horseNo,rr.frame_no frameNo,rr.horse_name horseName,
               rr.sex_age sexAge,rr.horse_weight horseWeight,rr.weight_change weightChange,
               rr.jockey,rr.assigned_weight assignedWeight,rr.trainer,rr.stable,
               rr.win_odds winOdds,rr.popularity,rr.runner_status runnerStatus
        FROM rt_races r
        JOIN rt_runners rr ON rr.race_id=r.race_id
        WHERE r.status!='finished'
          AND r.start_time_utc IS NOT NULL
          AND datetime(r.start_time_utc)>datetime('now')
          AND datetime(r.start_time_utc)<=datetime('now','+14 days')
        ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
        """
    )


def history_features(store, key, race_date):
    return v4.get_history(store, key).features(race_date)


def make_features(row, raw, stores, market, field_size):
    race_date = raw["raceDate"]
    venue = raw["venue"]
    surface = raw.get("surface") or "unknown"
    distance = v4.number(raw.get("distanceM"))
    bucket = v4.distance_bucket(distance)
    horse = history_features(stores["horse"], row.get("horseName") or "", race_date)
    jockey = history_features(stores["jockey"], row.get("jockey") or "", race_date)
    trainer = history_features(stores["trainer"], row.get("trainer") or "", race_date)
    stable = history_features(stores["stable"], row.get("stable") or "", race_date)
    horse_course = history_features(stores["horse_course"], f'{row.get("horseName")}|{venue}|{surface}|{bucket}', race_date)
    jockey_course = history_features(stores["jockey_course"], f'{row.get("jockey")}|{surface}|{bucket}', race_date)
    trainer_course = history_features(stores["trainer_course"], f'{row.get("trainer")}|{surface}|{bucket}', race_date)
    stable_course = history_features(stores["stable_course"], f'{row.get("stable")}|{surface}|{bucket}', race_date)
    condition = str(raw.get("trackCondition") or "")
    return [
        math.log(max(market, 1e-8)), market,
        -v4.number(row.get("popularity"), field_size / 2) / field_size,
        horse[0], horse[1], -horse[2] / 12, horse[3], -horse[4] / 12, horse[5], (36 - horse[6]) / 5, -horse[7] / 180,
        jockey[0], jockey[1], trainer[0], trainer[1], stable[0], stable[1],
        horse_course[0], horse_course[1], jockey_course[0], jockey_course[1],
        trainer_course[0], trainer_course[1], stable_course[0], stable_course[1],
        (v4.number(row.get("assignedWeight")) - 55) / 6,
        (v4.number(row.get("horseWeight")) - 480) / 100,
        max(-30, min(30, v4.number(row.get("weightChange")))) / 30,
        (v4.parse_age(row.get("sexAge")) - 4) / 5,
        int("牝" in str(row.get("sexAge") or "")), int("セ" in str(row.get("sexAge") or "")),
        (v4.number(row.get("frameNo")) - 4.5) / 4.5,
        field_size / 18, distance / 3200, v4.number(raw.get("raceNo")) / 12,
        int(surface == "芝"), int(surface == "ダート"),
        int("良" in condition), int("稍" in condition), int("重" in condition and "不" not in condition), int("不" in condition),
        *[int(venue == item) for item in VENUES],
    ]


def update_stores(stores, raw, row):
    finish = int(v4.number(row.get("finishPosition")))
    if finish <= 0:
        return
    race_date = raw["raceDate"]
    venue = raw["venue"]
    surface = raw.get("surface") or "unknown"
    bucket = v4.distance_bucket(v4.number(raw.get("distanceM")))
    final3f = v4.number(row.get("final3f"))
    keys = {
        "horse": row.get("horseName") or "",
        "jockey": row.get("jockey") or "",
        "trainer": row.get("trainer") or "",
        "stable": row.get("stable") or "",
        "horse_course": f'{row.get("horseName")}|{venue}|{surface}|{bucket}',
        "jockey_course": f'{row.get("jockey")}|{surface}|{bucket}',
        "trainer_course": f'{row.get("trainer")}|{surface}|{bucket}',
        "stable_course": f'{row.get("stable")}|{surface}|{bucket}',
    }
    for store_name, key in keys.items():
        v4.get_history(stores[store_name], key).update(finish, final3f, race_date)


def group_rows(rows):
    grouped = defaultdict(list)
    metadata = {}
    for row in rows:
        grouped[row["raceId"]].append(row)
        metadata[row["raceId"]] = row
    ids = sorted(grouped, key=lambda race_id: (
        metadata[race_id]["raceDate"], metadata[race_id]["venue"], v4.number(metadata[race_id]["raceNo"])
    ))
    return grouped, metadata, ids


def build_training(rows):
    grouped, metadata, ids = group_rows(rows)
    stores = {name: {} for name in [
        "horse", "jockey", "trainer", "stable", "horse_course", "jockey_course", "trainer_course", "stable_course"
    ]}
    races = []
    for race_id in ids:
        raw = metadata[race_id]
        active = [row for row in grouped[race_id] if row.get("runnerStatus") == "active" and v4.number(row.get("winOdds")) > 1 and v4.number(row.get("finishPosition")) > 0]
        inverse = [1 / v4.number(row["winOdds"]) for row in active]
        total = sum(inverse)
        if len(active) >= 3 and total > 0 and any(int(v4.number(row.get("finishPosition"))) == 1 for row in active):
            runners = []
            for index, row in enumerate(active):
                market = inverse[index] / total
                runners.append({
                    "horseNo": int(v4.number(row.get("horseNo"))),
                    "horseName": row.get("horseName") or "",
                    "features": make_features(row, raw, stores, market, len(active)),
                    "market": market,
                    "winOdds": v4.number(row.get("winOdds")),
                    "popularity": int(v4.number(row.get("popularity"), 99)),
                    "finish": int(v4.number(row.get("finishPosition"))),
                })
            if raw["raceDate"] >= TRAIN_START:
                races.append({
                    "raceId": race_id,
                    "raceDate": raw["raceDate"],
                    "venue": raw["venue"],
                    "raceNo": int(v4.number(raw.get("raceNo"))),
                    "runners": runners,
                })
        for row in grouped[race_id]:
            update_stores(stores, raw, row)
    return races, stores


def build_future(rows, stores):
    grouped, metadata, ids = group_rows(rows)
    races = []
    for race_id in ids:
        raw = metadata[race_id]
        active = [row for row in grouped[race_id] if row.get("runnerStatus") == "active" and v4.number(row.get("winOdds")) > 1]
        inverse = [1 / v4.number(row["winOdds"]) for row in active]
        total = sum(inverse)
        if len(active) < 3 or total <= 0:
            continue
        runners = []
        for index, row in enumerate(active):
            market = inverse[index] / total
            runners.append({
                "horseNo": int(v4.number(row.get("horseNo"))),
                "horseName": row.get("horseName") or "",
                "features": make_features(row, raw, stores, market, len(active)),
                "market": market,
                "winOdds": v4.number(row.get("winOdds")),
                "popularity": int(v4.number(row.get("popularity"), 99)),
            })
        races.append({
            "raceId": race_id,
            "raceDate": raw["raceDate"],
            "venue": raw["venue"],
            "raceNo": int(v4.number(raw.get("raceNo"))),
            "startTimeUtc": raw.get("startTimeUtc"),
            "runners": runners,
        })
    return races


def fit_model(races):
    x = []
    y = []
    weights = []
    for race in races:
        field_size = len(race["runners"])
        for runner in race["runners"]:
            x.append(runner["features"])
            y.append(int(runner["finish"] == 1))
            weights.append(1 / max(1, field_size))
    if not x:
        raise RuntimeError("PRODUCTION_MODEL_NO_TRAINING_ROWS")
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=15,
        learning_rate=0.035,
        max_iter=180,
        l2_regularization=2.0,
        min_samples_leaf=40,
        random_state=42,
    )
    model.fit(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.int8), sample_weight=np.asarray(weights, dtype=np.float64))
    return model


def attach_predictions(model, races):
    for race in races:
        x = np.asarray([runner["features"] for runner in race["runners"]], dtype=np.float64)
        probabilities = model.predict_proba(x)[:, 1]
        probabilities = probabilities / max(1e-12, probabilities.sum())
        for runner, probability in zip(race["runners"], probabilities):
            runner["probability"] = float(probability)
            runner["edge"] = float(probability / max(1e-8, runner["market"]))
        race["runners"].sort(key=lambda item: item["probability"], reverse=True)
        race["disagreement"] = sum(abs(runner["probability"] - runner["market"]) for runner in race["runners"])
    return races


def selected_race_ids(races):
    groups = defaultdict(list)
    for race in races:
        groups[(race["raceDate"], race["venue"])].append(race)
    selected = set()
    for group in groups.values():
        if len(group) < 5:
            continue
        group.sort(key=lambda race: (-race["disagreement"], race["raceNo"]))
        selected.update(race["raceId"] for race in group[:5])
    return selected


def ordered_probability(order, weights):
    remaining = sum(weights.values())
    probability = 1.0
    used = set()
    for horse_no in order:
        if horse_no in used or remaining <= 0:
            return 0.0
        weight = weights.get(horse_no, 0.0)
        if weight <= 0:
            return 0.0
        probability *= weight / remaining
        remaining -= weight
        used.add(horse_no)
    return min(1.0, max(0.0, probability))


def unordered_top_three(horses, weights):
    return min(1.0, sum(ordered_probability(order, weights) for order in itertools.permutations(horses)))


def wide_probability(first, second, weights):
    return min(1.0, sum(
        unordered_top_three((first, second, third), weights)
        for third in weights
        if third not in {first, second}
    ))


def assumed_odds(probability, payout_ratio):
    return math.floor(min(2500.0, max(1.1, payout_ratio / max(1e-8, probability))) * 10) / 10


def build_bets(race):
    if len(race["runners"]) < 3:
        return []
    first, second, third = race["runners"][:3]
    model_weights = {runner["horseNo"]: runner["probability"] for runner in race["runners"]}
    market_weights = {runner["horseNo"]: runner["market"] for runner in race["runners"]}
    definitions = [
        ("ワイド", (first["horseNo"], second["horseNo"]), 0.10, wide_probability(first["horseNo"], second["horseNo"], model_weights), wide_probability(first["horseNo"], second["horseNo"], market_weights), 0.77, 0.92),
        ("ワイド", (first["horseNo"], third["horseNo"]), 0.10, wide_probability(first["horseNo"], third["horseNo"], model_weights), wide_probability(first["horseNo"], third["horseNo"], market_weights), 0.77, 0.92),
        ("3連複", (first["horseNo"], second["horseNo"], third["horseNo"]), 0.80, unordered_top_three((first["horseNo"], second["horseNo"], third["horseNo"]), model_weights), unordered_top_three((first["horseNo"], second["horseNo"], third["horseNo"]), market_weights), 0.75, 0.82),
    ]
    bets = []
    for course, budget in COURSE_BUDGETS.items():
        for bet_type, horses, share, hit_probability, market_probability, payout_ratio, reliability in definitions:
            odds = assumed_odds(market_probability, payout_ratio)
            bets.append({
                "betType": f"{course}｜{bet_type}",
                "combination": "-".join(map(str, sorted(horses))),
                "stakeYen": int(round(budget * share / 100) * 100),
                "assumedOdds": odds,
                "hitProbability": hit_probability,
                "expectedValuePct": hit_probability * odds * 100 * reliability,
            })
    return bets


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def execute(sql, params=None):
    return v4.sql(sql, params or [])


def insert_many(table_sql, rows, columns_per_row):
    if not rows:
        return
    placeholders = ",".join(["(" + ",".join(["?"] * columns_per_row) + ")"] * len(rows))
    params = [value for row in rows for value in row]
    execute(table_sql.format(values=placeholders), params)


def publish_race(race, selected):
    existing = execute(
        "SELECT id,status FROM rt_predictions WHERE race_id=? AND model_version=?",
        [race["raceId"], MODEL_VERSION],
    )
    if existing and existing[0].get("status") == "locked":
        return {"lockedSkipped": 1, "published": 0, "tickets": 0}

    generated_at = now_iso()
    start = race.get("startTimeUtc")
    minutes_to_start = 999999
    if start:
        parsed = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        minutes_to_start = (parsed - datetime.now(timezone.utc)).total_seconds() / 60
    status = "locked" if minutes_to_start <= 15 else "draft"

    execute(
        """
        INSERT INTO rt_predictions (race_id,model_version,status,generated_at,locked_at,source_odds_at,updated_at)
        VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(race_id,model_version) DO UPDATE SET
          status=excluded.status,generated_at=excluded.generated_at,
          locked_at=CASE WHEN excluded.status='locked' THEN excluded.locked_at ELSE rt_predictions.locked_at END,
          source_odds_at=excluded.source_odds_at,updated_at=CURRENT_TIMESTAMP
        WHERE rt_predictions.status!='locked'
        """,
        [race["raceId"], MODEL_VERSION, status, generated_at, generated_at if status == "locked" else None, generated_at],
    )
    prediction_rows = execute(
        "SELECT id,status FROM rt_predictions WHERE race_id=? AND model_version=?",
        [race["raceId"], MODEL_VERSION],
    )
    if not prediction_rows:
        raise RuntimeError(f'PRODUCTION_PREDICTION_ID_MISSING:{race["raceId"]}')
    prediction_id = int(prediction_rows[0]["id"])
    execute("DELETE FROM rt_prediction_runners WHERE prediction_id=?", [prediction_id])
    execute("DELETE FROM rt_bets WHERE prediction_id=? AND settlement_status='pending'", [prediction_id])

    runner_values = []
    for order, runner in enumerate(race["runners"], start=1):
        probability = runner["probability"]
        odds = runner["winOdds"] if runner["winOdds"] > 1 else None
        runner_values.append((
            prediction_id, runner["horseNo"], runner["horseName"], order, probability,
            min(0.96, max(probability, 1 - (1 - probability) ** 3)),
            1 / probability if probability > 0 else 999,
            odds,
            probability * odds * 100 if odds else None,
            "nonlinear-hgb-v4：市場確率と時系列実績の非線形予測",
        ))
    insert_many(
        """INSERT INTO rt_prediction_runners (
          prediction_id,horse_no,horse_name,predicted_order,win_probability,place_probability,
          fair_odds,current_odds,expected_value_pct,explanation
        ) VALUES {values}""",
        runner_values,
        10,
    )

    bets = build_bets(race) if selected else []
    bet_values = [(
        prediction_id, race["raceId"], bet["betType"], bet["combination"], bet["stakeYen"],
        bet["assumedOdds"], bet["hitProbability"], bet["expectedValuePct"],
    ) for bet in bets]
    insert_many(
        """INSERT INTO rt_bets (
          prediction_id,race_id,bet_type,combination,stake_yen,assumed_odds,hit_probability,expected_value_pct,settlement_status
        ) VALUES """ + ",".join(["(?,?,?,?,?,?,?,?,'pending')"] * len(bet_values)) if bet_values else "SELECT 1",
        [],
        1,
    ) if False else None
    if bet_values:
        placeholders = ",".join(["(?,?,?,?,?,?,?,?,'pending')"] * len(bet_values))
        execute(
            """INSERT INTO rt_bets (
              prediction_id,race_id,bet_type,combination,stake_yen,assumed_odds,
              hit_probability,expected_value_pct,settlement_status
            ) VALUES """ + placeholders,
            [value for row in bet_values for value in row],
        )
    return {"lockedSkipped": 0, "published": 1, "tickets": len(bets)}


def save_state(summary):
    generated_at = now_iso()
    values = {
        f"production_model:{MODEL_VERSION}:last_run": generated_at,
        f"production_model:{MODEL_VERSION}:summary": json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
    }
    for key, value in values.items():
        execute(
            """
            INSERT INTO rt_system_state (state_key,state_value,updated_at)
            VALUES (?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
            """,
            [key, value],
        )


def main():
    finished_rows = load_finished_rows()
    future_rows = load_future_rows()
    training_races, stores = build_training(finished_rows)
    future_races = build_future(future_rows, stores)
    model = fit_model(training_races)
    attach_predictions(model, future_races)
    selected = selected_race_ids(future_races)

    totals = {"published": 0, "tickets": 0, "lockedSkipped": 0}
    for race in future_races:
        result = publish_race(race, race["raceId"] in selected)
        for key in totals:
            totals[key] += result[key]

    summary = {
        "modelVersion": MODEL_VERSION,
        "trainingRaces": len(training_races),
        "futureRaces": len(future_races),
        "selectedRaces": len(selected),
        **totals,
    }
    save_state(summary)
    Path("production-nonlinear-v4.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
