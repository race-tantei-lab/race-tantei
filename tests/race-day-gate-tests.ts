import { strict as assert } from "node:assert";
import { shouldRunOnJraRaceDay } from "../src/v1/race-day-gate.js";
import type { FetchPageResult } from "../src/v1/jra.js";

function page(url: string, html: string): FetchPageResult {
  return { url, html, status: 200, contentType: "text/html; charset=utf-8" };
}

const RACE_DAY_HTML = `
  <div>4回中山2日</div>
  <div>1レース 2歳未勝利 1,200（芝） 10時00分</div>
`;

async function main(): Promise<void> {
  const raceDay = await shouldRunOnJraRaceDay(
    new Date("2026-09-05T15:00:00.000Z"),
    async (url) => page(url, RACE_DAY_HTML),
  );
  assert.equal(raceDay.raceDate, "2026-09-06");
  assert.equal(raceDay.shouldRun, true);
  assert.equal(raceDay.reason, "official_calendar");

  const missingDaily = await shouldRunOnJraRaceDay(
    new Date("2026-09-06T15:00:00.000Z"),
    async () => { throw new Error("HTTP_404"); },
  );
  assert.equal(missingDaily.raceDate, "2026-09-07");
  assert.equal(missingDaily.shouldRun, false);
  assert.equal(missingDaily.reason, "no_calendar");

  const genericDailyNotListed = await shouldRunOnJraRaceDay(
    new Date("2026-09-06T15:00:00.000Z"),
    async (url) => url.endsWith("0907.html")
      ? page(url, "<html><body>JRA calendar</body></html>")
      : page(url, "<html><body><a href=\"0906.html\">9/6</a><a href=\"0912.html\">9/12</a></body></html>"),
  );
  assert.equal(genericDailyNotListed.shouldRun, false);
  assert.equal(genericDailyNotListed.reason, "not_listed_in_official_month_calendar");

  const parserFailureOnListedRaceDay = await shouldRunOnJraRaceDay(
    new Date("2026-09-06T15:00:00.000Z"),
    async (url) => url.endsWith("0907.html")
      ? page(url, "<html><body>unexpected new JRA markup</body></html>")
      : page(url, "<html><body><a href=\"0907.html\">9/7</a></body></html>"),
  );
  assert.equal(parserFailureOnListedRaceDay.shouldRun, true);
  assert.equal(parserFailureOnListedRaceDay.reason, "unparsed_calendar_fail_open");

  const blockedNonRaceMonday = await shouldRunOnJraRaceDay(
    new Date("2026-09-06T15:00:00.000Z"),
    async () => { throw new Error("HTTP_403"); },
  );
  assert.equal(blockedNonRaceMonday.raceDate, "2026-09-07");
  assert.equal(blockedNonRaceMonday.shouldRun, false);
  assert.equal(blockedNonRaceMonday.reason, "official_annual_schedule_fallback");

  const blockedRaceSaturday = await shouldRunOnJraRaceDay(
    new Date("2026-09-11T15:00:00.000Z"),
    async () => { throw new Error("HTTP_403"); },
  );
  assert.equal(blockedRaceSaturday.raceDate, "2026-09-12");
  assert.equal(blockedRaceSaturday.shouldRun, true);
  assert.equal(blockedRaceSaturday.reason, "official_annual_schedule_fallback");

  const blockedSpecialMonday = await shouldRunOnJraRaceDay(
    new Date("2026-09-20T15:00:00.000Z"),
    async () => { throw new Error("HTTP_403"); },
  );
  assert.equal(blockedSpecialMonday.raceDate, "2026-09-21");
  assert.equal(blockedSpecialMonday.shouldRun, true);
  assert.equal(blockedSpecialMonday.reason, "official_annual_schedule_fallback");

  const blockedBeforeSeason = await shouldRunOnJraRaceDay(
    new Date("2026-01-02T15:00:00.000Z"),
    async () => { throw new Error("HTTP_403"); },
  );
  assert.equal(blockedBeforeSeason.raceDate, "2026-01-03");
  assert.equal(blockedBeforeSeason.shouldRun, false);
  assert.equal(blockedBeforeSeason.reason, "official_annual_schedule_fallback");

  const unknownYearNetworkFailure = await shouldRunOnJraRaceDay(
    new Date("2027-09-06T15:00:00.000Z"),
    async () => { throw new Error("HTTP_503"); },
  );
  assert.equal(unknownYearNetworkFailure.raceDate, "2027-09-07");
  assert.equal(unknownYearNetworkFailure.shouldRun, true);
  assert.equal(unknownYearNetworkFailure.reason, "probe_failed_fail_open");

  console.log("RACE_DAY_GATE_TESTS_OK");
}

await main();
