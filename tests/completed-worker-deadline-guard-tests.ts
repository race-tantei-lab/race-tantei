import { strict as assert } from "node:assert";
import {
  DEADLINE_GUARD_ARM_MS,
  DEADLINE_GUARD_MS,
  isDeadlineGuardMissed,
  shouldDeadlineGuardLock,
} from "../src/v1/completed-worker-deadline-guard.js";

assert.equal(DEADLINE_GUARD_MS, 15 * 60 * 1000, "the public finalization deadline remains T-15");
assert.equal(DEADLINE_GUARD_ARM_MS, 20 * 60 * 1000, "arm five minutes early so the final is immutable before T-15");

assert.equal(shouldDeadlineGuardLock(DEADLINE_GUARD_ARM_MS), true, "the T-20 backup tick may arm the final");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000 + 1), true, "the finalization window remains open immediately before T-15");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000), true, "the exact T-15 boundary is the last permitted instant");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000 - 1), false, "no new final may be created after T-15");
assert.equal(shouldDeadlineGuardLock(14 * 60 * 1000), false, "T-14 is a breach, not a recovery window");
assert.equal(shouldDeadlineGuardLock(1), false, "a race one millisecond from start must never get a late final");
assert.equal(shouldDeadlineGuardLock(DEADLINE_GUARD_ARM_MS + 1), false, "do not lock before the T-20 arm window");
assert.equal(shouldDeadlineGuardLock(0), false, "never create a new final at the recorded start instant");
assert.equal(shouldDeadlineGuardLock(-1), false, "never create a new final after the recorded start instant");
assert.equal(shouldDeadlineGuardLock(Number.NaN), false);

assert.equal(isDeadlineGuardMissed(15 * 60 * 1000), false, "exactly T-15 is still on time");
assert.equal(isDeadlineGuardMissed(15 * 60 * 1000 - 1), true, "one millisecond past T-15 is a hard miss");
assert.equal(isDeadlineGuardMissed(14 * 60 * 1000), true);
assert.equal(isDeadlineGuardMissed(1), true);
assert.equal(isDeadlineGuardMissed(0), false, "post-start is handled separately and never recoverable");
assert.equal(isDeadlineGuardMissed(-1), false);
assert.equal(isDeadlineGuardMissed(Number.NaN), false);

console.log("completed-worker-deadline-guard-tests: ok");
