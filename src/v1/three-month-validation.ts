import { savePredictionWithCourses, settleRaceWithCourses } from "./course-db.js";
import { getRace, getRunnerHistoryStats, getRunners } from "./db.js";
import { generatePrediction } from "./model.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE,
  THREE_MONTH_VALIDATION_CONFIGS
} from "./three-month-scope.js";
import type { PredictionOutput } from "./types.js";
import { nowIso } from "./utils.js";
import {
  summarizeValidationTickets,
  type CourseValidationSummary,
  type ValidationDateSnapshot,
  type ValidationSnapshot,
  type ValidationTicketInput
} from "./validation.js";
import { ensureValidationVenueQuotas, type VenueQuotaResult } from "./venue-quota.js";

const MODEL_SUFFIX = "-roi-policy-v1-3m";
const CONFIG_BY_DATE = new Map(THREE_MONTH_VALIDATION_CONFIGS.map((config) => [config.raceDate, config]));

interface PredictionRow {
  raceId: string;
  raceDate: string;
}

interface TotalRow {
  raceDate: string;
  count: number;
}

interface TicketRow extends ValidationTicketInput {
  raceDate: string;
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

function numericTicket(row: TicketRow): TicketRow {
  return {
    ...row,
    stakeYen: Number(row.stakeYen),
    returnYen: row.returnYen === null ? null : Number(row.returnYen),
    expectedValuePct: Number(row.expectedValuePct)
  };
}

export async function getThreeMonthValidationSnapshot(
  db: D1Database
): Promise<ThreeMonthValidationSnapshot> {
  const [totalRows, predictionRows, ticketRows, venueRow] = await Promise.all([
    db.prepare(`
      SELECT race_date AS raceDate, COUNT(*) AS count
      FROM rt_races
      WHERE race_date BETWEEN ? AND ? AND status='finished'
      GROUP BY race_date
      ORDER BY race_date
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<TotalRow>(),
    db.prepare(`
      SELECT r.race_date AS raceDate, p.race_id AS raceId
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date BETWEEN ? AND ?
        AND p.model_version=('validation-' || r.race_date || ?)
        AND p.status='locked'
      ORDER BY r.race_date, r.venue, r.race_no
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX).all<PredictionRow>(),
    db.prepare(`
      SELECT r.race_date AS raceDate, b.race_id AS raceId, b.bet_type AS betType,
        b.stake_yen AS stakeYen, b.return_yen AS returnYen,
        b.expected_value_pct AS expectedValuePct, b.settlement_status AS settlementStatus
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date BETWEEN ? AND ?
        AND p.model_version=('validation-' || r.race_date || ?)
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ORDER BY r.race_date, b.race_id, b.id
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE, MODEL_SUFFIX).all<TicketRow>(),
    db.prepare(`
      SELECT COUNT(*) AS count FROM (
        SELECT race_date, venue
        FROM rt_races
        WHERE race_date BETWEEN ? AND ? AND status='finished'
        GROUP BY race_date, venue
      )
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).first<{ count: number }>()
  ]);

  const totalByDate = new Map(totalRows.results.map((row) => [row.raceDate, Number(row.count)]));
  const processedByDate = new Map<string, string[]>();
  for (const row of predictionRows.results) {
    const values = processedByDate.get(row.raceDate) ?? [];
    values.push(row.raceId);
    processedByDate.set(row.raceDate, values);
  }
  const ticketsByDate = new Map<string, TicketRow[]>();
  for (const raw of ticketRows.results) {
    const row = numericTicket(raw);
    const values = ticketsByDate.get(row.raceDate) ?? [];
    values.push(row);
    ticketsByDate.set(row.raceDate, values);
  }

  const dates: ValidationDateSnapshot[] = THREE_MONTH_VALIDATION_CONFIGS.map((config) => {
    const totalRaces = totalByDate.get(config.raceDate) ?? 0;
    const processedRaceIds = processedByDate.get(config.raceDate) ?? [];
    const tickets = ticketsByDate.get(config.raceDate) ?? [];
    const processedRaces = new Set(processedRaceIds).size;
    const wageredRaces = new Set(tickets.map((ticket) => ticket.raceId)).size;
    return {
      raceDate: config.raceDate,
      label: config.label,
      modelVersion: config.modelVersion,
      totalRaces,
      processedRaces,
      remainingRaces: Math.max(0, totalRaces - processedRaces),
      noBetRaces: Math.max(0, processedRaces - wageredRaces),
      complete: totalRaces > 0 && processedRaces >= totalRaces,
      courses: summarizeValidationTickets(processedRaceIds, tickets)
    };
  }).filter((row) => row.totalRaces > 0);

  const allProcessedRaceIds = predictionRows.results.map((row) => row.raceId);
  const allTickets = ticketRows.results.map(numericTicket);
  const totalRaces = dates.reduce((sum, row) => sum + row.totalRaces, 0);
  const processedRaces = new Set(allProcessedRaceIds).size;
  const wageredRaces = new Set(allTickets.map((row) => row.raceId)).size;
  const months = [...new Set(dates.map((row) => row.raceDate.slice(0, 7)))];
  const monthly = months.map((month) => {
    const monthRaceIds = predictionRows.results
      .filter((row) => row.raceDate.startsWith(month))
      .map((row) => row.raceId);
    const monthTickets = allTickets.filter((row) => row.raceDate.startsWith(month));
    return { month, courses: summarizeValidationTickets(monthRaceIds, monthTickets) };
  });

  return {
    phase: "three-month-validation-v1",
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    startDate: THREE_MONTH_START_DATE,
    endDate: THREE_MONTH_END_DATE,
    generatedAt: nowIso(),
    complete: totalRaces > 0 && processedRaces >= totalRaces,
    totalRaces,
    processedRaces,
    remainingRaces: Math.max(0, totalRaces - processedRaces),
    noBetRaces: Math.max(0, processedRaces - wageredRaces),
    venueDays: Number(venueRow?.count ?? 0),
    dates,
    combined: summarizeValidationTickets(allProcessedRaceIds, allTickets),
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
