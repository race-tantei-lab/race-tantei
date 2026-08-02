import { strict as assert } from "node:assert";
import { buildBudgetCourseBets } from "../src/v1/budget-courses.js";
import type { RunnerPrediction } from "../src/v1/types.js";

function runner(
  horseNo: number,
  winProbability: number,
  currentOdds: number,
  predictedOrder: number
): RunnerPrediction {
  return {
    horseNo,
    horseName: `テスト${horseNo}`,
    winProbability,
    placeProbability: Math.min(0.96, 1 - Math.pow(1 - winProbability, 3)),
    fairOdds: 1 / winProbability,
    currentOdds,
    expectedValuePct: winProbability * currentOdds * 100,
    predictedOrder,
    explanation: "最低購入単位の回帰テスト"
  };
}

const moderateEdge: RunnerPrediction[] = [
  runner(1, 0.30, 4.0, 1),
  runner(2, 0.25, 4.0, 2),
  runner(3, 0.20, 5.0, 3),
  runner(4, 0.15, 6.7, 4),
  runner(5, 0.10, 10.0, 5)
];

const bets = buildBudgetCourseBets(moderateEdge, 108);
const lightWin = bets.find((bet) =>
  bet.course === "ライト" && bet.betType === "単勝" && bet.combination === "1"
);

assert.ok(lightWin, "期待値基準を通過した買い目が100円未満のKelly切り捨てで消えてはいけない");
assert.equal(lightWin.stakeYen, 100);
assert.ok(lightWin.expectedValuePct >= 108);

console.log("race-tantei minimum stake regression test passed");
