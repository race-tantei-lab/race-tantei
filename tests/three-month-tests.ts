import { strict as assert } from "node:assert";
import { summarizeThreeMonthPeriod } from "../src/v1/three-month-evaluation.js";
import { parseHistoricalMeetings } from "../src/v1/three-month-history.js";
import type { ThreeMonthValidationSnapshot } from "../src/v1/three-month-validation.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_EVALUATION_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_START_DATE,
  THREE_MONTH_TUNING_START_DATE,
  THREE_MONTH_VALIDATION_CONFIGS,
  isThreeMonthTuningDate
} from "../src/v1/three-month-scope.js";
import type { BudgetCourse } from "../src/v1/types.js";
import type { CourseValidationSummary, ValidationDateSnapshot } from "../src/v1/validation.js";

assert.equal(THREE_MONTH_START_DATE, "2026-05-02");
assert.equal(THREE_MONTH_EVALUATION_END_DATE, "2026-07-26");
assert.equal(THREE_MONTH_TUNING_START_DATE, "2026-08-01");
assert.equal(THREE_MONTH_END_DATE, "2026-08-02");
assert.equal(THREE_MONTH_RACE_DATES.length, 28);
assert.equal(THREE_MONTH_VALIDATION_CONFIGS.length, 28);
assert.equal(new Set(THREE_MONTH_VALIDATION_CONFIGS.map((row) => row.modelVersion)).size, 28);
assert.equal(isThreeMonthTuningDate("2026-07-26"), false);
assert.equal(isThreeMonthTuningDate("2026-08-01"), true);
assert.equal(isThreeMonthTuningDate("2026-08-02"), true);

const meetings = parseHistoricalMeetings(`
  <main>
    <h2>2026年5月2日（土曜） 競馬番組</h2>
    <section><h3>2回東京3日</h3></section>
    <section><h3>3回京都3日</h3></section>
    <section><h3>1回新潟1日</h3></section>
    <footer>2回東京3日</footer>
  </main>
`, "2026-05-02");

assert.equal(meetings.length, 3);
assert.deepEqual(
  meetings.map((row) => ({ venue: row.venue, meetingNo: row.meetingNo, meetingDay: row.meetingDay }))
    .sort((a, b) => a.venue.localeCompare(b.venue, "ja")),
  [
    { venue: "京都", meetingNo: 3, meetingDay: 3 },
    { venue: "新潟", meetingNo: 1, meetingDay: 1 },
    { venue: "東京", meetingNo: 2, meetingDay: 3 }
  ].sort((a, b) => a.venue.localeCompare(b.venue, "ja"))
);

function courseSummary(
  course: BudgetCourse,
  stakeYen: number,
  returnYen: number
): CourseValidationSummary {
  return {
    course,
    processedRaces: 1,
    selectedRaces: 1,
    skippedRaces: 0,
    hitRaces: returnYen > 0 ? 1 : 0,
    tickets: 1,
    pendingTickets: 0,
    stakeYen,
    returnYen,
    profitYen: returnYen - stakeYen,
    expectedReturnYen: 0,
    roiPct: returnYen / stakeYen * 100,
    expectedRoiPct: null,
    hitRatePct: returnYen > 0 ? 100 : 0,
    byTicketType: []
  };
}

function dateSnapshot(
  raceDate: string,
  lightReturn: number,
  standardReturn: number,
  premiumReturn: number
): ValidationDateSnapshot {
  return {
    raceDate,
    label: raceDate,
    modelVersion: `validation-${raceDate}-roi-policy-v1-3m`,
    totalRaces: 1,
    processedRaces: 1,
    remainingRaces: 0,
    noBetRaces: 0,
    complete: true,
    courses: [
      courseSummary("ライト", 1600, lightReturn),
      courseSummary("スタンダード", 4200, standardReturn),
      courseSummary("プレミアム", 8800, premiumReturn)
    ]
  };
}

const syntheticSnapshot = {
  phase: "three-month-validation-v2-sql-aggregate",
  scopeVersion: "test",
  startDate: THREE_MONTH_START_DATE,
  endDate: THREE_MONTH_END_DATE,
  generatedAt: "2026-08-03T00:00:00.000Z",
  complete: true,
  totalRaces: 2,
  processedRaces: 2,
  remainingRaces: 0,
  noBetRaces: 0,
  venueDays: 2,
  dates: [
    dateSnapshot("2026-05-02", 800, 2100, 4400),
    dateSnapshot("2026-08-01", 3200, 8400, 17600)
  ],
  combined: [],
  monthly: []
} satisfies ThreeMonthValidationSnapshot;

const evaluation = summarizeThreeMonthPeriod(
  syntheticSnapshot,
  THREE_MONTH_START_DATE,
  THREE_MONTH_EVALUATION_END_DATE
);
const tuning = summarizeThreeMonthPeriod(
  syntheticSnapshot,
  THREE_MONTH_TUNING_START_DATE,
  THREE_MONTH_END_DATE
);

assert.equal(evaluation.dates.length, 1);
assert.equal(evaluation.dates[0]?.raceDate, "2026-05-02");
assert.equal(evaluation.combined.find((row) => row.course === "ライト")?.roiPct, 50);
assert.equal(evaluation.combined.find((row) => row.course === "スタンダード")?.roiPct, 50);
assert.equal(evaluation.combined.find((row) => row.course === "プレミアム")?.roiPct, 50);
assert.equal(tuning.dates.length, 1);
assert.equal(tuning.combined.find((row) => row.course === "ライト")?.roiPct, 200);
assert.equal(tuning.combined.find((row) => row.course === "スタンダード")?.roiPct, 200);
assert.equal(tuning.combined.find((row) => row.course === "プレミアム")?.roiPct, 200);

console.log("race-tantei three month scope tests passed");
