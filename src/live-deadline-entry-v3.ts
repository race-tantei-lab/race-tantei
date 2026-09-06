import liveDeadlineV2 from "./live-deadline-entry-v2.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

const REQUIRED_LIVE_INDEXES = [
  "rt_idx_ml_horse_hist_lookup",
  "rt_idx_ml_horse_total_lookup",
  "rt_idx_ml_horse_surface_lookup",
  "rt_idx_ml_horse_dist_lookup",
  "rt_idx_ml_horse_venue_lookup",
  "rt_idx_ml_jockey_lookup",
  "rt_idx_ml_trainer_lookup",
  "rt_idx_ml_pair_lookup",
] as const;

const RECHECK_MS = 60_000;
const PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v1";
const PRIMARY_STALE_SECONDS = 150;
let indexState: { ready: boolean; checkedAt: number; missing: string[] } | null = null;

type LiveRoleEnv = Env & { LIVE_DEADLINE_ROLE?: string };

async function requiredLiveIndexesReady(db: D1Database): Promise<{ ready: boolean; missing: string[] }> {
  const now = Date.now();
  if (indexState && (indexState.ready || now - indexState.checkedAt < RECHECK_MS)) {
    return { ready: indexState.ready, missing: indexState.missing };
  }

  const placeholders = REQUIRED_LIVE_INDEXES.map(() => "?").join(",");
  const result = await db
    .prepare(`SELECT name FROM sqlite_master WHERE type='index' AND name IN (${placeholders})`)
    .bind(...REQUIRED_LIVE_INDEXES)
    .all<{ name: string }>();
  const present = new Set((result.results || []).map((row) => String(row.name)));
  const missing = REQUIRED_LIVE_INDEXES.filter((name) => !present.has(name));
  indexState = { ready: missing.length === 0, checkedAt: now, missing: [...missing] };
  return { ready: indexState.ready, missing: indexState.missing };
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

    const state = await requiredLiveIndexesReady(env.DB);
    if (!state.ready) {
      console.warn("LIVE_DEADLINE_WAITING_FOR_INDEXES", JSON.stringify(state.missing));
      return;
    }

    const role = String(env.LIVE_DEADLINE_ROLE || "primary").toLowerCase();
    if (role === "backup") {
      if (await primaryIsAlive(env.DB)) return;
      console.warn("LIVE_DEADLINE_BACKUP_TAKEOVER", new Date().toISOString());
      await liveDeadlineV2.scheduled(controller, env);
      return;
    }

    // A heartbeat means the primary finished its live tick successfully. If the
    // tick throws, the heartbeat stays stale and the standby can take over.
    await liveDeadlineV2.scheduled(controller, env);
    await markPrimaryAlive(env.DB);
  },
} satisfies ExportedHandler<LiveRoleEnv>;
