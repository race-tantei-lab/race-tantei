import { strict as assert } from "node:assert";
import {
  candidateJraEntryUrls,
  fetchFastJraOfficialOddsForRace,
  jraOddsUrlForEntry,
} from "../src/v1/jra-official-odds-fetch.js";
import { parseFastJraOfficialOddsRows } from "../src/v1/jra-official-odds-fast.js";

const spSource = "https://sp.jra.jp/JRADB/accessD.html?CNAME=sample";
const candidates = candidateJraEntryUrls(spSource);
assert.equal(candidates[0], spSource);
assert.ok(candidates.includes("https://www.jra.go.jp/JRADB/accessD.html?CNAME=sample"));
assert.ok(candidates.includes("https://jra.jp/JRADB/accessD.html?CNAME=sample"));
assert.equal(new Set(candidates).size, candidates.length);
assert.equal(jraOddsUrlForEntry(spSource), "https://sp.jra.jp/JRADB/accessO.html");
assert.equal(jraOddsUrlForEntry("https://www.jra.go.jp/JRADB/accessD.html?CNAME=x"), "https://www.jra.go.jp/JRADB/accessO.html");

// Real JRA-shaped win rows: horse number, odds and other decimal cells coexist.
// Only td.num and td.odds_tan are authoritative for the win market.
const winRegressionHtml = `<!doctype html><table class="basic narrow-xy tanpuku"><tbody>
  <tr><td class="num">12</td><td class="horse">メイショウナナシロ</td><td class="odds_tan"><strong>1.9</strong></td><td class="odds_fuku"><span class="min">1.1</span><span class="max">1.1</span></td><td class="weight">57.0</td></tr>
  <tr><td class="num">13</td><td class="horse">アビル</td><td class="odds_tan">4.4</td><td class="weight">57.0</td></tr>
  <tr><td class="num">11</td><td class="horse">ラミエルノムスコ</td><td class="odds_tan">9.1</td><td class="weight">57.0</td></tr>
</tbody></table>`;
const winRegressionRows = parseFastJraOfficialOddsRows(winRegressionHtml, "単勝");
assert.deepEqual(winRegressionRows, [
  { betType: "単勝", combination: "11", oddsMin: 9.1, oddsMax: 9.1 },
  { betType: "単勝", combination: "12", oddsMin: 1.9, oddsMax: 1.9 },
  { betType: "単勝", combination: "13", oddsMin: 4.4, oddsMax: 4.4 },
]);
assert.equal(winRegressionRows.find((row) => row.combination === "12")?.oddsMin, 1.9);

// 1.0 is a legitimate tote value and must not be rejected just because the old
// safety gate used >1 rather than >=1.
const winOnePointZero = `<table class="tanpuku"><tr><td class="num">1</td><td class="odds_tan">1.0</td></tr></table>`;
assert.equal(parseFastJraOfficialOddsRows(winOnePointZero, "単勝")[0]?.oddsMin, 1.0);

const umarenHtml = `<table class="basic narrow-xy umaren"><caption>1</caption><tbody><tr><th scope="row">12</th><td>19.5</td></tr></tbody></table>`;
assert.deepEqual(parseFastJraOfficialOddsRows(umarenHtml, "馬連"), [
  { betType: "馬連", combination: "1-12", oddsMin: 19.5, oddsMax: 19.5 },
]);

const wideRegressionHtml = `<table class="basic narrow-xy wide"><caption>11</caption><tbody>
  <tr><th scope="row">12</th><td class="odds"><span class="inner"><span class="min">2.3</span><span class="cap">-</span><span class="max">5.3</span></span></td></tr>
</tbody></table>`;
assert.deepEqual(parseFastJraOfficialOddsRows(wideRegressionHtml, "ワイド"), [
  { betType: "ワイド", combination: "11-12", oddsMin: 2.3, oddsMax: 5.3 },
]);

const umatanHtml = `<table class="basic narrow-xy umatan"><caption>12</caption><tbody><tr><th scope="row">1</th><td>7.4</td></tr></tbody></table>`;
assert.deepEqual(parseFastJraOfficialOddsRows(umatanHtml, "馬単"), [
  { betType: "馬単", combination: "12-1", oddsMin: 7.4, oddsMax: 7.4 },
]);

const fuku3Html = `<table class="basic narrow-xy fuku3"><caption>1-12</caption><tbody><tr><th scope="row">13</th><td>25.4</td></tr></tbody></table>`;
assert.deepEqual(parseFastJraOfficialOddsRows(fuku3Html, "3連複"), [
  { betType: "3連複", combination: "1-12-13", oddsMin: 25.4, oddsMax: 25.4 },
]);

const tan3Html = `<li>
  <div class="p_line"><div class="inner"><div class="cap"><span>1着</span></div><div class="num">12</div></div></div>
  <div class="p_line"><div class="inner"><div class="cap"><span>2着</span></div><div class="num">1</div></div></div>
  <table class="basic narrow-xy tan3"><caption><span>3着</span></caption><tbody><tr><th scope="row">13</th><td>42.6</td></tr></tbody></table>
</li>`;
assert.deepEqual(parseFastJraOfficialOddsRows(tan3Html, "3連単"), [
  { betType: "3連単", combination: "12-1-13", oddsMin: 42.6, oddsMax: 42.6 },
]);

// A generic table containing plausible numbers is intentionally not parsed. The
// parser must recognize JRA's semantic table/cell roles, not merely numeric text.
const ambiguousHtml = `<table><tr><td>12</td><td>1.9</td><td>57.0</td></tr></table>`;
assert.deepEqual(parseFastJraOfficialOddsRows(ambiguousHtml, "単勝"), []);
assert.deepEqual(parseFastJraOfficialOddsRows(ambiguousHtml, "馬連"), []);

const originalFetch = globalThis.fetch;
const target = { raceDate: "2026-08-09", venue: "中京", raceNo: 11 } as const;
const suffix = "S301202601061120260809Z/EA";
const cnames = {
  "単勝": `pw151ou${suffix}`,
  "馬連": `pw154ou${suffix}`,
  "ワイド": `pw155ou${suffix}`,
  "馬単": `pw156ou${suffix}`,
  "3連複": `pw157ou${suffix}`,
  "3連単": `pw158ou${suffix}`,
} as const;

const entryHtml = `<!doctype html><html><body>${Object.values(cnames).map((cname) =>
  `<a href="#" onclick="doAction('/JRADB/accessO.html','${cname}')">odds</a>`
).join("")}</body></html>`;

function pageFor(cname: string): string {
  const heading = `<h1>2026年8月9日 3回中京6日</h1>`;
  if (cname.startsWith("pw151ou")) return `<!doctype html><html><body>${heading}<table class="basic narrow-xy tanpuku"><tbody>
    <tr><td class="num">1</td><td class="horse">A</td><td class="odds_tan">2.5</td></tr>
    <tr><td class="num">2</td><td class="horse">B</td><td class="odds_tan">3.5</td></tr>
  </tbody></table>${Object.values(cnames).map((link) => `<a onclick="doAction('/JRADB/accessO.html','${link}')">x</a>`).join("")}</body></html>`;
  if (cname.startsWith("pw154ou")) return `<!doctype html><html><body>${heading}<table class="basic narrow-xy umaren"><caption>1</caption><tr><th scope="row">2</th><td>6.4</td></tr></table></body></html>`;
  if (cname.startsWith("pw155ou")) return `<!doctype html><html><body>${heading}<table class="basic narrow-xy wide"><caption>1</caption><tr><th scope="row">2</th><td class="odds"><span class="min">2.3</span>-<span class="max">5.3</span></td></tr></table></body></html>`;
  if (cname.startsWith("pw156ou")) return `<!doctype html><html><body>${heading}<table class="basic narrow-xy umatan"><caption>1</caption><tr><th scope="row">2</th><td>7.4</td></tr></table></body></html>`;
  if (cname.startsWith("pw157ou")) return `<!doctype html><html><body>${heading}<table class="basic narrow-xy fuku3"><caption>1-2</caption><tr><th scope="row">3</th><td>12.8</td></tr></table></body></html>`;
  return `<!doctype html><html><body>${heading}<li><div class="p_line"><span>1着</span><div class="num">1</div></div><div class="p_line"><span>2着</span><div class="num">2</div></div><table class="basic narrow-xy tan3"><tr><th scope="row">3</th><td>15.2</td></tr></table></li></body></html>`;
}

let firstWinPost = true;
globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(input);
  if (url.includes("/JRADB/accessO.html")) {
    const body = String(init?.body ?? "");
    const cname = new URLSearchParams(body).get("cname") ?? "";
    if (cname === cnames["単勝"] && firstWinPost) {
      firstWinPost = false;
      return new Response("not found", { status: 404 });
    }
    if (Object.values(cnames).includes(cname as never)) {
      return new Response(pageFor(cname), { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
    }
    return new Response("not found", { status: 404 });
  }
  if (url.includes("entry.test")) return new Response(entryHtml, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
  return new Response("not found", { status: 404 });
};

try {
  const result = await fetchFastJraOfficialOddsForRace("https://entry.test/race", target);
  assert.equal(result.source, "jra-crawl-official");
  assert.ok(result.fallbackReason?.includes("JRA_ODDS_FAST_ALL_HOSTS_FAILED"));
  assert.equal(result.pages.length, 6);
  assert.deepEqual(new Set(result.pages.map((page) => page.betType)), new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]));
  assert.equal(result.rows.length, 7);
  assert.ok(result.rows.every((row) => row.oddsMin >= 1 && row.oddsMax >= row.oddsMin));
  assert.deepEqual(result.attemptedHosts, ["entry.test", "sp.jra.jp", "www.jra.go.jp", "jra.jp"]);
  console.log("JRA_OFFICIAL_ODDS_FETCH_OK", JSON.stringify({ source: result.source, fallbackReason: result.fallbackReason, attemptedHosts: result.attemptedHosts }));
} finally {
  globalThis.fetch = originalFetch;
}
