import { buildVenueCoverageBets, COURSE_TARGET_STAKES } from "./budget-courses.js";
import { getState, savePrediction, setState } from "./db.js";
import { ensureVenueDailyQuota } from "./venue-quota.js";
import {
  WALK_FORWARD_BASE_MODEL_VERSION,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_HOLDOUT_START_DATE,
  WALK_FORWARD_SCOPE_VERSION,
  WALK_FORWARD_TRAIN_END_DATE,
  WALK_FORWARD_TRAIN_START_DATE,
  WALK_FORWARD_VALIDATION_END_DATE,
  WALK_FORWARD_VALIDATION_START_DATE,
  type WalkForwardSplit,
  walkForwardSplitForDate
} from "./walk-forward-scope.js";
import { getWalkForwardTrainingProgress } from "./walk-forward-training.js";
import type { BudgetCourse, PredictionOutput, RunnerPrediction } from "./types.js";
import { clamp, nowIso } from "./utils.js";

export const WORKER_CALIBRATION_VERSION = "winner-logloss-calibration-v1";
export const WORKER_LEARNED_MODEL_VERSION = "v4.0.0-winner-calibration-v1";

const STATE_KEY = `worker_calibration:${WALK_FORWARD_SCOPE_VERSION}:${WORKER_CALIBRATION_VERSION}`;
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const WEIGHTS = Array.from({ length: 21 }, (_, index) => index / 20);
const TEMPERATURES = [0.65, 0.75, 0.85, 0.95, 1, 1.05, 1.15, 1.3, 1.45];
const CANDIDATES = WEIGHTS.flatMap((modelWeight) =>
  TEMPERATURES.map((temperature) => ({ modelWeight, temperature }))
);
const BASELINE_INDEX = CANDIDATES.findIndex((row) => row.modelWeight === 1 && row.temperature === 1);

interface LossAccumulator {
  loss: number;
  races: number;
  top1: number;
  top3: number;
}

interface Cursor {
  raceDate: string;
  raceId: string;
}

export interface LearnedCalibration {
  modelWeight: number;
  temperature: number;
  trainLogLoss: number;
  validationLogLoss: number;
  baselineValidationLogLoss: number;
  validationImprovementPct: number;
}

interface HoldoutSummary {
  races: number;
  logLoss: number;
  baselineLogLoss: number;
  top1AccuracyPct: number;
  top3AccuracyPct: number;
  baselineTop1AccuracyPct: number;
  baselineTop3AccuracyPct: number;
}

export interface LearnedCourseMetrics {
  course: BudgetCourse;
  selectedRaces: number;
  stakeYen: number;
  returnYen: number;
  profitYen: number;
  roiPct: number;
  hitRaces: number;
  hitRatePct: number;
  pendingTickets: number;
  averageStakeYen: number;
  fixedStakeViolations: number;
}

export interface WorkerCalibrationState {
  version: string;
  phase: "waiting-data" | "score" | "holdout" | "apply" | "quota" | "complete" | "failed";
  scoreCursor: Cursor;
  holdoutCursor: Cursor;
  applyCursor: Cursor;
  train: LossAccumulator[];
  validation: LossAccumulator[];
  selected: LearnedCalibration | null;
  holdout: HoldoutSummary | null;
  holdoutSelected: LossAccumulator;
  holdoutBaseline: LossAccumulator;
  scoredRaces: number;
  appliedRaces: number;
  quotaDateIndex: number;
  quotaDates: string[];
  metrics: LearnedCourseMetrics[];
  integrityValid: boolean;
  active: boolean;
  error: string | null;
  updatedAt: string;
}

interface RaceRow {
  raceId: string;
  raceDate: string;
  predictionId: number;
  winnerHorseNo: number;
}

interface StoredRunner {
  horseNo: number;
  horseName: string;
  winProbability: number;
  placeProbability: number;
  fairOdds: number;
  currentOdds: number | null;
  expectedValuePct: number | null;
  predictedOrder: number;
  explanation: string;
  popularity: number | null;
}

function emptyAccumulator(): LossAccumulator {
  return { loss: 0, races: 0, top1: 0, top3: 0 };
}

function initialState(): WorkerCalibrationState {
  return {
    version: WORKER_CALIBRATION_VERSION,
    phase: "waiting-data",
    scoreCursor: { raceDate: "", raceId: "" },
    holdoutCursor: { raceDate: "", raceId: "" },
    applyCursor: { raceDate: "", raceId: "" },
    train: CANDIDATES.map(emptyAccumulator),
    validation: CANDIDATES.map(emptyAccumulator),
    selected: null,
    holdout: null,
    holdoutSelected: emptyAccumulator(),
    holdoutBaseline: emptyAccumulator(),
    scoredRaces: 0,
    appliedRaces: 0,
    quotaDateIndex: 0,
    quotaDates: [],
    metrics: [],
    integrityValid: false,
    active: false,
    error: null,
    updatedAt: nowIso()
  };
}

function parseState(value: string | null): WorkerCalibrationState {
  if (!value) return initialState();
  try {
    const parsed = JSON.parse(value) as WorkerCalibrationState;
    if (parsed.version !== WORKER_CALIBRATION_VERSION) return initialState();
    return parsed;
  } catch {
    return initialState();
  }
}

async function loadState(db: D1Database): Promise<WorkerCalibrationState> {
  return parseState(await getState(db, STATE_KEY));
}

async function saveState(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  state.updatedAt = nowIso();
  await setState(db, STATE_KEY, JSON.stringify(state));
}

function normalized(values: Map<number, number>): Map<number, number> {
  const total = [...values.values()].reduce((sum, value) => sum + Math.max(0, value), 0);
  const result = new Map<number, number>();
  const fallback = values.size > 0 ? 1 / values.size : 0;
  for (const [horseNo, value] of values) {
    result.set(horseNo, total > 0 ? Math.max(0, value) / total : fallback);
  }
  return result;
}

function calibratedProbabilities(
  runners: StoredRunner[],
  modelWeight: number,
  temperature: number
): Map<number, number> {
  const base = normalized(new Map(runners.map((row) => [row.horseNo, Number(row.winProbability)])));
  const market = normalized(new Map(runners.map((row) => [
    row.horseNo,
    row.currentOdds !== null && row.currentOdds > 1
      ? 1 / row.currentOdds
      : Math.max(0.000001, base.get(row.horseNo) ?? 0)
  ])));
  const scores = new Map<number, number>();
  let maximum = Number.NEGATIVE_INFINITY;
  for (const row of runners) {
    const score = (
      modelWeight * Math.log(Math.max(0.000000001, base.get(row.horseNo) ?? 0))
      + (1 - modelWeight) * Math.log(Math.max(0.000000001, market.get(row.horseNo) ?? 0))
    ) / temperature;
    scores.set(row.horseNo, score);
    maximum = Math.max(maximum, score);
  }
  const exponentials = new Map<number, number>();
  for (const [horseNo, score] of scores) {
    exponentials.set(horseNo, Math.exp(clamp(score - maximum, -40, 0)));
  }
  return normalized(exponentials);
}

function updateLoss(
  accumulator: LossAccumulator,
  probabilities: Map<number, number>,
  winnerHorseNo: number
): void {
  const ranked = [...probabilities.entries()].sort((a, b) => b[1] - a[1]);
  accumulator.loss += -Math.log(Math.max(0.000000000001, probabilities.get(winnerHorseNo) ?? 0));
  accumulator.races += 1;
  accumulator.top1 += ranked[0]?.[0] === winnerHorseNo ? 1 : 0;
  accumulator.top3 += ranked.slice(0, 3).some(([horseNo]) => horseNo === winnerHorseNo) ? 1 : 0;
}

function averageLoss(value: LossAccumulator): number {
  return value.races > 0 ? value.loss / value.races : Number.POSITIVE_INFINITY;
}

async function loadRunners(db: D1Database, predictionId: number): Promise<StoredRunner[]> {
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
  `).bind(predictionId).all<StoredRunner>();
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

async function scoreRows(
  db: D1Database,
  cursor: Cursor,
  includeHoldout: boolean,
  limit: number
): Promise<RaceRow[]> {
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
    ORDER BY r.race_date, r.race_id
    LIMIT ?
  `).bind(
    WALK_FORWARD_BASE_MODEL_VERSION,
    ...bindings,
    cursor.raceDate,
    cursor.raceDate,
    cursor.raceId,
    limit
  ).all<RaceRow>();
  return rows.results.map((row) => ({
    ...row,
    predictionId: Number(row.predictionId),
    winnerHorseNo: Number(row.winnerHorseNo)
  }));
}

async function runScoreStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  const rows = await scoreRows(db, state.scoreCursor, false, 16);
  if (rows.length === 0) {
    const finalists = CANDIDATES.map((candidate, index) => ({
      ...candidate,
      index,
      trainLogLoss: averageLoss(state.train[index] ?? emptyAccumulator()),
      validationLogLoss: averageLoss(state.validation[index] ?? emptyAccumulator())
    }))
      .filter((row) => Number.isFinite(row.trainLogLoss) && Number.isFinite(row.validationLogLoss))
      .sort((a, b) => a.trainLogLoss - b.trainLogLoss)
      .slice(0, 24)
      .sort((a, b) => a.validationLogLoss - b.validationLogLoss);
    const winner = finalists[0];
    if (!winner) throw new Error("CALIBRATION_NO_VALID_CANDIDATE");
    const baselineValidationLogLoss = averageLoss(state.validation[BASELINE_INDEX] ?? emptyAccumulator());
    state.selected = {
      modelWeight: winner.modelWeight,
      temperature: winner.temperature,
      trainLogLoss: winner.trainLogLoss,
      validationLogLoss: winner.validationLogLoss,
      baselineValidationLogLoss,
      validationImprovementPct: baselineValidationLogLoss > 0
        ? (baselineValidationLogLoss - winner.validationLogLoss) / baselineValidationLogLoss * 100
        : 0
    };
    state.phase = "holdout";
    state.holdoutCursor = { raceDate: "", raceId: "" };
    return;
  }

  for (const row of rows) {
    const split = walkForwardSplitForDate(row.raceDate);
    if (split !== "train" && split !== "validation") continue;
    const runners = await loadRunners(db, row.predictionId);
    if (runners.length < 2) continue;
    CANDIDATES.forEach((candidate, index) => {
      const probabilities = calibratedProbabilities(runners, candidate.modelWeight, candidate.temperature);
      updateLoss(split === "train" ? state.train[index]! : state.validation[index]!, probabilities, row.winnerHorseNo);
    });
    state.scoredRaces += 1;
    state.scoreCursor = { raceDate: row.raceDate, raceId: row.raceId };
  }
}

async function runHoldoutStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  if (!state.selected) throw new Error("CALIBRATION_SELECTION_MISSING");
  const rows = await scoreRows(db, state.holdoutCursor, true, 20);
  if (rows.length === 0) {
    state.holdout = {
      races: state.holdoutSelected.races,
      logLoss: averageLoss(state.holdoutSelected),
      baselineLogLoss: averageLoss(state.holdoutBaseline),
      top1AccuracyPct: state.holdoutSelected.races > 0 ? state.holdoutSelected.top1 / state.holdoutSelected.races * 100 : 0,
      top3AccuracyPct: state.holdoutSelected.races > 0 ? state.holdoutSelected.top3 / state.holdoutSelected.races * 100 : 0,
      baselineTop1AccuracyPct: state.holdoutBaseline.races > 0 ? state.holdoutBaseline.top1 / state.holdoutBaseline.races * 100 : 0,
      baselineTop3AccuracyPct: state.holdoutBaseline.races > 0 ? state.holdoutBaseline.top3 / state.holdoutBaseline.races * 100 : 0
    };
    state.phase = "apply";
    state.applyCursor = { raceDate: "", raceId: "" };
    return;
  }
  for (const row of rows) {
    const runners = await loadRunners(db, row.predictionId);
    if (runners.length < 2) continue;
    updateLoss(
      state.holdoutSelected,
      calibratedProbabilities(runners, state.selected.modelWeight, state.selected.temperature),
      row.winnerHorseNo
    );
    updateLoss(
      state.holdoutBaseline,
      calibratedProbabilities(runners, 1, 1),
      row.winnerHorseNo
    );
    state.holdoutCursor = { raceDate: row.raceDate, raceId: row.raceId };
  }
}

function calibratedPrediction(
  runners: StoredRunner[],
  calibration: LearnedCalibration
): RunnerPrediction[] {
  const probabilities = calibratedProbabilities(runners, calibration.modelWeight, calibration.temperature);
  const result = runners.map((row) => {
    const winProbability = probabilities.get(row.horseNo) ?? 0;
    return {
      horseNo: row.horseNo,
      horseName: row.horseName,
      winProbability,
      placeProbability: clamp(1 - Math.pow(1 - winProbability, 3), winProbability, 0.96),
      fairOdds: winProbability > 0 ? 1 / winProbability : 999,
      currentOdds: row.currentOdds,
      expectedValuePct: row.currentOdds !== null ? winProbability * row.currentOdds * 100 : null,
      predictedOrder: 0,
      explanation: `${row.explanation}・12か月の勝敗データで確率校正`,
      popularity: row.popularity
    } satisfies RunnerPrediction;
  });
  result.sort((a, b) => b.winProbability - a.winProbability);
  result.forEach((row, index) => { row.predictedOrder = index + 1; });
  return result;
}

async function applyRows(db: D1Database, cursor: Cursor, limit: number): Promise<RaceRow[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, p.id AS predictionId, 0 AS winnerHorseNo
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
    WHERE (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
      AND (r.race_date>? OR (r.race_date=? AND r.race_id>?))
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
  ).all<RaceRow>();
  return rows.results.map((row) => ({ ...row, predictionId: Number(row.predictionId), winnerHorseNo: 0 }));
}

async function runApplyStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  if (!state.selected) throw new Error("CALIBRATION_SELECTION_MISSING");
  const rows = await applyRows(db, state.applyCursor, 12);
  if (rows.length === 0) {
    const dateRows = await db.prepare(`
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
    state.quotaDates = dateRows.results.map((row) => row.raceDate);
    state.quotaDateIndex = 0;
    state.phase = "quota";
    return;
  }

  for (const row of rows) {
    const stored = await loadRunners(db, row.predictionId);
    if (stored.length < 2) continue;
    const output: PredictionOutput = {
      modelVersion: WORKER_LEARNED_MODEL_VERSION,
      runners: calibratedPrediction(stored, state.selected),
      bets: [],
      generatedAt: nowIso()
    };
    await savePrediction(db, row.raceId, output, "locked");
    state.appliedRaces += 1;
    state.applyCursor = { raceDate: row.raceDate, raceId: row.raceId };
  }
}

async function loadMetrics(db: D1Database): Promise<LearnedCourseMetrics[]> {
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

async function runQuotaStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  const raceDate = state.quotaDates[state.quotaDateIndex];
  if (!raceDate) {
    state.metrics = await loadMetrics(db);
    const selectedCounts = new Set(state.metrics.map((row) => row.selectedRaces));
    state.integrityValid = selectedCounts.size === 1 && state.metrics.every((row) =>
      row.selectedRaces > 0
      && row.pendingTickets === 0
      && row.fixedStakeViolations === 0
      && Math.abs(row.averageStakeYen - COURSE_TARGET_STAKES[row.course]) < 0.01
    );
    state.active = state.integrityValid
      && state.selected !== null
      && state.selected.validationImprovementPct > 0
      && state.holdout !== null
      && state.holdout.logLoss <= state.holdout.baselineLogLoss;
    state.phase = "complete";
    return;
  }
  await ensureVenueDailyQuota(db, WORKER_LEARNED_MODEL_VERSION, raceDate, "validation", 5, 8);
  state.quotaDateIndex += 1;
}

export async function getWorkerCalibrationState(db: D1Database): Promise<WorkerCalibrationState> {
  return await loadState(db);
}

export async function getActiveLearnedModelVersion(db: D1Database): Promise<string | null> {
  const state = await loadState(db);
  return state.phase === "complete" && state.active ? WORKER_LEARNED_MODEL_VERSION : null;
}

export async function runWorkerCalibrationStep(db: D1Database): Promise<WorkerCalibrationState> {
  const state = await loadState(db);
  try {
    if (state.phase === "complete" || state.phase === "failed") return state;
    const progress = await getWalkForwardTrainingProgress(db);
    if (!progress.complete) {
      state.phase = "waiting-data";
      await saveState(db, state);
      return state;
    }
    if (state.phase === "waiting-data") state.phase = "score";
    if (state.phase === "score") await runScoreStep(db, state);
    else if (state.phase === "holdout") await runHoldoutStep(db, state);
    else if (state.phase === "apply") await runApplyStep(db, state);
    else if (state.phase === "quota") await runQuotaStep(db, state);
    await saveState(db, state);
    return state;
  } catch (error) {
    state.phase = "failed";
    state.error = error instanceof Error ? error.message : String(error);
    await saveState(db, state);
    return state;
  }
}

export function renderWorkerCalibrationPanel(state: WorkerCalibrationState): string {
  const phaseLabels: Record<WorkerCalibrationState["phase"], string> = {
    "waiting-data": "公式過去データを取得中",
    score: "勝率予測を学習中",
    holdout: "未使用期間で精度を検証中",
    apply: "新モデルで過去レースを再予想中",
    quota: "各会場5Rを固定額で再精算中",
    complete: state.active ? "新モデル反映済み" : "検証完了・現行モデルを維持",
    failed: "学習処理でエラー"
  };
  const metricCards = state.metrics.map((row) => `
    <div style="padding:12px;border:1px solid #315f55;border-radius:12px;background:#10231f">
      <b>${row.course}</b><strong style="display:block;font-size:24px;margin-top:4px">${row.roiPct.toFixed(1)}%</strong>
      <span style="font-size:12px;opacity:.8">${row.selectedRaces}R・的中率${row.hitRatePct.toFixed(1)}%・平均${Math.round(row.averageStakeYen).toLocaleString("ja-JP")}円</span>
    </div>`).join("");
  const accuracy = state.selected && state.holdout
    ? `<p style="margin:8px 0 0;font-size:13px">検証log loss ${state.selected.validationLogLoss.toFixed(4)}（旧${state.selected.baselineValidationLogLoss.toFixed(4)}）／未使用期間1着的中 ${state.holdout.top1AccuracyPct.toFixed(1)}%（旧${state.holdout.baselineTop1AccuracyPct.toFixed(1)}%）</p>`
    : `<p style="margin:8px 0 0;font-size:13px">結果や払戻を買い目選択に使わず、勝ち馬への予測確率を学習しています。</p>`;
  return `<section id="learned-model-status" style="margin:0 0 16px;padding:15px;border:1px solid ${state.phase === "failed" ? "#8d3d3d" : "#315f55"};border-radius:16px;background:#0d1d1a;color:#e7f6f1;line-height:1.55">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div><b style="font-size:16px">12か月学習モデル</b><div style="font-size:13px;opacity:.85">${phaseLabels[state.phase]}</div></div><span style="font-size:12px">${state.appliedRaces}R再予想</span></div>
    ${accuracy}
    ${metricCards ? `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px">${metricCards}</div>` : ""}
    ${state.error ? `<p style="color:#ffb1b1">${state.error}</p>` : ""}
  </section>`;
}
