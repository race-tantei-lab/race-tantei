import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import {
  acquireLiveDeadlineLease,
  auditLiveDeadlineSla,
  ensureLivePreviewSafetySchema,
  releaseLiveDeadlineLease,
  restoreNewestOfficialPreviewArchives,
} from "./v1/live-preview-safety.js";
import type { Env } from "./v1/types.js";

const DRIVER_VERSION = "live-deadline-v3-priority-guard-20260823";
const DRIVER_STATE_PREFIX = "live_deadline_driver:";
const PRIORITY_GUARD_SUCCESS_PREFIX = "live_deadline_priority_guard_success:";
const LEASE_SKIP_PREFIX = "live_deadline_lease_skip:";
const SELECTION_PREFIX = "final_daily_selection:";

function iso(now = new Date()): string { return now.toISOString(); }
function jstDate(now = new Date()): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }
function errorText(error: unknown): string { return error instanceof Error ? `${error.name}:${error.message}` : String(error); }

async function hasSelection(db: D1Database, date: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`).first<{ ok: number }>();
  return Number(row?.ok ?? 0) === 1;
}

async function saveState(db: D1Database, key: string, payload: Record<string, unknown>): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(key, JSON.stringify(payload)).run();
}

async function saveDriverState(db: D1Database, date: string, payload: Record<string, unknown>): Promise<void> {
  await saveState(db, `${DRIVER_STATE_PREFIX}${date}`, payload);
}

async function saveLeaseSkipState(db: D1Database, date: string, payload: Record<string, unknown>): Promise<void> {
  await saveState(db, `${LEASE_SKIP_PREFIX}${date}`, payload);
}

function auditGuard(guard: Awaited<ReturnType<typeof runCompletedWorkerDeadlineGuard>>) {
  return {
    status: guard.status,
    checkedAt: guard.checkedAt,
    dueRaceIds: guard.dueRaceIds,
    lockedRaceIds: guard.lockedRaceIds,
    deadlineMissedRaceIds: guard.deadlineMissedRaceIds,
    skippedAlreadyLockedRaceIds: guard.skippedAlreadyLockedRaceIds,
    errors: guard.errors,
  };
}

function auditLive(live: Awaited<ReturnType<typeof runCompletedWorkerLiveLock>>) {
  return {
    status: live.status,
    checkedAt: live.checkedAt,
    completeBefore: live.completeBefore,
    completeAfter: live.completeAfter,
    refreshedPreviewRaceIds: live.refreshedPreviewRaceIds,
    previewAvailableRaceIds: live.previewAvailableRaceIds,
    lockedByWorker: live.lockedByWorker,
    incompleteRaceIds: live.incompleteRaceIds,
    deadlineBreachRaceIds: live.deadlineBreachRaceIds,
    errors: live.errors,
  };
}

async function runIsolatedLiveDeadlineTick(env: Env, scheduledAt: string): Promise<Record<string, unknown>> {
  const started = new Date();
  const startedAt = iso(started);
  const date = jstDate(started);
  const owner = `${DRIVER_VERSION}:${crypto.randomUUID()}`;
  const base = { version: DRIVER_VERSION, date, scheduledAt, startedAt, owner };

  await ensureLivePreviewSafetySchema(env.DB);
  const acquired = await acquireLiveDeadlineLease(env.DB, owner, 55);
  if (!acquired) {
    const skipped = {
      ...base,
      status: "lease_busy",
      phase: "complete",
      ok: true,
      completedAt: iso(),
      durationMs: Date.now() - started.getTime(),
    };
    await saveLeaseSkipState(env.DB, date, skipped);
    return skipped;
  }

  try {
    // Priority path: rescue from an already-persisted official preview before any
    // selection repair, archive restore, JRA fetch/model inference, or SLA audit.
    // This keeps T-20 -> T-15 finalization alive even if the heavier pipeline fails.
    const priorityGuardNow = new Date();
    const priorityGuard = await runCompletedWorkerDeadlineGuard(env, priorityGuardNow);
    const priorityGuardPayload = {
      ...base,
      status: "completed",
      phase: "priority_guard",
      ok: true,
      priorityGuardCheckedAt: iso(priorityGuardNow),
      priorityGuard: auditGuard(priorityGuard),
      completedAt: iso(),
      durationMs: Date.now() - started.getTime(),
    };
    await saveState(env.DB, `${PRIORITY_GUARD_SUCCESS_PREFIX}${date}`, priorityGuardPayload);

    await saveDriverState(env.DB, date, {
      ...base,
      status: "running",
      phase: "selection",
      priorityGuardCheckedAt: iso(priorityGuardNow),
      priorityGuard: auditGuard(priorityGuard),
      completedAt: null,
      durationMs: null,
      ok: false,
    });

    const selectionNow = new Date();
    let selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow);
    let selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    let entryRepair: Record<string, unknown> | null = null;
    if (!selectionReady && String(selection.status || "") === "waiting_complete_program") {
      entryRepair = await runUpcomingEntryDerivedRepair(env, new Date()) as unknown as Record<string, unknown>;
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, new Date());
      selectionReady = await hasSelection(env.DB, jstDate(new Date()));
    }
    if (!selectionReady) {
      const firstRace = await env.DB.prepare("SELECT MIN(start_time_utc) AS firstStart FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL")
        .bind(date).first<{ firstStart: string | null }>();
      const firstStartMs = Date.parse(String(firstRace?.firstStart || ""));
      const remainingToFirstRaceMs = Number.isFinite(firstStartMs) ? firstStartMs - Date.now() : Number.NaN;
      const selectionCritical = Number.isFinite(remainingToFirstRaceMs) && remainingToFirstRaceMs <= 100 * 60_000;
      const completed = new Date();
      const result = {
        ...base,
        status: selectionCritical ? "selection_critical" : "waiting_selection",
        phase: "complete",
        ok: !selectionCritical,
        priorityGuardCheckedAt: iso(priorityGuardNow),
        priorityGuard: auditGuard(priorityGuard),
        selection,
        entryRepair,
        selectionCheckedAt: iso(selectionNow),
        remainingToFirstRaceMs,
        completedAt: iso(completed),
        durationMs: completed.getTime() - started.getTime(),
      };
      await saveDriverState(env.DB, date, result);
      if (selectionCritical) throw new Error(`LIVE_DEADLINE_SELECTION_CRITICAL:${date}:${remainingToFirstRaceMs}`);
      return result;
    }

    const restoredBefore = await restoreNewestOfficialPreviewArchives(env.DB, date);
    const slaBefore = await auditLiveDeadlineSla(env.DB, date, new Date());

    const guardBeforeNow = new Date();
    const guardBefore = await runCompletedWorkerDeadlineGuard(env, guardBeforeNow);

    const liveNow = new Date();
    let live: Awaited<ReturnType<typeof runCompletedWorkerLiveLock>> | null = null;
    let liveFailure: string | null = null;
    try {
      live = await runCompletedWorkerLiveLock(env, liveNow);
    } catch (error) {
      liveFailure = errorText(error);
    }

    const restoredAfter = await restoreNewestOfficialPreviewArchives(env.DB, date);
    const guardAfterNow = new Date();
    const guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    const slaAfter = await auditLiveDeadlineSla(env.DB, date, new Date());

    const due = new Set([...priorityGuard.dueRaceIds, ...guardBefore.dueRaceIds, ...guardAfter.dueRaceIds]);
    const locked = new Set([
      ...priorityGuard.lockedRaceIds,
      ...priorityGuard.skippedAlreadyLockedRaceIds,
      ...guardBefore.lockedRaceIds,
      ...guardAfter.lockedRaceIds,
      ...guardBefore.skippedAlreadyLockedRaceIds,
      ...guardAfter.skippedAlreadyLockedRaceIds,
      ...slaAfter.finalReadyRaceIds,
    ]);
    const unresolvedDueRaceIds = [...due].filter((raceId) => !locked.has(raceId));
    const unresolvedGuardErrors = [...priorityGuard.errors, ...guardBefore.errors, ...guardAfter.errors]
      .filter((row) => !locked.has(row.raceId));
    const hardDeadlineBreachRaceIds = [...new Set([
      ...priorityGuard.deadlineMissedRaceIds,
      ...guardBefore.deadlineMissedRaceIds,
      ...guardAfter.deadlineMissedRaceIds,
      ...(live?.deadlineBreachRaceIds ?? []),
      ...slaAfter.deadlineMissedRaceIds,
    ])];
    const preDeadlineCriticalRaceIds = [...new Set([
      ...slaAfter.previewMissingByT30RaceIds,
      ...slaAfter.finalMissingByT20RaceIds,
    ])].filter((raceId) => !locked.has(raceId));

    const completed = new Date();
    const ok = !liveFailure
      && !unresolvedGuardErrors.length
      && !unresolvedDueRaceIds.length
      && !hardDeadlineBreachRaceIds.length
      && !preDeadlineCriticalRaceIds.length;
    const result = {
      ...base,
      status: ok
        ? "ok"
        : hardDeadlineBreachRaceIds.length
          ? "deadline_breach"
          : preDeadlineCriticalRaceIds.length
            ? "predeadline_critical"
            : unresolvedDueRaceIds.length || unresolvedGuardErrors.length
              ? "deadline_unresolved"
              : "live_retry_needed",
      phase: "complete",
      ok,
      priorityGuardCheckedAt: iso(priorityGuardNow),
      priorityGuard: auditGuard(priorityGuard),
      selection,
      selectionCheckedAt: iso(selectionNow),
      restoredBefore,
      slaBefore,
      guardBeforeCheckedAt: iso(guardBeforeNow),
      guardBefore: auditGuard(guardBefore),
      liveStartedAt: iso(liveNow),
      liveFailure,
      live: live ? auditLive(live) : null,
      restoredAfter,
      guardAfterCheckedAt: iso(guardAfterNow),
      guardAfter: auditGuard(guardAfter),
      slaAfter,
      unresolvedDueRaceIds,
      unresolvedGuardErrors,
      hardDeadlineBreachRaceIds,
      preDeadlineCriticalRaceIds,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    await saveDriverState(env.DB, date, result);

    if (hardDeadlineBreachRaceIds.length) throw new Error(`LIVE_DEADLINE_HARD_T15_BREACH:${hardDeadlineBreachRaceIds.join(",")}`);
    if (preDeadlineCriticalRaceIds.length) throw new Error(`LIVE_DEADLINE_PREDEADLINE_CRITICAL:${preDeadlineCriticalRaceIds.join(",")}`);
    if (unresolvedDueRaceIds.length || unresolvedGuardErrors.length) {
      throw new Error(`LIVE_DEADLINE_DUE_UNRESOLVED:${unresolvedDueRaceIds.join(",")}:guards=${JSON.stringify(unresolvedGuardErrors)}`);
    }
    if (liveFailure) throw new Error(`LIVE_DEADLINE_GENERATION_FAILED:${liveFailure}`);
    return result;
  } catch (error) {
    const completed = new Date();
    let previousState: unknown = null;
    try {
      const row = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
        .bind(`${DRIVER_STATE_PREFIX}${date}`).first<{ value: string }>();
      previousState = row?.value ? JSON.parse(row.value) : null;
    } catch { /* preserve the primary failure even if audit recovery fails */ }
    const failure = {
      ...base,
      status: "error",
      phase: "failed",
      ok: false,
      error: errorText(error),
      previousState,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try { await saveDriverState(env.DB, date, failure); }
    catch (auditError) { console.error("LIVE_DEADLINE_AUDIT_WRITE_FAILED", auditError); }
    throw error;
  } finally {
    try { await releaseLiveDeadlineLease(env.DB, owner); }
    catch (leaseError) { console.error("LIVE_DEADLINE_LEASE_RELEASE_FAILED", leaseError); }
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json(
        { service: "race-tantei-live-deadline", version: DRIVER_VERSION, status: "up" },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return new Response("NOT_FOUND", { status: 404 });
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime)
      ? new Date(controller.scheduledTime).toISOString()
      : iso();
    await runIsolatedLiveDeadlineTick(env, scheduledAt);
  },
} satisfies ExportedHandler<Env>;
