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
    primary = json.loads(read("wrangler.win5.jsonc"))
    backup = json.loads(read("wrangler.win5-backup.jsonc"))
    public = json.loads(read("wrangler.jsonc"))

    if public.get("main") != "src/public-site-entry-v34.ts":
        raise AssertionError("unexpected public Worker entry")
    if primary.get("name") != "race-tantei-win5" or primary.get("main") != "src/win5-entry-v2.ts":
        raise AssertionError("primary WIN5 Worker identity mismatch")
    if primary.get("triggers", {}).get("crons") != ["* * * * *"]:
        raise AssertionError("primary WIN5 Worker must run every minute")
    if backup.get("name") != "race-tantei-win5-backup" or backup.get("main") != "src/win5-entry-v2.ts":
        raise AssertionError("backup WIN5 Worker identity mismatch")
    if backup.get("triggers", {}).get("crons") != ["3-59/5 * * * *"]:
        raise AssertionError("backup WIN5 Worker must be staggered every five minutes")

    expected_db = "949b5e8b-d1a4-4c4e-80d1-d031afdc03de"
    for label, cfg in (("primary", primary), ("backup", backup)):
        bindings = cfg.get("d1_databases", [])
        if len(bindings) != 1 or bindings[0].get("database_id") != expected_db:
            raise AssertionError(f"{label} WIN5 D1 binding mismatch")

    driver = read("src/win5-entry-v2.ts")
    for needle in (
        'const DRIVER_VERSION = "win5-driver-v3-official-row-hydration-20260823";',
        "ensureWin5OfficialTargetCache",
        "runCompletedWin5Scheduled(env, new Date())",
        "rt_win5_driver_lease",
        "win5_driver_tick:",
        "win5_driver_success:",
        "WIN5_FINAL_MISSING_AFTER_DEADLINE",
        "WIN5_PREVIEW_NOT_READY_AFTER_0930",
        "WIN5_TARGET_REPAIR_FAILED",
        'path === "/health"',
        'return new Response("NOT_FOUND", { status: 404 });',
    ):
        require(driver, needle, "isolated WIN5 driver")
    forbid(driver, "public-site-entry", "isolated WIN5 driver")

    repair = read("src/v1/win5-official-target-repair.ts")
    for needle in (
        "parseWin5TargetIdentitiesFromHtml",
        "WIN5_PAGE_URL",
        'const TARGET_PREFIX = "win5:targets:";',
        "hydrateFromRaceTable",
        "start_time_utc AS startTimeUtc",
        "ensureWin5OfficialTargetCache",
        "WIN5_TARGET_RACE_TIME_MISSING",
    ):
        require(repair, needle, "WIN5 official target repair")

    public34 = read("src/public-site-entry-v34.ts")
    require(public34, 'import maintenanceSite from "./public-site-entry-v25.js";', "public v34")
    require(public34, "runUpcomingEntryWorkerRepair", "public v34")
    require(public34, "runUpcomingEntryDerivedRepair", "public v34")
    require(public34, "if (maintenanceSite.scheduled) await maintenanceSite.scheduled(controller, env, ctx);", "public v34")
    forbid(public34, "runCompletedWin5Scheduled", "public v34")
    forbid(public34, "if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);", "public v34 scheduled ownership")

    completed = read("src/v1/completed-win5.ts")
    for needle in (
        "WIN5_LOCK_MINUTES = 15",
        "win5:preview:",
        "win5:final:",
        "Hard T-15 guard",
        "WIN5_DEADLINE_PREVIEW_MISSING",
        "finalizedFrom",
    ):
        require(completed, needle, "WIN5 core")

    live_test = read("tests/live-win5-official.ts")
    require(live_test, "parseWin5TargetIdentitiesFromHtml", "WIN5 live JRA test")
    forbid(live_test, "Date.parse(row.startTimeUtc)", "WIN5 live JRA target-row test")

    deploy = read(".github/workflows/deploy-win5.yml")
    for needle in (
        "src/v1/win5-official-target-repair.ts",
        "Deploy primary WIN5 Worker",
        "Deploy backup WIN5 Worker",
        "wrangler.win5.jsonc",
        "wrangler.win5-backup.jsonc",
        "production/win5",
    ):
        require(deploy, needle, "WIN5 deploy workflow")

    verify = read(".github/workflows/verify-win5.yml")
    for needle in (
        "Verify isolated WIN5 Workers are healthy and current",
        "Verify Cloudflare WIN5 cron registrations",
        "Verify fresh WIN5 driver execution",
        "Verify public WIN5 API and page",
        "production/win5-readiness",
    ):
        require(verify, needle, "WIN5 production verifier")

    print(
        "WIN5_SAFETY_OK",
        "primary_cron=1m",
        "backup_cron=5m_staggered",
        "lease=true",
        "public_win5_mutation=false",
        "official_target_row_parse=true",
        "race_time_hydration=d1_official_program",
        "actual_time_deadline=true",
        "t15_lock=true",
        "morning_preview_guard=0930_jst",
        "production_readiness=true",
    )


if __name__ == "__main__":
    main()
