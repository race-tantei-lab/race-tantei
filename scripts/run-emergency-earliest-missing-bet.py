#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "run-auto-final-live.py"
CANONICAL_PATH = ROOT / "scripts" / "run-ten-year-auto-final-live.py"
RECOVERY_OPEN_SECONDS = 40 * 60
HARD_DEADLINE_SECONDS = 15 * 60
MAX_ATTEMPTS_PER_RACE = 3


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def seconds_to_start(starts, race_id: str) -> int:
    return int((starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds())


def main():
    base = load(BASE_PATH, "emergency_auto_base")
    canonical = load(CANONICAL_PATH, "emergency_auto_canonical")
    base.validate_selection = canonical.validate_selection
    base.generate_dynamic_selection = canonical.generate_selection
    base.run_learned_generator = canonical.run_generator
    base.verify_locked = canonical.verify_locked
    base.COURSE_BUDGETS = canonical.COURSE_BUDGETS

    collector = base.collector_module()
    date = base.now_jst().date().isoformat()
    selection_path = pathlib.Path("/tmp") / f"emergency-race-tantei-selection-{date}.json"
    payload, state = base.freeze_or_load_selection(collector, date, selection_path)
    if payload is None:
        raise RuntimeError(f"EMERGENCY_SELECTION_NOT_READY:{state}")

    ids, _ = canonical.validate_selection(payload)
    starts = base.selected_timing(collector, ids)
    locked = base.locked_races(collector, ids)
    now = dt.datetime.now(dt.timezone.utc)
    missing = [rid for rid in ids if rid not in locked and starts.get(rid) and starts[rid] > now]
    missing.sort(key=lambda rid: starts[rid])
    if not missing:
        print(json.dumps({"status":"no_future_missing_bets","date":date}, ensure_ascii=False))
        return

    def remaining(rid: str) -> int:
        return int((starts[rid] - now).total_seconds())

    eligible = [rid for rid in missing if HARD_DEADLINE_SECONDS <= remaining(rid) <= RECOVERY_OPEN_SECONDS]
    deadline_missed = [rid for rid in missing if 0 < remaining(rid) < HARD_DEADLINE_SECONDS]
    waiting = [rid for rid in missing if remaining(rid) > RECOVERY_OPEN_SECONDS]
    if not eligible:
        print(json.dumps({
            "status":"waiting_emergency_window" if waiting else "hard_deadline_closed",
            "date":date,
            "eligibleRaceIds":[],
            "deadlineMissedRaceIds":deadline_missed,
            "waitingRaceIds":waiting,
            "nextRaceId":missing[0],
            "secondsToStart":remaining(missing[0]),
            "recoveryOpenSeconds":RECOVERY_OPEN_SECONDS,
            "hardDeadlineSeconds":HARD_DEADLINE_SECONDS,
        }, ensure_ascii=False))
        return

    recovered = []
    failures = []

    for rid in eligible:
        done = False
        last_error = None
        for attempt in range(1, MAX_ATTEMPTS_PER_RACE + 1):
            if rid in base.locked_races(collector, [rid]):
                canonical.verify_locked(collector, [rid])
                recovered.append({"raceId":rid,"status":"already_recovered","attempt":attempt})
                done = True
                break

            seconds = seconds_to_start(starts, rid)
            if seconds < HARD_DEADLINE_SECONDS:
                last_error = f"EMERGENCY_HARD_T15_CLOSED:{rid}:{seconds}"
                break

            try:
                report = base.collect_official_odds([rid])
                out_path = ROOT / "analysis-results" / f"emergency-auto-bet-{date}-{rid}.json"
                out_path.parent.mkdir(exist_ok=True)
                canonical.run_generator(date, selection_path, out_path)
                canonical.verify_locked(collector, [rid])
                recovered.append({
                    "raceId":rid,
                    "status":"emergency_bet_generated",
                    "attempt":attempt,
                    "secondsToStart":seconds,
                    "officialOddsRows":int(report.get("parsedOddsRows") or 0),
                })
                done = True
                break
            except Exception as exc:
                if rid in base.locked_races(collector, [rid]):
                    canonical.verify_locked(collector, [rid])
                    recovered.append({"raceId":rid,"status":"recovered_concurrently","attempt":attempt})
                    done = True
                    break
                last_error = f"{type(exc).__name__}:{exc}"
                print(json.dumps({
                    "status":"retry",
                    "raceId":rid,
                    "attempt":attempt,
                    "secondsToStart":seconds,
                    "error":last_error,
                }, ensure_ascii=False), flush=True)
                if attempt < MAX_ATTEMPTS_PER_RACE:
                    time.sleep(5)

        if not done:
            failures.append({"raceId":rid,"error":last_error or "UNKNOWN_EMERGENCY_RECOVERY_FAILURE"})

    now_after = dt.datetime.now(dt.timezone.utc)
    locked_after = base.locked_races(collector, ids)
    remaining_eligible = [
        rid for rid in ids
        if rid not in locked_after
        and starts.get(rid)
        and starts[rid] > now_after
        and HARD_DEADLINE_SECONDS <= int((starts[rid] - now_after).total_seconds()) <= RECOVERY_OPEN_SECONDS
    ]
    remaining_eligible.sort(key=lambda rid: starts[rid])

    summary = {
        "status":"emergency_batch_complete" if not remaining_eligible and not failures else "emergency_batch_incomplete",
        "date":date,
        "eligibleRaceIds":eligible,
        "deadlineMissedRaceIds":deadline_missed,
        "recovered":recovered,
        "failures":failures,
        "remainingEligibleRaceIds":remaining_eligible,
        "waitingRaceIds":waiting,
        "recoveryOpenSeconds":RECOVERY_OPEN_SECONDS,
        "hardDeadlineSeconds":HARD_DEADLINE_SECONDS,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)

    if remaining_eligible or failures:
        raise RuntimeError(
            "EMERGENCY_BATCH_RECOVERY_INCOMPLETE:"
            + json.dumps({"remaining":remaining_eligible,"failures":failures}, ensure_ascii=False)
        )


if __name__ == "__main__":
    main()
