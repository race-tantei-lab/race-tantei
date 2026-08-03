import { COURSE_TARGET_STAKES } from "./budget-courses.js";
import { savePrediction } from "./db.js";
import {
  loadCalibrationApplyRows,
  loadCalibrationDates,
  loadCalibrationRunners,
  loadCalibrationScoreRows,
  loadLearnedCourseMetrics,
  loadLearnedMonthlyMetrics,
  loadLearnedSelectionMismatchCount
} from "./learned-calibration-data.js";
import {
  buildCalibratedPrediction,
  calibratedProbabilities,
  updateCalibrationLoss
} from "./learned-calibration-math.js";
import {
  averageCalibrationLoss,
  CALIBRATION_BASELINE_INDEX,
  CALIBRATION_CANDIDATES,
  emptyLossAccumulator,
  loadWorkerCalibrationState,
  saveWorkerCalibrationState,
  WORKER_LEARNED_MODEL_VERSION,
  type WorkerCalibrationState
} from "./learned-calibration-state.js";
import { ensureLearnedVenueQuota } from "./learned-venue-quota.js";
import { walkForwardSplitForDate } from "./walk-forward-scope.js";
import { getWalkForwardTrainingProgress } from "./walk-forward-training.js";
import type { PredictionOutput } from "./types.js";
import { nowIso } from "./utils.js";

async function runScoreStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  const rows = await loadCalibrationScoreRows(db, state.scoreCursor, false, 16);
  if (rows.length === 0) {
    const finalists = CALIBRATION_CANDIDATES.map((candidate, index) => ({
      ...candidate,
      trainLogLoss: averageCalibrationLoss(state.train[index] ?? emptyLossAccumulator()),
      validationLogLoss: averageCalibrationLoss(state.validation[index] ?? emptyLossAccumulator())
    }))
      .filter((row) => Number.isFinite(row.trainLogLoss) && Number.isFinite(row.validationLogLoss))
      .sort((a, b) => a.trainLogLoss - b.trainLogLoss)
      .slice(0, 24)
      .sort((a, b) => a.validationLogLoss - b.validationLogLoss);
    const winner = finalists[0];
    if (!winner) throw new Error("CALIBRATION_NO_VALID_CANDIDATE");
    const baselineValidationLogLoss = averageCalibrationLoss(
      state.validation[CALIBRATION_BASELINE_INDEX] ?? emptyLossAccumulator()
    );
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
    state.scoreCursor = { raceDate: row.raceDate, raceId: row.raceId };
    const split = walkForwardSplitForDate(row.raceDate);
    if (split !== "train" && split !== "validation") continue;
    const runners = await loadCalibrationRunners(db, row.predictionId);
    if (runners.length < 2) continue;
    CALIBRATION_CANDIDATES.forEach((candidate, index) => {
      const probabilities = calibratedProbabilities(runners, candidate.modelWeight, candidate.temperature);
      updateCalibrationLoss(
        split === "train" ? state.train[index]! : state.validation[index]!,
        probabilities,
        row.winnerHorseNo
      );
    });
    state.scoredRaces += 1;
  }
}

async function runHoldoutStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  if (!state.selected) throw new Error("CALIBRATION_SELECTION_MISSING");
  const rows = await loadCalibrationScoreRows(db, state.holdoutCursor, true, 20);
  if (rows.length === 0) {
    state.holdout = {
      races: state.holdoutSelected.races,
      logLoss: averageCalibrationLoss(state.holdoutSelected),
      baselineLogLoss: averageCalibrationLoss(state.holdoutBaseline),
      top1AccuracyPct: state.holdoutSelected.races > 0
        ? state.holdoutSelected.top1 / state.holdoutSelected.races * 100
        : 0,
      top3AccuracyPct: state.holdoutSelected.races > 0
        ? state.holdoutSelected.top3 / state.holdoutSelected.races * 100
        : 0,
      baselineTop1AccuracyPct: state.holdoutBaseline.races > 0
        ? state.holdoutBaseline.top1 / state.holdoutBaseline.races * 100
        : 0,
      baselineTop3AccuracyPct: state.holdoutBaseline.races > 0
        ? state.holdoutBaseline.top3 / state.holdoutBaseline.races * 100
        : 0
    };
    state.phase = "apply";
    state.applyCursor = { raceDate: "", raceId: "" };
    return;
  }

  for (const row of rows) {
    state.holdoutCursor = { raceDate: row.raceDate, raceId: row.raceId };
    const runners = await loadCalibrationRunners(db, row.predictionId);
    if (runners.length < 2) continue;
    updateCalibrationLoss(
      state.holdoutSelected,
      calibratedProbabilities(runners, state.selected.modelWeight, state.selected.temperature),
      row.winnerHorseNo
    );
    updateCalibrationLoss(
      state.holdoutBaseline,
      calibratedProbabilities(runners, 1, 1),
      row.winnerHorseNo
    );
  }
}

async function runApplyStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  if (!state.selected) throw new Error("CALIBRATION_SELECTION_MISSING");
  const rows = await loadCalibrationApplyRows(db, state.applyCursor, 12);
  if (rows.length === 0) {
    state.quotaDates = await loadCalibrationDates(db);
    state.quotaDateIndex = 0;
    state.phase = "quota";
    return;
  }

  for (const row of rows) {
    state.applyCursor = { raceDate: row.raceDate, raceId: row.raceId };
    const stored = await loadCalibrationRunners(db, row.predictionId);
    if (stored.length < 2) continue;
    const output: PredictionOutput = {
      modelVersion: WORKER_LEARNED_MODEL_VERSION,
      runners: buildCalibratedPrediction(stored, state.selected),
      bets: [],
      generatedAt: nowIso()
    };
    await savePrediction(db, row.raceId, output, "locked");
    state.appliedRaces += 1;
  }
}

async function finalizeMetrics(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  state.metrics = await loadLearnedCourseMetrics(db);
  state.monthlyMetrics = await loadLearnedMonthlyMetrics(db);
  state.selectionMismatchRaces = await loadLearnedSelectionMismatchCount(db);
  const selectedCounts = new Set(state.metrics.map((row) => row.selectedRaces));
  state.integrityValid = selectedCounts.size === 1
    && state.selectionMismatchRaces === 0
    && state.metrics.every((row) =>
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
}

async function runQuotaStep(db: D1Database, state: WorkerCalibrationState): Promise<void> {
  const raceDate = state.quotaDates[state.quotaDateIndex];
  if (!raceDate) {
    await finalizeMetrics(db, state);
    return;
  }
  await ensureLearnedVenueQuota(db, raceDate);
  state.quotaDateIndex += 1;
}

export async function getWorkerCalibrationState(db: D1Database): Promise<WorkerCalibrationState> {
  return await loadWorkerCalibrationState(db);
}

export async function getActiveLearnedModelVersion(db: D1Database): Promise<string | null> {
  const state = await loadWorkerCalibrationState(db);
  return state.phase === "complete" && state.active ? WORKER_LEARNED_MODEL_VERSION : null;
}

export async function runWorkerCalibrationStep(db: D1Database): Promise<WorkerCalibrationState> {
  const state = await loadWorkerCalibrationState(db);
  try {
    if (state.phase === "complete" || state.phase === "failed") return state;
    const progress = await getWalkForwardTrainingProgress(db);
    if (!progress.complete) {
      state.phase = "waiting-data";
      await saveWorkerCalibrationState(db, state);
      return state;
    }
    if (state.phase === "waiting-data") state.phase = "score";
    if (state.phase === "score") await runScoreStep(db, state);
    else if (state.phase === "holdout") await runHoldoutStep(db, state);
    else if (state.phase === "apply") await runApplyStep(db, state);
    else if (state.phase === "quota") await runQuotaStep(db, state);
    await saveWorkerCalibrationState(db, state);
    return state;
  } catch (error) {
    state.phase = "failed";
    state.error = error instanceof Error ? error.message : String(error);
    await saveWorkerCalibrationState(db, state);
    return state;
  }
}
