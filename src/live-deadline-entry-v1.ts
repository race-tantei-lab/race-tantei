import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import type { Env } from "./v1/types.js";

const DRIVER_VERSION = "live-deadline-v1-isolated-actual-clock-20260822";
const DRIVER_STATE_PREFIX = "live_deadline_driver:";
const SELECTION_PREFIX = "final_daily_selection:";

function iso(now = new Date()): string {
  return now.toISOString();
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

async function hasSelection(db: D1Database, date: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`)
    .first<{ ok: number }>();
  return Number(row?.ok ?? 0) === 1;
}

async function saveDriverState(db: D1Database, date: string, payload: Record<string, unknown>): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${DRIVER_STATE_PREFIX}${date}`, JSON.stringify(payload)).run();
}

function auditGuard(guard: Awaited<ReturnType<typeof runCompletedWorkerDeadlineGuard>>) {
  return {
    status: guard.status,
    checkedAt: guard.checkedAt,
    dueRaceIds: guard.dueRaceIds,
    lockedRaceIds: guard.lockedRaceIds,
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
  // scheduledAt is audit metadata only. Every deadline-sensitive phase takes a
  // fresh wall-clock timestamp so a delayed cron can never reason from stale time.
  const started = new Date();
  const startedAt = iso(started);
  const date = jstDate(started);
  const base = {
    version: DRIVER_VERSION,
    date,
    scheduledAt,
    startedAt,
  };

  await saveDriverState(env.DB, date, {
    ...base,
    status: "running",
    phase: "selection",
    completedAt: null,
    durationMs: null,
    ok: false,
  });

  try {
    const selectionNow = new Date();
    const selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow);
    const selectionReady = await hasSelection(env.DB, jstDate(selectionNow));

    if (!selectionReady) {
      const completed = new Date();
      const result = {
        ...base,
        status: "waiting_selection",
        phase: "complete",
        ok: true,
        selection,
        selectionCheckedAt: iso(selectionNow),
        completedAt: iso(completed),
        durationMs: completed.getTime() - started.getTime(),
      };
      await saveDriverState(env.DB, date, result);
      return result;
    }

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

    // Never reuse guardBeforeNow/liveNow here. A preview generated during the
    // live phase is timestamped using real wall time and must be validated
    // against a fresh wall clock, not the cron's scheduled timestamp.
    const guardAfterNow = new Date();
    const guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);

    const due = new Set([...guardBefore.dueRaceIds, ...guardAfter.dueRaceIds]);
    const locked = new Set([
      ...guardBefore.lockedRaceIds,
      ...guardAfter.lockedRaceIds,
      ...guardBefore.skippedAlreadyLockedRaceIds,
      ...guardAfter.skippedAlreadyLockedRaceIds,
    ]);
    const unresolvedDueRaceIds = [...due].filter((raceId) => !locked.has(raceId));
    const guardErrors = [...guardBefore.errors, ...guardAfter.errors];
    const liveErrors = live?.errors ?? [];
    const completed = new Date();
    const ok = !liveFailure && !guardErrors.length && !unresolvedDueRaceIds.length;

    const result = {
      ...base,
      status: ok ? "ok" : unresolvedDueRaceIds.length || guardErrors.length ? "deadline_unresolved" : "live_retry_needed",
      phase: "complete",
      ok,
      selection,
      selectionCheckedAt: iso(selectionNow),
      guardBeforeCheckedAt: iso(guardBeforeNow),
      guardBefore: auditGuard(guardBefore),
      liveStartedAt: iso(liveNow),
      liveFailure,
      live: live ? auditLive(live) : null,
      liveErrors,
      guardAfterCheckedAt: iso(guardAfterNow),
      guardAfter: auditGuard(guardAfter),
      unresolvedDueRaceIds,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };

    await saveDriverState(env.DB, date, result);

    if (unresolvedDueRaceIds.length || guardErrors.length) {
      throw new Error(`LIVE_DEADLINE_DUE_UNRESOLVED:${unresolvedDueRaceIds.join(",")}:guards=${JSON.stringify(guardErrors)}`);
    }
    if (liveFailure) throw new Error(`LIVE_DEADLINE_GENERATION_FAILED:${liveFailure}`);
    return result;
  } catch (error) {
    const completed = new Date();
    const failure = {
      ...base,
      status: "error",
      phase: "failed",
      ok: false,
      error: errorText(error),
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try {
      await saveDriverState(env.DB, date, failure);
    } catch (auditError) {
      console.error("LIVE_DEADLINE_AUDIT_WRITE_FAILED", auditError);
    }
    throw error;
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
    // No public endpoint is allowed to mutate prediction/finalization state.
    return new Response("NOT_FOUND", { status: 404 });
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime)
      ? new Date(controller.scheduledTime).toISOString()
      : iso();
    await runIsolatedLiveDeadlineTick(env, scheduledAt);
  },
} satisfies ExportedHandler<Env>;
