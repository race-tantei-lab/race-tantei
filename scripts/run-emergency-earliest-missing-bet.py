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
RECOVERY_OPEN_SECONDS = 16 * 60


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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

    rid = missing[0]
    seconds_until_window = int((starts[rid] - now).total_seconds())
    if seconds_until_window > RECOVERY_OPEN_SECONDS:
        print(json.dumps({
            "status":"waiting_emergency_window",
            "date":date,
            "raceId":rid,
            "secondsToStart":seconds_until_window,
            "recoveryOpenSeconds":RECOVERY_OPEN_SECONDS,
        }, ensure_ascii=False))
        return

    for attempt in range(1, 4):
        if rid in base.locked_races(collector, [rid]):
            canonical.verify_locked(collector, [rid])
            print(json.dumps({"status":"already_recovered","raceId":rid,"attempt":attempt}, ensure_ascii=False))
            return
        seconds = int((starts[rid] - dt.datetime.now(dt.timezone.utc)).total_seconds())
        if seconds <= 0:
            raise RuntimeError(f"EMERGENCY_RACE_ALREADY_STARTED:{rid}")
        try:
            report = base.collect_official_odds([rid])
            out_path = ROOT / "analysis-results" / f"emergency-auto-bet-{date}-{rid}.json"
            out_path.parent.mkdir(exist_ok=True)
            canonical.run_generator(date, selection_path, out_path)
            canonical.verify_locked(collector, [rid])
            print(json.dumps({
                "status":"emergency_bet_generated",
                "raceId":rid,
                "attempt":attempt,
                "secondsToStart":seconds,
                "officialOddsRows":int(report.get("parsedOddsRows") or 0),
            }, ensure_ascii=False))
            return
        except Exception as exc:
            if rid in base.locked_races(collector, [rid]):
                canonical.verify_locked(collector, [rid])
                print(json.dumps({"status":"recovered_concurrently","raceId":rid,"attempt":attempt}, ensure_ascii=False))
                return
            print(json.dumps({"status":"retry","raceId":rid,"attempt":attempt,"secondsToStart":seconds,"error":f"{type(exc).__name__}:{exc}"}, ensure_ascii=False), flush=True)
            if attempt < 3:
                time.sleep(5)
    raise RuntimeError(f"EMERGENCY_BET_GENERATION_FAILED:{rid}")


if __name__ == "__main__":
    main()
