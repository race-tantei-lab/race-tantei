import type {
  PredictionOutput,
  RaceRecord,
  RunnerHistoryStats,
  RunnerPrediction,
  RunnerRecord
} from "./types.js";
import { buildBudgetCourseBets } from "./budget-courses.js";
import { clamp, nowIso } from "./utils.js";

function safeRate(wins: number, starts: number, priorWins: number, priorStarts: number): number {
  return (wins + priorWins) / (starts + priorStarts);
}

function softmax(scores: number[]): number[] {
  if (scores.length === 0) return [];
  const max = Math.max(...scores);
  const exp = scores.map((score) => Math.exp(score - max));
  const total = exp.reduce((sum, value) => sum + value, 0);
  return exp.map((value) => value / total);
}

function marketProbabilities(runners: RunnerRecord[]): Map<number, number> {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const inverse = active.map((runner) => ({
    horseNo: runner.horseNo,
    value: runner.winOdds && runner.winOdds > 1 ? 1 / runner.winOdds : 0
  }));
  const total = inverse.reduce((sum, item) => sum + item.value, 0);
  const result = new Map<number, number>();
  for (const item of inverse) result.set(item.horseNo, total > 0 ? item.value / total : 1 / Math.max(1, active.length));
  return result;
}

function historyAdjustment(stats: RunnerHistoryStats | undefined): { score: number; reasons: string[] } {
  if (!stats) return { score: 0, reasons: [] };
  const horseWin = safeRate(stats.horseWins, stats.horseStarts, 1, 12);
  const horsePlace = safeRate(stats.horsePlaces, stats.horseStarts, 3, 12);
  const jockeyWin = safeRate(stats.jockeyWins, stats.jockeyStarts, 1, 14);
  const trainerWin = safeRate(stats.trainerWins, stats.trainerStarts, 1, 14);
  const courseWin = safeRate(stats.courseWins, stats.courseStarts, 1, 16);
  const score =
    0.9 * Math.log(horseWin / (1 / 12)) +
    0.45 * Math.log(horsePlace / (3 / 12)) +
    0.35 * Math.log(jockeyWin / (1 / 14)) +
    0.25 * Math.log(trainerWin / (1 / 14)) +
    0.25 * Math.log(courseWin / (1 / 16));
  const reasons: string[] = [];
  if (stats.horseStarts >= 2) reasons.push(`馬の蓄積成績${stats.horseStarts}走`);
  if (stats.jockeyStarts >= 10) reasons.push(`騎手成績${stats.jockeyStarts}走`);
  if (stats.trainerStarts >= 10) reasons.push(`厩舎成績${stats.trainerStarts}走`);
  if (stats.courseStarts >= 3) reasons.push(`同条件${stats.courseStarts}走`);
  return { score: clamp(score, -0.7, 0.7), reasons };
}

function physicalAdjustment(runner: RunnerRecord): { score: number; reasons: string[] } {
  let score = 0;
  const reasons: string[] = [];
  if (runner.weightChange !== null) {
    if (runner.weightChange >= -8 && runner.weightChange <= 10) {
      score += 0.03;
      reasons.push("馬体重の増減が許容範囲");
    } else if (Math.abs(runner.weightChange) >= 18) {
      score -= 0.08;
      reasons.push("馬体重の大幅変動");
    }
  }
  if (runner.assignedWeight !== null && runner.assignedWeight <= 53) {
    score += 0.035;
    reasons.push("斤量面の恩恵");
  }
  return { score, reasons };
}

export function generatePrediction(
  race: RaceRecord,
  runners: RunnerRecord[],
  stats: RunnerHistoryStats[],
  modelVersion: string,
  minExpectedValuePct: number,
  maxRaceBudgetYen: number
): PredictionOutput {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const market = marketProbabilities(runners);
  const statsMap = new Map(stats.map((item) => [item.horseNo, item]));
  const rawScores = active.map((runner) => {
    const base = Math.log(Math.max(0.01, market.get(runner.horseNo) ?? 1 / Math.max(1, active.length)));
    const history = historyAdjustment(statsMap.get(runner.horseNo));
    const physical = physicalAdjustment(runner);
    return { runner, score: 0.84 * base + history.score + physical.score, reasons: [...history.reasons, ...physical.reasons] };
  });
  const probabilities = softmax(rawScores.map((item) => item.score));
  const predictions: RunnerPrediction[] = rawScores.map((item, index) => {
    const winProbability = probabilities[index] ?? 0;
    const currentOdds = item.runner.winOdds;
    const expectedValuePct = currentOdds ? winProbability * currentOdds * 100 : null;
    const placeProbability = clamp(1 - Math.pow(1 - winProbability, 3), winProbability, 0.96);
    const reasons = item.reasons.length > 0 ? item.reasons.join("・") : "市場オッズを中心に推定";
    return {
      horseNo: item.runner.horseNo,
      horseName: item.runner.horseName,
      winProbability,
      placeProbability,
      fairOdds: winProbability > 0 ? 1 / winProbability : 999,
      currentOdds,
      expectedValuePct,
      predictedOrder: 0,
      explanation: `${race.surface ?? "条件"}${race.distanceM ?? ""}mを前提に、${reasons}`,
      popularity: item.runner.popularity
    };
  });
  predictions.sort((a, b) => b.winProbability - a.winProbability);
  predictions.forEach((prediction, index) => { prediction.predictedOrder = index + 1; });

  const allBets = buildBudgetCourseBets(predictions, minExpectedValuePct);
  const bets = maxRaceBudgetYen <= 2000
    ? allBets.filter((bet) => bet.course === "ライト")
    : maxRaceBudgetYen <= 5000
      ? allBets.filter((bet) => bet.course !== "プレミアム")
      : allBets;
  return { modelVersion, runners: predictions, bets, generatedAt: nowIso() };
}
