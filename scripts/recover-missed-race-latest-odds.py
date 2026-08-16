#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "recover-predeadline-race.py"


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load(BASE_PATH, "predeadline_recovery_base")


def latest_official_odds(collector):
    rows = collector.d1_query(
        """
        SELECT bet_type AS betType,combination,odds_min AS oddsMin,odds_max AS oddsMax,
               captured_at_utc AS capturedAtUtc,source_url AS sourceUrl
        FROM rt_official_odds_latest
        WHERE race_id=?
        ORDER BY bet_type,combination
        """,
        [base.RACE_ID],
    )
    by_type = {}
    captured = {}
    odds = {}
    for row in rows:
        bet_type = str(row.get("betType") or "")
        combo = str(row.get("combination") or "")
        if bet_type not in base.BET_TYPES or not combo:
            continue
        lo = float(row.get("oddsMin") or 0)
        hi = float(row.get("oddsMax") or 0)
        value = (lo + hi) / 2.0
        if value <= 0:
            continue
        odds[(base.RACE_ID, bet_type, combo)] = value
        by_type[bet_type] = by_type.get(bet_type, 0) + 1
        captured[bet_type] = str(row.get("capturedAtUtc") or "")
    missing = [bet_type for bet_type in base.BET_TYPES if by_type.get(bet_type, 0) == 0]
    if missing:
        raise RuntimeError(f"LATEST_OFFICIAL_ODDS_MISSING:{base.RACE_ID}:{missing}:{by_type}")
    return odds, captured


base.predeadline_odds = latest_official_odds
base.main()

collector = base.load(ROOT / "scripts" / "collect-jra-official-odds.py", "recovery_audit_collector")
for key in (f"worker_live_final:{base.RACE_ID}", f"recovery_predeadline:{base.RACE_ID}"):
    rows = collector.d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [key])
    if not rows or not rows[0].get("value"):
        continue
    payload = json.loads(str(rows[0]["value"]))
    payload["postCutoffOddsUsed"] = True
    payload["oddsRecoveryMode"] = "latest_saved_official_odds"
    collector.d1_query(
        """
        INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        [key, json.dumps(payload, ensure_ascii=False)],
    )

artifact = ROOT / "analysis-results" / f"predeadline-recovery-{base.RACE_ID}.json"
if artifact.exists():
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["postCutoffOddsUsed"] = True
    payload["oddsRecoveryMode"] = "latest_saved_official_odds"
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
