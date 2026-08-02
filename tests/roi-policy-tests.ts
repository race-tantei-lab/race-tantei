import { strict as assert } from "node:assert";
import {
  buildVenueCoverageBets,
  COURSE_TARGET_STAKES,
  coverageRaceScore
} from "../src/v1/budget-courses.js";
import { ROI_POLICY_VERSION } from "../src/v1/roi-policy.js";
import type { BudgetCourse, RunnerPrediction } from "../src/v1/types.js";

function runner(
  horseNo: number,
  probability: number,
  odds: number,
  predictedOrder: number,
  popularity: number
): RunnerPrediction {
  return {
    horseNo,
    horseName: `固定ルール${horseNo}`,
    winProbability: probability,
    placeProbability: Math.min(0.96, 1 - Math.pow(1 - probability, 3)),
    fairOdds: 1 / probability,
    currentOdds: odds,
    expectedValuePct: probability * odds * 100,
    predictedOrder,
    explanation: "ROI固定ルールテスト",
    popularity
  };
}

const predictions: RunnerPrediction[] = [
  runner(1, 0.34, 2.8, 1, 1),
  runner(2, 0.22, 4.8, 2, 2),
  runner(3, 0.16, 7.2, 3, 3),
  runner(4, 0.12, 10.5, 4, 4),
  runner(5, 0.09, 15.0, 5, 5),
  runner(6, 0.07, 22.0, 6, 6)
];

assert.equal(ROI_POLICY_VERSION, "roi-policy-v1");
const bets = buildVenueCoverageBets(predictions);

const expectedCounts: Record<BudgetCourse, number> = {
  ライト: 6,
  スタンダード: 15,
  プレミアム: 16
};

for (const course of ["ライト", "スタンダード", "プレミアム"] as BudgetCourse[]) {
  const courseBets = bets.filter((bet) => bet.course === course);
  assert.equal(courseBets.length, expectedCounts[course], `${course}の点数が固定ルールと一致しません`);
  assert.equal(
    courseBets.reduce((sum, bet) => sum + bet.stakeYen, 0),
    COURSE_TARGET_STAKES[course],
    `${course}の購入額が固定ルールと一致しません`
  );
  assert.ok(courseBets.every((bet) => bet.stakeYen >= 100 && bet.stakeYen % 100 === 0));
}

const baseScore = coverageRaceScore(predictions);
const lessPopularTop: RunnerPrediction[] = predictions.map((prediction, index) => ({
  ...prediction,
  popularity: index === 0 ? 6 : prediction.popularity ?? null
}));
const changedScore = coverageRaceScore(lessPopularTop);
assert.ok(Number.isFinite(baseScore));
assert.ok(Number.isFinite(changedScore));
assert.ok(baseScore !== changedScore, "人気順位を含む固定レース選択スコアが反映されていません");

console.log("race-tantei ROI policy v1 tests passed");
