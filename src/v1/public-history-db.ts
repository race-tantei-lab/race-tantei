import type { BudgetCourse } from "./types.js";

export interface PublicCourseMetric {
  course: BudgetCourse;
  settledRaces: number;
  stakeYen: number;
  returnYen: number;
  roiPct: number | null;
}

export interface PublicMonthlyMetric extends PublicCourseMetric {
  month: string;
}

export interface PublicBetRow {
  course: BudgetCourse;
  betType: string;
  combination: string;
  stakeYen: number;
  assumedOdds: number | null;
  returnYen: number | null;
  settlementStatus: string;
}

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

/**
 * The production schema and historical public-bet backfill are migrations, not
 * request-time work. The old implementation performed CREATE/INDEX plus a
 * multi-table INSERT ... SELECT over historical rt_bets on every fresh Worker
 * isolate, which could consume the D1 daily rows-read allowance very quickly.
 *
 * Production has already been migrated and seeded, so runtime callers only need
 * the persisted rt_public_bets table. Keep this function for API compatibility,
 * but deliberately make it D1-free.
 */
export function ensurePublicHistory(db: D1Database): Promise<void> {
  void db;
  return Promise.resolve();
}

export async function getPublicCourseMetrics(db: D1Database): Promise<PublicCourseMetric[]> {
  const rows = await db.prepare(`SELECT course,COUNT(DISTINCT race_id) AS settledRaces,COALESCE(SUM(stake_yen),0) AS stakeYen,COALESCE(SUM(return_yen),0) AS returnYen
    FROM rt_public_bets WHERE settlement_status='settled' GROUP BY course`).all<{course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>();
  const map = new Map<BudgetCourse,{course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>(
    rows.results.map((row) => [row.course, row] as const),
  );
  return COURSES.map((course) => {
    const row = map.get(course);
    const stakeYen = Number(row?.stakeYen ?? 0);
    const returnYen = Number(row?.returnYen ?? 0);
    return {
      course,
      settledRaces: Number(row?.settledRaces ?? 0),
      stakeYen,
      returnYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
    };
  });
}

export async function getPublicMonthlyMetrics(db: D1Database): Promise<PublicMonthlyMetric[]> {
  const rows = await db.prepare(`SELECT substr(r.race_date,1,7) AS month,b.course,COUNT(DISTINCT b.race_id) AS settledRaces,COALESCE(SUM(b.stake_yen),0) AS stakeYen,COALESCE(SUM(b.return_yen),0) AS returnYen
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id WHERE b.settlement_status='settled' GROUP BY month,b.course ORDER BY month DESC,b.course`).all<{month:string;course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>();
  return rows.results.map((row) => {
    const stakeYen = Number(row.stakeYen);
    const returnYen = Number(row.returnYen);
    return {
      month: row.month,
      course: row.course,
      settledRaces: Number(row.settledRaces),
      stakeYen,
      returnYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
    };
  });
}

export async function getPublicBets(db: D1Database, raceId: string): Promise<PublicBetRow[]> {
  const rows = await db.prepare(`SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,return_yen AS returnYen,settlement_status AS settlementStatus
    FROM rt_public_bets WHERE race_id=? ORDER BY CASE course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 ELSE 3 END,id`).bind(raceId).all<PublicBetRow>();
  return rows.results.map((row) => ({
    ...row,
    stakeYen: Number(row.stakeYen),
    assumedOdds: row.assumedOdds === null ? null : Number(row.assumedOdds),
    returnYen: row.returnYen === null ? null : Number(row.returnYen),
  }));
}

export async function getPublicBetRaceIds(db: D1Database, raceIds: string[]): Promise<Set<string>> {
  if (!raceIds.length) return new Set();
  const placeholders = raceIds.map(() => "?").join(",");
  const rows = await db.prepare(`SELECT DISTINCT race_id AS raceId FROM rt_public_bets WHERE race_id IN (${placeholders})`).bind(...raceIds).all<{raceId:string}>();
  return new Set(rows.results.map((row) => row.raceId));
}
