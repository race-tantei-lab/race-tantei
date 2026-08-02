import { strict as assert } from "node:assert";
import {
  archiveResultUrl,
  fetchJraArchivePage,
  getArchiveMeetingCnames,
  getArchiveMonthChecksum,
  parseArchiveResultCnames
} from "../src/v1/three-month-archive.js";
import { fetchJraPage, parseResultPage } from "../src/v1/jra.js";
import { archiveRaceDate, getThreeMonthHistoryProgressV2 } from "../src/v1/three-month-history-v2.js";

void getThreeMonthHistoryProgressV2;

const checksum = await getArchiveMonthChecksum("202605");
assert.ok(/^[0-9A-F]{2}$/.test(checksum), `invalid archive checksum: ${checksum}`);

const meetings = await getArchiveMeetingCnames("202605");
assert.ok(meetings.length >= 20, `too few May archive meetings: ${meetings.length}`);
assert.ok(meetings.every((value) => /^(?:pw|sw)01srl/i.test(value)));

const meetingPage = await fetchJraArchivePage(meetings[0]!);
const resultCnames = parseArchiveResultCnames(meetingPage.html);
assert.ok(resultCnames.length >= 12, `too few result links in archive meeting: ${resultCnames.length}`);

const sampleUrl = archiveResultUrl(resultCnames[0]!);
const sampleDate = archiveRaceDate(sampleUrl);
assert.ok(sampleDate?.startsWith("2026-05-"), `unexpected archive result date: ${sampleDate}`);
const resultPage = await fetchJraPage(sampleUrl);
const result = parseResultPage(resultPage.html, resultPage.url);
assert.equal(result.race.raceDate, sampleDate);
assert.ok(result.results.some((row) => row.finishPosition === 1));
assert.ok(result.payouts.some((row) => row.payoutYen > 0));

console.log(JSON.stringify({
  ok: true,
  checksum,
  meetings: meetings.length,
  firstMeeting: meetings[0],
  resultLinks: resultCnames.length,
  sampleUrl,
  raceId: result.race.raceId,
  raceDate: result.race.raceDate,
  venue: result.race.venue,
  raceNo: result.race.raceNo
}, null, 2));
