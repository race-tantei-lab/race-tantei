import liveDeadlineV2 from "./live-deadline-entry-v2.js";
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

const RECHECK_MS = 5 * 60_000;
let indexState: { ready: boolean; checkedAt: number; missing: string[] } | null = null;

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

export default {
  async fetch(request: Request): Promise<Response> {
    return liveDeadlineV2.fetch(request);
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const state = await requiredLiveIndexesReady(env.DB);
    if (!state.ready) {
      console.warn("LIVE_DEADLINE_WAITING_FOR_INDEXES", JSON.stringify(state.missing));
      return;
    }
    await liveDeadlineV2.scheduled(controller, env);
  },
} satisfies ExportedHandler<Env>;
