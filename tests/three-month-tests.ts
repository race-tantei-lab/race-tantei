import { strict as assert } from "node:assert";
import { parseHistoricalMeetings } from "../src/v1/three-month-history.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_START_DATE,
  THREE_MONTH_VALIDATION_CONFIGS
} from "../src/v1/three-month-scope.js";

assert.equal(THREE_MONTH_START_DATE, "2026-05-02");
assert.equal(THREE_MONTH_END_DATE, "2026-08-02");
assert.equal(THREE_MONTH_RACE_DATES.length, 28);
assert.equal(THREE_MONTH_VALIDATION_CONFIGS.length, 28);
assert.equal(new Set(THREE_MONTH_VALIDATION_CONFIGS.map((row) => row.modelVersion)).size, 28);

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

console.log("race-tantei three month scope tests passed");
