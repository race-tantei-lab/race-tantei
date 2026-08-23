import { strict as assert } from "node:assert";
import {
  DEADLINE_GUARD_ARM_MS,
  DEADLINE_GUARD_MS,
  FINAL_REFLECTION_DEADLINE_MS,
  isDeadlineGuardMissed,
  shouldDeadlineGuardLock,
} from "../src/v1/completed-worker-deadline-guard.js";

assert.equal(DEADLINE_GUARD_MS, 15 * 60 * 1000, "the public finalization deadline remains T-15");
assert.equal(DEADLINE_GUARD_ARM_MS, 16 * 60 * 1000, "rescue guard arms before T-15");
assert.equal(FINAL_REFLECTION_DEADLINE_MS, 10 * 60 * 1000);

assert.equal(shouldDeadlineGuardLock(DEADLINE_GUARD_ARM_MS), true, "the T-16 rescue tick may arm the final");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000 + 1), true, "the finalization window remains open immediately before T-15");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000), true, "the exact T-15 boundary is the last permitted instant");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000 - 1), false, "no new final may be created after T-15");
assert.equal(shouldDeadlineGuardLock(14 * 60 * 1000), false, "T-14 is a breach, not a recovery window");
assert.equal(shouldDeadlineGuardLock(1), false, "a race one millisecond from start must never get a late final");
assert.equal(shouldDeadlineGuardLock(DEADLINE_GUARD_ARM_MS + 1), false, "do not rescue-lock before the T-16 arm window");
assert.equal(shouldDeadlineGuardLock(0), false, "never create a new final at the recorded start instant");
assert.equal(shouldDeadlineGuardLock(-1), false, "never create a new final after the recorded start instant");
assert.equal(shouldDeadlineGuardLock(Number.NaN), false);

assert.equal(isDeadlineGuardMissed(15 * 60 * 1000), false);
assert.equal(isDeadlineGuardMissed(14 * 60 * 1000), false);
assert.equal(isDeadlineGuardMissed(10 * 60 * 1000), false);
assert.equal(isDeadlineGuardMissed(10 * 60 * 1000 - 1), true);
assert.equal(isDeadlineGuardMissed(1), true);
assert.equal(isDeadlineGuardMissed(0), false, "post-start is handled separately and never recoverable");
assert.equal(isDeadlineGuardMissed(-1), false);
assert.equal(isDeadlineGuardMissed(Number.NaN), false);

console.log("completed-worker-deadline-guard-tests: ok");
