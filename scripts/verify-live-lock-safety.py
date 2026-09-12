#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(source: str, needle: str, label: str) -> None:
    require(needle in source, f"{label} missing required marker: {needle}")


def forbid_text(source: str, needle: str, label: str) -> None:
    require(needle not in source, f"{label} contains forbidden marker: {needle}")


def config(path: str) -> dict:
    return json.loads(read(path))


def main() -> None:
    public_cfg = config("wrangler.jsonc")
    primary_cfg = config("wrangler.live-deadline.jsonc")
    backup_cfg = config("wrangler.live-deadline-backup.jsonc")

    public_main = str(public_cfg.get("main") or "")
    primary_main = str(primary_cfg.get("main") or "")
    backup_main = str(backup_cfg.get("main") or "")

    allowed_public_entries = {
        "src/public-site-entry-recovery-20260906.ts",
        "src/public-site-entry-quota-recovery-20260912.ts",
    }
    require(public_main in allowed_public_entries, f"unexpected public entry: {public_main}")
    require(primary_main == backup_main, "primary/backup must use the exact same live entry")
    require(primary_main == "src/live-deadline-entry-v3.ts", f"unexpected live entry: {primary_main}")
    require(primary_cfg.get("triggers", {}).get("crons", []) == ["* * * * *"], "primary cron must remain every minute")
    require(backup_cfg.get("triggers", {}).get("crons", []) == ["2-59/5 * * * *"], "backup cron must remain every five minutes")
    require(primary_cfg.get("vars", {}).get("LIVE_DEADLINE_ROLE") == "primary", "primary role mismatch")
    require(backup_cfg.get("vars", {}).get("LIVE_DEADLINE_ROLE") == "backup", "backup role mismatch")

    public = read(public_main)
    public_sources = {public_main: public}
    if public_main == "src/public-site-entry-quota-recovery-20260912.ts":
        for needle in (
            'import recovery from "./public-site-entry-recovery-20260906.js";',
            "RECENT_PUBLIC_DAY_SNAPSHOT",
            'date === "2026-09-12"',
            "PUBLIC_D1_READ_LOCKOUT_SKIP",
            'fallbackSource: "recent-public-day-snapshot-v1-quota-lockout"',
            "if (recovery.scheduled) await recovery.scheduled(controller, env, ctx);",
        ):
            require_text(public, needle, "public quota recovery")
        lockout = public.index('if (date === "2026-09-12")')
        lockout_return = public.index("return;", lockout)
        delegated_schedule = public.index("recovery.scheduled", lockout_return)
        require(lockout < lockout_return < delegated_schedule, "public quota lockout must return before delegated D1 maintenance")
        public_sources["src/public-site-entry-recovery-20260906.ts"] = read("src/public-site-entry-recovery-20260906.ts")

    for path, source in public_sources.items():
        for forbidden in (
            "runCompletedWorkerLiveLock",
            "runCompletedWorkerDeadlineGuard",
            "runDirectLiveTick",
            "publicSite.scheduled",
            "CREATE TABLE",
            "CREATE INDEX",
            "CREATE TRIGGER",
        ):
            forbid_text(source, forbidden, f"public Worker live isolation: {path}")

    live_entry = read(primary_main)
    for needle in (
        "await shouldRunOnJraRaceDay",
        "if (!raceDay.shouldRun)",
        'PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v1"',
        "PRIMARY_STALE_SECONDS = 150",
        'if (role === "backup")',
        "if (await primaryIsAlive(env.DB)) return;",
        "LIVE_DEADLINE_BACKUP_TAKEOVER",
        "function isHistoricalRecencyScan",
        "function freeTierSafeDb",
        "function safeEnv",
        "LIVE_RECENCY_HISTORY_SCAN_SKIPPED_FREE_TIER",
        "const liveEnv = safeEnv(env);",
        "await liveDeadlineV2.scheduled(controller, liveEnv);",
    ):
        require_text(live_entry, needle, "live entry")
    require(live_entry.count("await liveDeadlineV2.scheduled(controller, liveEnv);") >= 2, "primary and backup must both use free-tier safe DB wrapper")
    forbid_text(live_entry, "await liveDeadlineV2.scheduled(controller, env);", "live entry raw DB path")

    runtime_schema_sensitive = {
        primary_main: live_entry,
        "src/live-deadline-entry-v2.ts": read("src/live-deadline-entry-v2.ts"),
        "src/v1/live-preview-safety.ts": read("src/v1/live-preview-safety.ts"),
        "src/v1/completed-final-invariants.ts": read("src/v1/completed-final-invariants.ts"),
        "src/v1/completed-worker-live-lock.ts": read("src/v1/completed-worker-live-lock.ts"),
        "src/v1/completed-worker-deadline-guard.ts": read("src/v1/completed-worker-deadline-guard.ts"),
    }
    for path, source in runtime_schema_sensitive.items():
        for forbidden in ("FROM sqlite_master", "PRAGMA table_info", "PRAGMA index_", "PRAGMA trigger_", "CREATE TABLE", "CREATE INDEX", "CREATE TRIGGER", "DROP TRIGGER"):
            forbid_text(source, forbidden, f"race-day runtime schema isolation: {path}")

    safety = runtime_schema_sensitive["src/v1/live-preview-safety.ts"]
    for needle in (
        "rt_live_deadline_lease",
        "acquireLiveDeadlineLease",
        "releaseLiveDeadlineLease",
        "restoreNewestOfficialPreviewArchives",
        "SLA_HEARTBEAT_INTERVAL_MS = 3 * 60_000",
        "persistSlaAuditIfNeeded",
        "previewMissingByT40RaceIds",
        "finalMissingByT30RaceIds",
        "finalMissingByT25RaceIds",
        "finalMissingByT16RaceIds",
        "deadlineMissedRaceIds",
    ):
        require_text(safety, needle, "live preview safety")
    require_text(safety, "export async function ensureLivePreviewSafetySchema(_db: D1Database)", "schema compatibility hook")

    invariants = runtime_schema_sensitive["src/v1/completed-final-invariants.ts"]
    require_text(invariants, "export async function ensureCompletedFinalImmutability(_db: D1Database)", "final invariant compatibility hook")

    driver = runtime_schema_sensitive["src/live-deadline-entry-v2.ts"]
    for needle in (
        "acquireLiveDeadlineLease",
        "runCompletedWorkerDeadlineGuard",
        "runCompletedWorkerLiveLock",
        "runUpcomingEntryDerivedRepair",
        "selection_critical",
        "predeadline_critical",
        "LIVE_DEADLINE_HARD_T15_BREACH",
        "slaAfter.previewMissingByT40RaceIds",
        "slaAfter.finalMissingByT30RaceIds",
        "slaAfter.finalMissingByT25RaceIds",
    ):
        require_text(driver, needle, "isolated live deadline driver")
    forbid_text(driver, "/_ops/live-tick", "isolated live deadline driver")

    lock = runtime_schema_sensitive["src/v1/completed-worker-live-lock.ts"]
    for needle in (
        'const PREVIEW_PREFIX = "worker_live_preview:";',
        'const FINAL_PREFIX = "worker_live_final:";',
        "PREVIEW_OPEN_MS = 90 * 60 * 1000",
        "FINAL_LOCK_ARM_MS = 30 * 60 * 1000",
        "DEADLINE_MS = 15 * 60 * 1000",
        "FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000",
        "MAX_PREVIEW_GENERATIONS_PER_TICK = 1",
        "WORKER_HARD_T15_START_MISSED",
        "WORKER_FRESH_GENERATION_STARTED_AFTER_T15",
        "WORKER_GENERATION_CROSSED_T10",
        "JRA_OFFICIAL_ODDS_PARSER_VERSION",
        'new Set(["jra-fast-official", "jra-crawl-official"])',
    ):
        require_text(lock, needle, "isolated live lock")
    forbid_text(lock, "chooseCompletedProbabilityFallbackTickets", "probability fallback")

    guard = runtime_schema_sensitive["src/v1/completed-worker-deadline-guard.ts"]
    for needle in (
        "DEADLINE_GUARD_MS = 15 * 60 * 1000",
        "DEADLINE_GUARD_ARM_MS = 25 * 60 * 1000",
        "FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000",
        "isDeadlineGuardMissed",
        "DEADLINE_GUARD_T15_MISSED",
        "JRA_OFFICIAL_ODDS_PARSER_VERSION",
        'snapshot.oddsSource !== "jra-fast-official" && snapshot.oddsSource !== "jra-crawl-official"',
    ):
        require_text(guard, needle, "persistent deadline guard")
    forbid_text(guard, "chooseCompletedProbabilityFallbackTickets", "deadline guard probability fallback")

    migration_sql = read("scripts/install-race-day-runtime-guards.sql")
    for needle in (
        "rt_live_preview_archive",
        "idx_live_preview_archive_race_id",
        "rt_live_deadline_lease",
        "rt_guard_final_bet_insert_deadline",
        "rt_guard_final_state_insert_deadline",
        "rt_guard_official_odds_final_insert",
        "rt_guard_probability_fallback_final_insert",
        "rt_ignore_unchanged_system_state",
        "rt_ignore_unchanged_runner",
        "rt_ignore_unchanged_race",
    ):
        require_text(migration_sql, needle, "deploy-time D1 guards")

    migration = read(".github/workflows/migrate-live-runtime-guards.yml")
    require_text(migration, "wrangler d1 execute race-tantei-phase0 --remote", "D1 migration workflow")
    require_text(migration, "Verify required guards", "D1 migration workflow")

    deploy = read(".github/workflows/deploy-live-deadline.yml")
    require_text(deploy, "Deploy primary live deadline Worker", "live deploy")
    require_text(deploy, "Deploy backup live deadline Worker", "live deploy")
    for forbidden in ("wrangler d1 execute", "scripts/install-race-day-runtime-guards.sql"):
        forbid_text(deploy, forbidden, "normal live deploy must not touch D1 schema")

    readiness = read(".github/workflows/verify-live-deadline-production.yml")
    for needle in (
        "race-tantei-live-deadline.race-tantei.workers.dev/health",
        "race-tantei-live-deadline-backup.race-tantei.workers.dev/health",
        "race-tantei-phase0.race-tantei.workers.dev/_ops/live-tick",
        "rt_live_preview_archive",
        "rt_live_deadline_lease",
        "production/live-deadline-readiness",
    ):
        require_text(readiness, needle, "production readiness")

    for obsolete in (".github/workflows/drive-live-tick.yml", ".github/workflows/auto-final-live-bets.yml"):
        require(not (ROOT / obsolete).exists(), f"obsolete workflow must remain removed: {obsolete}")

    print("LIVE_LOCK_SAFETY_OK runtime_schema_probe=false runtime_ddl=false primary=1m backup=5m public_live_mutation=false free_tier_historical_scan=false")


if __name__ == "__main__":
    main()
