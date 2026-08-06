import { strict as assert } from "node:assert";
import {
  discoverRaceUrls,
  extractEntryLinks,
  fetchJraPage,
  parseEntryPage
} from "../src/v1/jra.js";

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

if (liveEntry) {
  const { page, entry, url } = liveEntry;
  assert.equal(page.status, 200);
  assert.ok(page.html.length > 10_000, "official current entry response was unexpectedly small");
  assert.ok(entry.race.raceDate.length === 10, "current race date was not parsed");
  assert.ok(entry.race.venue.length > 0, "current venue was not parsed");
  assert.ok(entry.race.raceNo >= 1 && entry.race.raceNo <= 12, "current race number was not parsed");
  assert.ok(entry.runners.length >= 5, `too few live runners parsed: ${entry.runners.length}`);
  assert.ok(
    entry.runners.filter((runner) => runner.winOdds !== null).length >= 3,
    "current win odds were not parsed"
  );
  console.log(JSON.stringify({
    ok: true,
    currentEntryAvailable: true,
    url,
    raceId: entry.race.raceId,
    raceDate: entry.race.raceDate,
    venue: entry.race.venue,
    raceNo: entry.race.raceNo,
    runners: entry.runners.length,
    directEntryLinks: extractEntryLinks(page.html, page.url).length,
    discovered: allDiscovered.length,
    historicalValidation: "tests/live-jra-archive.ts"
  }, null, 2));
} else {
  console.log(JSON.stringify({
    ok: true,
    currentEntryAvailable: false,
    reason: allDiscovered.length === 0
      ? "NO_CURRENT_RACE_URLS_PUBLISHED"
      : "NO_CURRENT_ENTRY_PAGE_AVAILABLE",
    discovered: allDiscovered.length,
    sample: allDiscovered.slice(0, 5),
    historicalValidation: "tests/live-jra-archive.ts"
  }, null, 2));
}
