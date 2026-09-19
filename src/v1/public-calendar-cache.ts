import type { Env } from "./types.js";

const STATE_KEY = "public_calendar_cache:v1";
const ARCHIVE_END = "2026-08-09";
const REFRESH_MS = 6 * 60 * 60 * 1000;

export type CachedCalendarRow = { raceDate: string; venue: string; raceCount: number };
type CachePayload = { version: 1; refreshedAt: string; rows: CachedCalendarRow[] };

function validPayload(value: unknown): value is CachePayload {
  if (!value || typeof value !== "object") return false;
  const p = value as CachePayload;
  return p.version === 1 && typeof p.refreshedAt === "string" && Array.isArray(p.rows);
}

async function loadPayload(db: D1Database): Promise<CachePayload | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(STATE_KEY).first<{ value: string | null }>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value);
    return validPayload(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function readPublicCalendarCache(db: D1Database): Promise<CachedCalendarRow[]> {
  return (await loadPayload(db))?.rows ?? [];
}

export async function refreshPublicCalendarCache(env: Env, now = new Date()): Promise<{ refreshed: boolean; rows: number }> {
  const current = await loadPayload(env.DB);
  const refreshedMs = current ? Date.parse(current.refreshedAt) : Number.NaN;
  if (Number.isFinite(refreshedMs) && now.getTime() - refreshedMs < REFRESH_MS) {
    return { refreshed: false, rows: current!.rows.length };
  }

  const result = await env.DB.prepare(`
    SELECT race_date AS raceDate,venue,COUNT(*) AS raceCount
    FROM rt_races
    WHERE race_date>?
    GROUP BY race_date,venue
    ORDER BY race_date,venue
  `).bind(ARCHIVE_END).all<CachedCalendarRow>();

  const rows = (result.results ?? []).map((row) => ({
    raceDate: String(row.raceDate),
    venue: String(row.venue),
    raceCount: Number(row.raceCount),
  }));
  const payload: CachePayload = { version: 1, refreshedAt: now.toISOString(), rows };
  await env.DB.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(STATE_KEY, JSON.stringify(payload)).run();
  return { refreshed: true, rows: rows.length };
}
