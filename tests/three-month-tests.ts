import { strict as assert } from "node:assert";
import { summarizeThreeMonthPeriod } from "../src/v1/three-month-evaluation.js";
import {
  archiveResultUrl,
  parseArchiveResultCnames
} from "../src/v1/three-month-archive.js";
import { parseDesktopResultRunners } from "../src/v1/three-month-desktop.js";
import {
  parseHistoricalMeetings,
  parseHistoricalResultRunners
} from "../src/v1/three-month-history.js";
import type { ThreeMonthValidationSnapshot } from "../src/v1/three-month-validation.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_EVALUATION_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE,
  THREE_MONTH_TUNING_START_DATE,
  THREE_MONTH_VALIDATION_CONFIGS,
  isThreeMonthTuningDate
} from "../src/v1/three-month-scope.js";
import type { BudgetCourse } from "../src/v1/types.js";
import type { CourseValidationSummary, ValidationDateSnapshot } from "../src/v1/validation.js";

assert.equal(THREE_MONTH_SCOPE_VERSION, "three-month-2026-05-02-to-2026-08-02-v2-correct-popularity");
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

const canonicalCnames = parseArchiveResultCnames(`
  <a href="/JRADB/accessS.html?CNAME=sw01sde0105202602050120260509/26">mobile duplicate</a>
  <a href="/JRADB/accessS.html?CNAME=pw01sde0105202602050120260509/26">desktop</a>
  <script>const next = "sw01sde0108202603050720260509/73";</script>
`);
assert.deepEqual(canonicalCnames, [
  "pw01sde0105202602050120260509/26",
  "pw01sde0108202603050720260509/73"
]);
assert.equal(
  archiveResultUrl("sw01sde0105202602050120260509/26"),
  "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0105202602050120260509%2F26"
);

const runnerTableHtml = `
  <table>
    <tr>
      <td>1</td><td>2</td><td>5</td><td>キタノスター</td><td>牝4</td><td>55.0</td>
      <td>C.ルメール</td><td>1:33.4</td><td></td><td>1-1</td><td>34.4</td>
      <td>466kg(-4)</td><td>[栗東]矢作 芳人</td><td>1</td>
    </tr>
    <tr>
      <td>2</td><td>1</td><td>2</td><td>アオイホース</td><td>牡3</td><td>57.0</td>
      <td>横山 武史</td><td>1:33.5</td><td>クビ</td><td>3-3</td><td>34.1</td>
      <td>480kg(+2)</td><td>美浦・田中 博康</td><td>2</td>
    </tr>
    <tr>
      <td>3</td><td>3</td><td>7</td><td>ミナミノカゼ</td><td>セ5</td><td>58</td>
      <td>坂井 瑠星</td><td>1:33.7</td><td>1</td><td>5-5</td><td>34.2</td>
      <td>502(0)</td><td>栗東 矢野 英一</td><td>3</td>
    </tr>
  </table>
`;
const resultRunners = parseHistoricalResultRunners(runnerTableHtml);

assert.equal(resultRunners.length, 3);
const favorite = resultRunners.find((row) => row.horseNo === 5);
const secondFavorite = resultRunners.find((row) => row.horseNo === 2);
const thirdFavorite = resultRunners.find((row) => row.horseNo === 7);
assert.equal(favorite?.horseName, "キタノスター");
assert.equal(favorite?.sexAge, "牝4");
assert.equal(favorite?.assignedWeight, 55);
assert.equal(favorite?.jockey, "C.ルメール");
assert.equal(favorite?.horseWeight, 466);
assert.equal(favorite?.weightChange, -4);
assert.equal(favorite?.trainer, "矢作 芳人");
assert.equal(favorite?.stable, "栗東");
assert.equal(favorite?.popularity, 1);
assert.equal(secondFavorite?.popularity, 2);
assert.equal(secondFavorite?.horseWeight, 480);
assert.equal(secondFavorite?.weightChange, 2);
assert.equal(secondFavorite?.trainer, "田中 博康");
assert.equal(secondFavorite?.stable, "美浦");
assert.equal(thirdFavorite?.popularity, 3);
assert.ok((favorite?.winOdds ?? 999) < (secondFavorite?.winOdds ?? 0));
assert.ok((secondFavorite?.winOdds ?? 999) < (thirdFavorite?.winOdds ?? 0));

const desktopRunners = parseDesktopResultRunners(runnerTableHtml);
assert.equal(desktopRunners.length, 3);
assert.equal(desktopRunners.find((row) => row.horseNo === 5)?.popularity, 1);
assert.equal(desktopRunners.find((row) => row.horseNo === 2)?.popularity, 2);
assert.ok(
  (desktopRunners.find((row) => row.horseNo === 5)?.winOdds ?? 999)
    < (desktopRunners.find((row) => row.horseNo === 2)?.winOdds ?? 0)
);

const corruptPopularityHtml = `
  <table>
    <tr>
      <td>1</td><td>1</td><td>1</td><td>ホースワン</td><td>牡3</td><td>57</td>
      <td>騎手A</td><td>1:35.0</td><td></td><td>1-1</td><td>35.0</td>
      <td>480(0)</td><td>美浦・調教師A</td><td>63</td>
    </tr>
    <tr>
      <td>2</td><td>2</td><td>2</td><td>ホースツー</td><td>牝3</td><td>55</td>
      <td>騎手B</td><td>1:35.1</td><td>クビ</td><td>2-2</td><td>35.1</td>
      <td>470(+2)</td><td>栗東・調教師B</td><td>77</td>
    </tr>
  </table>
`;
const corruptPopularityRunners = parseHistoricalResultRunners(corruptPopularityHtml);
assert.equal(corruptPopularityRunners.length, 2);
assert.equal(corruptPopularityRunners[0]?.popularity, null);
assert.equal(corruptPopularityRunners[1]?.popularity, null);
assert.equal(corruptPopularityRunners[0]?.winOdds, null);
assert.equal(corruptPopularityRunners[1]?.winOdds, null);

const corruptDesktopRunners = parseDesktopResultRunners(corruptPopularityHtml);
assert.equal(corruptDesktopRunners.length, 2);
assert.equal(corruptDesktopRunners[0]?.popularity, null);
assert.equal(corruptDesktopRunners[1]?.popularity, null);
assert.equal(corruptDesktopRunners[0]?.winOdds, null);
assert.equal(corruptDesktopRunners[1]?.winOdds, null);

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
