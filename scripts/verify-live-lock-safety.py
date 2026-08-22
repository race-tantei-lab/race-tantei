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
        'const DEADLINE_MS = 15 * 60 * 1000;',
        'const PREVIEW_HISTORY = 3;',
        'oddsSnapshotSha256',
        'await savePreview(db, snapshot)',
        'latestOfficialBodyWeightPreview',
        '"deadline_watchdog"',
        'await db.batch(statements)',
        'if (isStrictComplete(existing)) return;',
        'bodyWeightBreachRaceIds',
    ):
        require(worker, needle, "Worker live-lock")
    forbid(worker, 'WORKER_FINAL_BODYWEIGHT_MISMATCH', "Worker live-lock")
    forbid(worker, "const FINALIZE_OPEN_MS = 16 * 60 * 1000;", "Worker live-lock")

    # T-15 must be a hard network/recompute boundary for normal races.
    t15_start = worker.index('if (remaining <= DEADLINE_MS)')
    t15_end = worker.index('let fresh: PreviewSnapshot | null = null;', t15_start)
    t15_block = worker[t15_start:t15_end]
    for forbidden in ('generatePreview(', 'fetchFastJraOfficialOddsForRace(', 'loadWorkerModel(', 'loadCompletedRecencyLearning('):
        forbid(t15_block, forbidden, "Worker T-15 hard boundary")
    require(t15_block, 'await commitSnapshot(env.DB, raceId, stored, now, "deadline_watchdog")', "Worker T-15 hard boundary")
    forbid(worker, 'const FINALIZE_OPEN_MS = DEADLINE_MS;', "Worker live-lock")

    guard = read("src/v1/completed-worker-deadline-guard.ts")
    for needle in (
        "export const DEADLINE_GUARD_MS = 15 * 60 * 1000;",
        "export const DEADLINE_GUARD_ARM_MS = 20 * 60 * 1000;",
        "remainingMs > 0 && remainingMs <= DEADLINE_GUARD_ARM_MS",
        "orderSelectedRaceIds",
        "start_time_utc AS startTimeUtc",
        'snapshot.oddsSource!=="jra-fast-official" && snapshot.oddsSource!=="jra-crawl-official"',
        'finalizedFrom:"persistent_official_deadline_guard"',
        "await db.batch(statements)",
        "for (const raceId of ids)",
        "ensureCompletedRaceFinalAtDeadline",
        "DEADLINE_GUARD_PREVIEW_MISSING",
        "ensureCompletedFinalImmutability",
    ):
        require(guard, needle, "persistent deadline guard")
    for forbidden in (
        "LATE_LIMIT_MS",
        "remaining > 14 * 60 * 1000",
        "remaining > LATE_LIMIT_MS",
        "fetch(",
        "probability_fallback_persistent_deadline_guard",
        "chooseCompletedProbabilityFallbackTickets",
        "emergencyRunnerWeights",
        "async function buildFallback",
        "async function commitFallback",
        "loadCompletedFeatureStateForRace",
        "loadCompletedRecencyLearning",
    ):
        forbid(guard, forbidden, "persistent deadline guard")

    production_wrapper = read("src/public-site-entry-v29.ts")
    for needle in (
        'import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";',
        'import { ensureCompletedRaceFinalAtDeadline, runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";',
        "await freezeCompletedWorkerSelectionIfNeeded(env, now);",
        'import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";',
        'await runNormalRacePreparation(env, "COMPLETED_WORKER_PREPARE_BEFORE")',
        'await ensureRaceDetailDeadlineFinal(env, path);',
        'await runDeadlineGuard(env, "COMPLETED_WORKER_DEADLINE_GUARD_BEFORE", false)',
        'await runDeadlineGuard(env, "COMPLETED_WORKER_DEADLINE_GUARD_AFTER", true)',
        'throw new Error(`${label}_DUE_RACE_UNRESOLVED:',
        "if (finalGuardError) throw finalGuardError;",
        "if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);",
    ):
        require(production_wrapper, needle, "production deadline wrapper")
    before_pos = production_wrapper.index('COMPLETED_WORKER_DEADLINE_GUARD_BEFORE')
    delegated_pos = production_wrapper.index("if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);")
    after_pos = production_wrapper.index('COMPLETED_WORKER_DEADLINE_GUARD_AFTER')
    if not (before_pos < delegated_pos < after_pos):
        raise AssertionError("deadline guard must run both before and after delegated scheduled work")
    forbid(production_wrapper, "runCompletedWorkerEmergencyLock", "production deadline wrapper")

    direct_wrapper = read("src/public-site-entry-v34.ts")
    for needle in (
        "const guardBefore = await runCompletedWorkerDeadlineGuard(env, now);",
        "live = await runCompletedWorkerLiveLock(env, now);",
        "const guardAfter = await runCompletedWorkerDeadlineGuard(env, now);",
        "const status = liveFailure || liveErrors.length",
        "DIRECT_LIVE_TICK_DUE_UNRESOLVED",
        'url.pathname === "/_ops/live-tick"',
    ):
        require(direct_wrapper, needle, "direct live tick")
    direct_before = direct_wrapper.index("const guardBefore = await runCompletedWorkerDeadlineGuard(env, now);")
    direct_live = direct_wrapper.index("live = await runCompletedWorkerLiveLock(env, now);")
    direct_after = direct_wrapper.index("const guardAfter = await runCompletedWorkerDeadlineGuard(env, now);")
    if not (direct_before < direct_live < direct_after):
        raise AssertionError("direct live tick must guard before live generation and guard again after it")

    invariants = read("src/v1/completed-final-invariants.ts")
    for needle in (
        'CREATE TRIGGER IF NOT EXISTS rt_guard_locked_public_bet_terms',
        'IMMUTABLE_FINAL_BET_TERMS',
        'CREATE TRIGGER IF NOT EXISTS rt_guard_locked_worker_final_state',
        'IMMUTABLE_WORKER_FINAL_STATE',
        'CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_insert',
        'CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_update',
        'PROBABILITY_FALLBACK_FORBIDDEN',
        'CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_insert',
        'CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_update',
        "NOT IN ('jra-fast-official', 'jra-crawl-official')",
        'OFFICIAL_JRA_ODDS_REQUIRED',
    ):
        require(invariants, needle, "final immutability")

    scheduled_gate = read("src/public-site-entry-v25.ts")
    for needle in (
        "const PRIOR_LEARNING_FAIL_OPEN_MINUTE_JST = 8 * 60 + 30;",
        "let priorReady = false;",
        "PRIOR_DAY_LEARNING_FAIL_OPEN",
        "if (jstMinuteOfDay(now) < PRIOR_LEARNING_FAIL_OPEN_MINUTE_JST) return;",
        "if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);",
    ):
        require(scheduled_gate, needle, "prior-day learning gate")
    forbid(
        scheduled_gate,
        'if (!readiness.ready) {\n          console.error("PRIOR_DAY_LEARNING_NOT_READY", JSON.stringify(readiness));\n          // Keep the generic JRA synchronizer running',
        "prior-day learning gate",
    )

    automatic = read(".github/workflows/auto-final-live-bets.yml")
    for needle in (
        'cron: "*/5 23 * * 5,6,0"',
        'cron: "*/5 0-10 * * 6,0,1"',
        "timeout-minutes: 3",
        "scripts/run-stored-preview-deadline-backup.py",
        "stored_preview_only",
        "generatedRaceIds",
        "urgentMissingRaceIds",
        "failures",
        "POST_DEADLINE_GENERATION_FORBIDDEN",
    ):
        require(automatic, needle, "independent GitHub live backup")
    forbid(automatic, "timezone:", "independent GitHub live backup")
    for forbidden in (
        "run-critical-auto-bet-generation.py",
        "refresh-selected-bodyweights-direct.mjs",
        "lightgbm",
        "generate-ten-year-live-bets.py",
        "collect-current-jra-official-odds",
        "Existing live backup monitor detected",
        "for _ in $(seq 1 350)",
        "sleep 60",
        'cron: "7,37 9-19',
    ):
        forbid(automatic, forbidden, "independent GitHub live backup")

    driver = read(".github/workflows/drive-live-tick.yml")
    for needle in (
        'cron: "*/5 23 * * 5,6,0"',
        'cron: "*/5 0-10 * * 6,0,1"',
        "race-tantei-phase0.race-tantei.workers.dev/_ops/live-tick",
        "LIVE_TICK_EXECUTED_WITH_HISTORICAL_BREACH",
        "LIVE_TICK_CURRENT_ERROR",
    ):
        require(driver, needle, "independent live tick driver")
    forbid(driver, "timezone:", "independent live tick driver")

    backup = read("scripts/run-stored-preview-deadline-backup.py")
    for needle in (
        '"mode": "stored_preview_only"',
        '"generatedRaceIds": []',
        "trigger_race_page(race_id)",
        "0 < remaining <= 15 * 60",
        "strict_complete(race_id)",
    ):
        require(backup, needle, "stored-preview GitHub backup")
    for forbidden in (
        "lightgbm",
        "generate-ten-year-live-bets",
        "collect-current-jra-official-odds",
        "run-critical-auto-bet-generation",
    ):
        forbid(backup, forbidden, "stored-preview GitHub backup")

    critical_workflow = read(".github/workflows/critical-auto-bet-generation.yml")
    require(critical_workflow, "workflow_dispatch:", "critical recovery workflow")
    forbid(critical_workflow, "schedule:", "critical recovery workflow")

    print(
        "LIVE_LOCK_SAFETY_OK",
        "worker_cron=1m",
        "preview_open=45m",
        "preview_history=3",
        "guard_arm=20m",
        "finalize_open=15m",
        "deadline=15m",
        "persistent_guard=stored_preview_only",
        "guard_order=start_time",
        "guard_runs=before_and_after_scheduled",
        "direct_guard_runs=before_and_after_live_generation",
        "guard_second_pass=fail_closed",
        "guard_selection_recovery=canonical_db_only",
        "guard_external_http=false",
        "race_page_self_heal=stored_preview_only",
        "final_db_immutability=true",
        "official_jra_odds_required=true",
        "probability_fallback_forbidden=true",
        "prior_learning_fail_open=08:30JST",
        "github_driver=live_tick_5m_UTC_mapped_to_JST",
        "github_backup=stored_preview_only_5m_UTC_mapped_to_JST",
        "post_deadline_prediction_generation=false",
        "critical_schedule=disabled",
    )


if __name__ == "__main__":
    main()
