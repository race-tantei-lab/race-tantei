import type { Env } from "./types.js";

export const CUMULATIVE_PERFORMANCE_VERSION = "cumulative-performance-v3-daily-light";
export const CUMULATIVE_PERFORMANCE_STATE_KEY = "public_cumulative_performance:v1";
export const CUMULATIVE_HISTORICAL_THROUGH = "2026-08-09";
export const CUMULATIVE_LIVE_FROM = "2026-08-10";

export type CumulativeMetric = {
  races: number;
  stakeYen: number;
  returnYen: number;
  roiPct: number;
};

export type CumulativeVenueMetric = CumulativeMetric & { venue: string };

export type CumulativePerformanceSnapshot = {
  version: string;
  basis: "ten-year-backtest-plus-production-light";
  historicalThrough: string;
  liveFrom: string;
  asOfDate: string;
  closedThroughDate: string;
  currentDate: string | null;
  currentSettledRaces: number;
  updatedAt: string | null;
  total: CumulativeMetric;
  venues: CumulativeVenueMetric[];
  live: CumulativeMetric;
  closedTotal: CumulativeMetric;
  closedVenues: CumulativeVenueMetric[];
  closedLive: CumulativeMetric;
  unresolvedRaceIds: string[];
};

type DeltaRaceRow = {
  raceDate: string;
  raceId: string;
  venue: string;
  rowCount: number;
  settledRows: number;
  stakeYen: number;
  returnYen: number;
};

const LEGACY_VERSIONS = new Set([
  "cumulative-performance-v1-nightly-light",
  "cumulative-performance-v2-five-minute-light",
]);
const HISTORICAL_TOTAL = { races: 14410, stakeYen: 28820000, returnYen: 124401700 } as const;
const HISTORICAL_VENUES = [
  { venue: "札幌", races: 670, stakeYen: 1340000, returnYen: 5330600 },
  { venue: "函館", races: 600, stakeYen: 1200000, returnYen: 5272100 },
  { venue: "福島", races: 960, stakeYen: 1920000, returnYen: 10264200 },
  { venue: "新潟", races: 1360, stakeYen: 2720000, returnYen: 12600700 },
  { venue: "東京", races: 2230, stakeYen: 4460000, returnYen: 17897900 },
  { venue: "中山", races: 2085, stakeYen: 4170000, returnYen: 16402800 },
  { venue: "中京", races: 1515, stakeYen: 3030000, returnYen: 11882300 },
  { venue: "京都", races: 1705, stakeYen: 3410000, returnYen: 13982100 },
  { venue: "阪神", races: 2115, stakeYen: 4230000, returnYen: 16787400 },
  { venue: "小倉", races: 1170, stakeYen: 2340000, returnYen: 13981600 },
] as const;
const CACHE_MS = 30_000;
const MAX_UNRESOLVED_RECONCILE = 40;
let cache: { expiresAt: number; value: CumulativePerformanceSnapshot } | null = null;

function metric(races: number, stakeYen: number, returnYen: number): CumulativeMetric {
  return { races, stakeYen, returnYen, roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : 0 };
}

function cloneVenue(row: CumulativeVenueMetric): CumulativeVenueMetric {
  return { venue: row.venue, ...metric(row.races, row.stakeYen, row.returnYen) };
}

export function historicalCumulativeBaseline(): CumulativePerformanceSnapshot {
  const venues = HISTORICAL_VENUES.map((row) => ({ venue: row.venue, ...metric(row.races, row.stakeYen, row.returnYen) }));
  const total = metric(HISTORICAL_TOTAL.races, HISTORICAL_TOTAL.stakeYen, HISTORICAL_TOTAL.returnYen);
  const live = metric(0, 0, 0);
  return {
    version: CUMULATIVE_PERFORMANCE_VERSION,
    basis: "ten-year-backtest-plus-production-light",
    historicalThrough: CUMULATIVE_HISTORICAL_THROUGH,
    liveFrom: CUMULATIVE_LIVE_FROM,
    asOfDate: CUMULATIVE_HISTORICAL_THROUGH,
    closedThroughDate: CUMULATIVE_HISTORICAL_THROUGH,
    currentDate: null,
    currentSettledRaces: 0,
    updatedAt: null,
    total,
    venues,
    live,
    closedTotal: total,
    closedVenues: venues.map(cloneVenue),
    closedLive: live,
    unresolvedRaceIds: [],
  };
}

function normalizeStored(value: unknown): CumulativePerformanceSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (
    row.basis !== "ten-year-backtest-plus-production-light"
    || typeof row.asOfDate !== "string"
    || !row.total
    || !Array.isArray(row.venues)
    || !row.live
    || (row.version !== CUMULATIVE_PERFORMANCE_VERSION && !LEGACY_VERSIONS.has(String(row.version ?? "")))
  ) return null;

  const total = row.total as CumulativeMetric;
  const venues = row.venues as CumulativeVenueMetric[];
  const live = row.live as CumulativeMetric;
  const closedTotal = (row.closedTotal as CumulativeMetric | undefined) ?? total;
  const closedVenues = (row.closedVenues as CumulativeVenueMetric[] | undefined) ?? venues;
  const closedLive = (row.closedLive as CumulativeMetric | undefined) ?? live;
  const closedThroughDate = String(row.closedThroughDate ?? row.asOfDate);
  return {
    version: CUMULATIVE_PERFORMANCE_VERSION,
    basis: "ten-year-backtest-plus-production-light",
    historicalThrough: CUMULATIVE_HISTORICAL_THROUGH,
    liveFrom: CUMULATIVE_LIVE_FROM,
    asOfDate: String(row.asOfDate),
    closedThroughDate,
    currentDate: typeof row.currentDate === "string" ? row.currentDate : null,
    currentSettledRaces: Number(row.currentSettledRaces ?? 0),
    updatedAt: typeof row.updatedAt === "string" ? row.updatedAt : null,
    total: metric(Number(total.races), Number(total.stakeYen), Number(total.returnYen)),
    venues: venues.map(cloneVenue),
    live: metric(Number(live.races), Number(live.stakeYen), Number(live.returnYen)),
    closedTotal: metric(Number(closedTotal.races), Number(closedTotal.stakeYen), Number(closedTotal.returnYen)),
    closedVenues: closedVenues.map(cloneVenue),
    closedLive: metric(Number(closedLive.races), Number(closedLive.stakeYen), Number(closedLive.returnYen)),
    unresolvedRaceIds: Array.isArray(row.unresolvedRaceIds) ? row.unresolvedRaceIds.map(String).filter(Boolean).slice(0, MAX_UNRESOLVED_RECONCILE) : [],
  };
}

async function readStored(db: D1Database): Promise<CumulativePerformanceSnapshot | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(CUMULATIVE_PERFORMANCE_STATE_KEY)
    .first<{ value: string }>();
  if (!row?.value) return null;
  try { return normalizeStored(JSON.parse(row.value)); } catch { return null; }
}

export async function loadCumulativePerformance(db: D1Database): Promise<CumulativePerformanceSnapshot> {
  if (cache && cache.expiresAt > Date.now()) return cache.value;
  const value = await readStored(db) ?? historicalCumulativeBaseline();
  cache = { expiresAt: Date.now() + CACHE_MS, value };
  return value;
}

function jstDate(now: Date, offsetDays = 0): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 86400_000).toISOString().slice(0, 10);
}

const DAILY_REFRESH_HOUR_JST = 19;
const DAILY_REFRESH_MINUTE_JST = 5;

function dueForDailyRefresh(now: Date): boolean {
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return jst.getUTCHours() === DAILY_REFRESH_HOUR_JST
    && jst.getUTCMinutes() === DAILY_REFRESH_MINUTE_JST;
}

async function rowsByDateRange(db: D1Database, afterDate: string, throughDate: string): Promise<DeltaRaceRow[]> {
  if (afterDate >= throughDate) return [];
  const result = await db.prepare(`
    SELECT r.race_date AS raceDate,b.race_id AS raceId,r.venue,
           COUNT(*) AS rowCount,
           SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS stakeYen,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date>? AND r.race_date<=?
      AND b.course='ライト'
      AND b.source_prediction_id=-2
    GROUP BY r.race_date,b.race_id,r.venue
    ORDER BY r.race_date,b.race_id
  `).bind(afterDate, throughDate).all<DeltaRaceRow>();
  return normalizeRows(result.results ?? []);
}

async function rowsForDate(db: D1Database, date: string): Promise<DeltaRaceRow[]> {
  const result = await db.prepare(`
    SELECT r.race_date AS raceDate,b.race_id AS raceId,r.venue,
           COUNT(*) AS rowCount,
           SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS stakeYen,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date=?
      AND b.course='ライト'
      AND b.source_prediction_id=-2
    GROUP BY r.race_date,b.race_id,r.venue
    ORDER BY b.race_id
  `).bind(date).all<DeltaRaceRow>();
  return normalizeRows(result.results ?? []);
}

async function rowsForRaceIds(db: D1Database, raceIds: string[]): Promise<DeltaRaceRow[]> {
  if (!raceIds.length) return [];
  const ids = raceIds.slice(0, MAX_UNRESOLVED_RECONCILE);
  const marks = ids.map(() => "?").join(",");
  const result = await db.prepare(`
    SELECT r.race_date AS raceDate,b.race_id AS raceId,r.venue,
           COUNT(*) AS rowCount,
           SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS stakeYen,
           COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.race_id IN (${marks})
      AND b.course='ライト'
      AND b.source_prediction_id=-2
    GROUP BY r.race_date,b.race_id,r.venue
  `).bind(...ids).all<DeltaRaceRow>();
  return normalizeRows(result.results ?? []);
}

function normalizeRows(rows: DeltaRaceRow[]): DeltaRaceRow[] {
  return rows.map((row) => ({
    raceDate: String(row.raceDate),
    raceId: String(row.raceId),
    venue: String(row.venue),
    rowCount: Number(row.rowCount),
    settledRows: Number(row.settledRows),
    stakeYen: Number(row.stakeYen),
    returnYen: Number(row.returnYen),
  }));
}

function validSettled(row: DeltaRaceRow): boolean {
  return row.rowCount === 2 && row.settledRows === 2 && row.stakeYen === 2_000;
}

function addRows(
  total: CumulativeMetric,
  venues: CumulativeVenueMetric[],
  live: CumulativeMetric,
  rows: DeltaRaceRow[],
): { total: CumulativeMetric; venues: CumulativeVenueMetric[]; live: CumulativeMetric } {
  const byVenue = new Map(venues.map((row) => [row.venue, cloneVenue(row)]));
  let stake = 0;
  let returns = 0;
  for (const row of rows) {
    const current = byVenue.get(row.venue) ?? { venue: row.venue, ...metric(0, 0, 0) };
    current.races += 1;
    current.stakeYen += row.stakeYen;
    current.returnYen += row.returnYen;
    current.roiPct = current.stakeYen > 0 ? current.returnYen / current.stakeYen * 100 : 0;
    byVenue.set(row.venue, current);
    stake += row.stakeYen;
    returns += row.returnYen;
  }
  return {
    total: metric(total.races + rows.length, total.stakeYen + stake, total.returnYen + returns),
    venues: [...byVenue.values()],
    live: metric(live.races + rows.length, live.stakeYen + stake, live.returnYen + returns),
  };
}

function stableSignature(value: CumulativePerformanceSnapshot): string {
  return JSON.stringify({
    asOfDate: value.asOfDate,
    closedThroughDate: value.closedThroughDate,
    currentDate: value.currentDate,
    currentSettledRaces: value.currentSettledRaces,
    total: value.total,
    venues: value.venues,
    live: value.live,
    closedTotal: value.closedTotal,
    closedVenues: value.closedVenues,
    closedLive: value.closedLive,
    unresolvedRaceIds: value.unresolvedRaceIds,
  });
}

export type CumulativeRefreshAudit = {
  status: "outside_window" | "up_to_date" | "updated";
  asOfDate: string;
  closedThroughDate: string;
  currentDate: string;
  currentSettledRaces: number;
  unresolvedRaceIds: string[];
  addedClosedRaces: number;
  reconciledRaces: number;
};

export async function refreshCumulativePerformanceIfDue(env: Env, now = new Date()): Promise<CumulativeRefreshAudit> {
  const today = jstDate(now);
  const yesterday = jstDate(now, -1);

  // The public Worker still runs every five minutes for settlement/maintenance,
  // but cumulative ROI must not consume D1 on every tick. Only the scheduled
  // 19:05 JST tick is allowed past this guard.
  if (!dueForDailyRefresh(now)) {
    return {
      status: "outside_window",
      asOfDate: "",
      closedThroughDate: "",
      currentDate: today,
      currentSettledRaces: 0,
      unresolvedRaceIds: [],
      addedClosedRaces: 0,
      reconciledRaces: 0,
    };
  }

  const stored = await readStored(env.DB) ?? historicalCumulativeBaseline();
  const before = stableSignature(stored);

  let closedTotal = stored.closedTotal;
  let closedVenues = stored.closedVenues;
  let closedLive = stored.closedLive;
  let closedThroughDate = stored.closedThroughDate;
  let unresolved = new Set(stored.unresolvedRaceIds);
  let addedClosedRaces = 0;
  let reconciledRaces = 0;

  if (closedThroughDate < yesterday) {
    const rows = await rowsByDateRange(env.DB, closedThroughDate, yesterday);
    const complete = rows.filter(validSettled);
    const incomplete = rows.filter((row) => !validSettled(row));
    if (complete.length) {
      const added = addRows(closedTotal, closedVenues, closedLive, complete);
      closedTotal = added.total; closedVenues = added.venues; closedLive = added.live;
      addedClosedRaces += complete.length;
    }
    for (const row of incomplete) unresolved.add(row.raceId);
    closedThroughDate = yesterday;
  }

  if (unresolved.size) {
    const ids = [...unresolved].slice(0, MAX_UNRESOLVED_RECONCILE);
    const rows = await rowsForRaceIds(env.DB, ids);
    const byId = new Map(rows.map((row) => [row.raceId, row]));
    const newlySettled = ids.map((id) => byId.get(id)).filter((row): row is DeltaRaceRow => Boolean(row && validSettled(row)));
    if (newlySettled.length) {
      const added = addRows(closedTotal, closedVenues, closedLive, newlySettled);
      closedTotal = added.total; closedVenues = added.venues; closedLive = added.live;
      reconciledRaces = newlySettled.length;
      for (const row of newlySettled) unresolved.delete(row.raceId);
    }
  }

  const currentRows = closedThroughDate >= today ? [] : (await rowsForDate(env.DB, today)).filter(validSettled);
  const display = addRows(closedTotal, closedVenues, closedLive, currentRows);
  const next: CumulativePerformanceSnapshot = {
    version: CUMULATIVE_PERFORMANCE_VERSION,
    basis: "ten-year-backtest-plus-production-light",
    historicalThrough: CUMULATIVE_HISTORICAL_THROUGH,
    liveFrom: CUMULATIVE_LIVE_FROM,
    asOfDate: currentRows.length ? today : closedThroughDate,
    closedThroughDate,
    currentDate: today,
    currentSettledRaces: currentRows.length,
    updatedAt: stored.updatedAt,
    total: display.total,
    venues: display.venues,
    live: display.live,
    closedTotal,
    closedVenues,
    closedLive,
    unresolvedRaceIds: [...unresolved].slice(0, MAX_UNRESOLVED_RECONCILE),
  };

  const changed = before !== stableSignature(next);
  if (changed) {
    next.updatedAt = now.toISOString();
    await env.DB.prepare(`
      INSERT INTO rt_system_state(state_key,state_value,updated_at)
      VALUES(?,?,CURRENT_TIMESTAMP)
      ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
    `).bind(CUMULATIVE_PERFORMANCE_STATE_KEY, JSON.stringify(next)).run();
  }
  cache = { expiresAt: Date.now() + CACHE_MS, value: next };
  return {
    status: changed ? "updated" : "up_to_date",
    asOfDate: next.asOfDate,
    closedThroughDate,
    currentDate: today,
    currentSettledRaces: currentRows.length,
    unresolvedRaceIds: next.unresolvedRaceIds,
    addedClosedRaces,
    reconciledRaces,
  };
}

export async function cumulativePerformanceResponse(db: D1Database): Promise<Response> {
  const snapshot = await loadCumulativePerformance(db);
  return Response.json({ ok: true, ...snapshot }, {
    headers: {
      "cache-control": "public, max-age=30, stale-while-revalidate=60",
      "x-race-cumulative-performance": CUMULATIVE_PERFORMANCE_VERSION,
    },
  });
}
