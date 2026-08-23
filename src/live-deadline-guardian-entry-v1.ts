import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import type { Env } from "./v1/types.js";

const GUARDIAN_VERSION = "live-deadline-guardian-v1-cached-preview-20260823";
const LEASE_TTL_SECONDS = 45;
const TICK_PREFIX = "live_deadline_guardian_tick:";
const SUCCESS_PREFIX = "live_deadline_guardian_success:";

function iso(now = new Date()): string { return now.toISOString(); }
function jstDate(now: Date): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}
function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

async function ensureSchema(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      CREATE TABLE IF NOT EXISTS rt_live_deadline_guardian_lease (
        id INTEGER PRIMARY KEY CHECK(id=1),
        owner TEXT,
        expires_at INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    db.prepare("INSERT OR IGNORE INTO rt_live_deadline_guardian_lease(id,owner,expires_at,updated_at) VALUES(1,NULL,0,CURRENT_TIMESTAMP)"),
  ]);
}

async function acquireLease(db: D1Database, owner: string): Promise<boolean> {
  const nowSeconds = Math.floor(Date.now() / 1000);
  await db.prepare(`
    UPDATE rt_live_deadline_guardian_lease
    SET owner=?,expires_at=?,updated_at=CURRENT_TIMESTAMP
    WHERE id=1 AND expires_at<=?
  `).bind(owner, nowSeconds + LEASE_TTL_SECONDS, nowSeconds).run();
  const row = await db.prepare("SELECT owner FROM rt_live_deadline_guardian_lease WHERE id=1 LIMIT 1")
    .first<{ owner: string | null }>();
  return row?.owner === owner;
}

async function releaseLease(db: D1Database, owner: string): Promise<void> {
  await db.prepare(`
    UPDATE rt_live_deadline_guardian_lease
    SET owner=NULL,expires_at=0,updated_at=CURRENT_TIMESTAMP
    WHERE id=1 AND owner=?
  `).bind(owner).run();
}

async function saveState(db: D1Database, key: string, value: unknown): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(key, JSON.stringify(value)).run();
}

async function runGuardian(env: Env, scheduledAt: string): Promise<void> {
  const started = new Date();
  const date = jstDate(started);
  const owner = `${GUARDIAN_VERSION}:${crypto.randomUUID()}`;
  const base = { version: GUARDIAN_VERSION, date, scheduledAt, startedAt: iso(started), owner };

  await ensureSchema(env.DB);
  const acquired = await acquireLease(env.DB, owner);
  if (!acquired) {
    await saveState(env.DB, `${TICK_PREFIX}${date}`, {
      ...base,
      status: "lease_busy",
      ok: true,
      completedAt: iso(),
      durationMs: Date.now() - started.getTime(),
    });
    return;
  }

  try {
    const audit = await runCompletedWorkerDeadlineGuard(env, new Date());
    const completed = new Date();
    const payload = {
      ...base,
      status: "completed",
      ok: true,
      guardStatus: audit.status,
      dueRaceIds: audit.dueRaceIds,
      lockedRaceIds: audit.lockedRaceIds,
      skippedAlreadyLockedRaceIds: audit.skippedAlreadyLockedRaceIds,
      deadlineMissedRaceIds: audit.deadlineMissedRaceIds,
      errors: audit.errors,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    await saveState(env.DB, `${TICK_PREFIX}${date}`, payload);
    await saveState(env.DB, `${SUCCESS_PREFIX}${date}`, payload);
  } catch (error) {
    const completed = new Date();
    const payload = {
      ...base,
      status: "error",
      ok: false,
      error: errorText(error),
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try { await saveState(env.DB, `${TICK_PREFIX}${date}`, payload); }
    catch (auditError) { console.error("LIVE_DEADLINE_GUARDIAN_AUDIT_WRITE_FAILED", auditError); }
    throw error;
  } finally {
    try { await releaseLease(env.DB, owner); }
    catch (leaseError) { console.error("LIVE_DEADLINE_GUARDIAN_LEASE_RELEASE_FAILED", leaseError); }
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === "/health") {
      return Response.json(
        { service: "race-tantei-live-deadline-guardian", version: GUARDIAN_VERSION, status: "up" },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return new Response("NOT_FOUND", { status: 404 });
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime)
      ? new Date(controller.scheduledTime).toISOString()
      : iso();
    await runGuardian(env, scheduledAt);
  },
} satisfies ExportedHandler<Env>;
