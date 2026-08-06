import { strict as assert } from "node:assert";
import {
  discoverRaceUrls,
  extractEntryLinks,
  fetchJraPage,
  parseEntryPage,
  parseResultPage
} from "../src/v1/jra.js";
import {
  historicalResultUrl,
  parseHistoricalMeetings,
  parseHistoricalResultRunners
} from "../src/v1/three-month-history.js";

function snippet(html: string, needle: string): string | null {
  const index = html.indexOf(needle);
  if (index < 0) return null;
  return html.slice(Math.max(0, index - 500), Math.min(html.length, index + 1800));
}

async function findAvailableEntry(urls: string[]): Promise<{
  page: Awaited<ReturnType<typeof fetchJraPage>>;
  entry: ReturnType<typeof parseEntryPage>;
  url: string;
} | null> {
  for (const url of urls.slice(0, 60)) {
    try {
      const page = await fetchJraPage(url);
      if (!/出馬表/.test(page.html)) continue;
      const entry = parseEntryPage(page.html, page.url);
      if (entry.runners.length >= 5) return { page, entry, url };
    } catch {
      // Finished, not-yet-published, or temporarily absent pages are normal.
    }
  }
  return null;
}

const expiredFixtureUrl = "https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030520260801%2F15";
const allDiscovered = await discoverRaceUrls("https://sp.jra.jp/", [expiredFixtureUrl]);
const liveEntry = allDiscovered.length > 0
  ? await findAvailableEntry(allDiscovered.filter((url) => url !== expiredFixtureUrl))
  : null;
let liveSummary: Record<string, unknown> = {
  available: false,
  discovered: allDiscovered.length
};

if (liveEntry) {
  const { page: entryPage, entry, url } = liveEntry;
  assert.equal(entryPage.status, 200);
  assert.ok(entryPage.html.length > 10_000, "official current entry response was unexpectedly small");
  assert.ok(entry.race.raceDate.length === 10, "current race date was not parsed");
  assert.ok(entry.race.venue.length > 0, "current venue was not parsed");
  assert.ok(entry.race.raceNo >= 1 && entry.race.raceNo <= 12, "current race number was not parsed");
  assert.ok(entry.runners.length >= 5, `too few live runners parsed: ${entry.runners.length}`);
  assert.ok(
    entry.runners.filter((runner) => runner.winOdds !== null).length >= 3,
    "current win odds were not parsed"
  );
  const directLinks = extractEntryLinks(entryPage.html, entryPage.url);
  liveSummary = {
    available: true,
    url,
    raceId: entry.race.raceId,
    raceDate: entry.race.raceDate,
    venue: entry.race.venue,
    raceNo: entry.race.raceNo,
    runners: entry.runners.length,
    directEntryLinks: directLinks.length,
    discovered: allDiscovered.length
  };
} else {
  console.warn(JSON.stringify({
    stage: "current-entry-skip",
    reason: allDiscovered.length === 0
      ? "NO_CURRENT_RACE_URLS_PUBLISHED"
      : "NO_CURRENT_ENTRY_PAGE_AVAILABLE",
    discovered: allDiscovered.length,
    sample: allDiscovered.slice(0, 5)
  }));
}

const historicalTask = {
  raceDate: "2026-05-02",
  venue: "新潟",
  meetingNo: 1,
  meetingDay: 1
};
const generatedHistoricalUrl = historicalResultUrl(historicalTask, 8);
const historicalResultPage = await fetchJraPage(generatedHistoricalUrl);
assert.equal(historicalResultPage.status, 200);
assert.ok(historicalResultPage.html.length > 10_000, "historical result response was unexpectedly small");
assert.ok(/レース結果/.test(historicalResultPage.html), "historical result page was not returned");

let historicalResult;
try {
  historicalResult = parseResultPage(historicalResultPage.html, historicalResultPage.url);
} catch (error) {
  console.error(JSON.stringify({
    stage: "historical-result-parse",
    error: error instanceof Error ? error.message : String(error),
    finalUrl: historicalResultPage.url,
    htmlLength: historicalResultPage.html.length,
    snippets: {
      result: snippet(historicalResultPage.html, "着順"),
      payout: snippet(historicalResultPage.html, "払戻金")
    }
  }, null, 2));
  throw error;
}
const historicalRunners = parseHistoricalResultRunners(historicalResultPage.html);
assert.equal(historicalResult.race.raceDate, "2026-05-02");
assert.equal(historicalResult.race.venue, "新潟");
assert.equal(historicalResult.race.raceNo, 8);
assert.ok(historicalRunners.length >= 10, "historical result runners were not reconstructed");
assert.ok(
  historicalRunners.every((runner) => runner.horseName.length > 0),
  "historical horse names were not reconstructed"
);
const historicalActive = historicalRunners.filter((runner) => runner.runnerStatus === "active");
assert.ok(
  historicalActive.every((runner) => runner.winOdds !== null && runner.winOdds > 1),
  "popularity proxy odds were not reconstructed"
);
assert.equal(
  new Set(historicalActive.map((runner) => runner.popularity)).size,
  historicalActive.length,
  "historical popularity ranks were not unique"
);
assert.ok(
  historicalActive.every((runner) =>
    runner.popularity !== null
    && runner.popularity >= 1
    && runner.popularity <= historicalActive.length
  ),
  "historical popularity ranks were outside the field"
);
assert.ok(
  historicalRunners.some((runner) => runner.jockey && runner.trainer && runner.assignedWeight),
  "historical people and weight fields were not reconstructed"
);
assert.ok(
  historicalResult.results.some((runner) => runner.finishPosition === 1),
  "historical winner was not parsed"
);
assert.ok(
  historicalResult.payouts.some((payout) => payout.betType === "3連単" && payout.payoutYen > 0),
  "historical trifecta payout was not parsed"
);

const calendarPage = await fetchJraPage("https://www.jra.go.jp/keiba/calendar2026/2026/5/0502.html");
const calendarMeetings = parseHistoricalMeetings(calendarPage.html, "2026-05-02");
assert.ok(
  calendarMeetings.some((row) => row.venue === "新潟" && row.meetingNo === 1 && row.meetingDay === 1),
  "historical calendar did not expose Niigata meeting"
);
assert.ok(calendarMeetings.length >= 3, "historical calendar meetings were incomplete");

console.log(JSON.stringify({
  ok: true,
  live: liveSummary,
  historicalRaceId: historicalResult.race.raceId,
  generatedHistoricalUrl,
  historicalResultFinalUrl: historicalResultPage.url,
  historicalRunners: historicalRunners.slice(0, 4),
  calendarMeetings,
  historicalResults: historicalResult.results.length,
  historicalPayouts: historicalResult.payouts.length,
  allDiscovered: allDiscovered.length
}, null, 2));
