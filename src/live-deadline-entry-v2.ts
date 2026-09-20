import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import {
  acquireLiveDeadlineLease,
  auditLiveDeadlineSla,
  ensureLivePreviewSafetySchema,
  releaseLiveDeadlineLease,
  restoreNewestOfficialPreviewArchives,
} from "./v1/live-preview-safety.js";
import type { Env } from "./v1/types.js";

const DRIVER_VERSION = "live-deadline-v12-preview-first-fallback-20260920";
const DRIVER_STATE_PREFIX = "live_deadline_driver:";
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
    // Selection first, then protect future races before any watchdog/archive work.
    // A missing historical race must never consume the tick that should create
    // the next race's last-good preview.
    const selectionNow = new Date();
    let selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    let selection: Record<string, unknown> = { status: "already_frozen" };
    if (!selectionReady) {
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow) as unknown as Record<string, unknown>;
      selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    }
    if (!selectionReady) {
      const firstRace = await env.DB.prepare("SELECT MIN(start_time_utc) AS firstStart FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL")
        .bind(date).first<{ firstStart: string | null }>();
      const firstStartMs = Date.parse(String(firstRace?.firstStart || ""));
      const remainingToFirstRaceMs = Number.isFinite(firstStartMs) ? firstStartMs - Date.now() : Number.NaN;
      const selectionCritical = Number.isFinite(remainingToFirstRaceMs) && remainingToFirstRaceMs <= 110 * 60_000;
      const completed = new Date();
      const result = {
        ...base,
        status: selectionCritical ? "selection_critical" : "waiting_selection",
        phase: "complete",
        ok: !selectionCritical,
        selection,
        entryRepair: null,
        selectionCheckedAt: iso(selectionNow),
        remainingToFirstRaceMs,
        completedAt: iso(completed),
        durationMs: completed.getTime() - started.getTime(),
      };
      await saveDriverState(env.DB, date, result);
      if (selectionCritical) throw new Error(`LIVE_DEADLINE_SELECTION_CRITICAL:${date}:${remainingToFirstRaceMs}`);
      return result;
    }

    const liveNow = new Date();
    let live: Awaited<ReturnType<typeof runCompletedWorkerLiveLock>> | null = null;
    let liveFailure: string | null = null;
    try {
      live = await runCompletedWorkerLiveLock(env, liveNow);
    } catch (error) {
      liveFailure = errorText(error);
    }

    // The persistent deadline guard is now secondary insurance. It can promote
    // the official last-good, or a network-independent probability fallback,
    // but it no longer gets to starve preview generation for later races.
    let priorityGuardNow = new Date();
    let priorityGuard = await runCompletedWorkerDeadlineGuard(env, priorityGuardNow);
    let restoredBefore: string[] = [];
    if (priorityGuard.errors.some((row) => row.error.includes("PREVIEW_MISSING"))) {
      restoredBefore = await restoreNewestOfficialPreviewArchives(env.DB, date);
      priorityGuardNow = new Date();
      priorityGuard = await runCompletedWorkerDeadlineGuard(env, priorityGuardNow);
    }
    const slaBefore = null;
    const guardBeforeNow = priorityGuardNow;
    const guardBefore = priorityGuard;

    let restoredAfter: string[] = [];
    let guardAfterNow = new Date();
    let guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    if (guardAfter.errors.some((row) => row.error.includes("PREVIEW_MISSING"))) {
      restoredAfter = await restoreNewestOfficialPreviewArchives(env.DB, date);
      guardAfterNow = new Date();
      guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    }
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
      ...slaAfter.previewMissingByT40RaceIds,
      ...slaAfter.previewMissingByT30RaceIds,
      ...slaAfter.finalMissingByT30RaceIds,
      ...slaAfter.finalMissingByT25RaceIds,
      ...slaAfter.finalMissingByT16RaceIds,
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

    // T-15 breaches are immutable by design: never backfill them. Record them,
    // but keep the primary heartbeat alive so later selected races continue to
    // receive previews/finals instead of treating an unfixable past miss as a
    // reason to stop the whole race day.
    if (hardDeadlineBreachRaceIds.length) {
      console.error("LIVE_DEADLINE_HARD_T15_BREACH_RECORDED", hardDeadlineBreachRaceIds.join(","));
    }
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
    } catch { }
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
