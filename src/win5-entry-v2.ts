import { runCompletedWin5Scheduled, type Win5PublicState } from "./v1/completed-win5.js";
import type { Env } from "./v1/types.js";

const DRIVER_VERSION = "win5-driver-v2-isolated-dual-20260823";
const TICK_PREFIX = "win5_driver_tick:";
const SUCCESS_PREFIX = "win5_driver_success:";
const LEASE_TTL_SECONDS = 180;
const PREVIEW_REQUIRED_MINUTE_JST = 9 * 60 + 30;

function iso(now = new Date()): string { return now.toISOString(); }
function jstShift(now: Date): Date { return new Date(now.getTime() + 9 * 60 * 60 * 1000); }
function jstDate(now: Date): string { return jstShift(now).toISOString().slice(0, 10); }
function jstMinuteOfDay(now: Date): number {
  const shifted = jstShift(now).toISOString();
  return Number(shifted.slice(11, 13)) * 60 + Number(shifted.slice(14, 16));
}
function jstDayOfWeek(now: Date): number { return jstShift(now).getUTCDay(); }
function errorText(error: unknown): string { return error instanceof Error ? `${error.name}:${error.message}` : String(error); }

async function ensureDriverSchema(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      CREATE TABLE IF NOT EXISTS rt_win5_driver_lease (
        id INTEGER PRIMARY KEY CHECK(id=1),
        owner TEXT,
        expires_at INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    db.prepare("INSERT OR IGNORE INTO rt_win5_driver_lease(id,owner,expires_at,updated_at) VALUES(1,NULL,0,CURRENT_TIMESTAMP)"),
  ]);
}

async function acquireLease(db: D1Database, owner: string): Promise<boolean> {
  const nowSeconds = Math.floor(Date.now() / 1000);
  await db.prepare(`
    UPDATE rt_win5_driver_lease
    SET owner=?,expires_at=?,updated_at=CURRENT_TIMESTAMP
    WHERE id=1 AND expires_at<=?
  `).bind(owner, nowSeconds + LEASE_TTL_SECONDS, nowSeconds).run();
  const row = await db.prepare("SELECT owner FROM rt_win5_driver_lease WHERE id=1 LIMIT 1").first<{ owner: string | null }>();
  return row?.owner === owner;
}

async function releaseLease(db: D1Database, owner: string): Promise<void> {
  await db.prepare(`
    UPDATE rt_win5_driver_lease
    SET owner=NULL,expires_at=0,updated_at=CURRENT_TIMESTAMP
    WHERE id=1 AND owner=?
  `).bind(owner).run();
}

async function saveState(db: D1Database, key: string, payload: Record<string, unknown>): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(key, JSON.stringify(payload)).run();
}

function summarize(state: Win5PublicState): Record<string, unknown> {
  return {
    win5Status: state.status,
    targetCount: state.targets.length,
    snapshotReady: state.snapshot !== null,
    snapshotLocked: state.snapshot?.locked === true,
    generatedAt: state.snapshot?.generatedAt ?? null,
    lockedAt: state.snapshot?.lockedAt ?? null,
    lockDeadlineUtc: state.snapshot?.lockDeadlineUtc ?? null,
    firstRaceStartUtc: state.snapshot?.firstRaceStartUtc ?? null,
  };
}

function assertOperationalState(state: Win5PublicState, now: Date): void {
  if (state.targets.length === 5) {
    const firstStartMs = Math.min(...state.targets.map((row) => Date.parse(row.startTimeUtc)));
    const deadlineMs = firstStartMs - 15 * 60 * 1000;
    if (Number.isFinite(deadlineMs) && now.getTime() >= deadlineMs && state.status !== "final") {
      throw new Error(`WIN5_FINAL_MISSING_AFTER_DEADLINE:${state.date}:${state.status}`);
    }
    if (
      Number.isFinite(deadlineMs)
      && now.getTime() < deadlineMs
      && jstMinuteOfDay(now) >= PREVIEW_REQUIRED_MINUTE_JST
      && state.snapshot === null
    ) {
      throw new Error(`WIN5_PREVIEW_NOT_READY_AFTER_0930:${state.date}:${state.status}`);
    }
  }

  // Regular Sunday WIN5 must be discoverable by the morning readiness window.
  // Other weekdays/holiday schedules remain fail-open here because the JRA calendar
  // is the source of truth and the live integration test verifies published targets.
  if (
    state.targets.length === 0
    && jstDayOfWeek(now) === 0
    && jstMinuteOfDay(now) >= PREVIEW_REQUIRED_MINUTE_JST
    && jstMinuteOfDay(now) < 18 * 60
  ) {
    throw new Error(`WIN5_SUNDAY_TARGETS_MISSING_AFTER_0930:${state.date}`);
  }
}

async function runIsolatedWin5Tick(env: Env, scheduledAt: string): Promise<Record<string, unknown>> {
  const started = new Date();
  const date = jstDate(started);
  const owner = `${DRIVER_VERSION}:${crypto.randomUUID()}`;
  const base = { version: DRIVER_VERSION, date, scheduledAt, startedAt: iso(started), owner };

  await ensureDriverSchema(env.DB);
  const acquired = await acquireLease(env.DB, owner);
  if (!acquired) {
    const skipped = { ...base, status: "lease_busy", ok: true, completedAt: iso(), durationMs: Date.now() - started.getTime() };
    await saveState(env.DB, `${TICK_PREFIX}${date}`, skipped);
    return skipped;
  }

  try {
    // Deadline decisions must use the actual execution time, not a delayed cron timestamp.
    const state = await runCompletedWin5Scheduled(env, new Date());
    assertOperationalState(state, new Date());
    const completed = new Date();
    const result = {
      ...base,
      status: "ok",
      ok: true,
      ...summarize(state),
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    await saveState(env.DB, `${TICK_PREFIX}${date}`, result);
    await saveState(env.DB, `${SUCCESS_PREFIX}${date}`, result);
    return result;
  } catch (error) {
    const completed = new Date();
    const failure = {
      ...base,
      status: "error",
      ok: false,
      error: errorText(error),
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try { await saveState(env.DB, `${TICK_PREFIX}${date}`, failure); }
    catch (auditError) { console.error("WIN5_DRIVER_AUDIT_WRITE_FAILED", auditError); }
    throw error;
  } finally {
    try { await releaseLease(env.DB, owner); }
    catch (leaseError) { console.error("WIN5_DRIVER_LEASE_RELEASE_FAILED", leaseError); }
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === "/health") {
      return Response.json(
        { service: "race-tantei-win5", version: DRIVER_VERSION, status: "up" },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return new Response("NOT_FOUND", { status: 404 });
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime)
      ? new Date(controller.scheduledTime).toISOString()
      : iso();
    await runIsolatedWin5Tick(env, scheduledAt);
  },
} satisfies ExportedHandler<Env>;
