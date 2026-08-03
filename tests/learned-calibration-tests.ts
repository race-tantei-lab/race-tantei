import { strict as assert } from "node:assert";
import {
  buildLearnedVenueBets,
  learnedPredictionRaceScore
} from "../src/v1/learned-betting-policy.js";
import {
  buildCalibratedPrediction,
  calibratedProbabilities,
  updateCalibrationLoss,
  type StoredCalibrationRunner
} from "../src/v1/learned-calibration-math.js";
import { emptyLossAccumulator } from "../src/v1/learned-calibration-state.js";

const runners: StoredCalibrationRunner[] = [
  {
    horseNo: 1,
    horseName: "A",
    winProbability: 0.6,
    placeProbability: 0.9,
    fairOdds: 1.67,
    currentOdds: 4,
    expectedValuePct: 240,
    predictedOrder: 1,
    explanation: "base",
    popularity: 2
  },
  {
    horseNo: 2,
    horseName: "B",
    winProbability: 0.3,
    placeProbability: 0.7,
    fairOdds: 3.33,
    currentOdds: 2,
    expectedValuePct: 60,
    predictedOrder: 2,
    explanation: "base",
    popularity: 1
  },
  {
    horseNo: 3,
    horseName: "C",
    winProbability: 0.1,
    placeProbability: 0.3,
    fairOdds: 10,
    currentOdds: 10,
    expectedValuePct: 100,
    predictedOrder: 3,
    explanation: "base",
    popularity: 3
  }
];

const modelOnly = calibratedProbabilities(runners, 1, 1);
assert.ok(Math.abs((modelOnly.get(1) ?? 0) - 0.6) < 1e-9);
assert.ok(Math.abs([...modelOnly.values()].reduce((sum, value) => sum + value, 0) - 1) < 1e-9);

const marketOnly = calibratedProbabilities(runners, 0, 1);
assert.ok((marketOnly.get(2) ?? 0) > (marketOnly.get(1) ?? 0));
assert.ok(Math.abs([...marketOnly.values()].reduce((sum, value) => sum + value, 0) - 1) < 1e-9);

const blended = calibratedProbabilities(runners, 0.5, 1);
assert.ok((blended.get(1) ?? 0) > 0);
assert.ok((blended.get(2) ?? 0) > 0);
assert.ok(Math.abs([...blended.values()].reduce((sum, value) => sum + value, 0) - 1) < 1e-9);

const accumulator = emptyLossAccumulator();
updateCalibrationLoss(accumulator, modelOnly, 1);
assert.equal(accumulator.races, 1);
assert.equal(accumulator.top1, 1);
assert.equal(accumulator.top3, 1);
assert.ok(accumulator.loss > 0);

const predictions = buildCalibratedPrediction(runners, {
  modelWeight: 1,
  temperature: 1,
  trainLogLoss: 1,
  validationLogLoss: 1,
  baselineValidationLogLoss: 1,
  validationImprovementPct: 0
});
assert.deepEqual(predictions.map((row) => row.horseNo), [1, 2, 3]);
assert.equal(predictions[0]?.predictedOrder, 1);
assert.ok(predictions.every((row) => row.explanation.includes("12か月")));

const bets = buildLearnedVenueBets(predictions);
const stakeByCourse = new Map<string, number>();
for (const bet of bets) {
  stakeByCourse.set(bet.course, (stakeByCourse.get(bet.course) ?? 0) + bet.stakeYen);
}
assert.equal(stakeByCourse.get("ライト"), 1600);
assert.equal(stakeByCourse.get("スタンダード"), 4200);
assert.equal(stakeByCourse.get("プレミアム"), 8800);
assert.ok(Number.isFinite(learnedPredictionRaceScore(predictions)));

console.log("race-tantei learned calibration tests passed");
