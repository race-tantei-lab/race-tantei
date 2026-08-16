import {
  PERFORMANCE_EXCLUSIONS,
  performanceExclusionForRaceId,
  performanceExclusionSql
} from "../src/v1/performance-exclusions.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const expected = new Set([
  "2026-08-16-chukyo-01",
  "2026-08-16-niigata-02"
]);

assert(PERFORMANCE_EXCLUSIONS.length === 2, `EXPECTED_TWO_EXCLUSIONS:${PERFORMANCE_EXCLUSIONS.length}`);
for (const row of PERFORMANCE_EXCLUSIONS) {
  assert(expected.has(row.raceId), `UNEXPECTED_EXCLUSION:${row.raceId}`);
  assert(row.reasonCode === "system_bet_generation_failure", `INVALID_REASON:${row.raceId}`);
  assert(row.excludedFromPerformance === true, `NOT_EXCLUDED:${row.raceId}`);
  assert(row.displayReason.includes("成績集計対象外"), `MISSING_DISPLAY_REASON:${row.raceId}`);
}

assert(performanceExclusionForRaceId("2026-08-16-chukyo-01") !== null, "CHUKYO_01_NOT_EXCLUDED");
assert(performanceExclusionForRaceId("2026-08-16-niigata-02") !== null, "NIIGATA_02_NOT_EXCLUDED");
assert(performanceExclusionForRaceId("2026-08-16-niigata-03") === null, "NIIGATA_03_WRONGLY_EXCLUDED");

const sql = performanceExclusionSql("b.race_id");
assert(sql.includes("2026-08-16-chukyo-01"), "SQL_MISSING_CHUKYO_01");
assert(sql.includes("2026-08-16-niigata-02"), "SQL_MISSING_NIIGATA_02");
assert(sql.startsWith("b.race_id NOT IN"), `SQL_INVALID:${sql}`);

console.log("PERFORMANCE_EXCLUSIONS_OK", JSON.stringify(PERFORMANCE_EXCLUSIONS));
