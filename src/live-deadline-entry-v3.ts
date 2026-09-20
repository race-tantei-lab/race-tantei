import liveDeadlineV2, { runIsolatedLiveDeadlineTick } from "./live-deadline-entry-v2.js";
import { runCompletedWorkerDeadlineGuard, type DeadlineGuardAudit } from "./v1/completed-worker-deadline-guard.js";
import {
  acquireNamedLiveDeadlineLease,
  releaseNamedLiveDeadlineLease,
  restoreNewestOfficialPreviewArchives,
} from "./v1/live-preview-safety.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

const PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v2";
const PRIMARY_STALE_SECONDS = 150;
const CRITICAL_GUARD_LEASE_KEY = "live_deadline_critical_guard:v1";
const CRITICAL_GUARD_LEASE_SECONDS = 20;

type LiveRoleEnv = Env & { LIVE_DEADLINE_ROLE?: string };

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function isHistoricalRecencyScan(sql: string): boolean {
  const q = sql.toLowerCase().replace(/\s+/g, " ");
  const runnerScan = q.includes("race_date between")
    && q.includes("join rt_runners")
    && q.includes("join rt_results")
    && q.includes("marketprobability");
  const featureDeltaScan = q.includes("select distinct ra.race_id as raceid")
    && q.includes("join rt_runners ru")
    && q.includes("ra.race_date>?")
    && q.includes("json_each(?)");
  const betScan = q.includes("from rt_public_bets b join rt_races r")
    && q.includes("race_date between")
    && q.includes("source_prediction_id=-2")
    && q.includes("settlement_status='settled'");
  return runnerScan || featureDeltaScan || betScan;
}

function emptyPreparedStatement(): D1PreparedStatement {
  const statement = {
    bind: (..._values: unknown[]) => statement,
    first: async () => null,
    all: async () => ({ results: [], success: true, meta: {} }),
    raw: async () => [],
    run: async () => ({ success: true, meta: {} }),
  };
  return statement as unknown as D1PreparedStatement;
}

function freeTierSafeDb(db: D1Database): D1Database {
  return new Proxy(db as object, {
    get(target, prop, receiver) {
      if (prop === "prepare") {
        return (sql: string) => {
          if (isHistoricalRecencyScan(sql)) {
            console.warn("LIVE_RECENCY_HISTORY_SCAN_SKIPPED_FREE_TIER");
            return emptyPreparedStatement();
          }
          return (db.prepare as (sql: string) => D1PreparedStatement).call(db, sql);
        };
      }
      const value = Reflect.get(target, prop, receiver);
      return typeof value === "function" ? value.bind(db) : value;
    },
  }) as unknown as D1Database;
}

function safeEnv(env: LiveRoleEnv): LiveRoleEnv {
  return { ...env, DB: freeTierSafeDb(env.DB) };
}

async function markPrimaryAlive(db: D1Database, result: Record<string, unknown>): Promise<void> {
  const value = JSON.stringify({
    role: "primary",
    checkedAt: new Date().toISOString(),
    status: result.status ?? null,
    driverVersion: result.version ?? null,
  });
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(PRIMARY_HEARTBEAT_KEY, value).run();
}

async function primaryIsAlive(db: D1Database): Promise<boolean> {
  const row = await db.prepare(`
    SELECT CASE WHEN unixepoch(updated_at) >= unixepoch('now') - ? THEN 1 ELSE 0 END AS alive
    FROM rt_system_state WHERE state_key=? LIMIT 1
  `).bind(PRIMARY_STALE_SECONDS, PRIMARY_HEARTBEAT_KEY).first<{ alive: number }>();
  return Number(row?.alive ?? 0) === 1;
}

async function runCriticalDeadlineProtection(
  env: LiveRoleEnv,
  now: Date,
  role: string,
): Promise<{ acquired: boolean; guard: DeadlineGuardAudit | null; restored: string[] }> {
  const owner = `critical-guard:${role}:${crypto.randomUUID()}`;
  const acquired = await acquireNamedLiveDeadlineLease(
    env.DB,
    CRITICAL_GUARD_LEASE_KEY,
    owner,
    CRITICAL_GUARD_LEASE_SECONDS,
  );
  if (!acquired) return { acquired: false, guard: null, restored: [] };

  try {
    let guard = await runCompletedWorkerDeadlineGuard(env, now);
    let restored: string[] = [];
    if (guard.errors.some((row) => row.error.includes("DEADLINE_GUARD_PREVIEW_MISSING"))) {
      restored = await restoreNewestOfficialPreviewArchives(env.DB, guard.date);
      guard = await runCompletedWorkerDeadlineGuard(env, new Date());
    }
    if (guard.errors.length) {
      console.error("LIVE_CRITICAL_GUARD_UNRESOLVED", JSON.stringify({
        role,
        dueRaceIds: guard.dueRaceIds,
        errors: guard.errors,
      }));
    }
    return { acquired: true, guard, restored };
  } finally {
    try {
      await releaseNamedLiveDeadlineLease(env.DB, CRITICAL_GUARD_LEASE_KEY, owner);
    } catch (error) {
      console.error("LIVE_CRITICAL_GUARD_LEASE_RELEASE_FAILED", errorText(error));
    }
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    return liveDeadlineV2.fetch(request);
  },

  async scheduled(controller: ScheduledController, env: LiveRoleEnv): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime) ? new Date(controller.scheduledTime) : new Date();
    const raceDay = await shouldRunOnJraRaceDay(scheduledAt);
    if (!raceDay.shouldRun) {
      console.log("LIVE_DEADLINE_NON_RACE_DAY_SKIP", JSON.stringify({
        raceDate: raceDay.raceDate,
        role: env.LIVE_DEADLINE_ROLE || "primary",
        reason: raceDay.reason,
      }));
      return;
    }

    const liveEnv = safeEnv(env);
    const role = String(env.LIVE_DEADLINE_ROLE || "primary").toLowerCase();

    // Critical finalization always runs before the CPU-heavy JRA/model path and
    // outside the heavy-work lease. Therefore a killed/stuck preview invocation
    // cannot prevent a previously stored official last-good from becoming final.
    try {
      await runCriticalDeadlineProtection(liveEnv, new Date(), role);
    } catch (error) {
      // Do not sacrifice preview generation if the guard itself has a transient
      // D1 problem. The other role gets an independent guard attempt as well.
      console.error("LIVE_CRITICAL_GUARD_FAILED", role, errorText(error));
    }

    if (role === "backup" && await primaryIsAlive(env.DB)) return;

    const result = await runIsolatedLiveDeadlineTick(liveEnv, scheduledAt.toISOString());

    if (role === "primary") {
      // lease_busy means another invocation owns the heavy path; it is NOT proof
      // that this primary completed useful work and must never refresh heartbeat.
      if (String(result.status || "") !== "lease_busy" && result.ok !== false) {
        await markPrimaryAlive(env.DB, result);
      }
      return;
    }

    console.warn("LIVE_DEADLINE_BACKUP_TAKEOVER", JSON.stringify({
      checkedAt: new Date().toISOString(),
      status: result.status ?? null,
    }));
  },
} satisfies ExportedHandler<LiveRoleEnv>;
