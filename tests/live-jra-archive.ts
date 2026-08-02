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

function mobileResultUrl(cname: string): string {
  const mobileCname = cname.replace(/^pw/i, "sw");
  return `https://sp.jra.jp/JRADB/accessS.html?CNAME=${encodeURIComponent(mobileCname)}`;
}

const checksum = await getArchiveMonthChecksum("202605");
assert.ok(/^[0-9A-F]{2}$/.test(checksum), `invalid archive checksum: ${checksum}`);

const meetings = await getArchiveMeetingCnames("202605");
assert.ok(meetings.length >= 20, `too few May archive meetings: ${meetings.length}`);
assert.ok(meetings.every((value) => /^(?:pw|sw)01srl/i.test(value)));

const meetingPage = await fetchJraArchivePage(meetings[0]!);
const resultCnames = parseArchiveResultCnames(meetingPage.html);
assert.ok(resultCnames.length >= 12, `too few result links in archive meeting: ${resultCnames.length}`);

const probes = [];
for (const resultCname of resultCnames.slice(0, 5)) {
  const desktopUrl = archiveResultUrl(resultCname);
  const desktopPage = await fetchJraPage(desktopUrl);
  const desktopResult = parseResultPage(desktopPage.html, desktopPage.url);
  let mobileResult: ReturnType<typeof parseResultPage> | null = null;
  let mobileError: string | null = null;
  try {
    const mobilePage = await fetchJraPage(mobileResultUrl(resultCname));
    mobileResult = parseResultPage(mobilePage.html, mobilePage.url);
  } catch (error) {
    mobileError = error instanceof Error ? error.message : String(error);
  }
  probes.push({
    resultCname,
    desktopUrl,
    desktop: {
      raceId: desktopResult.race.raceId,
      date: desktopResult.race.raceDate,
      venue: desktopResult.race.venue,
      raceNo: desktopResult.race.raceNo,
      results: desktopResult.results.length,
      payouts: desktopResult.payouts.length
    },
    mobile: mobileResult ? {
      raceId: mobileResult.race.raceId,
      date: mobileResult.race.raceDate,
      venue: mobileResult.race.venue,
      raceNo: mobileResult.race.raceNo,
      results: mobileResult.results.length,
      payouts: mobileResult.payouts.length
    } : null,
    mobileError
  });
}

const usable = probes.find((probe) => (probe.mobile?.payouts ?? 0) > 0)
  ?? probes.find((probe) => probe.desktop.payouts > 0);
assert.ok(usable, `no archive result with payouts: ${JSON.stringify(probes)}`);
const selectedDate = usable.mobile?.date ?? usable.desktop.date;
assert.ok(selectedDate.startsWith("2026-05-"), `unexpected archive result date: ${selectedDate}`);
assert.equal(archiveRaceDate(usable.desktopUrl), selectedDate);

console.log(JSON.stringify({
  ok: true,
  checksum,
  meetings: meetings.length,
  firstMeeting: meetings[0],
  resultLinks: resultCnames.length,
  probes,
  usable
}, null, 2));
