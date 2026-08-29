import { strict as assert } from "node:assert";
import {
  DEADLINE_GUARD_ARM_MS,
  DEADLINE_GUARD_MS,
  FINAL_REFLECTION_DEADLINE_MS,
  isDeadlineGuardMissed,
  shouldDeadlineGuardLock,
} from "../src/v1/completed-worker-deadline-guard.js";
import { MAX_PREVIEW_GENERATIONS_PER_TICK, livePreviewPriorityRank } from "../src/v1/completed-worker-live-lock.js";

assert.equal(DEADLINE_GUARD_MS, 15 * 60 * 1000, "the public finalization deadline remains T-15");
assert.equal(DEADLINE_GUARD_ARM_MS, 25 * 60 * 1000, "rescue guard arms at T-25 so public picks cannot remain missing near post");
assert.equal(FINAL_REFLECTION_DEADLINE_MS, 10 * 60 * 1000);

assert.equal(shouldDeadlineGuardLock(DEADLINE_GUARD_ARM_MS), true, "the T-25 rescue tick may arm the final");
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

const minute = 60 * 1000;
assert.equal(MAX_PREVIEW_GENERATIONS_PER_TICK, 1);
assert.equal(livePreviewPriorityRank({ remainingMs: 30 * minute, hasPreview: true, previewFresh: true }), 0);
assert.equal(livePreviewPriorityRank({ remainingMs: 31 * minute, hasPreview: false, previewFresh: false }), 2);
assert.equal(livePreviewPriorityRank({ remainingMs: 50 * minute, hasPreview: false, previewFresh: false }), 2);
assert.equal(livePreviewPriorityRank({ remainingMs: 31 * minute, hasPreview: true, previewFresh: false }), 3);
assert.equal(livePreviewPriorityRank({ remainingMs: 31 * minute, hasPreview: true, previewFresh: true }), 4);

let missing = Array.from({ length: 15 }, (_, index) => `missing-${index + 1}`);
for (let tick = 0; tick < 15; tick += 1) {
  const candidates = [
    ...missing.map((raceId, index) => ({ raceId, remainingMs: (90 - index) * minute, hasPreview: false, previewFresh: false })),
    { raceId: "stale-refresh", remainingMs: 31 * minute, hasPreview: true, previewFresh: false },
  ].sort((a, b) => livePreviewPriorityRank(a) - livePreviewPriorityRank(b) || a.remainingMs - b.remainingMs || a.raceId.localeCompare(b.raceId));
  const chosen = candidates.slice(0, MAX_PREVIEW_GENERATIONS_PER_TICK);
  assert.equal(chosen.length, 1);
  assert.ok(chosen[0].raceId !== "stale-refresh", "stale refresh must not starve missing preview coverage");
  missing = missing.filter((raceId) => raceId !== chosen[0].raceId);
}
assert.equal(missing.length, 0, "15 selected races are covered in 15 one-minute ticks, inside the T-90 to T-30 safety margin");

console.log("completed-worker-deadline-guard-tests: ok");
