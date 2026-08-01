import { strict as assert } from "node:assert";
import { extractEntryLinks, fetchJraPage, parseEntryPage, parseResultPage } from "../src/v1/jra.js";

function snippet(html: string, needle: string): string | null {
  const index = html.indexOf(needle);
  if (index < 0) return null;
  return html.slice(Math.max(0, index - 500), Math.min(html.length, index + 1800));
}

const entryUrl = "https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030520260801%2F15";
const entryPage = await fetchJraPage(entryUrl);
assert.equal(entryPage.status, 200);
assert.ok(entryPage.html.length > 10_000, "official current entry response was unexpectedly small");
assert.ok(/出馬表/.test(entryPage.html), "official current entry page was not returned");
const discoveredLinks = extractEntryLinks(entryPage.html, entryPage.url);

let entry;
try {
  entry = parseEntryPage(entryPage.html, entryPage.url);
} catch (error) {
  console.error(JSON.stringify({
    stage: "current-entry-parse",
    error: error instanceof Error ? error.message : String(error),
    finalUrl: entryPage.url,
    htmlLength: entryPage.html.length,
    counts: {
      table: [...entryPage.html.matchAll(/<table\b/gi)].length,
      tr: [...entryPage.html.matchAll(/<tr\b/gi)].length,
      li: [...entryPage.html.matchAll(/<li\b/gi)].length,
      div: [...entryPage.html.matchAll(/<div\b/gi)].length,
      discoveredEntryLinks: discoveredLinks.length
    },
    snippets: {
      date: snippet(entryPage.html, "2026年8月1日"),
      raceHeader: snippet(entryPage.html, "5レース"),
      horseHeader: snippet(entryPage.html, "馬名"),
      odds: snippet(entryPage.html, "番人気")
    }
  }, null, 2));
  throw error;
}

assert.equal(entry.race.raceDate, "2026-08-01");
assert.equal(entry.race.venue, "札幌");
assert.equal(entry.race.raceNo, 5);
assert.ok(entry.runners.length >= 5, `too few runners parsed: ${entry.runners.length}`);
assert.ok(entry.runners.filter((runner) => runner.winOdds !== null).length >= 3, "current win odds were not parsed");
assert.ok(entry.race.resultUrl.includes("accessS.html"), "official current result URL was not found");

const resultPage = await fetchJraPage(entry.race.resultUrl);
assert.equal(resultPage.status, 200);
assert.ok(resultPage.html.length > 10_000, "official current result response was unexpectedly small");
assert.ok(/レース結果/.test(resultPage.html), "official current result page was not returned");

let result;
try {
  result = parseResultPage(resultPage.html, resultPage.url);
} catch (error) {
  console.error(JSON.stringify({
    stage: "current-result-parse",
    error: error instanceof Error ? error.message : String(error),
    finalUrl: resultPage.url,
    htmlLength: resultPage.html.length,
    counts: {
      table: [...resultPage.html.matchAll(/<table\b/gi)].length,
      tr: [...resultPage.html.matchAll(/<tr\b/gi)].length,
      li: [...resultPage.html.matchAll(/<li\b/gi)].length,
      div: [...resultPage.html.matchAll(/<div\b/gi)].length
    },
    snippets: {
      result: snippet(resultPage.html, "着順"),
      payout: snippet(resultPage.html, "払戻金"),
      win: snippet(resultPage.html, "単勝")
    }
  }, null, 2));
  throw error;
}

assert.equal(result.race.raceId, entry.race.raceId);
assert.ok(result.results.length >= 5, `too few results parsed: ${result.results.length}`);
assert.ok(result.results.some((runner) => runner.finishPosition === 1), "winner was not parsed");
assert.ok(result.payouts.some((payout) => payout.betType === "単勝" && payout.payoutYen > 0), "win payout was not parsed");

console.log(JSON.stringify({
  ok: true,
  raceId: entry.race.raceId,
  runners: entry.runners.length,
  results: result.results.length,
  payouts: result.payouts.length,
  discoveredEntryLinks: discoveredLinks.length,
  resultUrl: entry.race.resultUrl
}, null, 2));
