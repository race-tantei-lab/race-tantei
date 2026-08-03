import { COURSE_TARGET_STAKES } from "./budget-courses.js";
import type {
  CalibrationCursor,
  LearnedCourseMetrics,
  LearnedMonthlyMetrics
} from "./learned-calibration-state.js";
import { WORKER_LEARNED_MODEL_VERSION } from "./learned-calibration-state.js";
import type { StoredCalibrationRunner } from "./learned-calibration-math.js";
import {
  WALK_FORWARD_BASE_MODEL_VERSION,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_HOLDOUT_START_DATE,
  WALK_FORWARD_TRAIN_END_DATE,
  WALK_FORWARD_TRAIN_START_DATE,
  WALK_FORWARD_VALIDATION_END_DATE,
  WALK_FORWARD_VALIDATION_START_DATE
} from "./walk-forward-scope.js";
import type { BudgetCourse } from "./types.js";

export interface CalibrationRaceRow {
  raceId: string;
  raceDate: string;
  predictionId: number;
  winnerHorseNo: number;
}

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

export async function loadCalibrationRunners(
  db: D1Database,
  predictionId: number
): Promise<StoredCalibrationRunner[]> {
  const rows = await db.prepare(`
    SELECT pr.horse_no AS horseNo, pr.horse_name AS horseName,
      pr.win_probability AS winProbability, pr.place_probability AS placeProbability,
      pr.fair_odds AS fairOdds, pr.current_odds AS currentOdds,
      pr.expected_value_pct AS expectedValuePct, pr.predicted_order AS predictedOrder,
      pr.explanation, rr.popularity
    FROM rt_prediction_runners pr
    JOIN rt_predictions p ON p.id=pr.prediction_id
    LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
    WHERE pr.prediction_id=?
    ORDER BY pr.predicted_order
  `).bind(predictionId).all<StoredCalibrationRunner>();
  return rows.results.map((row) => ({
    ...row,
    horseNo: Number(row.horseNo),
    winProbability: Number(row.winProbability),
    placeProbability: Number(row.placeProbability),
    fairOdds: Number(row.fairOdds),
    currentOdds: row.currentOdds === null ? null : Number(row.currentOdds),
    expectedValuePct: row.expectedValuePct === null ? null : Number(row.expectedValuePct),
    predictedOrder: Number(row.predictedOrder),
    popularity: row.popularity === null ? null : Number(row.popularity)
  }));
}

export async function loadCalibrationScoreRows(
  db: D1Database,
  cursor: CalibrationCursor,
  includeHoldout: boolean,
  limit: number
): Promise<CalibrationRaceRow[]> {
  const dateCondition = includeHoldout
    ? "r.race_date BETWEEN ? AND ?"
    : "(r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)";
  const bindings = includeHoldout
    ? [WALK_FORWARD_HOLDOUT_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE]
    : [
      WALK_FORWARD_TRAIN_START_DATE,
      WALK_FORWARD_TRAIN_END_DATE,
      WALK_FORWARD_VALIDATION_START_DATE,
      WALK_FORWARD_VALIDATION_END_DATE
    ];
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, p.id AS predictionId,
      (SELECT horse_no FROM rt_results rs WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseNo
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
    WHERE ${dateCondition}
      AND (r.race_date>? OR (r.race_date=? AND r.race_id>?))
      AND EXISTS (SELECT 1 FROM rt_results rs WHERE rs.race_id=r.race_id AND rs.finish_position=1)
      AND (SELECT COUNT(*) FROM rt_prediction_runners pr WHERE pr.prediction_id=p.id)>=2
    ORDER BY r.race_date, r.race_id
    LIMIT ?
  `).bind(
    WALK_FORWARD_BASE_MODEL_VERSION,
    ...bindings,
    cursor.raceDate,
    cursor.raceDate,
    cursor.raceId,
    limit
  ).all<CalibrationRaceRow>();
  return rows.results.map((row) => ({
    ...row,
    predictionId: Number(row.predictionId),
    winnerHorseNo: Number(row.winnerHorseNo)
  }));
}

export async function loadCalibrationApplyRows(
  db: D1Database,
  cursor: CalibrationCursor,
  limit: number
): Promise<CalibrationRaceRow[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, p.id AS predictionId, 0 AS winnerHorseNo
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
    WHERE (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
      AND (r.race_date>? OR (r.race_date=? AND r.race_id>?))
      AND (SELECT COUNT(*) FROM rt_prediction_runners pr WHERE pr.prediction_id=p.id)>=2
    ORDER BY r.race_date, r.race_id
    LIMIT ?
  `).bind(
    WALK_FORWARD_BASE_MODEL_VERSION,
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE,
    cursor.raceDate,
    cursor.raceDate,
    cursor.raceId,
    limit
  ).all<CalibrationRaceRow>();
  return rows.results.map((row) => ({
    ...row,
    predictionId: Number(row.predictionId),
    winnerHorseNo: 0
  }));
}

export async function loadCalibrationDates(db: D1Database): Promise<string[]> {
  const rows = await db.prepare(`
    SELECT DISTINCT race_date AS raceDate FROM rt_races
    WHERE (race_date BETWEEN ? AND ? OR race_date BETWEEN ? AND ?)
      AND status='finished'
    ORDER BY race_date
  `).bind(
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE
  ).all<{ raceDate: string }>();
  return rows.results.map((row) => row.raceDate);
}

export async function loadLearnedCourseMetrics(db: D1Database): Promise<LearnedCourseMetrics[]> {
  const metrics: LearnedCourseMetrics[] = [];
  for (const course of COURSES) {
    const prefix = `${course}｜%`;
    const row = await db.prepare(`
      SELECT COUNT(DISTINCT b.race_id) AS selectedRaces,
        COALESCE(SUM(b.stake_yen),0) AS stakeYen,
        COALESCE(SUM(b.return_yen),0) AS returnYen,
        COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces,
        COALESCE(SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END),0) AS pendingTickets
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE p.model_version=? AND b.bet_type LIKE ?
        AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
    `).bind(
      WORKER_LEARNED_MODEL_VERSION,
      prefix,
      WALK_FORWARD_VALIDATION_START_DATE,
      WALK_FORWARD_VALIDATION_END_DATE,
      WALK_FORWARD_HOLDOUT_START_DATE,
      WALK_FORWARD_HOLDOUT_END_DATE
    ).first<{ selectedRaces: number; stakeYen: number; returnYen: number; hitRaces: number; pendingTickets: number }>();
    const violations = await db.prepare(`
      SELECT COUNT(*) AS count FROM (
        SELECT b.race_id, SUM(b.stake_yen) AS stake
        FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND b.bet_type LIKE ?
          AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
        GROUP BY b.race_id HAVING stake<>?
      )
    `).bind(
      WORKER_LEARNED_MODEL_VERSION,
      prefix,
      WALK_FORWARD_VALIDATION_START_DATE,
      WALK_FORWARD_VALIDATION_END_DATE,
      WALK_FORWARD_HOLDOUT_START_DATE,
      WALK_FORWARD_HOLDOUT_END_DATE,
      COURSE_TARGET_STAKES[course]
    ).first<{ count: number }>();
    const selectedRaces = Number(row?.selectedRaces ?? 0);
    const stakeYen = Number(row?.stakeYen ?? 0);
    const returnYen = Number(row?.returnYen ?? 0);
    const hitRaces = Number(row?.hitRaces ?? 0);
    metrics.push({
      course,
      selectedRaces,
      stakeYen,
      returnYen,
      profitYen: returnYen - stakeYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : 0,
      hitRaces,
      hitRatePct: selectedRaces > 0 ? hitRaces / selectedRaces * 100 : 0,
      pendingTickets: Number(row?.pendingTickets ?? 0),
      averageStakeYen: selectedRaces > 0 ? stakeYen / selectedRaces : 0,
      fixedStakeViolations: Number(violations?.count ?? 0)
    });
  }
  return metrics;
}

export async function loadLearnedMonthlyMetrics(db: D1Database): Promise<LearnedMonthlyMetrics[]> {
  const values: LearnedMonthlyMetrics[] = [];
  for (const course of COURSES) {
    const rows = await db.prepare(`
      SELECT substr(r.race_date,1,7) AS month,
        COUNT(DISTINCT b.race_id) AS selectedRaces,
        COALESCE(SUM(b.stake_yen),0) AS stakeYen,
        COALESCE(SUM(b.return_yen),0) AS returnYen,
        COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces
      FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE p.model_version=? AND b.bet_type LIKE ?
        AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
      GROUP BY substr(r.race_date,1,7)
      ORDER BY month
    `).bind(
      WORKER_LEARNED_MODEL_VERSION,
      `${course}｜%`,
      WALK_FORWARD_VALIDATION_START_DATE,
      WALK_FORWARD_VALIDATION_END_DATE,
      WALK_FORWARD_HOLDOUT_START_DATE,
      WALK_FORWARD_HOLDOUT_END_DATE
    ).all<{ month: string; selectedRaces: number; stakeYen: number; returnYen: number; hitRaces: number }>();
    for (const row of rows.results) {
      const selectedRaces = Number(row.selectedRaces ?? 0);
      const stakeYen = Number(row.stakeYen ?? 0);
      const returnYen = Number(row.returnYen ?? 0);
      const hitRaces = Number(row.hitRaces ?? 0);
      values.push({
        month: row.month,
        course,
        selectedRaces,
        stakeYen,
        returnYen,
        profitYen: returnYen - stakeYen,
        roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : 0,
        hitRaces,
        hitRatePct: selectedRaces > 0 ? hitRaces / selectedRaces * 100 : 0
      });
    }
  }
  return values;
}

export async function loadLearnedSelectionMismatchCount(db: D1Database): Promise<number> {
  const row = await db.prepare(`
    SELECT COUNT(*) AS count FROM (
      SELECT b.race_id,
        COUNT(DISTINCT CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
          ELSE NULL END) AS courseCount
      FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE p.model_version=?
        AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
      GROUP BY b.race_id HAVING courseCount<>3
    )
  `).bind(
    WORKER_LEARNED_MODEL_VERSION,
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE
  ).first<{ count: number }>();
  return Number(row?.count ?? 0);
}
