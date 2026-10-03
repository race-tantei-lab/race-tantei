import type { Env } from "./types.js";

export const CUMULATIVE_PERFORMANCE_VERSION = "cumulative-performance-v1-nightly-light";
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
  updatedAt: string | null;
  total: CumulativeMetric;
  venues: CumulativeVenueMetric[];
  live: CumulativeMetric;
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

const EOD_FROM_MINUTE = 18 * 60 + 35;
const EOD_THROUGH_MINUTE = 23 * 60 + 5;
const EOD_SLOT_OFFSET = 5;
const CACHE_MS = 60_000;

let cache: { expiresAt: number; value: CumulativePerformanceSnapshot } | null = null;

function metric(races: number, stakeYen: number, returnYen: number): CumulativeMetric {
  return {
    races,
    stakeYen,
    returnYen,
    roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : 0,
  };
}

export function historicalCumulativeBaseline(): CumulativePerformanceSnapshot {
  return {
    version: CUMULATIVE_PERFORMANCE_VERSION,
    basis: "ten-year-backtest-plus-production-light",
    historicalThrough: CUMULATIVE_HISTORICAL_THROUGH,
    liveFrom: CUMULATIVE_LIVE_FROM,
    asOfDate: CUMULATIVE_HISTORICAL_THROUGH,
    updatedAt: null,
    total: metric(HISTORICAL_TOTAL.races, HISTORICAL_TOTAL.stakeYen, HISTORICAL_TOTAL.returnYen),
    venues: HISTORICAL_VENUES.map((row) => ({
      venue: row.venue,
      ...metric(row.races, row.stakeYen, row.returnYen),
    })),
    live: metric(0, 0, 0),
  };
}

function isSnapshot(value: unknown): value is CumulativePerformanceSnapshot {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<CumulativePerformanceSnapshot>;
  return row.version === CUMULATIVE_PERFORMANCE_VERSION
    && row.basis === "ten-year-backtest-plus-production-light"
    && typeof row.asOfDate === "string"
    && Boolean(row.total)
    && Array.isArray(row.venues)
    && Boolean(row.live);
}

async function readStored(db: D1Database): Promise<CumulativePerformanceSnapshot | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(CUMULATIVE_PERFORMANCE_STATE_KEY)
    .first<{ value: string }>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value);
    return isSnapshot(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function loadCumulativePerformance(db: D1Database): Promise<CumulativePerformanceSnapshot> {
  if (cache && cache.expiresAt > Date.now()) return cache.value;
  const value = await readStored(db) ?? historicalCumulativeBaseline();
  cache = { expiresAt: Date.now() + CACHE_MS, value };
  return value;
}

function jstDate(now: Date): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstMinuteOfDay(now: Date): number {
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return jst.getUTCHours() * 60 + jst.getUTCMinutes();
}

function dueForNightlyRefresh(now: Date): boolean {
  const minute = jstMinuteOfDay(now);
  return minute >= EOD_FROM_MINUTE
    && minute <= EOD_THROUGH_MINUTE
    && minute % 15 === EOD_SLOT_OFFSET;
}

async function deltaRows(db: D1Database, afterDate: string, throughDate: string): Promise<DeltaRaceRow[]> {
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
  return (result.results ?? []).map((row) => ({
    raceDate: String(row.raceDate),
    raceId: String(row.raceId),
    venue: String(row.venue),
    rowCount: Number(row.rowCount),
    settledRows: Number(row.settledRows),
    stakeYen: Number(row.stakeYen),
    returnYen: Number(row.returnYen),
  }));
}

export type CumulativeRefreshAudit = {
  status: "outside_window" | "up_to_date" | "waiting_settlement" | "updated";
  asOfDate: string;
  throughDate: string;
  addedRaces: number;
  incompleteRaceIds: string[];
};

export async function refreshCumulativePerformanceIfDue(env: Env, now = new Date()): Promise<CumulativeRefreshAudit> {
  const today = jstDate(now);
  if (!dueForNightlyRefresh(now)) {
    return { status: "outside_window", asOfDate: "", throughDate: today, addedRaces: 0, incompleteRaceIds: [] };
  }

  const current = await readStored(env.DB) ?? historicalCumulativeBaseline();
  if (current.asOfDate >= today) {
    cache = { expiresAt: Date.now() + CACHE_MS, value: current };
    return { status: "up_to_date", asOfDate: current.asOfDate, throughDate: today, addedRaces: 0, incompleteRaceIds: [] };
  }

  const rows = await deltaRows(env.DB, current.asOfDate, today);
  const incomplete = rows.filter((row) =>
    row.rowCount !== 2 || row.settledRows !== 2 || row.stakeYen !== 2_000
  );
  if (incomplete.length) {
    return {
      status: "waiting_settlement",
      asOfDate: current.asOfDate,
      throughDate: today,
      addedRaces: 0,
      incompleteRaceIds: incomplete.map((row) => row.raceId),
    };
  }

  const venues = new Map(current.venues.map((row) => [row.venue, { ...row }]));
  let addedStake = 0;
  let addedReturn = 0;
  for (const row of rows) {
    const existing = venues.get(row.venue) ?? {
      venue: row.venue,
      races: 0,
      stakeYen: 0,
      returnYen: 0,
      roiPct: 0,
    };
    existing.races += 1;
    existing.stakeYen += row.stakeYen;
    existing.returnYen += row.returnYen;
    existing.roiPct = existing.stakeYen > 0 ? existing.returnYen / existing.stakeYen * 100 : 0;
    venues.set(row.venue, existing);
    addedStake += row.stakeYen;
    addedReturn += row.returnYen;
  }

  const nextTotal = metric(
    current.total.races + rows.length,
    current.total.stakeYen + addedStake,
    current.total.returnYen + addedReturn,
  );
  const nextLive = metric(
    current.live.races + rows.length,
    current.live.stakeYen + addedStake,
    current.live.returnYen + addedReturn,
  );
  const next: CumulativePerformanceSnapshot = {
    ...current,
    asOfDate: today,
    updatedAt: now.toISOString(),
    total: nextTotal,
    venues: [...venues.values()],
    live: nextLive,
  };

  await env.DB.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(CUMULATIVE_PERFORMANCE_STATE_KEY, JSON.stringify(next)).run();

  cache = { expiresAt: Date.now() + CACHE_MS, value: next };
  return {
    status: "updated",
    asOfDate: next.asOfDate,
    throughDate: today,
    addedRaces: rows.length,
    incompleteRaceIds: [],
  };
}

export async function cumulativePerformanceResponse(db: D1Database): Promise<Response> {
  const snapshot = await loadCumulativePerformance(db);
  return Response.json({ ok: true, ...snapshot }, {
    headers: {
      "cache-control": "public, max-age=60, stale-while-revalidate=300",
      "x-race-cumulative-performance": CUMULATIVE_PERFORMANCE_VERSION,
    },
  });
}
