#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "run-auto-final-live.py"
CANONICAL_PATH = ROOT / "scripts" / "run-ten-year-auto-final-live.py"
RECOVERY_OPEN_SECONDS = 15 * 60


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    base = load(BASE_PATH, "resilient_recovery_base")
    canonical = load(CANONICAL_PATH, "resilient_recovery_canonical")

    base.validate_selection = canonical.validate_selection
    base.generate_dynamic_selection = canonical.generate_selection
    base.run_learned_generator = canonical.run_generator
    base.verify_locked = canonical.verify_locked
    base.COURSE_BUDGETS = canonical.COURSE_BUDGETS

    collector = base.collector_module()
    now = dt.datetime.now(dt.timezone.utc)
    date = base.now_jst().date().isoformat()
    selection_path = pathlib.Path("/tmp") / f"resilient-race-tantei-selection-{date}.json"
    payload, selection_state = base.freeze_or_load_selection(collector, date, selection_path)
    if payload is None:
        print(json.dumps({"status": selection_state, "date": date, "recoveredRaceIds": []}, ensure_ascii=False))
        return

    ids, venues = canonical.validate_selection(payload)
    starts = base.selected_timing(collector, ids)
    if len(starts) != len(ids):
        raise RuntimeError(f"RESILIENT_START_TIMES_MISSING:{len(starts)}/{len(ids)}")
    already = base.locked_races(collector, ids)
    seconds = {race_id: (starts[race_id] - now).total_seconds() for race_id in ids}

    started_missing = sorted(
        race_id for race_id in ids
        if race_id not in already and seconds[race_id] <= 0
    )
    recoverable = sorted(
        (
            race_id for race_id in ids
            if race_id not in already and 0 < seconds[race_id] <= RECOVERY_OPEN_SECONDS
        ),
        key=lambda race_id: starts[race_id],
    )

    report = {
        "status": "waiting_recovery_window",
        "date": date,
        "selectionState": selection_state,
        "venues": venues,
        "selectedRaceCount": len(ids),
        "alreadyLockedRaceCount": len(already),
        "startedMissingRaceIds": started_missing,
        "recoverableRaceIds": recoverable,
        "recoveredRaceIds": [],
        "failedRaceIds": [],
    }

    for race_id in recoverable:
        try:
            # Fetch official odds for this exact race now. Running one race at a time
            # prevents one bad target from suppressing every other imminent race.
            odds_report = base.collect_official_odds([race_id])
            out_path = ROOT / "analysis-results" / f"resilient-live-recovery-{date}-{race_id}.json"
            out_path.parent.mkdir(exist_ok=True)
            canonical.run_generator(date, selection_path, out_path)
            canonical.verify_locked(collector, [race_id])
            report["recoveredRaceIds"].append(race_id)
            print(json.dumps({
                "event": "RESILIENT_LIVE_RECOVERED",
                "raceId": race_id,
                "secondsToStart": int((starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds()),
                "officialOddsRows": int(odds_report.get("parsedOddsRows") or 0),
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            # A single race failure must never stop later races from being attempted.
            report["failedRaceIds"].append({"raceId": race_id, "error": f"{type(exc).__name__}:{exc}"})
            print(json.dumps({
                "event": "RESILIENT_LIVE_RECOVERY_FAILED",
                "raceId": race_id,
                "error": f"{type(exc).__name__}:{exc}",
            }, ensure_ascii=False), file=sys.stderr, flush=True)

    final_locked = base.locked_races(collector, ids)
    still_recoverable = sorted(
        race_id for race_id in ids
        if race_id not in final_locked and 0 < (starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds() <= RECOVERY_OPEN_SECONDS
    )
    report["remainingRecoverableRaceIds"] = still_recoverable
    report["status"] = "recovery_ok" if not still_recoverable else "recovery_incomplete"
    out = ROOT / "analysis-results" / "resilient-live-recovery.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)

    if still_recoverable:
        raise RuntimeError("RESILIENT_RECOVERY_STILL_MISSING:" + ",".join(still_recoverable))


if __name__ == "__main__":
    main()
