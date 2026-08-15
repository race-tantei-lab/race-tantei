import { strict as assert } from "node:assert";
import { assessPriorLearningRows, type PriorLearningRaceRow } from "../src/v1/prior-day-learning-gate.js";

function row(overrides: Partial<PriorLearningRaceRow> = {}): PriorLearningRaceRow {
  return {
    raceId: "2026-08-15-niigata-01",
    raceDate: "2026-08-15",
    status: "finished",
    activeRunners: 16,
    resultRows: 16,
    payoutTypes: 6,
    ...overrides,
  };
}

let result = assessPriorLearningRows("2026-08-16", "2026-08-09", [row()]);
assert.equal(result.ready, true);
assert.equal(result.priorRaceCount, 1);
assert.equal(result.completeRaceCount, 1);
assert.deepEqual(result.incompleteRaceIds, []);

result = assessPriorLearningRows("2026-08-16", "2026-08-09", [row({ resultRows: 15 })]);
assert.equal(result.ready, false);
assert.deepEqual(result.incompleteRaceIds, ["2026-08-15-niigata-01"]);

result = assessPriorLearningRows("2026-08-16", "2026-08-09", [row({ payoutTypes: 5 })]);
assert.equal(result.ready, false);

result = assessPriorLearningRows("2026-08-16", "2026-08-09", [row({ status: "scheduled" })]);
assert.equal(result.ready, false);

result = assessPriorLearningRows("2026-08-16", "2026-08-09", []);
assert.equal(result.ready, true);
assert.equal(result.priorRaceCount, 0);

console.log("prior-day learning gate tests passed");
