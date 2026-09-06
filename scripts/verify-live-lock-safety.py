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


def require_missing(path: str, label: str) -> None:
    if (ROOT / path).exists():
        raise AssertionError(f"{label} must be removed: {path}")


def verify_public_entry(public_main: str) -> None:
    if public_main == "src/public-site-entry-v37.ts":
        raise AssertionError("public v37 core scheduler still contains legacy race-day DDL; use bounded wrapper until core is migrated")
    if public_main != "src/public-site-entry-recovery-20260906.ts":
        raise AssertionError(f"unexpected public Worker entry: {public_main!r}")

    recovery = read(public_main)
    for needle in (
        'import publicSite from "./public-site-entry-v37.js";',
        'import { runUpcomingCalendarRepair } from "./v1/upcoming-calendar-repair.js";',
        'import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";',
        'import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";',
        'const RECOVERY_PATH = "/_ops/entry-seed-sync-20260906-7f4c9d2a";',
        'request.method === "POST" && url.pathname === RECOVERY_PATH',
        'runConfiguredEntrySeedWriteOnly(env, "2026-09-06")',
        "runBoundedPublicMaintenance",
        "await runUpcomingCalendarRepair(env, now)",
        "await runUpcomingEntryWorkerRepair(env, now)",
        "await runUpcomingEntryDerivedRepair(env, now)",
    ):
        require(recovery, needle, "temporary public recovery wrapper")
    forbid(recovery, "publicSite.scheduled", "public scheduler legacy-DDL isolation")
    for forbidden in (
        "rt_public_bets",
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "runDirectLiveTick",
        "live-deadline-entry",
        "completed-worker-live-lock",
        "CREATE INDEX",
        "CREATE TABLE",
        "CREATE TRIGGER",
    ):
        forbid(recovery, forbidden, "temporary public recovery wrapper live isolation")

    runner_recovery = read("src/v1/configured-entry-seed-write-only.ts")
    require(runner_recovery, "INSERT INTO rt_runners", "temporary runner recovery")
    require(runner_recovery, "WHERE rt_runners.frame_no IS NOT excluded.frame_no", "runner no-op write guard")
    for forbidden in (
        "rt_public_bets",
        "rt_official_odds_latest",
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
    ):
        forbid(runner_recovery, forbidden, "temporary runner recovery live isolation")


def main() -> None:
    public_wrangler = json.loads(read("wrangler.jsonc"))
    primary_wrangler = json.loads(read("wrangler.live-deadline.jsonc"))
    backup_wrangler = json.loads(read("wrangler.live-deadline-backup.jsonc"))

    verify_public_entry(str(public_wrangler.get("main") or ""))
    if public_wrangler.get("triggers", {}).get("crons", []) != ["*/15 * * * *"]:
        raise AssertionError("public maintenance Worker cron must remain every fifteen minutes")
    if primary_wrangler.get("name") != "race-tantei-live-deadline":
        raise AssertionError("primary live deadline Worker name mismatch")
    if primary_wrangler.get("main") != "src/live-deadline-entry-v3.ts":
        raise AssertionError("primary live deadline Worker must use v3 index-gated entry")
    if primary_wrangler.get("triggers", {}).get("crons", []) != ["* * * * *"]:
        raise AssertionError("primary live deadline Worker must run every minute")
    if primary_wrangler.get("vars", {}).get("LIVE_DEADLINE_ROLE") != "primary":
        raise AssertionError("primary live deadline Worker role mismatch")
    if backup_wrangler.get("name") != "race-tantei-live-deadline-backup":
        raise AssertionError("backup live deadline Worker name mismatch")
    if backup_wrangler.get("main") != "src/live-deadline-entry-v3.ts":
        raise AssertionError("backup live deadline Worker must use the exact same v3 entry/parser")
    if backup_wrangler.get("triggers", {}).get("crons", []) != ["2-59/5 * * * *"]:
        raise AssertionError("backup standby must check primary health every five minutes")
    if backup_wrangler.get("vars", {}).get("LIVE_DEADLINE_ROLE") != "backup":
        raise AssertionError("backup live deadline Worker role mismatch")

    gate = read("src/live-deadline-entry-v3.ts")
    for needle in (
        "rt_idx_ml_horse_hist_lookup",
        "rt_idx_ml_horse_total_lookup",
        "rt_idx_ml_horse_surface_lookup",
        "rt_idx_ml_horse_dist_lookup",
        "rt_idx_ml_horse_venue_lookup",
        "rt_idx_ml_jockey_lookup",
        "rt_idx_ml_trainer_lookup",
        "rt_idx_ml_pair_lookup",
        "LIVE_DEADLINE_WAITING_FOR_INDEXES",
        'PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v1"',
        "PRIMARY_STALE_SECONDS = 150",
        "markPrimaryAlive",
        "primaryIsAlive",
        'if (role === "backup")',
        "LIVE_DEADLINE_BACKUP_TAKEOVER",
        "if (await primaryIsAlive(env.DB)) return;",
        "await liveDeadlineV2.scheduled(controller, env);",
    ):
        require(gate, needle, "v3 primary/standby gate")
    for forbidden in ("CREATE TABLE", "CREATE INDEX", "CREATE TRIGGER", "DROP TRIGGER"):
        forbid(gate, forbidden, "v3 race-day DDL isolation")

    live = read("src/v1/completed-worker-live-lock.ts")
    for needle in (
        'const PREVIEW_PREFIX = "worker_live_preview:";',
        'const FINAL_PREFIX = "worker_live_final:";',
        'const PREVIEW_OPEN_MS = 90 * 60 * 1000;',
        'const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;',
        'const FINAL_LOCK_ARM_MS = 30 * 60 * 1000;',
        'const DEADLINE_MS = 15 * 60 * 1000;',
        'const FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000;',
        'new Set(["jra-fast-official", "jra-crawl-official"])',
        "JRA_OFFICIAL_ODDS_PARSER_VERSION",
        "livePreviewPriorityRank",
        "MAX_PREVIEW_GENERATIONS_PER_TICK",
        "cachedWorkerModel",
        "previewMissingUrgentRaceIds",
        "WORKER_HARD_T15_START_MISSED",
        "ids.length !== 15",
        "counts.size !== 3",
        "startMs - generationStartedMs <= DEADLINE_MS",
        "if (remaining <= DEADLINE_MS)",
        "WORKER_GENERATION_CROSSED_T10",
        "await db.batch(statements)",
        "if (isStrictComplete(existing)) return;",
    ):
        require(live, needle, "isolated live lock")
    forbid(live, "probability_fallback", "isolated live lock")
    forbid(live, "const ODDS_PARSER_VERSION", "isolated live lock parser provenance")

    guard = read("src/v1/completed-worker-deadline-guard.ts")
    for needle in (
        "export const DEADLINE_GUARD_MS = 15 * 60 * 1000;",
        "export const DEADLINE_GUARD_ARM_MS = 25 * 60 * 1000;",
        "remainingMs >= DEADLINE_GUARD_MS",
        "remainingMs <= DEADLINE_GUARD_ARM_MS",
        "isDeadlineGuardMissed",
        "deadlineMissedRaceIds",
        'snapshot.oddsSource !== "jra-fast-official" && snapshot.oddsSource !== "jra-crawl-official"',
        "JRA_OFFICIAL_ODDS_PARSER_VERSION",
        "ensureCompletedFinalImmutability",
    ):
        require(guard, needle, "persistent deadline guard")
    forbid(guard, "const ODDS_PARSER_VERSION", "persistent deadline guard parser provenance")
    for forbidden in (
        "fetch(",
        "probability_fallback_persistent_deadline_guard",
        "chooseCompletedProbabilityFallbackTickets",
        "loadCompletedFeatureStateForRace",
        "loadCompletedRecencyLearning",
    ):
        forbid(guard, forbidden, "persistent deadline guard")

    invariants = read("src/v1/completed-final-invariants.ts")
    for needle in (
        "sqlite_master",
        "FINAL_BET_REFLECTION_WINDOW_PASSED",
        "FINAL_STATE_REFLECTION_WINDOW_PASSED",
        "IMMUTABLE_FINAL_BET_TERMS",
        "IMMUTABLE_WORKER_FINAL_STATE",
        "PROBABILITY_FALLBACK_FORBIDDEN",
        "OFFICIAL_JRA_ODDS_REQUIRED",
        "FINAL_INVARIANT_TRIGGER_MISSING",
    ):
        require(invariants, needle, "D1 finalization invariant verifier")
    for forbidden in ("db.prepare(`CREATE TRIGGER", "db.prepare('DROP TRIGGER", "db.prepare(`DROP TRIGGER"):
        forbid(invariants, forbidden, "runtime invariant DDL")

    safety = read("src/v1/live-preview-safety.ts")
    for needle in (
        "rt_live_preview_archive",
        "idx_live_preview_archive_race_id",
        "rt_live_deadline_lease",
        "acquireLiveDeadlineLease",
        "restoreNewestOfficialPreviewArchives",
        "LIVE_PREVIEW_SCHEMA_MISSING",
        "SLA_HEARTBEAT_INTERVAL_MS = 3 * 60_000",
        "persistSlaAuditIfNeeded",
        "previewMissingByT40RaceIds",
        "previewMissingByT30RaceIds",
        "finalMissingByT30RaceIds",
        "finalMissingByT25RaceIds",
        "finalMissingByT17RaceIds",
        "finalMissingByT16RaceIds",
        "deadlineMissedRaceIds",
    ):
        require(safety, needle, "live preview safety")
    for forbidden in ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS", "CREATE TRIGGER IF NOT EXISTS"):
        forbid(safety, forbidden, "live preview race-day DDL")
    forbid(safety, "rt_archive_live_preview_insert", "automatic preview archive write amplification")
    forbid(safety, "rt_archive_live_preview_update", "automatic preview archive write amplification")

    driver = read("src/live-deadline-entry-v2.ts")
    for needle in (
        "acquireLiveDeadlineLease",
        "restoreNewestOfficialPreviewArchives",
        "auditLiveDeadlineSla",
        "runCompletedWorkerDeadlineGuard",
        "runCompletedWorkerLiveLock",
        "runUpcomingEntryDerivedRepair",
        "selection_critical",
        "predeadline_critical",
        "LIVE_DEADLINE_HARD_T15_BREACH",
        "slaAfter.previewMissingByT40RaceIds",
        "slaAfter.finalMissingByT30RaceIds",
        "slaAfter.finalMissingByT25RaceIds",
        'return new Response("NOT_FOUND", { status: 404 });',
    ):
        require(driver, needle, "isolated live deadline driver")
    forbid(driver, "/_ops/live-tick", "isolated live deadline driver")

    public29 = read("src/public-site-entry-v29.ts")
    for forbidden in (
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "ensureCompletedRaceFinalAtDeadline",
        "probability_fallback",
    ):
        forbid(public29, forbidden, "public v29")
    require(public29, "runCompletedWin5Scheduled", "public v29")
    require(public29, "if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);", "public v29")

    public34 = read("src/public-site-entry-v34.ts")
    for forbidden in (
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "runDirectLiveTick",
        "shouldOpportunisticallyDrive",
    ):
        forbid(public34, forbidden, "public v34")
    require(public34, 'pathname === "/_ops/live-tick"', "public v34")
    require(public34, "status: 404", "public v34")

    public37 = read("src/public-site-entry-v37.ts")
    public37_core = read("src/public-site-entry-v37-core.ts")
    require(public37, 'import core from "./public-site-entry-v37-core.js";', "public v37 wrapper")
    require(public37, 'pathname === "/_ops/live-tick"', "public v37 live isolation")
    require(public37, "status: 404", "public v37 live isolation")
    for needle in (
        "runPublicMaintenance",
        "runUpcomingCalendarRepair",
        "runUpcomingEntryWorkerRepair",
        "runUpcomingEntryDerivedRepair",
    ):
        require(public37_core, needle, "public v37 core maintenance")
    for forbidden in (
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "runDirectLiveTick",
        "shouldOpportunisticallyDrive",
    ):
        forbid(public37, forbidden, "public v37 wrapper live isolation")
        forbid(public37_core, forbidden, "public v37 core live isolation")

    require_missing(".github/workflows/drive-live-tick.yml", "obsolete public live driver")
    require_missing(".github/workflows/auto-final-live-bets.yml", "obsolete stored-preview finalizer")

    schema = read("scripts/install-race-day-runtime-guards.sql")
    for needle in (
        "rt_live_deadline_lease",
        "DROP TRIGGER IF EXISTS rt_archive_live_preview_insert",
        "DROP TRIGGER IF EXISTS rt_archive_live_preview_update",
        "rt_guard_final_bet_insert_deadline",
        "rt_guard_final_state_insert_deadline",
        "rt_ignore_unchanged_system_state",
        "rt_ignore_unchanged_runner",
        "rt_ignore_unchanged_race",
        "rt_ignore_unchanged_race_source",
    ):
        require(schema, needle, "deploy-time D1 runtime guards")

    deploy = read(".github/workflows/deploy-live-deadline.yml")
    for needle in (
        "Deploy primary live deadline Worker",
        "Deploy backup live deadline Worker",
        "src/live-deadline-entry-v3.ts",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "production/live-deadline",
    ):
        require(deploy, needle, "dual live deadline deploy")

    for forbidden in ("wrangler d1 execute", "scripts/install-race-day-runtime-guards.sql"):
        forbid(deploy, forbidden, "normal live deploy must not touch D1 schema")

    migration = read(".github/workflows/migrate-live-runtime-guards.yml")
    for needle in (
        "scripts/install-race-day-runtime-guards.sql",
        "wrangler d1 execute race-tantei-phase0 --remote",
        "Verify required guards",
    ):
        require(migration, needle, "separate live D1 migration")

    readiness = read(".github/workflows/verify-live-deadline-production.yml")
    for needle in (
        "race-tantei-live-deadline.race-tantei.workers.dev/health",
        "race-tantei-live-deadline-backup.race-tantei.workers.dev/health",
        "race-tantei-phase0.race-tantei.workers.dev/_ops/live-tick",
        "rt_live_preview_archive",
        "rt_live_deadline_lease",
        "production/live-deadline-readiness",
    ):
        require(readiness, needle, "production readiness audit")

    fast = read("src/v1/jra-official-odds-fetch.ts")
    for needle in (
        "const FETCH_BUDGET_MS = 25_000;",
        "JRA_ODDS_FETCH_BUDGET_EXHAUSTED",
        "deadlineMs",
        'export const JRA_OFFICIAL_ODDS_PARSER_VERSION = "jra-semantic-table-parser-v3-20260823";',
    ):
        require(fast, needle, "JRA official odds fetch")
    crawl = read("src/v1/jra-official-odds.ts")
    for needle in (
        "const CRAWL_PAGE_TIMEOUT_MS = 3_500;",
        "JRA_ODDS_CRAWL_BUDGET_EXHAUSTED",
    ):
        require(crawl, needle, "JRA official odds crawl")

    watchdog = read(".github/workflows/ensure-auto-final-live.yml")
    require(watchdog, "preview_coverage_ok", "automatic live watchdog")
    require(watchdog, "minutesToStart > 17 AND minutesToStart <= 40", "automatic live watchdog")
    require(readiness, "PREVIEW_T40_COVERAGE_OK", "production readiness audit")
    for persistent_workflow in (
        ".github/workflows/ensure-auto-final-live.yml",
        ".github/workflows/verify-live-deadline-production.yml",
        ".github/workflows/deploy-live-deadline.yml",
        ".github/workflows/critical-auto-bet-generation.yml",
    ):
        workflow_text = read(persistent_workflow)
        for obsolete in ("auto-final-live-bets.yml", "drive-live-tick.yml"):
            forbid(workflow_text, obsolete, persistent_workflow)

    critical_workflow = read(".github/workflows/critical-auto-bet-generation.yml")
    require(critical_workflow, "workflow_dispatch:", "critical recovery workflow")
    forbid(critical_workflow, "schedule:", "critical recovery workflow")

    print(
        "LIVE_LOCK_SAFETY_OK",
        "public_maintenance_cron=15m_bounded_no_ddl",
        "primary_cron=1m",
        "backup_cron=1m_true_standby",
        "backup_takeover_after=150s",
        "runtime_ddl=false",
        "preview_auto_archive=false",
        "unchanged_runner_writes=false",
        "preview_open=90m",
        "preview_required=30m",
        "public_final_target=30m",
        "rescue_guard_arm=25m",
        "generation_start_deadline=15m_hard",
        "fresh_reflection_deadline=10m_hard",
        "official_jra_odds_required=true",
        "probability_fallback_forbidden=true",
        "public_live_mutation=false",
        "post_t15_creation=false",
        "critical_schedule=disabled",
    )


if __name__ == "__main__":
    main()
