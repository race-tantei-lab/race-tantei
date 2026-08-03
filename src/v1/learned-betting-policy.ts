import {
  buildBudgetCourseBets,
  COURSE_TARGET_STAKES
} from "./budget-courses.js";
import type {
  BetRecommendation,
  BudgetCourse,
  RunnerPrediction
} from "./types.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

function recommendationScore(row: BetRecommendation): number {
  const value = Math.max(0.01, row.expectedValuePct / 100);
  return value * Math.sqrt(Math.max(0.000001, row.hitProbability));
}

function fallbackSingle(
  course: BudgetCourse,
  predictions: RunnerPrediction[]
): BetRecommendation[] {
  const top = [...predictions]
    .filter((row) => row.winProbability > 0 && row.currentOdds !== null && row.currentOdds > 1)
    .sort((a, b) => b.winProbability - a.winProbability)[0];
  if (!top || top.currentOdds === null) return [];
  return [{
    course,
    betType: "単勝",
    combination: String(top.horseNo),
    stakeYen: 100,
    assumedOdds: top.currentOdds,
    hitProbability: top.winProbability,
    expectedValuePct: top.winProbability * top.currentOdds * 100
  }];
}

function normalizeCourseStakes(
  course: BudgetCourse,
  rows: BetRecommendation[]
): BetRecommendation[] {
  if (rows.length === 0) return [];
  const target = COURSE_TARGET_STAKES[course];
  const stakes = rows.map(() => 100);
  const scores = rows.map(recommendationScore);
  let remaining = target - stakes.length * 100;
  while (remaining >= 100) {
    let selectedIndex = 0;
    let selectedScore = Number.NEGATIVE_INFINITY;
    for (let index = 0; index < rows.length; index += 1) {
      const adjusted = (scores[index] ?? 0) / (1 + (stakes[index] ?? 0) / 100);
      if (adjusted > selectedScore) {
        selectedScore = adjusted;
        selectedIndex = index;
      }
    }
    stakes[selectedIndex] = (stakes[selectedIndex] ?? 0) + 100;
    remaining -= 100;
  }
  return rows.map((row, index) => ({ ...row, stakeYen: stakes[index] ?? 100 }));
}

export function buildLearnedVenueBets(predictions: RunnerPrediction[]): BetRecommendation[] {
  const raw = buildBudgetCourseBets(predictions, 100);
  return COURSES.flatMap((course) => {
    const courseRows = raw
      .filter((row) => row.course === course)
      .sort((a, b) => recommendationScore(b) - recommendationScore(a));
    const selected = courseRows.length > 0 ? courseRows : fallbackSingle(course, predictions);
    return normalizeCourseStakes(course, selected);
  });
}

export function learnedPredictionRaceScore(predictions: RunnerPrediction[]): number {
  const ranked = [...predictions]
    .filter((row) => row.winProbability > 0)
    .sort((a, b) => b.winProbability - a.winProbability);
  if (ranked.length < 2) return Number.NEGATIVE_INFINITY;
  const bets = buildLearnedVenueBets(ranked);
  if (bets.length === 0) return Number.NEGATIVE_INFINITY;
  const first = ranked[0]?.winProbability ?? 0;
  const second = ranked[1]?.winProbability ?? 0;
  const third = ranked[2]?.winProbability ?? 0;
  const perCourseValue = COURSES.reduce((sum, course) => {
    const best = bets
      .filter((row) => row.course === course)
      .reduce((maximum, row) => Math.max(maximum, recommendationScore(row)), 0);
    return sum + best;
  }, 0);
  const entropy = ranked.reduce(
    (sum, row) => sum - row.winProbability * Math.log(Math.max(0.000000001, row.winProbability)),
    0
  );
  const maximumEntropy = Math.log(Math.max(2, ranked.length));
  const confidence = maximumEntropy > 0 ? 1 - entropy / maximumEntropy : 0;
  return first * 4 + (first - second) * 3 + (first + second + third) + confidence * 2 + perCourseValue;
}
