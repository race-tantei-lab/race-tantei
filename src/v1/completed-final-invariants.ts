type TriggerRow = { name: string; sql: string | null };

const VERIFY_INTERVAL_MS = 5 * 60_000;
const REQUIRED_TRIGGERS = [
  "rt_guard_final_bet_insert_deadline",
  "rt_guard_final_state_insert_deadline",
  "rt_guard_locked_public_bet_terms",
  "rt_guard_locked_worker_final_state",
  "rt_guard_probability_fallback_final_insert",
  "rt_guard_probability_fallback_final_update",
  "rt_guard_official_odds_final_insert",
  "rt_guard_official_odds_final_update",
] as const;

let lastVerifiedAt = 0;

// Production DDL is installed once by deploy-live-deadline.yml. Race-day
// scheduled Workers only verify it. Never CREATE/DROP triggers in the hot path:
// rebuilding schema objects during a race day can consume D1 rows_written.
export async function ensureCompletedFinalImmutability(db: D1Database): Promise<void> {
  const now = Date.now();
  if (lastVerifiedAt && now - lastVerifiedAt < VERIFY_INTERVAL_MS) return;

  const placeholders = REQUIRED_TRIGGERS.map(() => "?").join(",");
  const rows = await db.prepare(`SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN (${placeholders})`)
    .bind(...REQUIRED_TRIGGERS)
    .all<TriggerRow>();
  const triggerSql = new Map((rows.results ?? []).map((row) => [String(row.name), String(row.sql || "")]));
  const missing = REQUIRED_TRIGGERS.filter((name) => !triggerSql.has(name));
  if (missing.length) throw new Error(`FINAL_INVARIANT_TRIGGER_MISSING:${missing.join(",")}`);

  const betSql = triggerSql.get("rt_guard_final_bet_insert_deadline") ?? "";
  const stateSql = triggerSql.get("rt_guard_final_state_insert_deadline") ?? "";
  const officialInsertSql = triggerSql.get("rt_guard_official_odds_final_insert") ?? "";
  const officialUpdateSql = triggerSql.get("rt_guard_official_odds_final_update") ?? "";
  if (!betSql.includes("FINAL_BET_REFLECTION_WINDOW_PASSED")) throw new Error("FINAL_BET_DEADLINE_TRIGGER_STALE");
  if (!stateSql.includes("FINAL_STATE_REFLECTION_WINDOW_PASSED")) throw new Error("FINAL_STATE_DEADLINE_TRIGGER_STALE");
  if (!triggerSql.get("rt_guard_locked_public_bet_terms")?.includes("IMMUTABLE_FINAL_BET_TERMS")) throw new Error("FINAL_BET_IMMUTABILITY_TRIGGER_STALE");
  if (!triggerSql.get("rt_guard_locked_worker_final_state")?.includes("IMMUTABLE_WORKER_FINAL_STATE")) throw new Error("FINAL_STATE_IMMUTABILITY_TRIGGER_STALE");
  if (!triggerSql.get("rt_guard_probability_fallback_final_insert")?.includes("PROBABILITY_FALLBACK_FORBIDDEN")) throw new Error("FINAL_FALLBACK_INSERT_TRIGGER_STALE");
  if (!triggerSql.get("rt_guard_probability_fallback_final_update")?.includes("PROBABILITY_FALLBACK_FORBIDDEN")) throw new Error("FINAL_FALLBACK_UPDATE_TRIGGER_STALE");
  if (!officialInsertSql.includes("OFFICIAL_JRA_ODDS_REQUIRED") || !officialUpdateSql.includes("OFFICIAL_JRA_ODDS_REQUIRED")) {
    throw new Error("FINAL_OFFICIAL_ODDS_TRIGGER_STALE");
  }
  if (!officialInsertSql.includes("jra-fast-official") || !officialInsertSql.includes("jra-crawl-official")) {
    throw new Error("FINAL_OFFICIAL_ODDS_SOURCE_TRIGGER_STALE");
  }

  lastVerifiedAt = now;
}
