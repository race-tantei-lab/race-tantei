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
    spec = importlib.util.spec_from_file_location("worker_e2e_verify_d1", D1_CLIENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("D1_CLIENT_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules["worker_e2e_verify_d1"] = module
    spec.loader.exec_module(module)
    return module


def read_state(d1, key: str):
    rows = d1.d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [key])
    if not rows:
        return None
    return json.loads(rows[0]["value"])


def checked_at(payload):
    if not payload:
        return None
    raw = str(payload.get("checkedAt") or "")
    if not raw:
        return None
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def main() -> int:
    d1 = load_d1_client()
    started = dt.datetime.now(dt.timezone.utc)
    today = dt.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    selection_audit = live_audit = None

    for attempt in range(40):
        selection_audit = read_state(d1, f"worker_selection:{today}")
        live_audit = read_state(d1, f"worker_live_lock:{today}")
        sel_time = checked_at(selection_audit)
        live_time = checked_at(live_audit)
        fresh_sel = sel_time is not None and sel_time >= started - dt.timedelta(seconds=15)
        fresh_live = live_time is not None and live_time >= started - dt.timedelta(seconds=15)
        if fresh_sel and fresh_live:
            break
        print(json.dumps({
            "status": "WAITING_NATURAL_WORKER_CRON",
            "attempt": attempt + 1,
            "started": started.isoformat(),
            "selectionCheckedAt": selection_audit.get("checkedAt") if selection_audit else None,
            "liveCheckedAt": live_audit.get("checkedAt") if live_audit else None,
        }, ensure_ascii=False), flush=True)
        time.sleep(15)
    else:
        raise RuntimeError(f"NO_FRESH_END_TO_END_CRON:selection={selection_audit}:live={live_audit}")

    assert selection_audit is not None and live_audit is not None
    assert selection_audit.get("status") in {"loaded", "frozen"}, selection_audit
    assert selection_audit.get("sourceModel") == "ten-year-completed-model", selection_audit
    assert selection_audit.get("date") == today, selection_audit
    assert int(selection_audit.get("selectedRaceCount") or 0) == 15, selection_audit
    assert selection_audit.get("resultDataUsedForTargetDay") is False, selection_audit
    venue_counts = selection_audit.get("selectedVenueCounts") or {}
    assert len(venue_counts) == 3 and all(int(v) == 5 for v in venue_counts.values()), selection_audit

    assert live_audit.get("status") == "ok", live_audit
    assert live_audit.get("sourceModel") == "ten-year-completed-model", live_audit
    assert live_audit.get("date") == today, live_audit
    assert int(live_audit.get("selectedRaceCount") or 0) == 15, live_audit
    assert int(live_audit.get("completeAfter") or 0) == 15, live_audit
    assert live_audit.get("incompleteRaceIds") == [], live_audit
    assert live_audit.get("deadlineBreachRaceIds") == [], live_audit
    assert live_audit.get("errors") == [], live_audit

    selection = read_state(d1, f"final_daily_selection:{today}")
    assert selection, today
    assert selection.get("sourceModel") == "ten-year-completed-model", selection
    assert selection.get("resultDataUsedForTargetDay") is False, selection
    selected = [str(row.get("raceId") or "") for row in selection.get("selected") or []]
    assert len(selected) == 15 and len(set(selected)) == 15 and all(selected), selected
    audit_ids = [str(x) for x in selection_audit.get("selectedRaceIds") or []]
    assert audit_ids == selected, (audit_ids, selected)

    rows = d1.d1_query(
        "SELECT race_id AS raceId,course,bet_type AS betType,combination,stake_yen AS stakeYen,source_prediction_id AS sourcePredictionId FROM rt_public_bets WHERE race_id IN (SELECT value FROM json_each(?)) ORDER BY race_id,course,bet_type,combination",
        [json.dumps(selected, separators=(",", ":"))],
    )
    by_race: dict[str, list[dict]] = {}
    for row in rows:
        by_race.setdefault(str(row["raceId"]), []).append(row)
    budgets = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
    for race_id in selected:
        race_rows = by_race.get(race_id, [])
        assert len(race_rows) == 6, (race_id, len(race_rows))
        by_course: dict[str, list[dict]] = {}
        for row in race_rows:
            assert int(row["sourcePredictionId"]) == -2, row
            by_course.setdefault(str(row["course"]), []).append(row)
        assert set(by_course) == set(budgets), (race_id, by_course.keys())
        identity = None
        for course, budget in budgets.items():
            course_rows = by_course[course]
            assert len(course_rows) == 2, (race_id, course, course_rows)
            assert len({str(row["betType"]) for row in course_rows}) == 2, (race_id, course, course_rows)
            assert sum(int(row["stakeYen"]) for row in course_rows) == budget, (race_id, course, course_rows)
            signature = sorted((str(row["betType"]), str(row["combination"])) for row in course_rows)
            if identity is None:
                identity = signature
            else:
                assert signature == identity, (race_id, course, signature, identity)

    print(json.dumps({
        "status": "WORKER_END_TO_END_CRON_OK",
        "targetDate": today,
        "selectionCheckedAt": selection_audit["checkedAt"],
        "liveCheckedAt": live_audit["checkedAt"],
        "selectionStatus": selection_audit["status"],
        "selectedRaceCount": len(selected),
        "completeAfter": live_audit["completeAfter"],
        "deadlineBreachRaceIds": live_audit["deadlineBreachRaceIds"],
        "errors": live_audit["errors"],
        "canonicalBetRows": len(rows),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
