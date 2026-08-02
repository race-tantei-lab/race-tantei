import { strict as assert } from "node:assert";
import { discoverRaceUrls, extractEntryLinks, fetchJraPage, parseEntryPage, parseResultPage } from "../src/v1/jra.js";
import { stripHtml } from "../src/v1/utils.js";

function snippet(html: string, needle: string): string | null {
  const index = html.indexOf(needle);
  if (index < 0) return null;
  return html.slice(Math.max(0, index - 500), Math.min(html.length, index + 1800));
}
function cnameOf(url: string): string { return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? ""); }
function resultRunnerRows(html: string): string[][] {
  const values: string[][] = [];
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...(match[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)]
      .map((cell) => stripHtml(cell[1] ?? "").replace(/\s+/g, " ").trim());
    if (cells.some((cell) => /(?:\d+:\d{2}\.\d|除外|中止|失格|取消)/.test(cell))) values.push(cells);
  }
  return values;
}

const entryUrl = "https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030520260801%2F15";
const entryPage = await fetchJraPage(entryUrl);
assert.equal(entryPage.status, 200);
assert.ok(entryPage.html.length > 10_000, "official current entry response was unexpectedly small");
assert.ok(/出馬表/.test(entryPage.html), "official current entry page was not returned");
const directLinks = extractEntryLinks(entryPage.html, entryPage.url);

let entry;
try { entry = parseEntryPage(entryPage.html, entryPage.url); }
catch (error) {
  console.error(JSON.stringify({ stage: "current-entry-parse", error: error instanceof Error ? error.message : String(error), finalUrl: entryPage.url, htmlLength: entryPage.html.length, counts: { table: [...entryPage.html.matchAll(/<table\b/gi)].length, tr: [...entryPage.html.matchAll(/<tr\b/gi)].length, directLinks: directLinks.length }, snippets: { date: snippet(entryPage.html, "2026年8月1日"), raceHeader: snippet(entryPage.html, "5レース"), odds: snippet(entryPage.html, "番人気") } }, null, 2));
  throw error;
}
assert.equal(entry.race.raceDate, "2026-08-01");
assert.equal(entry.race.venue, "札幌");
assert.equal(entry.race.raceNo, 5);
assert.equal(entry.race.raceName, "メイクデビュー札幌");
assert.ok(entry.runners.length >= 5, `too few runners parsed: ${entry.runners.length}`);
assert.ok(entry.runners.filter((runner) => runner.winOdds !== null).length >= 3, "current win odds were not parsed");
assert.ok(entry.race.resultUrl.includes("accessS.html"), "official current result URL was not found");

const resultPage = await fetchJraPage(entry.race.resultUrl);
assert.equal(resultPage.status, 200);
assert.ok(resultPage.html.length > 10_000, "official current result response was unexpectedly small");
assert.ok(/レース結果/.test(resultPage.html), "official current result page was not returned");
let result;
try { result = parseResultPage(resultPage.html, resultPage.url); }
catch (error) {
  console.error(JSON.stringify({ stage: "current-result-parse", error: error instanceof Error ? error.message : String(error), finalUrl: resultPage.url, htmlLength: resultPage.html.length, snippets: { result: snippet(resultPage.html, "着順"), payout: snippet(resultPage.html, "払戻金") } }, null, 2));
  throw error;
}
assert.equal(result.race.raceId, entry.race.raceId);
assert.ok(result.results.length >= 5, `too few results parsed: ${result.results.length}`);
assert.ok(result.results.some((runner) => runner.finishPosition === 1), "winner was not parsed");
assert.ok(result.payouts.some((payout) => payout.betType === "単勝" && payout.payoutYen > 0), "win payout was not parsed");

const historicalResultUrl = "https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde0104202601010820260502%2F34";
const historicalResultPage = await fetchJraPage(historicalResultUrl);
const historicalResult = parseResultPage(historicalResultPage.html, historicalResultPage.url);
const historicalRows = resultRunnerRows(historicalResultPage.html);
assert.equal(historicalResult.race.raceDate, "2026-05-02");
assert.equal(historicalResult.race.venue, "新潟");
assert.equal(historicalResult.race.raceNo, 8);
assert.ok(historicalRows.length >= 5, "historical result runner rows were not found");
assert.ok(historicalResult.results.some((runner) => runner.finishPosition === 1), "historical winner was not parsed");
assert.ok(historicalResult.payouts.some((payout) => payout.betType === "3連単" && payout.payoutYen > 0), "historical trifecta payout was not parsed");

const allDiscovered = await discoverRaceUrls("https://sp.jra.jp/", [entryUrl]);
const currentDayLinks = allDiscovered.filter((url) => cnameOf(url).includes("20260801/"));
const nextDayLinks = allDiscovered.filter((url) => cnameOf(url).includes("20260802/"));
assert.ok(currentDayLinks.length >= 36, `current-day discovery incomplete: ${currentDayLinks.length}`);
assert.ok(nextDayLinks.length >= 36, `next-day discovery incomplete: ${nextDayLinks.length}`);

console.log(JSON.stringify({
  ok: true,
  raceId: entry.race.raceId,
  historicalRaceId: historicalResult.race.raceId,
  historicalResultFinalUrl: historicalResultPage.url,
  historicalRunnerRows: historicalRows.slice(0, 4),
  runners: entry.runners.length,
  results: result.results.length,
  historicalResults: historicalResult.results.length,
  payouts: result.payouts.length,
  historicalPayouts: historicalResult.payouts.length,
  directEntryLinks: directLinks.length,
  allDiscovered: allDiscovered.length,
  currentDayLinks: currentDayLinks.length,
  nextDayLinks: nextDayLinks.length,
  resultUrl: entry.race.resultUrl
}, null, 2));
