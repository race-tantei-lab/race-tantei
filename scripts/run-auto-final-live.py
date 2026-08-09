import argparse
import collections
import datetime as dt
import importlib.util
import json
import math
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SELECTION_SOURCE = ROOT / "scripts" / "generate-final-preday-selection-remote.py"
GENERATOR_SOURCE = ROOT / "scripts" / "generate-final-live-bets.py"
ODDS_LIVE_SOURCE = ROOT / "scripts" / "collect-current-jra-official-odds-live.py"
RULES_SOURCE = ROOT / "scripts" / "final-rules-payload.py"
SELECTION_STATE_PREFIX = "final_daily_selection:"
LEARNING_STATE_KEY = "final_rule_learning:state"
COURSE_BUDGETS = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
MIN_LOCK_SECONDS = 15 * 60
MAX_LOCK_SECONDS = 45 * 60


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def collector_module():
    return load_module("auto_final_live_collector", ROOT / "scripts" / "collect-jra-official-odds.py")


def now_jst() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))


def parse_utc(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def validate_selection(payload: dict) -> tuple[list[str], list[str]]:
    selected = payload.get("selected")
    if not isinstance(selected, list) or not selected:
        raise RuntimeError("AUTO_SELECTION_EMPTY")
    if payload.get("resultDataUsedForTargetDay") is not False:
        raise RuntimeError("AUTO_SELECTION_USED_TARGET_RESULTS")
    if int(payload.get("sourceRuleCount") or 0) != 316:
        raise RuntimeError("AUTO_SELECTION_RULE_COUNT_INVALID")
    counts = collections.Counter(str(row.get("venue") or "") for row in selected)
    if "" in counts or any(count != 5 for count in counts.values()):
        raise RuntimeError(f"AUTO_SELECTION_NOT_FIVE_PER_VENUE:{dict(counts)}")
    ids = [str(row.get("raceId") or "") for row in selected]
    if any(not race_id for race_id in ids) or len(set(ids)) != len(ids):
        raise RuntimeError("AUTO_SELECTION_RACE_IDS_INVALID")
    return ids, list(counts)


def generate_dynamic_selection(date: str, out_path: pathlib.Path) -> dict:
    source = SELECTION_SOURCE.read_text(encoding="utf-8")
    venue_filter = "WHERE race_date=? AND venue IN ('札幌','新潟','中京')"
    if source.count(venue_filter) != 1:
        raise RuntimeError("AUTO_SELECTION_VENUE_PATCH_TARGET_MISSING")
    source = source.replace(venue_filter, "WHERE race_date=?", 1)

    fixed_count = '''    if len(race_rows) != 36:\n        raise RuntimeError(f"TARGET_RACE_COUNT_INVALID:{len(race_rows)}")\n'''
    dynamic_count = '''    venue_counts = collections.Counter(str(row["venue"]) for row in race_rows)\n    if len(venue_counts) < 2 or any(count != 12 for count in venue_counts.values()):\n        raise RuntimeError(f"TARGET_RACE_STRUCTURE_INCOMPLETE:{dict(venue_counts)}")\n'''
    if source.count(fixed_count) != 1:
        raise RuntimeError("AUTO_SELECTION_COUNT_PATCH_TARGET_MISSING")
    source = source.replace(fixed_count, dynamic_count, 1)

    fixed_loop = '    for venue in ("札幌","新潟","中京"):\n'
    dynamic_loop = '    for venue in sorted({str(x["venue"]) for x in targets}, key=lambda v: pmod.VENUES.index(v)):\n'
    if source.count(fixed_loop) != 1:
        raise RuntimeError("AUTO_SELECTION_LOOP_PATCH_TARGET_MISSING")
    source = source.replace(fixed_loop, dynamic_loop, 1)

    namespace = {"__name__": "auto_dynamic_selection", "__file__": str(SELECTION_SOURCE)}
    exec(compile(source, str(SELECTION_SOURCE), "exec"), namespace, namespace)
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(SELECTION_SOURCE), "--date", date, "--out", str(out_path)]
        namespace["main"]()
    finally:
        sys.argv = old_argv
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    validate_selection(payload)
    return payload


def freeze_or_load_selection(collector, date: str, out_path: pathlib.Path):
    key = f"{SELECTION_STATE_PREFIX}{date}"
    existing = collector.d1_query(
        "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [key]
    )
    if existing:
        payload = json.loads(str(existing[0].get("value") or "{}"))
        validate_selection(payload)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload, "loaded"

    structure = collector.d1_query(
        """
        SELECT venue,COUNT(*) AS races,
               SUM(CASE WHEN start_time_utc IS NOT NULL THEN 1 ELSE 0 END) AS timed,
               SUM(CASE WHEN EXISTS(SELECT 1 FROM rt_runners u WHERE u.race_id=r.race_id AND COALESCE(u.runner_status,'active')='active') THEN 1 ELSE 0 END) AS withRunners
        FROM rt_races r
        WHERE race_date=?
        GROUP BY venue
        ORDER BY venue
        """,
        [date],
    )
    if len(structure) < 2:
        return None, "waiting_race_program"
    if any(int(row.get("races") or 0) != 12 or int(row.get("timed") or 0) != 12 or int(row.get("withRunners") or 0) != 12 for row in structure):
        return None, "waiting_complete_program"

    payload = generate_dynamic_selection(date, out_path)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    collector.d1_query(
        """
        INSERT INTO rt_system_state(state_key,state_value,updated_at)
        VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO NOTHING
        """,
        [key, encoded],
    )
    authoritative = collector.d1_query(
        "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [key]
    )
    if not authoritative:
        raise RuntimeError("AUTO_SELECTION_FREEZE_VERIFY_MISSING")
    payload = json.loads(str(authoritative[0].get("value") or "{}"))
    validate_selection(payload)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, "frozen"


def selected_timing(collector, ids: list[str]) -> dict[str, dt.datetime]:
    out = {}
    for start in range(0, len(ids), 20):
        chunk = ids[start:start + 20]
        placeholders = ",".join("?" for _ in chunk)
        rows = collector.d1_query(
            f"SELECT race_id AS raceId,start_time_utc AS startTimeUtc FROM rt_races WHERE race_id IN ({placeholders})",
            chunk,
        )
        for row in rows:
            parsed = parse_utc(row.get("startTimeUtc"))
            if parsed is not None:
                out[str(row["raceId"])] = parsed
    return out


def locked_races(collector, ids: list[str]) -> set[str]:
    out = set()
    for start in range(0, len(ids), 20):
        chunk = ids[start:start + 20]
        placeholders = ",".join("?" for _ in chunk)
        rows = collector.d1_query(
            f"SELECT DISTINCT race_id AS raceId FROM rt_public_bets WHERE race_id IN ({placeholders})",
            chunk,
        )
        out.update(str(row["raceId"]) for row in rows)
    return out


def collect_official_odds(window_ids: list[str]) -> dict:
    live = load_module("auto_final_live_odds", ODDS_LIVE_SOURCE)
    fast = live.base
    fast.selected_ids = lambda: set(window_ids)
    fast.main()
    report = json.loads((ROOT / "official-odds-collection-report.json").read_text(encoding="utf-8"))
    if int(report.get("eligibleFixedTargetCount") or 0) != len(window_ids):
        raise RuntimeError(
            f"AUTO_ODDS_TARGETS_INCOMPLETE:{report.get('eligibleFixedTargetCount')}/{len(window_ids)}"
        )
    if int(report.get("errorCount") or 0) != 0:
        raise RuntimeError(f"AUTO_ODDS_ERRORS:{report.get('errors')}")
    covered = report.get("racesByBetType") or {}
    for bet_type in ("単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"):
        if int(covered.get(bet_type) or 0) != len(window_ids):
            raise RuntimeError(f"AUTO_ODDS_TYPE_INCOMPLETE:{bet_type}:{covered.get(bet_type)}/{len(window_ids)}")
    return report


def load_learning_buckets(base_namespace: dict) -> dict:
    try:
        collector = base_namespace["load_collector"](ROOT)
        rows = collector.d1_query(
            "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
            [LEARNING_STATE_KEY],
        )
        if not rows:
            return {}
        state = json.loads(str(rows[0].get("value") or "{}"))
        buckets = state.get("buckets") if isinstance(state, dict) else None
        return buckets if isinstance(buckets, dict) else {}
    except Exception:
        return {}


def run_learned_generator(date: str, selection_path: pathlib.Path, out_path: pathlib.Path):
    source = GENERATOR_SOURCE.read_text(encoding="utf-8")
    fixed = "    sel=json.loads((repo/a.selection).read_text(encoding='utf-8'));ids=[r['raceId'] for r in sel['selected']];assert len(ids)==15 and sel.get('resultDataUsedForTargetDay') is False\n"
    dynamic = """    sel=json.loads((repo/a.selection).read_text(encoding='utf-8'));ids=[r['raceId'] for r in sel['selected']]\n    venue_counts=collections.Counter(str(r.get('venue') or '') for r in sel.get('selected',[]))\n    if not venue_counts or '' in venue_counts or len(ids)!=5*len(venue_counts) or any(v!=5 for v in venue_counts.values()):raise RuntimeError(f'SELECTION_FIVE_PER_VENUE_INVALID:{dict(venue_counts)}:{len(ids)}')\n    if sel.get('resultDataUsedForTargetDay') is not False:raise RuntimeError('TARGET_RESULT_DATA_USED')\n"""
    if source.count(fixed) != 1:
        raise RuntimeError("AUTO_GENERATOR_SELECTION_PATCH_TARGET_MISSING")
    source = source.replace(fixed, dynamic, 1)
    namespace = {"__name__": "auto_final_live_base", "__file__": str(GENERATOR_SOURCE)}
    exec(compile(source, str(GENERATOR_SOURCE), "exec"), namespace, namespace)

    original_history = namespace["history_features_remote"]
    original_score = namespace["rule_score"]
    buckets = load_learning_buckets(namespace)

    def batched_history(collector, target, current_runners):
        result = {}
        for start in range(0, len(current_runners), 24):
            result.update(original_history(collector, target, current_runners[start:start + 24]))
        return result

    def bucket_adjustment(key, maximum_weight):
        row = buckets.get(key)
        if not isinstance(row, dict):
            return 0.0
        try:
            factor = float(row.get("factor", 1.0))
            samples = int(row.get("samples", 0))
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(factor) or samples <= 0:
            return 0.0
        evidence = min(1.0, samples / 20.0)
        return maximum_weight * evidence * math.log(max(0.50, min(1.50, factor)))

    def learned_score(rules_by_bet, bet, vals, preday=False):
        score = float(original_score(rules_by_bet, bet, vals, preday))
        if score <= 0:
            return score
        try:
            bet_index = int(bet)
            venue = int(vals.get("venue"))
            odds = int(vals.get("odds"))
        except (TypeError, ValueError):
            return score
        adjustment = 0.0
        adjustment += bucket_adjustment(f"b:{bet_index}", 0.40)
        adjustment += bucket_adjustment(f"b:{bet_index}|v:{venue}", 0.20)
        adjustment += bucket_adjustment(f"b:{bet_index}|o:{odds}", 0.25)
        adjustment += bucket_adjustment(f"b:{bet_index}|v:{venue}|o:{odds}", 0.15)
        factor = max(0.80, min(1.20, math.exp(adjustment)))
        return score * factor

    namespace["history_features_remote"] = batched_history
    namespace["rule_score"] = learned_score
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            str(GENERATOR_SOURCE),
            "--repo", str(ROOT),
            "--date", date,
            "--selection", str(selection_path),
            "--odds-file", str(ROOT / "current-selected-official-odds.json.gz"),
            "--out", str(out_path),
            "--insert",
        ]
        namespace["main"]()
    finally:
        sys.argv = old_argv


def verify_locked(collector, ids: list[str]):
    for race_id in ids:
        rows = collector.d1_query(
            """
            SELECT course,COUNT(*) AS tickets,COUNT(DISTINCT bet_type) AS betTypes,
                   SUM(stake_yen) AS stakeYen,MIN(locked_at) AS lockedAt,
                   MAX(CASE WHEN source_prediction_id=-2 THEN 1 ELSE 0 END) AS finalSource
            FROM rt_public_bets
            WHERE race_id=?
            GROUP BY course
            """,
            [race_id],
        )
        by_course = {str(row["course"]): row for row in rows}
        if set(by_course) != set(COURSE_BUDGETS):
            raise RuntimeError(f"AUTO_PUBLIC_COURSES_MISSING:{race_id}:{sorted(by_course)}")
        for course, budget in COURSE_BUDGETS.items():
            row = by_course[course]
            tickets = int(row.get("tickets") or 0)
            bet_types = int(row.get("betTypes") or 0)
            stake = int(row.get("stakeYen") or 0)
            if not 3 <= tickets <= 10 or bet_types < 2 or stake != budget or int(row.get("finalSource") or 0) != 1:
                raise RuntimeError(
                    f"AUTO_PUBLIC_BET_GATE_FAILED:{race_id}:{course}:tickets={tickets}:types={bet_types}:stake={stake}:source={row.get('finalSource')}"
                )


def check_only(collector):
    rules = load_module("auto_final_rules_check", RULES_SOURCE).load_rules()
    if len(rules) != 316:
        raise RuntimeError(f"AUTO_RULE_COUNT_INVALID:{len(rules)}")
    tables = collector.d1_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('rt_races','rt_runners','rt_public_bets','rt_system_state')"
    )
    names = {str(row.get("name")) for row in tables}
    required = {"rt_races", "rt_runners", "rt_public_bets", "rt_system_state"}
    if names != required:
        raise RuntimeError(f"AUTO_D1_TABLES_MISSING:{sorted(required-names)}")
    print(json.dumps({"status": "check_ok", "rules": len(rules), "tables": sorted(names)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    collector = collector_module()
    if args.check_only:
        check_only(collector)
        return

    now = dt.datetime.now(dt.timezone.utc)
    date = now_jst().date().isoformat()
    selection_path = pathlib.Path("/tmp") / f"race-tantei-selection-{date}.json"
    payload, selection_state = freeze_or_load_selection(collector, date, selection_path)
    report = {
        "date": date,
        "selectionState": selection_state,
        "windowRaceIds": [],
        "lockedRaceIds": [],
        "status": selection_state,
    }
    if payload is None:
        pathlib.Path("analysis-results").mkdir(exist_ok=True)
        pathlib.Path("analysis-results/auto-final-live-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    ids, venues = validate_selection(payload)
    starts = selected_timing(collector, ids)
    if len(starts) != len(ids):
        raise RuntimeError(f"AUTO_SELECTED_START_TIMES_MISSING:{len(starts)}/{len(ids)}")
    already = locked_races(collector, ids)
    seconds = {race_id: (starts[race_id] - now).total_seconds() for race_id in ids}
    missed = [race_id for race_id in ids if race_id not in already and seconds[race_id] <= MIN_LOCK_SECONDS]
    if missed:
        raise RuntimeError(f"AUTO_LOCK_DEADLINE_MISSED:{','.join(missed)}")
    window = [
        race_id for race_id in ids
        if race_id not in already and MIN_LOCK_SECONDS < seconds[race_id] <= MAX_LOCK_SECONDS
    ]
    report.update({
        "venues": venues,
        "selectedRaceCount": len(ids),
        "alreadyLockedRaceCount": len(already),
        "windowRaceIds": window,
    })
    if not window:
        report["status"] = "waiting_lock_window"
    else:
        odds_report = collect_official_odds(window)
        out_path = pathlib.Path("analysis-results") / f"auto-final-live-{date}.json"
        out_path.parent.mkdir(exist_ok=True)
        run_learned_generator(date, selection_path, out_path)
        verify_locked(collector, window)
        report["status"] = "locked"
        report["lockedRaceIds"] = window
        report["officialOddsRows"] = int(odds_report.get("parsedOddsRows") or 0)

    pathlib.Path("analysis-results").mkdir(exist_ok=True)
    pathlib.Path("analysis-results/auto-final-live-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
