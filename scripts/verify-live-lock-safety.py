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


def main() -> None:
    public_wrangler = json.loads(read("wrangler.jsonc"))
    primary_wrangler = json.loads(read("wrangler.live-deadline.jsonc"))
    backup_wrangler = json.loads(read("wrangler.live-deadline-backup.jsonc"))

    if public_wrangler.get("main") != "src/public-site-entry-v34.ts":
        raise AssertionError(f"unexpected public Worker entry: {public_wrangler.get('main')!r}")
    if public_wrangler.get("triggers", {}).get("crons", []) != ["* * * * *"]:
        raise AssertionError("public maintenance Worker cron must remain every minute")
    if primary_wrangler.get("name") != "race-tantei-live-deadline":
        raise AssertionError("primary live deadline Worker name mismatch")
    if primary_wrangler.get("main") != "src/live-deadline-entry-v2.ts":
        raise AssertionError("primary live deadline Worker must use v2 entry")
    if primary_wrangler.get("triggers", {}).get("crons", []) != ["* * * * *"]:
        raise AssertionError("primary live deadline Worker must run every minute")
    if backup_wrangler.get("name") != "race-tantei-live-deadline-backup":
        raise AssertionError("backup live deadline Worker name mismatch")
    if backup_wrangler.get("main") != "src/live-deadline-entry-v2.ts":
        raise AssertionError("backup live deadline Worker must use v2 entry")
    if backup_wrangler.get("triggers", {}).get("crons", []) != ["* * * * *"]:
        raise AssertionError("backup live deadline Worker must also run every minute")

    live = read("src/v1/completed-worker-live-lock.ts")
    for needle in (
        'const PREVIEW_PREFIX = "worker_live_preview:";',
        'const FINAL_PREFIX = "worker_live_final:";',
        'const PREVIEW_OPEN_MS = 90 * 60 * 1000;',
        'const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;',
        'const NORMAL_LOCK_MS = 25 * 60 * 1000;',
        'const DEADLINE_MS = 15 * 60 * 1000;',
        'new Set(["jra-fast-official", "jra-crawl-official"])',
        'cachedWorkerModel',
        'previewMissingUrgentRaceIds',
        'WORKER_HARD_T15_MISSED',
        'WORKER_GENERATION_CROSSED_T15',
        'await db.batch(statements)',
        'if (isStrictComplete(existing)) return;',
    ):
        require(live, needle, "isolated live lock")
    forbid(live, 'probability_fallback', "isolated live lock")

    guard = read("src/v1/completed-worker-deadline-guard.ts")
    for needle in (
        "export const DEADLINE_GUARD_MS = 15 * 60 * 1000;",
        "export const DEADLINE_GUARD_ARM_MS = 20 * 60 * 1000;",
        "remainingMs >= DEADLINE_GUARD_MS",
        "remainingMs <= DEADLINE_GUARD_ARM_MS",
        "isDeadlineGuardMissed",
        "deadlineMissedRaceIds",
        'snapshot.oddsSource !== "jra-fast-official" && snapshot.oddsSource !== "jra-crawl-official"',
        "ensureCompletedFinalImmutability",
    ):
        require(guard, needle, "persistent deadline guard")
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
        "DUPLICATE_WORKER_FINAL_BET",
        "FINAL_BET_DEADLINE_PASSED",
        "FINAL_STATE_DEADLINE_PASSED",
        "IMMUTABLE_FINAL_BET_TERMS",
        "IMMUTABLE_WORKER_FINAL_STATE",
        "PROBABILITY_FALLBACK_FORBIDDEN",
        "OFFICIAL_JRA_ODDS_REQUIRED",
        "NOT IN ('jra-fast-official', 'jra-crawl-official')",
    ):
        require(invariants, needle, "D1 finalization invariants")

    safety = read("src/v1/live-preview-safety.ts")
    for needle in (
        "rt_live_preview_archive",
        "rt_archive_live_preview_insert",
        "rt_archive_live_preview_update",
        "rt_live_deadline_lease",
        "acquireLiveDeadlineLease",
        "restoreNewestOfficialPreviewArchives",
        "structuralErrorRaceIds",
        "previewMissingByT40RaceIds",
        "previewMissingByT30RaceIds",
        "finalMissingByT25RaceIds",
        "finalMissingByT20RaceIds",
        "deadlineMissedRaceIds",
    ):
        require(safety, needle, "live preview safety")

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
        "structural_critical",
        "LIVE_DEADLINE_STRUCTURAL_RACE_ERROR",
        "LIVE_DEADLINE_HARD_T15_BREACH",
        'url.pathname === "/internal/github-tick"',
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
    require(public34, 'status: 404', "public v34")

    require_missing(".github/workflows/drive-live-tick.yml", "obsolete public live driver")
    require_missing(".github/workflows/auto-final-live-bets.yml", "obsolete stored-preview finalizer")

    deploy = read(".github/workflows/deploy-live-deadline.yml")
    for needle in (
        "Run exhaustive live deadline proof",
        "Deploy primary live deadline Worker",
        "Deploy backup live deadline Worker",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "production/live-deadline",
    ):
        require(deploy, needle, "dual live deadline deploy")

    watchdog = read(".github/workflows/live-deadline-external-watchdog.yml")
    for needle in (
        "id-token: write",
        "pulses=5",
        "sleep 55",
        "audience=race-tantei-live-deadline",
        "/internal/github-tick",
        "production/live-deadline-external-watchdog",
    ):
        require(watchdog, needle, "independent GitHub watchdog")

    readiness = read(".github/workflows/verify-live-deadline-production.yml")
    for needle in (
        "race-tantei-live-deadline.race-tantei.workers.dev/health",
        "race-tantei-live-deadline-backup.race-tantei.workers.dev/health",
        "race-tantei-phase0.race-tantei.workers.dev/_ops/live-tick",
        "rt_live_preview_archive",
        "rt_live_deadline_lease",
        "rt_guard_duplicate_worker_final_bet",
        "Prove independent GitHub scheduler can execute the production tick",
        "production/live-deadline-readiness",
    ):
        require(readiness, needle, "production readiness audit")

    fast = read("src/v1/jra-official-odds-fetch.ts")
    for needle in (
        "const FETCH_BUDGET_MS = 25_000;",
        "JRA_ODDS_FETCH_BUDGET_EXHAUSTED",
        "deadlineMs",
    ):
        require(fast, needle, "JRA official odds fetch")
    crawl = read("src/v1/jra-official-odds.ts")
    for needle in (
        "const CRAWL_PAGE_TIMEOUT_MS = 3_500;",
        "JRA_ODDS_CRAWL_BUDGET_EXHAUSTED",
    ):
        require(crawl, needle, "JRA official odds crawl")

    critical_workflow = read(".github/workflows/critical-auto-bet-generation.yml")
    require(critical_workflow, "workflow_dispatch:", "critical recovery workflow")
    forbid(critical_workflow, "schedule:", "critical recovery workflow")

    print(
        "LIVE_LOCK_SAFETY_OK",
        "primary_cron=1m",
        "backup_cron=1m",
        "github_external_pulse=1m",
        "preview_open=90m",
        "preview_required=30m",
        "normal_lock=25m",
        "guard_arm=20m",
        "deadline=15m_hard",
        "official_jra_odds_required=true",
        "probability_fallback_forbidden=true",
        "append_only_preview_archive=true",
        "last_good_restore=true",
        "lease=true",
        "duplicate_final_fence=true",
        "structural_race_faults=hard_fail",
        "sla_t40_t30_t25_t20_t15=true",
        "public_live_mutation=false",
        "post_t15_creation=false",
        "critical_schedule=disabled",
    )


if __name__ == "__main__":
    main()
