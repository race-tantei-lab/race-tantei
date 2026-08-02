import type {
  BetRecommendation,
  PredictionOutput,
  RaceRecord,
  RunnerHistoryStats,
  RunnerPrediction,
  RunnerRecord
} from "./types.js";
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

function estimatedOdds(type: BetRecommendation["betType"], picks: RunnerPrediction[]): number {
  const odds = picks.map((pick) => Math.max(1.1, pick.currentOdds ?? pick.fairOdds));
  if (type === "単勝") return odds[0] ?? 1;
  if (type === "ワイド") return Math.max(1.5, Math.sqrt((odds[0] ?? 1) * (odds[1] ?? 1)) * 0.42);
  if (type === "馬連") return Math.max(2, Math.sqrt((odds[0] ?? 1) * (odds[1] ?? 1)) * 1.15);
  if (type === "馬単") return Math.max(3, (odds[0] ?? 1) * Math.sqrt(odds[1] ?? 1) * 0.95);
  if (type === "3連複") return Math.max(5, Math.cbrt((odds[0] ?? 1) * (odds[1] ?? 1) * (odds[2] ?? 1)) * 2.8);
  return Math.max(8, (odds[0] ?? 1) * Math.sqrt((odds[1] ?? 1) * (odds[2] ?? 1)) * 1.5);
}

function makeBet(
  betType: BetRecommendation["betType"],
  picks: RunnerPrediction[],
  stakeYen: number,
  probability: number
): BetRecommendation {
  const ordered = betType === "馬単" || betType === "3連単";
  const horseNos = picks.map((pick) => pick.horseNo);
  const combination = (ordered ? horseNos : [...horseNos].sort((a, b) => a - b)).join("-");
  const assumedOdds = estimatedOdds(betType, picks);
  return {
    betType,
    combination,
    stakeYen,
    assumedOdds,
    hitProbability: clamp(probability, 0.001, 0.95),
    expectedValuePct: clamp(probability * assumedOdds * 100, 1, 999)
  };
}

function buildTicket(predictions: RunnerPrediction[], maxBudget: number): BetRecommendation[] {
  const [top, second, third] = predictions;
  if (!top) return [];
  const budget = Math.max(0, Math.floor(maxBudget / 100) * 100);
  if (budget < 100) return [];
  if (!second || !third || budget < 600) {
    return [makeBet("単勝", [top], budget, top.winProbability)];
  }

  const confidenceGap = top.winProbability - second.winProbability;
  const strong = top.winProbability >= 0.34 || confidenceGap >= 0.12;
  const units = strong
    ? [6, 5, 3, 3, 2, 1]
    : [2, 5, 4, 4, 2, 3];
  const totalUnits = units.reduce((sum, value) => sum + value, 0);
  const unitYen = Math.max(100, Math.floor(budget / totalUnits / 100) * 100);
  const stakes = units.map((unit) => unit * unitYen);
  const used = stakes.reduce((sum, value) => sum + value, 0);
  stakes[0] = (stakes[0] ?? 0) + Math.max(0, budget - used);

  const p1 = top.winProbability;
  const p2 = second.winProbability;
  const p3 = third.winProbability;
  const place12 = clamp(top.placeProbability * second.placeProbability * 0.72, 0.01, 0.8);
  const place13 = clamp(top.placeProbability * third.placeProbability * 0.65, 0.01, 0.75);
  const quinella12 = clamp(2 * p1 * p2 * 1.45, 0.005, 0.6);
  const exacta12 = clamp(p1 * p2 * 1.2, 0.003, 0.45);
  const trio123 = clamp(6 * p1 * p2 * p3 * 1.8, 0.002, 0.45);

  return [
    makeBet("単勝", [top], stakes[0] ?? 0, p1),
    makeBet("ワイド", [top, second], stakes[1] ?? 0, place12),
    makeBet("ワイド", [top, third], stakes[2] ?? 0, place13),
    makeBet("馬連", [top, second], stakes[3] ?? 0, quinella12),
    makeBet("馬単", [top, second], stakes[4] ?? 0, exacta12),
    makeBet("3連複", [top, second, third], stakes[5] ?? 0, trio123)
  ].filter((bet) => bet.stakeYen >= 100);
}

export function generatePrediction(
  race: RaceRecord,
  runners: RunnerRecord[],
  stats: RunnerHistoryStats[],
  modelVersion: string,
  _minExpectedValuePct: number,
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
      explanation: `${race.surface ?? "条件"}${race.distanceM ?? ""}mを前提に、${reasons}`
    };
  });
  predictions.sort((a, b) => b.winProbability - a.winProbability);
  predictions.forEach((prediction, index) => { prediction.predictedOrder = index + 1; });
  return { modelVersion, runners: predictions, bets: buildTicket(predictions, maxRaceBudgetYen), generatedAt: nowIso() };
}
