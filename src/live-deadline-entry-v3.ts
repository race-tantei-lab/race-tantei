import liveDeadlineV2 from "./live-deadline-entry-v2.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

const PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v1";
const PRIMARY_STALE_SECONDS = 150;

type LiveRoleEnv = Env & { LIVE_DEADLINE_ROLE?: string };

function isHistoricalRecencyScan(sql: string): boolean {
  const q = sql.toLowerCase().replace(/\s+/g, " ");
  const runnerScan = q.includes("with scored as")
    && q.includes("join rt_runners")
    && q.includes("join rt_results")
    && q.includes("row_number") === false
    && q.includes("race_date between");
  const betScan = q.includes("from rt_public_bets b join rt_races r")
    && q.includes("race_date between")
    && q.includes("source_prediction_id=-2")
    && q.includes("settlement_status='settled'");
  return runnerScan || betScan;
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

async function markPrimaryAlive(db: D1Database): Promise<void> {
  const value = JSON.stringify({ role: "primary", checkedAt: new Date().toISOString() });
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

export default {
  async fetch(request: Request): Promise<Response> {
    return liveDeadlineV2.fetch(request);
  },

  async scheduled(controller: ScheduledController, env: LiveRoleEnv): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime) ? new Date(controller.scheduledTime) : new Date();
    const raceDay = await shouldRunOnJraRaceDay(scheduledAt);
    if (!raceDay.shouldRun) {
      console.log("LIVE_DEADLINE_NON_RACE_DAY_SKIP", JSON.stringify({ raceDate: raceDay.raceDate, role: env.LIVE_DEADLINE_ROLE || "primary", reason: raceDay.reason }));
      return;
    }

    // Live ticks may use only bounded current-race/day reads. The 30-day recency
    // feature scans are intentionally neutralized here: running them every minute
    // exhausted the D1 Free rows_read allowance before midday.
    const liveEnv = safeEnv(env);
    const role = String(env.LIVE_DEADLINE_ROLE || "primary").toLowerCase();
    if (role === "backup") {
      if (await primaryIsAlive(env.DB)) return;
      console.warn("LIVE_DEADLINE_BACKUP_TAKEOVER", new Date().toISOString());
      await liveDeadlineV2.scheduled(controller, liveEnv);
      return;
    }

    // A heartbeat means the primary finished its live tick successfully. If the
    // tick throws, the heartbeat stays stale and the standby can take over.
    await liveDeadlineV2.scheduled(controller, liveEnv);
    await markPrimaryAlive(env.DB);
  },
} satisfies ExportedHandler<LiveRoleEnv>;
