#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label} missing required marker: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label} contains forbidden marker: {needle}")


def main() -> None:
    wrangler = json.loads(read("wrangler.jsonc"))
    crons = wrangler.get("triggers", {}).get("crons", [])
    if crons != ["* * * * *"]:
        raise AssertionError(f"production Worker cron must be exactly every minute, got {crons!r}")

    worker = read("src/v1/completed-worker-live-lock.ts")
    for needle in (
        'const PREVIEW_PREFIX = "worker_live_preview:";',
        'const FINAL_PREFIX = "worker_live_final:";',
        'const PREVIEW_OPEN_MS = 45 * 60 * 1000;',
        'const FINALIZE_OPEN_MS = 17 * 60 * 1000;',
        'const DEADLINE_MS = 15 * 60 * 1000;',
        'const PREVIEW_HISTORY = 3;',
        'oddsSnapshotSha256',
        'await savePreview(db, snapshot)',
        'fresh ?? await latestPreview(env.DB, raceId)',
        '"deadline_watchdog"',
        'await db.batch(statements)',
        'if (isStrictComplete(existing)) return;',
    ):
        require(worker, needle, "Worker live-lock")

    canonical = read("scripts/run-ten-year-auto-final-live.py")
    require(canonical, "base.MIN_LOCK_SECONDS=15*60", "canonical GitHub fallback")
    require(canonical, "base.MAX_LOCK_SECONDS=17*60", "canonical GitHub fallback")

    emergency = read("scripts/run-emergency-earliest-missing-bet.py")
    require(emergency, "RECOVERY_OPEN_SECONDS = 17 * 60", "emergency fallback")
    require(emergency, '"status":"waiting_emergency_window"', "emergency fallback")

    critical_script = read("scripts/run-critical-auto-bet-generation.py")
    require(critical_script, "RECOVERY_OPEN_SECONDS = 17 * 60", "manual critical recovery")
    require(critical_script, "base.MAX_LOCK_SECONDS = RECOVERY_OPEN_SECONDS", "manual critical recovery")

    critical_workflow = read(".github/workflows/critical-auto-bet-generation.yml")
    require(critical_workflow, "workflow_dispatch:", "critical recovery workflow")
    forbid(critical_workflow, "schedule:", "critical recovery workflow")

    print(
        "LIVE_LOCK_SAFETY_OK",
        "worker_cron=1m",
        "preview_open=45m",
        "preview_history=3",
        "finalize_open=17m",
        "deadline=15m",
        "github_fallback=17m",
        "emergency_fallback=17m",
        "critical_schedule=disabled",
    )


if __name__ == "__main__":
    main()
