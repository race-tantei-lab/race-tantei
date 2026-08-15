#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "run-auto-final-live.py"
CANONICAL_PATH = ROOT / "scripts" / "run-ten-year-auto-final-live.py"


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    base = load(BASE_PATH, "critical_auto_base")
    canonical = load(CANONICAL_PATH, "critical_auto_canonical")

    # Force the completed ten-year model implementation; never fall back to legacy rules.
    base.validate_selection = canonical.validate_selection
    base.generate_dynamic_selection = canonical.generate_selection
    base.run_learned_generator = canonical.run_generator
    base.verify_locked = canonical.verify_locked
    base.COURSE_BUDGETS = canonical.COURSE_BUDGETS

    collector = base.collector_module()
    now = dt.datetime.now(dt.timezone.utc)
    date = base.now_jst().date().isoformat()
    selection_path = pathlib.Path("/tmp") / f"critical-race-tantei-selection-{date}.json"
    payload, selection_state = base.freeze_or_load_selection(collector, date, selection_path)
    if payload is None:
        result = {
            "status": selection_state,
            "date": date,
            "selectionState": selection_state,
            "generatedRaceIds": [],
            "alreadyGeneratedRaceIds": [],
            "remainingFutureRaceIds": [],
            "failures": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    ids, venues = canonical.validate_selection(payload)
    starts = base.selected_timing(collector, ids)
    if len(starts) != len(ids):
        raise RuntimeError(f"CRITICAL_SELECTED_START_TIMES_MISSING:{len(starts)}/{len(ids)}")

    def collect_exact_race_official_odds(rid: str) -> dict:
        # Explicit selected-race recovery must not depend on rt_races.status. A stale/incorrect
        # result sync must never be able to suppress pre-race ticket generation.
        race_rows = collector.d1_query(
            """
            SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,
                   start_time_utc AS startTimeUtc,entry_url AS entryUrl
            FROM rt_races WHERE race_id=? LIMIT 1
            """,
            [rid],
        )
        if not race_rows:
            raise RuntimeError(f"CRITICAL_RACE_ROW_MISSING:{rid}")
        live = base.load_module(f"critical_live_odds_{rid.replace('-', '_')}", base.ODDS_LIVE_SOURCE)
        fast = live.base
        fast.selected_ids = lambda: {rid}
        fast.base.upcoming_races = lambda: race_rows
        fast.main()
        report = json.loads((ROOT / "official-odds-collection-report.json").read_text(encoding="utf-8"))
        if int(report.get("eligibleFixedTargetCount") or 0) != 1:
            raise RuntimeError(f"CRITICAL_ODDS_TARGET_MISSING:{rid}:{report.get('eligibleFixedTargetCount')}")
        if int(report.get("errorCount") or 0) != 0:
            raise RuntimeError(f"CRITICAL_ODDS_ERRORS:{rid}:{report.get('errors')}")
        covered = report.get("racesByBetType") or {}
        for bet_type in ("単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"):
            if int(covered.get(bet_type) or 0) != 1:
                raise RuntimeError(f"CRITICAL_ODDS_TYPE_MISSING:{rid}:{bet_type}:{covered.get(bet_type)}")
        return report

    already = base.locked_races(collector, ids)
    future = [rid for rid in ids if starts[rid] > now]
    # Normal lock timing remains the published <=45 minute window. The five-minute
    # fail-safe keeps retrying every missing due race right up until the start.
    pending = [
        rid for rid in future
        if rid not in already and (starts[rid] - now).total_seconds() <= base.MAX_LOCK_SECONDS
    ]
    pending.sort(key=lambda rid: starts[rid])

    generated = []
    failures = []
    for rid in pending:
        seconds_to_start = int((starts[rid] - dt.datetime.now(dt.timezone.utc)).total_seconds())
        if seconds_to_start <= 0:
            continue
        try:
            odds_report = collect_exact_race_official_odds(rid)
            out_path = ROOT / "analysis-results" / f"critical-auto-bet-{date}-{rid}.json"
            out_path.parent.mkdir(exist_ok=True)
            canonical.run_generator(date, selection_path, out_path)
            canonical.verify_locked(collector, [rid])
            generated.append(rid)
            print(json.dumps({
                "event": "CRITICAL_BET_GENERATED",
                "raceId": rid,
                "secondsToStart": seconds_to_start,
                "officialOddsRows": int(odds_report.get("parsedOddsRows") or 0),
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            # A concurrent path may have completed this race while this process was collecting odds.
            if rid in base.locked_races(collector, [rid]):
                generated.append(rid)
                print(json.dumps({
                    "event": "CRITICAL_BET_ALREADY_GENERATED_CONCURRENTLY",
                    "raceId": rid,
                    "secondsToStart": seconds_to_start,
                }, ensure_ascii=False), flush=True)
                continue
            failures.append({
                "raceId": rid,
                "secondsToStart": seconds_to_start,
                "error": f"{type(exc).__name__}:{exc}",
            })
            print(json.dumps({
                "event": "CRITICAL_BET_RETRY_REQUIRED",
                "raceId": rid,
                "secondsToStart": seconds_to_start,
                "error": f"{type(exc).__name__}:{exc}",
            }, ensure_ascii=False), flush=True)
            traceback.print_exc()

    locked_after = base.locked_races(collector, ids)
    remaining_future = [rid for rid in ids if starts[rid] > dt.datetime.now(dt.timezone.utc) and rid not in locked_after]
    remaining_future.sort(key=lambda rid: starts[rid])
    urgent_missing = [
        rid for rid in remaining_future
        if (starts[rid] - dt.datetime.now(dt.timezone.utc)).total_seconds() <= base.MAX_LOCK_SECONDS
    ]

    result = {
        "status": "critical_generation_ok" if not urgent_missing else "critical_generation_urgent_missing",
        "date": date,
        "selectionState": selection_state,
        "venues": venues,
        "selectedRaceCount": len(ids),
        "futureSelectedRaceCount": len(future),
        "alreadyGeneratedRaceIds": sorted(already),
        "generatedRaceIds": generated,
        "lockedRaceCountAfter": len(locked_after),
        "remainingFutureRaceIds": remaining_future,
        "urgentMissingRaceIds": urgent_missing,
        "failures": failures,
    }
    out = ROOT / "analysis-results" / "critical-auto-bet-generation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)

    # Never allow a selected race to remain without tickets once it enters the 45-minute window.
    if urgent_missing:
        raise RuntimeError("CRITICAL_PRE_RACE_BETS_MISSING:" + ",".join(urgent_missing))


if __name__ == "__main__":
    main()
