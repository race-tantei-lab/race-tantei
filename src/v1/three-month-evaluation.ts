import type { CourseMetric } from "./course-db.js";
import {
  getThreeMonthValidationSnapshot,
  type ThreeMonthValidationSnapshot
} from "./three-month-validation.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_EVALUATION_END_DATE,
  THREE_MONTH_START_DATE,
  THREE_MONTH_TUNING_START_DATE
} from "./three-month-scope.js";
import type { BetType, BudgetCourse } from "./types.js";
import type {
  CourseValidationSummary,
  TicketTypeValidationSummary,
  ValidationDateSnapshot
} from "./validation.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const TICKET_ORDER: BetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

export interface ThreeMonthPeriodSummary {
  startDate: string;
  endDate: string;
  complete: boolean;
  totalRaces: number;
  processedRaces: number;
  remainingRaces: number;
  noBetRaces: number;
  dates: ValidationDateSnapshot[];
  combined: CourseValidationSummary[];
  monthly: Array<{ month: string; courses: CourseValidationSummary[] }>;
}

export interface CorrectedThreeMonthPerformance {
  full: ThreeMonthValidationSnapshot;
  evaluation: ThreeMonthPeriodSummary;
  tuning: ThreeMonthPeriodSummary;
}

function finishTicketSummary(row: TicketTypeValidationSummary): TicketTypeValidationSummary {
  return {
    ...row,
    profitYen: row.returnYen - row.stakeYen,
    roiPct: row.stakeYen > 0 ? row.returnYen / row.stakeYen * 100 : null,
    expectedRoiPct: row.stakeYen > 0 ? row.expectedReturnYen / row.stakeYen * 100 : null
  };
}

function mergeCourseSummaries(
  summaries: CourseValidationSummary[],
  processedRaces: number
): CourseValidationSummary[] {
  return COURSES.map((course) => {
    const rows = summaries.filter((row) => row.course === course);
    const selectedRaces = rows.reduce((sum, row) => sum + row.selectedRaces, 0);
    const hitRaces = rows.reduce((sum, row) => sum + row.hitRaces, 0);
    const tickets = rows.reduce((sum, row) => sum + row.tickets, 0);
    const pendingTickets = rows.reduce((sum, row) => sum + row.pendingTickets, 0);
    const stakeYen = rows.reduce((sum, row) => sum + row.stakeYen, 0);
    const returnYen = rows.reduce((sum, row) => sum + row.returnYen, 0);
    const expectedReturnYen = rows.reduce((sum, row) => sum + row.expectedReturnYen, 0);
    const byTicketType = TICKET_ORDER.map((betType) => {
      const ticketRows = rows
        .flatMap((row) => row.byTicketType)
        .filter((row) => row.betType === betType);
      return finishTicketSummary({
        betType,
        tickets: ticketRows.reduce((sum, row) => sum + row.tickets, 0),
        pendingTickets: ticketRows.reduce((sum, row) => sum + row.pendingTickets, 0),
        stakeYen: ticketRows.reduce((sum, row) => sum + row.stakeYen, 0),
        returnYen: ticketRows.reduce((sum, row) => sum + row.returnYen, 0),
        profitYen: 0,
        expectedReturnYen: ticketRows.reduce((sum, row) => sum + row.expectedReturnYen, 0),
        roiPct: null,
        expectedRoiPct: null,
        hits: ticketRows.reduce((sum, row) => sum + row.hits, 0)
      });
    }).filter((row) => row.tickets > 0);

    return {
      course,
      processedRaces,
      selectedRaces,
      skippedRaces: Math.max(0, processedRaces - selectedRaces),
      hitRaces,
      tickets,
      pendingTickets,
      stakeYen,
      returnYen,
      profitYen: returnYen - stakeYen,
      expectedReturnYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
      expectedRoiPct: stakeYen > 0 ? expectedReturnYen / stakeYen * 100 : null,
      hitRatePct: selectedRaces > 0 ? hitRaces / selectedRaces * 100 : null,
      byTicketType
    };
  });
}

export function summarizeThreeMonthPeriod(
  snapshot: ThreeMonthValidationSnapshot,
  startDate: string,
  endDate: string
): ThreeMonthPeriodSummary {
  const dates = snapshot.dates.filter((row) => row.raceDate >= startDate && row.raceDate <= endDate);
  const totalRaces = dates.reduce((sum, row) => sum + row.totalRaces, 0);
  const processedRaces = dates.reduce((sum, row) => sum + row.processedRaces, 0);
  const noBetRaces = dates.reduce((sum, row) => sum + row.noBetRaces, 0);
  const combined = mergeCourseSummaries(dates.flatMap((row) => row.courses), processedRaces);
  const months = [...new Set(dates.map((row) => row.raceDate.slice(0, 7)))];
  const monthly = months.map((month) => {
    const monthDates = dates.filter((row) => row.raceDate.startsWith(month));
    return {
      month,
      courses: mergeCourseSummaries(
        monthDates.flatMap((row) => row.courses),
        monthDates.reduce((sum, row) => sum + row.processedRaces, 0)
      )
    };
  });
  return {
    startDate,
    endDate,
    complete: dates.length > 0 && dates.every((row) => row.complete),
    totalRaces,
    processedRaces,
    remainingRaces: Math.max(0, totalRaces - processedRaces),
    noBetRaces,
    dates,
    combined,
    monthly
  };
}

export async function getCorrectedThreeMonthPerformance(
  db: D1Database
): Promise<CorrectedThreeMonthPerformance> {
  const full = await getThreeMonthValidationSnapshot(db);
  return {
    full,
    evaluation: summarizeThreeMonthPeriod(
      full,
      THREE_MONTH_START_DATE,
      THREE_MONTH_EVALUATION_END_DATE
    ),
    tuning: summarizeThreeMonthPeriod(
      full,
      THREE_MONTH_TUNING_START_DATE,
      THREE_MONTH_END_DATE
    )
  };
}

function numberValue(value: unknown): number {
  return Number(value ?? 0);
}

export async function getLiveCourseMetricsOutsideThreeMonthScope(
  db: D1Database,
  liveModel: string
): Promise<CourseMetric[]> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
      COUNT(DISTINCT b.race_id) AS settledRaces,
      COUNT(*) AS betCount,
      COALESCE(SUM(b.stake_yen),0) AS stakeYen,
      COALESCE(SUM(b.return_yen),0) AS returnYen,
      COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE p.model_version=? AND p.status='locked' AND b.settlement_status='settled'
      AND (r.race_date<? OR r.race_date>?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(liveModel, THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<{
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hitRaces: number;
  }>();
  const map = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map((course) => {
    const row = map.get(course);
    const settledRaces = numberValue(row?.settledRaces);
    const hitRaces = numberValue(row?.hitRaces);
    const stakeYen = numberValue(row?.stakeYen);
    const returnYen = numberValue(row?.returnYen);
    return {
      course,
      settledRaces,
      betCount: numberValue(row?.betCount),
      stakeYen,
      returnYen,
      profitYen: returnYen - stakeYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
      hitRatePct: settledRaces > 0 ? hitRaces / settledRaces * 100 : null
    };
  });
}

export async function getLiveMonthlyMetricsOutsideThreeMonthScope(
  db: D1Database,
  liveModel: string
): Promise<Array<CourseMetric & { month: string }>> {
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
      COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE p.model_version=? AND p.status='locked' AND b.settlement_status='settled'
      AND (r.race_date<? OR r.race_date>?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY month, course
    ORDER BY month DESC, course
  `).bind(liveModel, THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<{
    month: string;
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hitRaces: number;
  }>();
  return rows.results.map((row) => {
    const settledRaces = numberValue(row.settledRaces);
    const hitRaces = numberValue(row.hitRaces);
    const stakeYen = numberValue(row.stakeYen);
    const returnYen = numberValue(row.returnYen);
    return {
      month: row.month,
      course: row.course,
      settledRaces,
      betCount: numberValue(row.betCount),
      stakeYen,
      returnYen,
      profitYen: returnYen - stakeYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
      hitRatePct: settledRaces > 0 ? hitRaces / settledRaces * 100 : null
    };
  });
}
