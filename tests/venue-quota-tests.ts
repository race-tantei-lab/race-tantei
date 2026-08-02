import { strict as assert } from "node:assert";
import {
  buildBudgetCourseBets,
  buildVenueCoverageBets,
  COURSE_BUDGETS,
  COURSE_TARGET_STAKES,
  coverageRaceScore
} from "../src/v1/budget-courses.js";
import type { BudgetCourse, RunnerPrediction } from "../src/v1/types.js";

function runner(
  horseNo: number,
  probability: number,
  odds: number,
  predictedOrder: number
): RunnerPrediction {
  return {
    horseNo,
    horseName: `テスト${horseNo}`,
    winProbability: probability,
    placeProbability: Math.min(0.96, 1 - Math.pow(1 - probability, 3)),
    fairOdds: 1 / probability,
    currentOdds: odds,
    expectedValuePct: probability * odds * 100,
    predictedOrder,
    explanation: "会場選抜テスト"
  };
}

const marketAligned: RunnerPrediction[] = [
  runner(1, 0.40, 2.5, 1),
  runner(2, 0.22, 4.5, 2),
  runner(3, 0.15, 6.7, 3),
  runner(4, 0.10, 10, 4),
  runner(5, 0.07, 14, 5),
  runner(6, 0.06, 16, 6)
];

assert.deepEqual(buildBudgetCourseBets(marketAligned, 108), []);
const coverage = buildVenueCoverageBets(marketAligned);
assert.ok(coverage.length > 0);
assert.ok(Number.isFinite(coverageRaceScore(marketAligned)));
assert.ok(coverage.every((bet) => bet.stakeYen >= 100 && bet.stakeYen % 100 === 0));

for (const course of ["ライト", "スタンダード", "プレミアム"] as BudgetCourse[]) {
  const courseBets = coverage.filter((bet) => bet.course === course);
  const stake = courseBets.reduce((sum, bet) => sum + bet.stakeYen, 0);
  assert.ok(courseBets.length > 0, `${course}に補完買い目がありません`);
  assert.equal(stake, COURSE_TARGET_STAKES[course], `${course}の購入額が目安額と一致しません`);
  assert.ok(stake <= COURSE_BUDGETS[course], `${course}が上限予算を超えています`);
}

const lightCount = coverage.filter((bet) => bet.course === "ライト").length;
const standardCount = coverage.filter((bet) => bet.course === "スタンダード").length;
const premiumCount = coverage.filter((bet) => bet.course === "プレミアム").length;
assert.ok(lightCount < standardCount, "スタンダードはライトより点数を増やす必要があります");
assert.ok(standardCount < premiumCount, "プレミアムはスタンダードより点数を増やす必要があります");

console.log("race-tantei venue quota budget tests passed");
