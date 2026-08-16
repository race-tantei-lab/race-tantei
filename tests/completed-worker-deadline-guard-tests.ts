import assert from "node:assert/strict";
import { DEADLINE_GUARD_MS, shouldDeadlineGuardLock } from "../src/v1/completed-worker-deadline-guard.js";

assert.equal(DEADLINE_GUARD_MS, 15 * 60 * 1000);
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000), true, "exactly 15 minutes before start must lock");
assert.equal(shouldDeadlineGuardLock(14 * 60 * 1000), true, "a missed first cron must still be recoverable at 14 minutes");
assert.equal(shouldDeadlineGuardLock(10 * 60 * 1000), true, "the guard must remain active throughout the pre-start catch-up window");
assert.equal(shouldDeadlineGuardLock(1), true, "a still-unstarted race must remain recoverable");
assert.equal(shouldDeadlineGuardLock(15 * 60 * 1000 + 1), false, "do not lock before the configured deadline");
assert.equal(shouldDeadlineGuardLock(0), false, "never create a new final at the recorded start instant");
assert.equal(shouldDeadlineGuardLock(-1), false, "never create a new final after the recorded start instant");
assert.equal(shouldDeadlineGuardLock(Number.NaN), false);

console.log("completed-worker-deadline-guard-tests: ok");
