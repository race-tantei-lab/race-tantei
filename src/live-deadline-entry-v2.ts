import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import { acquireEntryRepairLease, releaseEntryRepairLease } from "./v1/entry-repair-lease.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import {
  acquireLiveDeadlineLease,
  ensureLivePreviewSafetySchema,
  releaseLiveDeadlineLease,
} from "./v1/live-preview-safety.js";
import type { Env } from "./v1/types.js";

export const DRIVER_VERSION = "live-deadline-v14-guard-first-cpu-safe-20260920";
const DRIVER_STATE_PREFIX = "live_deadline_driver:";
const LEASE_SKIP_PREFIX = "live_deadline_lease_skip:";
const SELECTION_PREFIX = "final_daily_selection:";
const LIVE_SELECTION_REPAIR_PREFIX = "live_selection_entry_repair:";
const LIVE_SELECTION_REPAIR_THRESHOLD_MS = 30 * 60 * 1000;
const LIVE_SELECTION_REPAIR_MIN_INTERVAL_MS = 5 * 60 * 1000;

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

async function runLiveSelectionEntryRepairIfDue(
  env: Env,
  date: string,
  now: Date,
  remainingToFirstRaceMs: number,
): Promise<Record<string, unknown>> {
  if (!Number.isFinite(remainingToFirstRaceMs) || remainingToFirstRaceMs > LIVE_SELECTION_REPAIR_THRESHOLD_MS) {
    return { attempted: false, reason: "outside_t30", remainingToFirstRaceMs };
  }

  const stateKey = `${LIVE_SELECTION_REPAIR_PREFIX}${date}`;
  const previous = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(stateKey).first<{ value: string }>();
  if (previous?.value) {
    try {
      const parsed = JSON.parse(previous.value) as { checkedAt?: string };
      const previousMs = Date.parse(String(parsed.checkedAt || ""));
      if (Number.isFinite(previousMs) && now.getTime() - previousMs < LIVE_SELECTION_REPAIR_MIN_INTERVAL_MS) {
        return { attempted: false, reason: "throttled", checkedAt: parsed.checkedAt ?? null, remainingToFirstRaceMs };
      }
    } catch { /* stale audit state must not block recovery */ }
  }

  const owner = `live-selection-entry-repair:${crypto.randomUUID()}`;
  const acquired = await acquireEntryRepairLease(env.DB, owner);
  if (!acquired) {
    return { attempted: false, reason: "shared_entry_repair_lease_busy", remainingToFirstRaceMs };
  }

  const checkedAt = iso(now);
  let status = "error";
  let savedRaceIds: string[] = [];
  let groups: unknown[] = [];
  let errors: string[] = [];
  try {
    // Live is only the last-resort T-30 fallback. Keep this deterministic and
    // missing-only: broad published-link discovery/probing remains owned by the
    // public 5-minute repair pipeline to avoid duplicate JRA traffic.
    const repair = await runUpcomingEntryDerivedRepair(env, now);
    status = repair.status;
    savedRaceIds = repair.savedRaceIds;
    groups = repair.groups;
    errors = repair.errors;
  } catch (error) {
    errors = [errorText(error)];
  } finally {
    try { await releaseEntryRepairLease(env.DB, owner); }
    catch (error) { console.error("LIVE_SELECTION_ENTRY_REPAIR_LEASE_RELEASE_FAILED", errorText(error)); }
  }

  const audit = {
    attempted: true,
    checkedAt,
    date,
    remainingToFirstRaceMs,
    status,
    savedRaceIds,
    groups,
    errors,
  };
  await saveState(env.DB, stateKey, audit);
  console.warn("LIVE_SELECTION_T30_ENTRY_REPAIR", JSON.stringify(audit));
  return audit;
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

export async function runIsolatedLiveDeadlineTick(
  env: Env,
  scheduledAt: string,
): Promise<Record<string, unknown>> {
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
      ok: false,
      completedAt: iso(),
      durationMs: Date.now() - started.getTime(),
    };
    await saveLeaseSkipState(env.DB, date, skipped);
    return skipped;
  }

  try {
    const selectionNow = new Date();
    let selectionReady = await hasSelection(env.DB, date);
    let selection: Record<string, unknown> = { status: "already_frozen" };
    if (!selectionReady) {
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow) as unknown as Record<string, unknown>;
      selectionReady = await hasSelection(env.DB, date);
    }
    if (!selectionReady) {
      const firstRace = await env.DB.prepare(
        "SELECT MIN(start_time_utc) AS firstStart FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL",
      ).bind(date).first<{ firstStart: string | null }>();
      const firstStartMs = Date.parse(String(firstRace?.firstStart || ""));
      const remainingToFirstRaceMs = Number.isFinite(firstStartMs) ? firstStartMs - Date.now() : Number.NaN;

      const selectionRepair = await runLiveSelectionEntryRepairIfDue(
        env,
        date,
        new Date(),
        remainingToFirstRaceMs,
      );
      if (selectionRepair.attempted === true) {
        selection = await freezeCompletedWorkerSelectionIfNeeded(env, new Date()) as unknown as Record<string, unknown>;
        selectionReady = await hasSelection(env.DB, date);
      }

      if (!selectionReady) {
        const selectionCritical = Number.isFinite(remainingToFirstRaceMs) && remainingToFirstRaceMs <= 110 * 60_000;
        const completed = new Date();
        const result = {
          ...base,
          status: selectionCritical ? "selection_critical" : "waiting_selection",
          phase: "complete",
          ok: !selectionCritical,
          selection,
          selectionRepair,
          selectionCheckedAt: iso(selectionNow),
          remainingToFirstRaceMs,
          completedAt: iso(completed),
          durationMs: completed.getTime() - started.getTime(),
        };
        await saveDriverState(env.DB, date, result);
        if (selectionCritical) throw new Error(`LIVE_DEADLINE_SELECTION_CRITICAL:${date}:${remainingToFirstRaceMs}`);
        return result;
      }
    }

    // Heavy work is intentionally isolated from critical finalization. The v3
    // wrapper runs the stored-official T-25..T-15 guard before this function, so
    // an exceededCpu here can never prevent an already-protected race from being
    // finalized.
    const liveNow = new Date();
    let live: Awaited<ReturnType<typeof runCompletedWorkerLiveLock>> | null = null;
    let liveFailure: string | null = null;
    try {
      live = await runCompletedWorkerLiveLock(env, liveNow);
    } catch (error) {
      liveFailure = errorText(error);
    }

    const completed = new Date();
    const hardDeadlineBreachRaceIds = live?.deadlineBreachRaceIds ?? [];
    const result = {
      ...base,
      status: liveFailure
        ? "live_retry_needed"
        : hardDeadlineBreachRaceIds.length
          ? "deadline_breach"
          : live?.status ?? "ok",
      phase: "complete",
      ok: !liveFailure,
      selection,
      selectionCheckedAt: iso(selectionNow),
      liveStartedAt: iso(liveNow),
      liveFailure,
      live: live ? auditLive(live) : null,
      hardDeadlineBreachRaceIds,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    await saveDriverState(env.DB, date, result);
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
