import type { LearnedCalibration, LossAccumulator } from "./learned-calibration-state.js";
import type { RunnerPrediction } from "./types.js";
import { clamp } from "./utils.js";

export interface StoredCalibrationRunner {
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

function normalized(values: Map<number, number>): Map<number, number> {
  const total = [...values.values()].reduce((sum, value) => sum + Math.max(0, value), 0);
  const result = new Map<number, number>();
  const fallback = values.size > 0 ? 1 / values.size : 0;
  for (const [horseNo, value] of values) {
    result.set(horseNo, total > 0 ? Math.max(0, value) / total : fallback);
  }
  return result;
}

export function calibratedProbabilities(
  runners: StoredCalibrationRunner[],
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

export function updateCalibrationLoss(
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

export function buildCalibratedPrediction(
  runners: StoredCalibrationRunner[],
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
