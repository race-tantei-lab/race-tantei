import { savePredictionWithCourses, settleRaceWithCourses } from "./course-db.js";
import { getRace, getRunnerHistoryStats, getRunners } from "./db.js";
import { generatePrediction } from "./model.js";
import { getThreeMonthHistoryProgressV2 as getThreeMonthHistoryProgress } from "./three-month-history-v2.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE,
  THREE_MONTH_VALIDATION_CONFIGS
} from "./three-month-scope.js";
import type { BetType, BudgetCourse, PredictionOutput } from "./types.js";
import { nowIso } from "./utils.js";
import type {
  CourseValidationSummary,
  TicketTypeValidationSummary,
  ValidationDateSnapshot,
  ValidationSnapshot
} from "./validation.js";
import { ensureValidationVenueQuotas, type VenueQuotaResult } from "./venue-quota.js";

const MODEL_SUFFIX = "-roi-policy-v1-3m";
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const TICKET_ORDER: BetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

interface DateAggregateRow {
  raceDate: string;
  totalRaces: number;
  processedRaces: number;
  wageredRaces: number;
}

interface CourseAggregateRow {
  raceDate: string;
  course: string;
  selectedRaces: number;
  hitRaces: number;
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
  expectedReturnYen: number;
}

interface TicketAggregateRow {
  raceDate: string;
  course: string;
  betType: string;
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
  expectedReturnYen: number;
  hits: number;
}

export interface ThreeMonthValidationSnapshot extends ValidationSnapshot {
  scopeVersion: string;
  startDate: string;
  endDate: string;
  venueDays: number;
  monthly: Array<{ month: string; courses: CourseValidationSummary[] }>;
}

function modelForDate(raceDate: string): string {
  return `validation-${raceDate}${MODEL_SUFFIX}`;
}

function emptyPrediction(modelVersion: string): PredictionOutput {
  return { modelVersion, runners: [], bets: [], generatedAt: nowIso() };
}

async function pendingRaces(
  db: D1Database,
  limit: number
): Promise<Array<{ raceId: string; raceDate: string }>> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate
    FROM rt_races r
    WHERE r.race_date BETWEEN ? AND ? AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id
          AND p.model_version=('validation-' || r.race_date || ?)
          AND p.status='locked'
      )
    ORDER BY r.race_date, r.venue, r.race_no
    LIMIT ?
  `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX, limit)
    .all<{ raceId: string; raceDate: string }>();
  return rows.results;
}

async function remainingCount(db: D1Database): Promise<number> {
  const row = await db.prepare(`
    SELECT COUNT(*) AS count
    FROM rt_races r
    WHERE r.race_date BETWEEN ? AND ? AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id
          AND p.model_version=('validation-' || r.race_date || ?)
          AND p.status='locked'
      )
  `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX)
    .first<{ count: number }>();
  return Number(row?.count ?? 0);
}

export async function runThreeMonthValidationBatch(
  db: D1Database,
  limit = 24
): Promise<{ processed: number; errors: number; remaining: number }> {
  let processed = 0;
  let errors = 0;
  const rows = await pendingRaces(db, limit);

  for (const row of rows) {
    try {
      const race = await getRace(db, row.raceId);
      if (!race || race.status !== "finished") continue;
      const modelVersion = modelForDate(row.raceDate);
      const runners = await getRunners(db, row.raceId);
      const usable = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
      if (usable.length < 2) {
        await savePredictionWithCourses(db, row.raceId, emptyPrediction(modelVersion), "locked");
        processed += 1;
        continue;
      }
      const history = await getRunnerHistoryStats(db, race, runners);
      const prediction = generatePrediction(race, runners, history, modelVersion, 108, 10000);
      await savePredictionWithCourses(db, row.raceId, prediction, "locked");
      await settleRaceWithCourses(db, row.raceId);
      processed += 1;
    } catch (error) {
      errors += 1;
      console.error("THREE_MONTH_VALIDATION_FAILED", row.raceId, error);
    }
  }

  return { processed, errors, remaining: await remainingCount(db) };
}

function numeric(value: unknown): number {
  return Number(value ?? 0);
}

function validCourse(value: string): BudgetCourse | null {
  return COURSES.includes(value as BudgetCourse) ? value as BudgetCourse : null;
}

function validTicket(value: string): BetType | null {
  return TICKET_ORDER.includes(value as BetType) ? value as BetType : null;
}

function emptyTicketSummary(betType: BetType): TicketTypeValidationSummary {
  return {
    betType,
    tickets: 0,
    stakeYen: 0,
    returnYen: 0,
    profitYen: 0,
    expectedReturnYen: 0,
    roiPct: null,
    expectedRoiPct: null,
    hits: 0,
    pendingTickets: 0
  };
}

function finishTicketSummary(row: TicketTypeValidationSummary): TicketTypeValidationSummary {
  return {
    ...row,
    profitYen: row.returnYen - row.stakeYen,
    roiPct: row.stakeYen > 0 ? row.returnYen / row.stakeYen * 100 : null,
    expectedRoiPct: row.stakeYen > 0 ? row.expectedReturnYen / row.stakeYen * 100 : null
  };
}

function courseSummaryForDate(
  processedRaces: number,
  course: BudgetCourse,
  aggregate: CourseAggregateRow | undefined,
  ticketRows: TicketAggregateRow[]
): CourseValidationSummary {
  const selectedRaces = numeric(aggregate?.selectedRaces);
  const hitRaces = numeric(aggregate?.hitRaces);
  const tickets = numeric(aggregate?.tickets);
  const pendingTickets = numeric(aggregate?.pendingTickets);
  const stakeYen = numeric(aggregate?.stakeYen);
  const returnYen = numeric(aggregate?.returnYen);
  const expectedReturnYen = numeric(aggregate?.expectedReturnYen);
  const byTicketType = TICKET_ORDER.map((betType) => {
    const raw = ticketRows.find((row) => row.betType === betType);
    if (!raw) return emptyTicketSummary(betType);
    return finishTicketSummary({
      betType,
      tickets: numeric(raw.tickets),
      pendingTickets: numeric(raw.pendingTickets),
      stakeYen: numeric(raw.stakeYen),
      returnYen: numeric(raw.returnYen),
      profitYen: 0,
      expectedReturnYen: numeric(raw.expectedReturnYen),
      roiPct: null,
      expectedRoiPct: null,
      hits: numeric(raw.hits)
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
      const ticketRows = rows.flatMap((row) => row.byTicketType).filter((row) => row.betType === betType);
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

export async function getThreeMonthValidationSnapshot(
  db: D1Database
): Promise<ThreeMonthValidationSnapshot> {
  const [dateRows, courseRows, ticketRows, venueRow, historyProgress] = await Promise.all([
    db.prepare(`
      WITH prediction_state AS (
        SELECT p.id AS predictionId, p.race_id AS raceId, r.race_date AS raceDate
        FROM rt_predictions p
        JOIN rt_races r ON r.race_id=p.race_id
        WHERE r.race_date BETWEEN ? AND ?
          AND p.model_version=('validation-' || r.race_date || ?)
          AND p.status='locked'
      ), selected_state AS (
        SELECT DISTINCT ps.raceId, ps.raceDate
        FROM prediction_state ps
        JOIN rt_bets b ON b.prediction_id=ps.predictionId
        WHERE b.bet_type LIKE 'ライト｜%'
           OR b.bet_type LIKE 'スタンダード｜%'
           OR b.bet_type LIKE 'プレミアム｜%'
      )
      SELECT r.race_date AS raceDate,
        COUNT(DISTINCT r.race_id) AS totalRaces,
        COUNT(DISTINCT ps.raceId) AS processedRaces,
        COUNT(DISTINCT ss.raceId) AS wageredRaces
      FROM rt_races r
      LEFT JOIN prediction_state ps ON ps.raceId=r.race_id
      LEFT JOIN selected_state ss ON ss.raceId=r.race_id
      WHERE r.race_date BETWEEN ? AND ? AND r.status='finished'
      GROUP BY r.race_date
      ORDER BY r.race_date
    `).bind(
      THREE_MONTH_START_DATE,
      THREE_MONTH_END_DATE,
      MODEL_SUFFIX,
      THREE_MONTH_START_DATE,
      THREE_MONTH_END_DATE
    ).all<DateAggregateRow>(),
    db.prepare(`
      SELECT r.race_date AS raceDate,
        CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        END AS course,
        COUNT(DISTINCT b.race_id) AS selectedRaces,
        COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces,
        COUNT(*) AS tickets,
        SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END) AS pendingTickets,
        COALESCE(SUM(b.stake_yen),0) AS stakeYen,
        COALESCE(SUM(b.return_yen),0) AS returnYen,
        COALESCE(SUM(b.stake_yen * b.expected_value_pct / 100.0),0) AS expectedReturnYen
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date BETWEEN ? AND ?
        AND p.model_version=('validation-' || r.race_date || ?)
        AND p.status='locked'
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      GROUP BY r.race_date, course
      ORDER BY r.race_date, course
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX).all<CourseAggregateRow>(),
    db.prepare(`
      SELECT r.race_date AS raceDate,
        CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        END AS course,
        substr(b.bet_type, instr(b.bet_type, '｜') + 1) AS betType,
        COUNT(*) AS tickets,
        SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END) AS pendingTickets,
        COALESCE(SUM(b.stake_yen),0) AS stakeYen,
        COALESCE(SUM(b.return_yen),0) AS returnYen,
        COALESCE(SUM(b.stake_yen * b.expected_value_pct / 100.0),0) AS expectedReturnYen,
        SUM(CASE WHEN b.return_yen>0 THEN 1 ELSE 0 END) AS hits
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date BETWEEN ? AND ?
        AND p.model_version=('validation-' || r.race_date || ?)
        AND p.status='locked'
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      GROUP BY r.race_date, course, betType
      ORDER BY r.race_date, course, betType
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX).all<TicketAggregateRow>(),
    db.prepare(`
      SELECT COUNT(*) AS count FROM (
        SELECT race_date, venue
        FROM rt_races
        WHERE race_date BETWEEN ? AND ? AND status='finished'
        GROUP BY race_date, venue
      )
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).first<{ count: number }>(),
    getThreeMonthHistoryProgress(db)
  ]);

  const dateAggregate = new Map(dateRows.results.map((row) => [row.raceDate, row]));
  const normalizedCourseRows = courseRows.results.filter((row) => validCourse(row.course));
  const normalizedTicketRows = ticketRows.results.filter((row) => validCourse(row.course) && validTicket(row.betType));

  const dates: ValidationDateSnapshot[] = THREE_MONTH_VALIDATION_CONFIGS.map((config) => {
    const state = dateAggregate.get(config.raceDate);
    const totalRaces = numeric(state?.totalRaces);
    const processedRaces = numeric(state?.processedRaces);
    const wageredRaces = numeric(state?.wageredRaces);
    const courses = COURSES.map((course) => courseSummaryForDate(
      processedRaces,
      course,
      normalizedCourseRows.find((row) => row.raceDate === config.raceDate && row.course === course),
      normalizedTicketRows.filter((row) => row.raceDate === config.raceDate && row.course === course)
    ));
    return {
      raceDate: config.raceDate,
      label: config.label,
      modelVersion: config.modelVersion,
      totalRaces,
      processedRaces,
      remainingRaces: Math.max(0, totalRaces - processedRaces),
      noBetRaces: Math.max(0, processedRaces - wageredRaces),
      complete: totalRaces > 0 && processedRaces >= totalRaces,
      courses
    };
  }).filter((row) => row.totalRaces > 0);

  const totalRaces = dates.reduce((sum, row) => sum + row.totalRaces, 0);
  const processedRaces = dates.reduce((sum, row) => sum + row.processedRaces, 0);
  const noBetRaces = dates.reduce((sum, row) => sum + row.noBetRaces, 0);
  const combined = mergeCourseSummaries(
    dates.flatMap((row) => row.courses),
    processedRaces
  );
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
  const validationComplete = totalRaces > 0 && processedRaces >= totalRaces;

  return {
    phase: "three-month-validation-v2-sql-aggregate",
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    startDate: THREE_MONTH_START_DATE,
    endDate: THREE_MONTH_END_DATE,
    generatedAt: nowIso(),
    complete: historyProgress.complete && validationComplete,
    totalRaces,
    processedRaces,
    remainingRaces: Math.max(0, totalRaces - processedRaces),
    noBetRaces,
    venueDays: Number(venueRow?.count ?? 0),
    dates,
    combined,
    monthly
  };
}

export async function normalizeThreeMonthVenueQuotas(
  db: D1Database,
  maximumVenuesToNormalize = 2
): Promise<VenueQuotaResult[]> {
  return ensureValidationVenueQuotas(
    db,
    THREE_MONTH_VALIDATION_CONFIGS,
    maximumVenuesToNormalize
  );
}

export function isThreeMonthValidationModel(modelVersion: string | null | undefined): boolean {
  return Boolean(modelVersion?.endsWith(MODEL_SUFFIX));
}

export function configuredThreeMonthDates(): readonly string[] {
  return THREE_MONTH_VALIDATION_CONFIGS.map((config) => config.raceDate);
}
