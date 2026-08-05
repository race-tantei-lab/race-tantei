import { getState, setState } from "./db.js";
import { WALK_FORWARD_SCOPE_VERSION } from "./walk-forward-scope.js";
import type { BudgetCourse } from "./types.js";
import { nowIso } from "./utils.js";

export const WORKER_CALIBRATION_VERSION = "winner-logloss-calibration-v2";
export const WORKER_LEARNED_MODEL_VERSION = "v4.0.0-winner-calibration-v2";
export const CALIBRATION_COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
export const CALIBRATION_WEIGHTS = Array.from({ length: 21 }, (_, index) => index / 20);
export const CALIBRATION_TEMPERATURES = [0.65, 0.75, 0.85, 0.95, 1, 1.05, 1.15, 1.3, 1.45];
export const CALIBRATION_CANDIDATES = CALIBRATION_WEIGHTS.flatMap((modelWeight) =>
  CALIBRATION_TEMPERATURES.map((temperature) => ({ modelWeight, temperature }))
);
export const CALIBRATION_BASELINE_INDEX = CALIBRATION_CANDIDATES.findIndex(
  (row) => row.modelWeight === 1 && row.temperature === 1
);

// プロジェクトの最終目標。未使用期間を含む検証でこの水準に届かないモデルは採用しない。
export const TARGET_ROI_PCT = 200;
export const MIN_ROI_SAMPLE_RACES = 100;

const STATE_KEY = `worker_calibration:${WALK_FORWARD_SCOPE_VERSION}:${WORKER_CALIBRATION_VERSION}`;

export interface LossAccumulator {
  loss: number;
  races: number;
  top1: number;
  top3: number;
}

export interface CalibrationCursor {
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

export interface HoldoutSummary {
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

export interface LearnedMonthlyMetrics {
  month: string;
  course: BudgetCourse;
  selectedRaces: number;
  stakeYen: number;
  returnYen: number;
  profitYen: number;
  roiPct: number;
  hitRaces: number;
  hitRatePct: number;
}

export interface WorkerCalibrationState {
  version: string;
  phase: "waiting-data" | "score" | "holdout" | "apply" | "quota" | "complete" | "failed";
  scoreCursor: CalibrationCursor;
  holdoutCursor: CalibrationCursor;
  applyCursor: CalibrationCursor;
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
  monthlyMetrics: LearnedMonthlyMetrics[];
  selectionMismatchRaces: number;
  integrityValid: boolean;
  active: boolean;
  error: string | null;
  updatedAt: string;
}

export function emptyLossAccumulator(): LossAccumulator {
  return { loss: 0, races: 0, top1: 0, top3: 0 };
}

export function averageCalibrationLoss(value: LossAccumulator): number {
  return value.races > 0 ? value.loss / value.races : Number.POSITIVE_INFINITY;
}

export function meetsRoi200AcceptanceGate(state: WorkerCalibrationState): boolean {
  return state.integrityValid
    && state.selected !== null
    && state.selected.validationImprovementPct > 0
    && state.holdout !== null
    && state.holdout.logLoss <= state.holdout.baselineLogLoss
    && state.metrics.length === CALIBRATION_COURSES.length
    && state.metrics.every((row) =>
      row.selectedRaces >= MIN_ROI_SAMPLE_RACES
      && row.roiPct >= TARGET_ROI_PCT
      && row.pendingTickets === 0
      && row.fixedStakeViolations === 0
    );
}

export function initialWorkerCalibrationState(): WorkerCalibrationState {
  return {
    version: WORKER_CALIBRATION_VERSION,
    phase: "waiting-data",
    scoreCursor: { raceDate: "", raceId: "" },
    holdoutCursor: { raceDate: "", raceId: "" },
    applyCursor: { raceDate: "", raceId: "" },
    train: CALIBRATION_CANDIDATES.map(() => emptyLossAccumulator()),
    validation: CALIBRATION_CANDIDATES.map(() => emptyLossAccumulator()),
    selected: null,
    holdout: null,
    holdoutSelected: emptyLossAccumulator(),
    holdoutBaseline: emptyLossAccumulator(),
    scoredRaces: 0,
    appliedRaces: 0,
    quotaDateIndex: 0,
    quotaDates: [],
    metrics: [],
    monthlyMetrics: [],
    selectionMismatchRaces: 0,
    integrityValid: false,
    active: false,
    error: null,
    updatedAt: nowIso()
  };
}

export async function loadWorkerCalibrationState(db: D1Database): Promise<WorkerCalibrationState> {
  const value = await getState(db, STATE_KEY);
  if (!value) return initialWorkerCalibrationState();
  try {
    const parsed = JSON.parse(value) as WorkerCalibrationState;
    return parsed.version === WORKER_CALIBRATION_VERSION ? parsed : initialWorkerCalibrationState();
  } catch {
    return initialWorkerCalibrationState();
  }
}

export async function saveWorkerCalibrationState(
  db: D1Database,
  state: WorkerCalibrationState
): Promise<void> {
  state.updatedAt = nowIso();
  await setState(db, STATE_KEY, JSON.stringify(state));
}
