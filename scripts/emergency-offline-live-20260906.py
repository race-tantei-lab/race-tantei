#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
ODDS_LIVE_PATH = ROOT / "scripts" / "collect-current-jra-official-odds-live.py"
GENERATOR_PATH = ROOT / "scripts" / "generate-ten-year-live-bets.py"
CANONICAL_PATH = ROOT / "scripts" / "run-ten-year-auto-final-live.py"
DATE = "2026-09-06"
GENERATE_AT_SECONDS = 30 * 60
HARD_T15_SECONDS = 15 * 60
EXPECTED_COURSES = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


class HybridCollector:
    """Read from a quota-free local D1 export; mirror only intentional mutations to production."""

    def __init__(self, db_path: pathlib.Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), timeout=120)
        self.conn.row_factory = sqlite3.Row
        self.account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.database_id = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
        self.token = os.environ["CLOUDFLARE_API_TOKEN"]
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.database_id}/query"
        self.active_race_id: str | None = None
        self.active_start: dt.datetime | None = None
        self.remote_mutations = 0

    @staticmethod
    def _kind(sql: str) -> str:
        stripped = sql.lstrip()
        while stripped.startswith("--"):
            stripped = stripped.split("\n", 1)[1].lstrip() if "\n" in stripped else ""
        return (stripped.split(None, 1)[0].upper() if stripped else "")

    def _local(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.conn.execute(sql, params or [])
        if cur.description:
            return [dict(row) for row in cur.fetchall()]
        self.conn.commit()
        return []

    def _remote_mutation(self, sql: str, params: list | None = None) -> None:
        if "rt_public_bets" in sql.lower() and self.active_start is not None:
            remaining = (self.active_start - dt.datetime.now(dt.timezone.utc)).total_seconds()
            if remaining <= HARD_T15_SECONDS:
                raise RuntimeError(f"EMERGENCY_HARD_T15_WRITE_BLOCK:{self.active_race_id}:{remaining:.1f}")
        payload = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"D1_REMOTE_MUTATION_HTTP_{exc.code}:{detail[:1000]}") from exc
        if not body.get("success"):
            raise RuntimeError(f"D1_REMOTE_MUTATION_FAILED:{body}")
        self.remote_mutations += 1

    def d1_query(self, sql: str, params: list | None = None) -> list[dict]:
        kind = self._kind(sql)
        # All reads and schema checks stay on the local export. DDL is also local-only;
        # the production schema already exists and rebuilding indexes during a quota
        # incident is explicitly forbidden.
        if kind in {"SELECT", "WITH", "PRAGMA", "EXPLAIN"}:
            return self._local(sql, params)
        if kind in {"CREATE", "ALTER", "DROP", "VACUUM", "REINDEX"}:
            return self._local(sql, params)
        if kind not in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            raise RuntimeError(f"EMERGENCY_SQL_KIND_NOT_ALLOWED:{kind}")
        self._remote_mutation(sql, params)
        return self._local(sql, params)


def exact_six(collector: HybridCollector, race_id: str) -> bool:
    rows = collector.d1_query(
        "SELECT course,bet_type,combination,stake_yen,source_prediction_id,locked_at,settlement_status "
        "FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination",
        [race_id],
    )
    if len(rows) != 6:
        return False
    by_course: dict[str, list[dict]] = {}
    for row in rows:
        by_course.setdefault(str(row["course"]), []).append(row)
    if set(by_course) != set(EXPECTED_COURSES):
        return False
    tickets = []
    for course, budget in EXPECTED_COURSES.items():
        crow = by_course[course]
        if len(crow) != 2 or len({str(r["bet_type"]) for r in crow}) != 2:
            return False
        if sum(int(r["stake_yen"] or 0) for r in crow) != budget:
            return False
        if any(int(r["source_prediction_id"] or 0) != -2 or not r["locked_at"] or str(r["settlement_status"]) != "pending" for r in crow):
            return False
        tickets.append({(str(r["bet_type"]), str(r["combination"])) for r in crow})
    return tickets[0] == tickets[1] == tickets[2]


def collect_official_odds(collector: HybridCollector, race_id: str) -> dict:
    race_rows = collector.d1_query(
        "SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,"
        "start_time_utc AS startTimeUtc,entry_url AS entryUrl FROM rt_races WHERE race_id=? LIMIT 1",
        [race_id],
    )
    if not race_rows:
        raise RuntimeError(f"EMERGENCY_RACE_ROW_MISSING:{race_id}")
    live = load(ODDS_LIVE_PATH, f"emergency_live_odds_{race_id.replace('-', '_')}_{int(time.time())}")
    fast = live.base
    # Exact single-race scope. All D1 reads are redirected to the local export;
    # official win-odds persistence remains a production mutation through HybridCollector.
    fast.selected_ids = lambda: {race_id}
    fast.base.upcoming_races = lambda: race_rows
    fast.base.d1_query = collector.d1_query
    fast.runtime.base.d1_query = collector.d1_query
    fast.main()
    report = json.loads((ROOT / "official-odds-collection-report.json").read_text(encoding="utf-8"))
    if int(report.get("eligibleFixedTargetCount") or 0) != 1:
        raise RuntimeError(f"EMERGENCY_ODDS_TARGET_INVALID:{race_id}:{report}")
    if int(report.get("errorCount") or 0) != 0:
        raise RuntimeError(f"EMERGENCY_ODDS_ERRORS:{race_id}:{report.get('errors')}")
    covered = report.get("racesByBetType") or {}
    for bet_type in ("単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"):
        if int(covered.get(bet_type) or 0) != 1:
            raise RuntimeError(f"EMERGENCY_ODDS_TYPE_MISSING:{race_id}:{bet_type}")
    return report


def generate_bets(collector: HybridCollector, selection_path: pathlib.Path, race_id: str) -> pathlib.Path:
    generator = load(GENERATOR_PATH, f"emergency_generator_{race_id.replace('-', '_')}_{int(time.time())}")
    original_load = generator.load

    def emergency_load(path, name):
        if pathlib.Path(path).resolve() == COLLECTOR_PATH.resolve():
            return collector
        return original_load(path, name)

    generator.load = emergency_load
    out = ROOT / "analysis-results" / f"emergency-offline-live-{DATE}-{race_id}.json"
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            str(GENERATOR_PATH), "--repo", str(ROOT), "--date", DATE,
            "--selection", str(selection_path),
            "--odds-file", str(ROOT / "current-selected-official-odds.json.gz"),
            "--out", str(out), "--insert",
        ]
        generator.main()
    finally:
        sys.argv = old_argv
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()
    collector = HybridCollector(pathlib.Path(args.db))
    canonical = load(CANONICAL_PATH, "emergency_canonical_validation")

    state_rows = collector.d1_query(
        "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
        [f"final_daily_selection:{DATE}"],
    )
    if not state_rows:
        raise RuntimeError("EMERGENCY_SELECTION_MISSING")
    selection = json.loads(str(state_rows[0]["value"]))
    ids, venues = canonical.validate_selection(selection)
    if len(ids) != 15 or len(venues) != 3:
        raise RuntimeError(f"EMERGENCY_SELECTION_INVALID:{len(ids)}:{venues}")
    selection_path = pathlib.Path("/tmp") / f"emergency-selection-{DATE}.json"
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    q = ",".join("?" for _ in ids)
    timing_rows = collector.d1_query(
        f"SELECT race_id AS raceId,start_time_utc AS startUtc FROM rt_races WHERE race_id IN ({q})",
        ids,
    )
    starts = {str(row["raceId"]): parse_utc(str(row["startUtc"])) for row in timing_rows if row.get("startUtc")}
    if len(starts) != 15:
        raise RuntimeError(f"EMERGENCY_START_TIMES_MISSING:{len(starts)}/15")

    audit = {
        "version": "emergency-offline-live-20260906-v1",
        "date": DATE,
        "sourceModel": selection.get("sourceModel"),
        "resultDataUsedForTargetDay": selection.get("resultDataUsedForTargetDay"),
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "events": [],
    }
    audit_path = ROOT / "analysis-results" / "emergency-offline-live-20260906.json"
    audit_path.parent.mkdir(exist_ok=True)

    for race_id in sorted(ids, key=lambda rid: starts[rid]):
        if exact_six(collector, race_id):
            audit["events"].append({"raceId": race_id, "status": "already_exact_six"})
            continue
        now = dt.datetime.now(dt.timezone.utc)
        remaining = (starts[race_id] - now).total_seconds()
        if remaining <= HARD_T15_SECONDS:
            audit["events"].append({"raceId": race_id, "status": "closed_without_backfill", "secondsToStart": int(remaining)})
            continue

        # Wait only inside this production recovery job until the canonical T-30 window.
        # This is not a new model rule; it preserves the existing T-30 finalization policy.
        while True:
            now = dt.datetime.now(dt.timezone.utc)
            remaining = (starts[race_id] - now).total_seconds()
            if remaining <= GENERATE_AT_SECONDS:
                break
            time.sleep(min(30.0, max(1.0, remaining - GENERATE_AT_SECONDS)))

        remaining = (starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining <= HARD_T15_SECONDS:
            audit["events"].append({"raceId": race_id, "status": "closed_without_backfill", "secondsToStart": int(remaining)})
            continue

        collector.active_race_id = race_id
        collector.active_start = starts[race_id]
        try:
            odds_report = collect_official_odds(collector, race_id)
            before_insert = (starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds()
            if before_insert <= HARD_T15_SECONDS:
                raise RuntimeError(f"EMERGENCY_GENERATION_CROSSED_T15:{race_id}:{before_insert:.1f}")
            artifact = generate_bets(collector, selection_path, race_id)
            if not exact_six(collector, race_id):
                raise RuntimeError(f"EMERGENCY_EXACT_SIX_VERIFY_FAILED:{race_id}")
            audit["events"].append({
                "raceId": race_id,
                "status": "generated_exact_six",
                "secondsToStartAtOddsStart": int(remaining),
                "officialOddsRows": int(odds_report.get("parsedOddsRows") or 0),
                "artifact": str(artifact.relative_to(ROOT)),
            })
            print(json.dumps(audit["events"][-1], ensure_ascii=False), flush=True)
        except Exception as exc:
            audit["events"].append({
                "raceId": race_id,
                "status": "generation_failed",
                "secondsToStart": int((starts[race_id] - dt.datetime.now(dt.timezone.utc)).total_seconds()),
                "error": f"{type(exc).__name__}:{exc}",
            })
            print(json.dumps(audit["events"][-1], ensure_ascii=False), flush=True)
        finally:
            collector.active_race_id = None
            collector.active_start = None
            audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    audit["remoteMutations"] = collector.remote_mutations
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
