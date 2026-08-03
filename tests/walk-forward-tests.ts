import { strict as assert } from "node:assert";
import {
  WALK_FORWARD_ARCHIVE_MONTHS,
  WALK_FORWARD_CONTEXT_START_DATE,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_HOLDOUT_START_DATE,
  WALK_FORWARD_TRAIN_END_DATE,
  WALK_FORWARD_TRAIN_START_DATE,
  WALK_FORWARD_VALIDATION_END_DATE,
  WALK_FORWARD_VALIDATION_START_DATE,
  isWalkForwardArchiveDate,
  walkForwardSplitForDate
} from "../src/v1/walk-forward-scope.js";

assert.equal(WALK_FORWARD_CONTEXT_START_DATE, "2024-05-01");
assert.equal(WALK_FORWARD_TRAIN_START_DATE, "2025-05-01");
assert.equal(WALK_FORWARD_TRAIN_END_DATE, "2026-04-30");
assert.equal(WALK_FORWARD_VALIDATION_START_DATE, "2026-05-02");
assert.equal(WALK_FORWARD_VALIDATION_END_DATE, "2026-06-28");
assert.equal(WALK_FORWARD_HOLDOUT_START_DATE, "2026-07-04");
assert.equal(WALK_FORWARD_HOLDOUT_END_DATE, "2026-07-26");

assert.equal(walkForwardSplitForDate("2025-05-01"), "train");
assert.equal(walkForwardSplitForDate("2026-04-30"), "train");
assert.equal(walkForwardSplitForDate("2026-05-01"), null);
assert.equal(walkForwardSplitForDate("2026-05-02"), "validation");
assert.equal(walkForwardSplitForDate("2026-06-28"), "validation");
assert.equal(walkForwardSplitForDate("2026-06-29"), null);
assert.equal(walkForwardSplitForDate("2026-07-04"), "holdout");
assert.equal(walkForwardSplitForDate("2026-07-26"), "holdout");
assert.equal(walkForwardSplitForDate("2026-08-01"), null);
assert.equal(walkForwardSplitForDate("2026-08-02"), null);

assert.equal(isWalkForwardArchiveDate("2024-05-01"), true);
assert.equal(isWalkForwardArchiveDate("2025-04-30"), true);
assert.equal(walkForwardSplitForDate("2025-04-30"), null, "context history must never become training labels");
assert.equal(isWalkForwardArchiveDate("2026-07-26"), true);
assert.equal(isWalkForwardArchiveDate("2026-08-01"), false);

assert.equal(WALK_FORWARD_ARCHIVE_MONTHS[0], "202405");
assert.equal(WALK_FORWARD_ARCHIVE_MONTHS.at(-1), "202607");
assert.equal(new Set(WALK_FORWARD_ARCHIVE_MONTHS).size, WALK_FORWARD_ARCHIVE_MONTHS.length);

console.log("race-tantei walk-forward scope tests passed");
