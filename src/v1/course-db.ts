import { savePrediction, settleRace } from "./db.js";
import { performanceExclusionSql } from "./performance-exclusions.js";
import type { BudgetCourse, PredictionOutput } from "./types.js";
import { nowIso } from "./utils.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

function storedBetType(course: BudgetCourse, betType: string): string {
  return `${course}｜${betType}`;
}

function splitStoredType(value: string): { course: BudgetCourse | null; ticket: string } {
  const [course, ticket] = value.split("｜");
  if (COURSES.includes(course as BudgetCourse) && ticket) {
    return { course: course as BudgetCourse, ticket };
  }
  return { course: null, ticket: value };
}

function canonicalCombination(ticket: string, combination: string): string {
  const numbers = (combination.match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(ticket)) numbers.sort((a, b) => a - b);
  return numbers.join("-");
}

export async function savePredictionWithCourses(
  db: D1Database,
  raceId: string,
  prediction: PredictionOutput,
  status: "draft" | "locked"
): Promise<{ saved: boolean; predictionId: number | null }> {
  const encoded: PredictionOutput = {
    ...prediction,
    bets: prediction.bets.map((bet) => ({
      ...bet,
      betType: storedBetType(bet.course, bet.betType) as typeof bet.betType
    }))
  };
  return savePrediction(db, raceId, encoded, status);
}

export async function settleRaceWithCourses(db: D1Database, raceId: string): Promise<number> {
  const race = await db.prepare(`SELECT refund_horse_nos_json AS refunds FROM rt_races WHERE race_id=? AND status='finished'`)
    .bind(raceId).first<{ refunds: string }>();
  if (!race) return 0;

  const refunds = new Set<number>(JSON.parse(race.refunds || "[]") as number[]);
  const payoutRows = await db.prepare(`
    SELECT bet_type AS betType, combination, payout_yen AS payoutYen
    FROM rt_payouts WHERE race_id=?
  `).bind(raceId).all<{ betType: string; combination: string; payoutYen: number }>();

  const payoutMap = new Map(
    payoutRows.results.map((row) => [
      `${row.betType}:${canonicalCombination(row.betType, row.combination)}`,
      row.payoutYen
    ])
  );

  const pending = await db.prepare(`
    SELECT b.id, b.bet_type AS betType, b.combination, b.stake_yen AS stakeYen
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE b.race_id=? AND b.settlement_status='pending' AND p.status='locked'
  `).bind(raceId).all<{ id: number; betType: string; combination: string; stakeYen: number }>();

  for (const bet of pending.results) {
    const { ticket } = splitStoredType(bet.betType);
    const horses = (bet.combination.match(/\d{1,2}/g) ?? []).map(Number);
    let returnYen = 0;
    if (horses.some((horseNo) => refunds.has(horseNo))) {
      returnYen = bet.stakeYen;
    } else {
      const payout = payoutMap.get(`${ticket}:${canonicalCombination(ticket, bet.combination)}`) ?? 0;
      returnYen = Math.round((bet.stakeYen / 100) * payout);
    }
    await db.prepare(`
      UPDATE rt_bets SET settlement_status='settled', return_yen=?, settled_at=? WHERE id=?
    `).bind(returnYen, nowIso(), bet.id).run();
  }

  return pending.results.length;
}

export interface CourseMetric {
  course: BudgetCourse;
  settledRaces: number;
  betCount: number;
  stakeYen: number;
  returnYen: number;
  profitYen: number;
  roiPct: number | null;
  hitRatePct: number | null;
}

export async function getCourseMetrics(
  db: D1Database,
  modelVersion?: string
): Promise<CourseMetric[]> {
  const filter = modelVersion ?? "";
  const exclusion = performanceExclusionSql("b.race_id");
  const rows = await db.prepare(`
    SELECT
      CASE
        WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
        WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
        WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        ELSE NULL
      END AS course,
      COUNT(DISTINCT b.race_id) AS settledRaces,
      COUNT(*) AS betCount,
      COALESCE(SUM(b.stake_yen),0) AS stakeYen,
      COALESCE(SUM(b.return_yen),0) AS returnYen,
      COALESCE(SUM(CASE WHEN b.return_yen > 0 THEN 1 ELSE 0 END),0) AS hits
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE b.settlement_status='settled'
      AND ${exclusion}
      AND (?='' OR p.model_version=?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(filter, filter).all<{
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hits: number;
  }>();

  const byCourse = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map((course) => {
    const row = byCourse.get(course);
    const stakeYen = Number(row?.stakeYen ?? 0);
    const returnYen = Number(row?.returnYen ?? 0);
    const betCount = Number(row?.betCount ?? 0);
    const hits = Number(row?.hits ?? 0);
    return {
      course,
      settledRaces: Number(row?.settledRaces ?? 0),
      betCount,
      stakeYen,
      returnYen,
      profitYen: returnYen - stakeYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
      hitRatePct: betCount > 0 ? hits / betCount * 100 : null
    };
  });
}

export async function getCourseMonthlyMetrics(
  db: D1Database,
  modelVersion?: string
): Promise<Array<CourseMetric & { month: string }>> {
  const filter = modelVersion ?? "";
  const exclusion = performanceExclusionSql("b.race_id");
  const rows = await db.prepare(`
    SELECT substr(r.race_date,1,7) AS month,
      CASE
        WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
        WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
        WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
      END AS course,
      COUNT(DISTINCT b.race_id) AS settledRaces,
      COUNT(*) AS betCount,
      COALESCE(SUM(b.stake_yen),0) AS stakeYen,
      COALESCE(SUM(b.return_yen),0) AS returnYen,
      COALESCE(SUM(CASE WHEN b.return_yen > 0 THEN 1 ELSE 0 END),0) AS hits
    FROM rt_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE b.settlement_status='settled'
      AND ${exclusion}
      AND (?='' OR p.model_version=?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY month, course
    ORDER BY month DESC, course
  `).bind(filter, filter).all<{
    month: string;
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hits: number;
  }>();

  return rows.results.map((row) => ({
    month: row.month,
    course: row.course,
    settledRaces: Number(row.settledRaces),
    betCount: Number(row.betCount),
    stakeYen: Number(row.stakeYen),
    returnYen: Number(row.returnYen),
    profitYen: Number(row.returnYen) - Number(row.stakeYen),
    roiPct: Number(row.stakeYen) > 0 ? Number(row.returnYen) / Number(row.stakeYen) * 100 : null,
    hitRatePct: Number(row.betCount) > 0 ? Number(row.hits) / Number(row.betCount) * 100 : null
  }));
}

export function decodeStoredBetType(value: string): { course: BudgetCourse | null; ticket: string } {
  return splitStoredType(value);
}

export { settleRace };