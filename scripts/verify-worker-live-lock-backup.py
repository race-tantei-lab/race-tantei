#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys
import time
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
D1_CLIENT = ROOT / "scripts" / "seed-worker-feature-state.py"


def load_d1_client():
    spec = importlib.util.spec_from_file_location("worker_live_lock_verify_d1", D1_CLIENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("D1_CLIENT_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules["worker_live_lock_verify_d1"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    d1 = load_d1_client()
    started = dt.datetime.now(dt.timezone.utc)
    today = dt.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    audit = None
    audit_key = f"worker_live_lock:{today}"
    for attempt in range(36):
        rows = d1.d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [audit_key])
        if rows:
            try:
                candidate = json.loads(rows[0]["value"])
                checked = dt.datetime.fromisoformat(str(candidate.get("checkedAt", "")).replace("Z", "+00:00"))
                audit = candidate
                if checked >= started - dt.timedelta(seconds=15):
                    break
            except Exception:
                pass
        print(json.dumps({"status": "WAITING_FRESH_WORKER_AUDIT", "attempt": attempt + 1, "last": audit}, ensure_ascii=False), flush=True)
        time.sleep(15)
    else:
        raise RuntimeError(f"NO_FRESH_WORKER_CRON_AUDIT:{audit}")

    assert audit is not None
    assert audit.get("status") == "ok", audit
    assert audit.get("sourceModel") == "ten-year-completed-model", audit
    assert audit.get("date") == today, audit
    assert int(audit.get("selectedRaceCount") or 0) == 15, audit
    assert int(audit.get("completeAfter") or 0) == 15, audit
    assert audit.get("errors") == [], audit
    assert audit.get("deadlineBreachRaceIds") == [], audit
    assert audit.get("incompleteRaceIds") == [], audit

    selection_rows = d1.d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [f"final_daily_selection:{today}"])
    assert selection_rows, today
    selection = json.loads(selection_rows[0]["value"])
    assert selection.get("sourceModel") == "ten-year-completed-model", selection
    assert selection.get("resultDataUsedForTargetDay") is False, selection
    selected = [str(row["raceId"]) for row in selection.get("selected") or []]
    assert len(selected) == 15 and len(set(selected)) == 15, selected

    bet_rows = d1.d1_query(
        "SELECT race_id AS raceId,course,bet_type AS betType,combination,stake_yen AS stakeYen,source_prediction_id AS sourcePredictionId FROM rt_public_bets WHERE race_id IN (SELECT value FROM json_each(?)) ORDER BY race_id,course,bet_type,combination",
        [json.dumps(selected, separators=(",", ":"))],
    )
    by_race: dict[str, list[dict]] = {}
    for row in bet_rows:
        by_race.setdefault(str(row["raceId"]), []).append(row)
    for race_id in selected:
        rows = by_race.get(race_id, [])
        assert len(rows) == 6, (race_id, len(rows))
        by_course: dict[str, list[dict]] = {}
        for row in rows:
            assert int(row["sourcePredictionId"]) == -2, row
            by_course.setdefault(str(row["course"]), []).append(row)
        assert set(by_course) == {"ライト", "スタンダード", "プレミアム"}, (race_id, by_course.keys())
        identity = None
        for course, total in {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}.items():
            course_rows = by_course[course]
            assert len(course_rows) == 2, (race_id, course, course_rows)
            assert len({row["betType"] for row in course_rows}) == 2, (race_id, course, course_rows)
            assert sum(int(row["stakeYen"]) for row in course_rows) == total, (race_id, course, course_rows)
            signature = sorted((str(row["betType"]), str(row["combination"])) for row in course_rows)
            if identity is None:
                identity = signature
            else:
                assert signature == identity, (race_id, course, signature, identity)

    print(json.dumps({
        "status": "WORKER_LIVE_LOCK_CRON_OK",
        "checkedAt": audit["checkedAt"],
        "targetDate": today,
        "selectedRaceCount": audit["selectedRaceCount"],
        "completeAfter": audit["completeAfter"],
        "deadlineBreachRaceIds": audit["deadlineBreachRaceIds"],
        "errors": audit["errors"],
        "canonicalBetRows": len(bet_rows),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
