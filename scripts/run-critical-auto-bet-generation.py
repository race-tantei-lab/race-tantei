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
HARD_DEADLINE_SECONDS = 15 * 60
RECOVERY_OPEN_SECONDS = 15 * 60
EXPECTED_COURSES = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_utc(value):
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def ticket_state(collector, ids):
    if not ids:
        return {}, set(), set()
    placeholders = ",".join("?" for _ in ids)
    rows = collector.d1_query(
        f"""
        SELECT race_id AS raceId,course,bet_type AS betType,combination,
               stake_yen AS stakeYen,settlement_status AS settlementStatus,
               locked_at AS lockedAt,source_prediction_id AS sourcePredictionId
        FROM rt_public_bets
        WHERE race_id IN ({placeholders})
        ORDER BY race_id,course,bet_type,combination
        """,
        list(ids),
    )
    grouped = {rid: [] for rid in ids}
    for row in rows:
        grouped.setdefault(str(row.get("raceId")), []).append(row)

    details = {}
    complete = set()
    partial = set()
    for rid in ids:
        race_rows = grouped.get(rid, [])
        by_course = {}
        for row in race_rows:
            by_course.setdefault(str(row.get("course") or ""), []).append(row)

        course_ok = set(by_course) == set(EXPECTED_COURSES)
        ticket_sets = []
        per_course = {}
        for course, budget in EXPECTED_COURSES.items():
            course_rows = by_course.get(course, [])
            ticket_keys = {(str(r.get("betType") or ""), str(r.get("combination") or "")) for r in course_rows}
            bet_types = {str(r.get("betType") or "") for r in course_rows}
            stake_total = sum(int(r.get("stakeYen") or 0) for r in course_rows)
            canonical_sources = all(int(r.get("sourcePredictionId") or 0) == -2 for r in course_rows)
            locked = all(bool(r.get("lockedAt")) for r in course_rows)
            ok = (
                len(course_rows) == 2
                and len(ticket_keys) == 2
                and len(bet_types) == 2
                and stake_total == budget
                and canonical_sources
                and locked
            )
            per_course[course] = {
                "rows": len(course_rows),
                "distinctTickets": len(ticket_keys),
                "distinctBetTypes": len(bet_types),
                "stakeYen": stake_total,
                "canonicalSource": canonical_sources,
                "locked": locked,
                "ok": ok,
            }
            if course_rows:
                ticket_sets.append(ticket_keys)

        same_two_tickets = len(ticket_sets) == 3 and ticket_sets[0] == ticket_sets[1] == ticket_sets[2]
        all_rows_canonical = bool(race_rows) and all(int(r.get("sourcePredictionId") or 0) == -2 for r in race_rows)
        all_rows_pending = bool(race_rows) and all(str(r.get("settlementStatus") or "") == "pending" for r in race_rows)
        locked_times = [parse_utc(r.get("lockedAt")) for r in race_rows if r.get("lockedAt")]
        latest_locked_at = max((x for x in locked_times if x is not None), default=None)
        is_complete = (
            len(race_rows) == 6
            and course_ok
            and all(per_course[c]["ok"] for c in EXPECTED_COURSES)
            and same_two_tickets
        )
        if is_complete:
            complete.add(rid)
        elif race_rows:
            partial.add(rid)
        details[rid] = {
            "rowCount": len(race_rows),
            "complete": is_complete,
            "courseSetOk": course_ok,
            "sameTwoTicketsAcrossCourses": same_two_tickets,
            "allRowsCanonical": all_rows_canonical,
            "allRowsPending": all_rows_pending,
            "latestLockedAt": latest_locked_at.isoformat() if latest_locked_at else None,
            "courses": per_course,
        }
    return details, complete, partial


def main():
    base = load(BASE_PATH, "critical_auto_base")
    canonical = load(CANONICAL_PATH, "critical_auto_canonical")

    base.validate_selection = canonical.validate_selection
    base.generate_dynamic_selection = canonical.generate_selection
    base.run_learned_generator = canonical.run_generator
    base.verify_locked = canonical.verify_locked
    base.COURSE_BUDGETS = canonical.COURSE_BUDGETS
    # This recovery path must never pre-empt the one-minute Worker and lock stale
    # odds early, even when manually dispatched.
    base.MAX_LOCK_SECONDS = RECOVERY_OPEN_SECONDS

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
            "deadlineBreachRaceIds": [],
            "failures": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    ids, venues = canonical.validate_selection(payload)
    starts = base.selected_timing(collector, ids)
    if len(starts) != len(ids):
        raise RuntimeError(f"CRITICAL_SELECTED_START_TIMES_MISSING:{len(starts)}/{len(ids)}")

    def collect_exact_race_official_odds(rid: str) -> dict:
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

    initial_details, already, initial_partial = ticket_state(collector, ids)
    future = [rid for rid in ids if starts[rid] > now]
    pending = [
        rid for rid in future
        if rid not in already and (starts[rid] - now).total_seconds() <= base.MAX_LOCK_SECONDS
    ]
    pending.sort(key=lambda rid: starts[rid])

    generated = []
    repaired = []
    failures = []
    for rid in pending:
        seconds_to_start = int((starts[rid] - dt.datetime.now(dt.timezone.utc)).total_seconds())
        if seconds_to_start <= 0:
            continue
        try:
            current_details, current_complete, current_partial = ticket_state(collector, [rid])
            if rid in current_complete:
                generated.append(rid)
                continue
            if rid in current_partial:
                detail = current_details[rid]
                if not detail["allRowsCanonical"] or not detail["allRowsPending"]:
                    raise RuntimeError(f"CRITICAL_PARTIAL_BETS_NOT_SAFE_TO_REPAIR:{rid}:{detail}")
                collector.d1_query(
                    "DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'",
                    [rid],
                )
                after_delete = collector.d1_query("SELECT COUNT(*) AS n FROM rt_public_bets WHERE race_id=?", [rid])
                if int(after_delete[0].get("n") or 0) != 0:
                    raise RuntimeError(f"CRITICAL_PARTIAL_BET_DELETE_INCOMPLETE:{rid}:{after_delete}")
                repaired.append(rid)
                print(json.dumps({"event": "CRITICAL_PARTIAL_BETS_CLEARED", "raceId": rid}, ensure_ascii=False), flush=True)

            odds_report = collect_exact_race_official_odds(rid)
            out_path = ROOT / "analysis-results" / f"critical-auto-bet-{date}-{rid}.json"
            out_path.parent.mkdir(exist_ok=True)
            canonical.run_generator(date, selection_path, out_path)
            canonical.verify_locked(collector, [rid])
            verify_details, verify_complete, _ = ticket_state(collector, [rid])
            if rid not in verify_complete:
                raise RuntimeError(f"CRITICAL_COMPLETE_TICKET_GATE_FAILED:{rid}:{verify_details.get(rid)}")
            generated.append(rid)
            print(json.dumps({
                "event": "CRITICAL_BET_GENERATED",
                "raceId": rid,
                "secondsToStart": seconds_to_start,
                "officialOddsRows": int(odds_report.get("parsedOddsRows") or 0),
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            _, concurrent_complete, _ = ticket_state(collector, [rid])
            if rid in concurrent_complete:
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

    final_details, complete_after, partial_after = ticket_state(collector, ids)
    audit_now = dt.datetime.now(dt.timezone.utc)
    remaining_future = [rid for rid in ids if starts[rid] > audit_now and rid not in complete_after]
    remaining_future.sort(key=lambda rid: starts[rid])
    urgent_missing = [
        rid for rid in remaining_future
        if (starts[rid] - audit_now).total_seconds() <= base.MAX_LOCK_SECONDS
    ]
    deadline_breaches = [
        rid for rid in remaining_future
        if (starts[rid] - audit_now).total_seconds() <= HARD_DEADLINE_SECONDS
    ]
    late_lock_breaches = []
    for rid in ids:
        if rid not in complete_after or starts[rid] <= audit_now:
            continue
        latest_locked = parse_utc(final_details[rid].get("latestLockedAt"))
        if latest_locked is not None and (starts[rid] - latest_locked).total_seconds() < HARD_DEADLINE_SECONDS:
            late_lock_breaches.append(rid)

    breach_ids = sorted(set(deadline_breaches + late_lock_breaches))
    result = {
        "status": "critical_generation_ok" if not urgent_missing and not breach_ids else "critical_generation_breach",
        "date": date,
        "selectionState": selection_state,
        "venues": venues,
        "selectedRaceCount": len(ids),
        "futureSelectedRaceCount": len(future),
        "completeRaceCount": len(complete_after),
        "alreadyGeneratedRaceIds": sorted(already),
        "generatedRaceIds": generated,
        "repairedPartialRaceIds": repaired,
        "initialPartialRaceIds": sorted(initial_partial),
        "partialRaceIdsAfter": sorted(partial_after),
        "remainingFutureRaceIds": remaining_future,
        "urgentMissingRaceIds": urgent_missing,
        "deadlineBreachRaceIds": breach_ids,
        "ticketIntegrity": final_details,
        "failures": failures,
    }
    out = ROOT / "analysis-results" / "critical-auto-bet-generation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)

    if breach_ids:
        raise RuntimeError("PRE_RACE_15_MINUTE_DEADLINE_BREACH:" + ",".join(breach_ids))
    if urgent_missing:
        raise RuntimeError("CRITICAL_PRE_RACE_BETS_MISSING:" + ",".join(urgent_missing))


if __name__ == "__main__":
    main()
