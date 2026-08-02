import { strict as assert } from "node:assert";
import {
  buildBudgetCourseBets,
  buildVenueCoverageBets,
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
  runner(1, 0.5, 2, 1),
  runner(2, 0.25, 4, 2),
  runner(3, 0.125, 8, 3),
  runner(4, 0.0625, 16, 4),
  runner(5, 0.0625, 16, 5)
];

assert.deepEqual(buildBudgetCourseBets(marketAligned, 108), []);
const coverage = buildVenueCoverageBets(marketAligned);
assert.ok(coverage.length > 0);
assert.ok(Number.isFinite(coverageRaceScore(marketAligned)));
assert.ok(coverage.every((bet) => bet.stakeYen >= 100 && bet.stakeYen % 100 === 0));

for (const course of ["ライト", "スタンダード", "プレミアム"] as BudgetCourse[]) {
  assert.ok(coverage.some((bet) => bet.course === course), `${course}に補完買い目がありません`);
}

console.log("race-tantei venue quota tests passed");
