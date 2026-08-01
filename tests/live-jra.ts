import { strict as assert } from "node:assert";
import {
  fetchJraPage,
  pageLooksLikeEntry,
  pageLooksLikeResult,
  parseEntryPage,
  parseResultPage
} from "../src/v1/jra.js";

const entryUrl = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde1001202601011220260725%2FE1";

const entryPage = await fetchJraPage(entryUrl);
assert.equal(pageLooksLikeEntry(entryPage.html), true, "official JRA entry signature was not detected");
const entry = parseEntryPage(entryPage.html, entryPage.url);
assert.equal(entry.race.raceDate, "2026-07-25");
assert.equal(entry.race.venue, "札幌");
assert.equal(entry.race.raceNo, 12);
assert.ok(entry.runners.length >= 8, `too few runners parsed: ${entry.runners.length}`);
assert.ok(entry.runners.filter((runner) => runner.winOdds !== null).length >= 5, "win odds were not parsed");
assert.ok(entry.race.resultUrl.includes("accessS.html"), "official result URL was not found on entry page");

const resultPage = await fetchJraPage(entry.race.resultUrl);
assert.equal(pageLooksLikeResult(resultPage.html), true, "official JRA result signature was not detected");
const result = parseResultPage(resultPage.html, resultPage.url);
assert.equal(result.race.raceId, entry.race.raceId);
assert.ok(result.results.length >= 8, `too few results parsed: ${result.results.length}`);
assert.ok(result.results.some((runner) => runner.finishPosition === 1), "winner was not parsed");
assert.ok(result.payouts.some((payout) => payout.betType === "単勝" && payout.payoutYen > 0), "win payout was not parsed");

console.log(JSON.stringify({
  ok: true,
  raceId: entry.race.raceId,
  runners: entry.runners.length,
  results: result.results.length,
  payouts: result.payouts.length,
  resultUrl: entry.race.resultUrl
}, null, 2));
