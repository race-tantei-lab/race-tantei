#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import pathlib
import sys

import lightgbm as lgb
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
RACE_ID = os.environ.get("RECOVERY_RACE_ID", "2026-08-16-chukyo-01")
RACE_DATE = os.environ.get("RECOVERY_RACE_DATE", "2026-08-16")
CUTOFF_UTC = os.environ.get("RECOVERY_CUTOFF_UTC", "2026-08-16T00:35:00Z")
MODEL_VERSION = "ten-year-completed-model"
COURSE_STAKES = {"ライト": [1000, 1000], "スタンダード": [2500, 2500], "プレミアム": [5000, 5000]}
BET_TYPES = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def predeadline_odds(collector) -> tuple[dict[tuple[str, str, str], float], dict[str, str]]:
    rows = collector.d1_query(
        """
        WITH latest AS (
          SELECT bet_type,MAX(captured_at_utc) AS captured_at_utc
          FROM rt_official_odds_snapshots
          WHERE race_id=? AND datetime(captured_at_utc)<=datetime(?)
          GROUP BY bet_type
        )
        SELECT s.bet_type AS betType,s.combination,s.odds_min AS oddsMin,s.odds_max AS oddsMax,
               s.captured_at_utc AS capturedAtUtc,s.source_url AS sourceUrl
        FROM rt_official_odds_snapshots s
        JOIN latest x ON x.bet_type=s.bet_type AND x.captured_at_utc=s.captured_at_utc
        WHERE s.race_id=?
        ORDER BY s.bet_type,s.combination
        """,
        [RACE_ID, CUTOFF_UTC, RACE_ID],
    )
    by_type: dict[str, int] = {}
    captured: dict[str, str] = {}
    odds: dict[tuple[str, str, str], float] = {}
    for row in rows:
        bet_type = str(row.get("betType") or "")
        combo = str(row.get("combination") or "")
        if bet_type not in BET_TYPES or not combo:
            continue
        lo = float(row.get("oddsMin") or 0)
        hi = float(row.get("oddsMax") or 0)
        value = (lo + hi) / 2.0
        if not math.isfinite(value) or value <= 0:
            continue
        odds[(RACE_ID, bet_type, combo)] = value
        by_type[bet_type] = by_type.get(bet_type, 0) + 1
        captured[bet_type] = str(row.get("capturedAtUtc") or "")
    missing = [bet_type for bet_type in BET_TYPES if by_type.get(bet_type, 0) == 0]
    if missing:
        raise RuntimeError(f"PREDEADLINE_OFFICIAL_ODDS_MISSING:{RACE_ID}:{missing}:{by_type}")
    for value in captured.values():
        if parse_utc(value) > parse_utc(CUTOFF_UTC):
            raise RuntimeError(f"POST_CUTOFF_ODDS_REJECTED:{value}>{CUTOFF_UTC}")
    return odds, captured


def load_predeadline_bodyweight(collector) -> dict[int, tuple[int, int | None]] | None:
    rows = collector.d1_query(
        "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
        [f"worker_bodyweight_snapshot:{RACE_ID}"],
    )
    if not rows or not rows[0].get("value"):
        return None
    try:
        snapshot = json.loads(str(rows[0]["value"]))
    except Exception:
        return None
    fetched_at = str(snapshot.get("fetchedAt") or "")
    if not fetched_at or parse_utc(fetched_at) > parse_utc(CUTOFF_UTC):
        return None
    out: dict[int, tuple[int, int | None]] = {}
    for row in snapshot.get("activeRunners") or []:
        horse_no = int(row.get("horseNo") or 0)
        weight = int(row.get("horseWeight") or 0)
        change = row.get("weightChange")
        if horse_no > 0 and 250 <= weight <= 700:
            out[horse_no] = (weight, None if change is None else int(change))
    return out or None


def main() -> None:
    cutoff = parse_utc(CUTOFF_UTC)
    if cutoff >= dt.datetime.now(dt.timezone.utc):
        raise RuntimeError("RECOVERY_CUTOFF_MUST_BE_IN_PAST")

    collector = load(ROOT / "scripts" / "collect-jra-official-odds.py", "recovery_collector")
    core = load(ROOT / "scripts" / "ten-year-production-core.py", "recovery_core")
    learning = load(ROOT / "scripts" / "live-recency-learning.py", "recovery_learning")
    generator = load(ROOT / "scripts" / "generate-ten-year-live-bets.py", "recovery_generator")

    selection_rows = collector.d1_query(
        "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
        [f"final_daily_selection:{RACE_DATE}"],
    )
    if not selection_rows or not selection_rows[0].get("value"):
        raise RuntimeError("RECOVERY_SELECTION_MISSING")
    selection = json.loads(str(selection_rows[0]["value"]))
    if selection.get("sourceModel") != MODEL_VERSION or selection.get("resultDataUsedForTargetDay") is not False:
        raise RuntimeError("RECOVERY_SELECTION_INVALID")
    selected_ids = {str(row.get("raceId") or "") for row in selection.get("selected") or []}
    if RACE_ID not in selected_ids:
        raise RuntimeError(f"RECOVERY_RACE_NOT_SELECTED:{RACE_ID}")

    existing = collector.d1_query("SELECT COUNT(*) AS n FROM rt_public_bets WHERE race_id=?", [RACE_ID])
    if int(existing[0].get("n") or 0) != 0:
        print(json.dumps({"status": "already_has_bets", "raceId": RACE_ID}, ensure_ascii=False))
        return

    odds, odds_captured = predeadline_odds(collector)
    bodyweights = load_predeadline_bodyweight(collector)

    cfg = core.load_config()
    state = core.load_feature_state()
    delta = core.delta_bundles(collector, state["throughDate"], RACE_DATE)
    core.advance_feature_state(state, delta)
    target_map = {str(bundle["race"]["raceId"]): bundle for bundle in core.target_bundles(collector, RACE_DATE)}
    bundle = target_map.get(RACE_ID)
    if bundle is None:
        raise RuntimeError(f"RECOVERY_TARGET_RACE_MISSING:{RACE_ID}")

    runners = [dict(row) for row in bundle.get("runners") or [] if (row.get("runnerStatus") or "active") == "active"]
    runners.sort(key=lambda row: int(row.get("horseNo") or 0))
    if len(runners) < 3:
        raise RuntimeError(f"RECOVERY_TOO_FEW_RUNNERS:{len(runners)}")

    # Do not permit a post-cutoff runner market snapshot to enter the model.
    # Bodyweight is restored only from a snapshot explicitly timestamped at or before T-15.
    for runner in runners:
        horse_no = int(runner.get("horseNo") or 0)
        runner["winOdds"] = None
        runner["popularity"] = None
        if bodyweights and horse_no in bodyweights:
            runner["horseWeight"], runner["weightChange"] = bodyweights[horse_no]
        else:
            runner["horseWeight"] = None
            runner["weightChange"] = None

    features = list(cfg["runnerProbabilityModel"]["features"])
    booster = lgb.Booster(model_file=str(core.MODEL_PATH))
    if booster.num_feature() != len(features):
        raise RuntimeError("RECOVERY_MODEL_FEATURE_COUNT_INVALID")
    feature_rows = [core.ml_feature_row(state, bundle["race"], runner, len(runners)) for runner in runners]
    matrix = np.asarray([[float(row[name]) for name in features] for row in feature_rows], dtype=np.float64)
    raw = np.asarray(booster.predict(matrix), dtype=np.float64)
    if raw.shape != (len(runners),) or not np.all(np.isfinite(raw)) or np.any(raw <= 0):
        raise RuntimeError("RECOVERY_MODEL_PREDICTION_INVALID")
    base_weights = raw / raw.sum()

    try:
        runner_rows, bet_rows = learning.load_recent_learning_rows(collector, RACE_DATE, CUTOFF_UTC)
        bet_learning = learning.build_bet_learning(bet_rows, CUTOFF_UTC, RACE_DATE)
        factors, runner_detail, runner_audit = learning.build_runner_learning(
            runner_rows, bundle["race"], runners, CUTOFF_UTC, RACE_DATE
        )
        learning_error = None
    except Exception as exc:
        factors = [1.0] * len(runners)
        runner_detail = [{"horseNo": int(row["horseNo"]), "factor": 1.0} for row in runners]
        runner_audit = {"runnerHistoryRaces": 0, "sameDayFinishedRaces": 0, "previousDayFinishedRaces": 0, "last7DaysFinishedRaces": 0}
        bet_learning = {"buckets": {}, "audit": {"betHistoryRaces": 0, "sameDaySettledBetRaces": 0, "previousDaySettledBetRaces": 0, "last7DaysSettledBetRaces": 0}}
        learning_error = f"{type(exc).__name__}:{exc}"

    adjusted = np.asarray([base_weights[i] * float(factors[i]) for i in range(len(runners))], dtype=np.float64)
    weights = adjusted / adjusted.sum()
    chosen = generator.choose_two(
        core,
        learning,
        RACE_ID,
        runners,
        weights,
        odds,
        bet_learning,
        str(bundle["race"].get("venue") or ""),
    )
    if len(chosen) != 2 or len({ticket["betType"] for ticket in chosen}) != 2:
        raise RuntimeError("RECOVERY_TWO_TICKETS_INVALID")

    course_bets = []
    for course, stakes in COURSE_STAKES.items():
        for index, ticket in enumerate(chosen):
            course_bets.append({
                "course": course,
                "betType": ticket["betType"],
                "combination": ticket["combination"],
                "stakeYen": stakes[index],
                "assumedOdds": float(ticket["officialOdds"]),
            })

    # Logical lock remains the original T-15 deadline. The separate recovery audit below
    # preserves the actual time at which this one-off repair was inserted.
    locked_at = CUTOFF_UTC
    for bet in course_bets:
        collector.d1_query(
            """
            INSERT INTO rt_public_bets(
              race_id,course,bet_type,combination,stake_yen,assumed_odds,
              return_yen,settlement_status,locked_at,source_prediction_id
            ) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)
            """,
            [RACE_ID, bet["course"], bet["betType"], bet["combination"], int(bet["stakeYen"]), round(float(bet["assumedOdds"]), 6), locked_at],
        )

    saved = collector.d1_query(
        "SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,locked_at AS lockedAt,source_prediction_id AS sourcePredictionId FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination",
        [RACE_ID],
    )
    if len(saved) != 6 or any(int(row.get("sourcePredictionId") or 0) != -2 for row in saved):
        raise RuntimeError(f"RECOVERY_PUBLIC_BET_VERIFY_FAILED:{saved}")

    recovered_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    audit = {
        "status": "predeadline_recovery",
        "raceId": RACE_ID,
        "sourceModel": MODEL_VERSION,
        "intendedDeadlineAt": CUTOFF_UTC,
        "recoveredAt": recovered_at,
        "targetRaceResultUsed": False,
        "postCutoffOddsUsed": False,
        "postCutoffBodyWeightUsed": False,
        "bodyWeightSnapshotUsed": bool(bodyweights),
        "oddsCapturedAtByBetType": odds_captured,
        "onlineLearning": {**runner_audit, **(bet_learning.get("audit") or {}), "cutoffUtc": CUTOFF_UTC, "error": learning_error},
        "runnerRecencyFactors": runner_detail,
        "tickets": chosen,
    }
    collector.d1_query(
        """
        INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        [f"worker_live_final:{RACE_ID}", json.dumps({**audit, "status": "locked", "lockedAt": CUTOFF_UTC, "finalizedFrom": "predeadline_recovery"}, ensure_ascii=False)],
    )
    collector.d1_query(
        """
        INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        [f"recovery_predeadline:{RACE_ID}", json.dumps(audit, ensure_ascii=False)],
    )

    out = ROOT / "analysis-results" / f"predeadline-recovery-{RACE_ID}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "recovered",
        "raceId": RACE_ID,
        "cutoffUtc": CUTOFF_UTC,
        "tickets": [{"betType": row["betType"], "combination": row["combination"], "officialOdds": row["officialOdds"]} for row in chosen],
        "bodyWeightSnapshotUsed": bool(bodyweights),
        "oddsCapturedAtByBetType": odds_captured,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
