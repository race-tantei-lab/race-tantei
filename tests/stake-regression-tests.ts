import { strict as assert } from "node:assert";
import { buildBudgetCourseBets, COURSE_BUDGETS } from "../src/v1/budget-courses.js";
import type { BudgetCourse, RunnerPrediction } from "../src/v1/types.js";

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
    explanation: "コース予算配分の回帰テスト"
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

assert.ok(lightWin, "期待値基準を通過した買い目が消えてはいけない");
assert.ok(lightWin.stakeYen >= 100 && lightWin.stakeYen % 100 === 0);
assert.ok(lightWin.expectedValuePct >= 108);

const totals = new Map<BudgetCourse, number>();
for (const course of ["ライト", "スタンダード", "プレミアム"] as BudgetCourse[]) {
  const total = bets
    .filter((bet) => bet.course === course)
    .reduce((sum, bet) => sum + bet.stakeYen, 0);
  totals.set(course, total);
  assert.ok(total > 0, `${course}の買い目がありません`);
  assert.ok(total <= COURSE_BUDGETS[course], `${course}が予算上限を超えています`);
}

assert.ok((totals.get("スタンダード") ?? 0) > (totals.get("ライト") ?? 0));
assert.ok((totals.get("プレミアム") ?? 0) > (totals.get("スタンダード") ?? 0));

console.log("race-tantei course budget regression test passed");
