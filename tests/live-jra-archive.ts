import { strict as assert } from "node:assert";
import {
  archiveResultUrl,
  fetchJraArchivePage,
  getArchiveMeetingCnames,
  getArchiveMonthChecksum,
  parseArchiveResultCnames
} from "../src/v1/three-month-archive.js";
import {
  desktopResultPlainText,
  parseDesktopPayouts,
  parseDesktopResultRunners
} from "../src/v1/three-month-desktop.js";
import { fetchJraPage, parseResultPage } from "../src/v1/jra.js";
import { archiveRaceDate, getThreeMonthHistoryProgressV2 } from "../src/v1/three-month-history-v2.js";

void getThreeMonthHistoryProgressV2;

function around(text: string, needle: string): string | null {
  const index = text.indexOf(needle);
  if (index < 0) return null;
  return text.slice(Math.max(0, index - 200), Math.min(text.length, index + 1200));
}

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
const runners = parseDesktopResultRunners(resultPage.html);
const payouts = parseDesktopPayouts(resultPage.html);
const plain = desktopResultPlainText(resultPage.html);

assert.equal(result.race.raceDate, sampleDate);
assert.ok(result.results.some((row) => row.finishPosition === 1));
assert.ok(runners.length >= 5, `too few desktop runners: ${runners.length}`);
assert.ok(runners.every((row) => row.horseName.length > 0), "desktop horse names were not parsed");
assert.ok(
  runners.filter((row) => row.runnerStatus === "active").every((row) => row.winOdds !== null && row.winOdds > 1),
  "desktop popularity proxy odds were not parsed"
);
if (payouts.length < 6) {
  console.error(JSON.stringify({
    stage: "desktop-payout-diagnostic",
    sampleUrl,
    plainLength: plain.length,
    snippets: {
      payout: around(plain, "払戻"),
      win: around(plain, "単勝"),
      exacta: around(plain, "馬単"),
      trifecta: around(plain, "3連単"),
      yen: around(plain, "円")
    },
    rawMarkers: {
      payout: resultPage.html.indexOf("払戻"),
      win: resultPage.html.indexOf("単勝"),
      trifecta: resultPage.html.indexOf("3連単"),
      yen: resultPage.html.indexOf("円")
    }
  }, null, 2));
}
assert.ok(payouts.length >= 6, `too few desktop payouts: ${payouts.length}`);
assert.ok(payouts.some((row) => row.betType === "単勝" && row.payoutYen > 0));
assert.ok(payouts.some((row) => row.betType === "馬連" && row.payoutYen > 0));
assert.ok(payouts.some((row) => row.betType === "3連単" && row.payoutYen > 0));

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
  raceNo: result.race.raceNo,
  runners: runners.length,
  payouts: payouts.length,
  payoutSample: payouts.slice(0, 8)
}, null, 2));
