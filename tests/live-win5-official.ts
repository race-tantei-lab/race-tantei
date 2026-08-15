import { strict as assert } from "node:assert";
import { decodeJraHtml } from "../src/v1/jra-official-odds.js";
import { parseWin5TargetsFromHtml, WIN5_PAGE_URL } from "../src/v1/completed-win5.js";

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

const date = jstDate();
const response = await fetch(WIN5_PAGE_URL, {
  headers: {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Cache-Control": "no-cache",
    "Referer": "https://www.jra.go.jp/",
  },
  redirect: "follow",
});
assert.equal(response.ok, true, `JRA WIN5 page HTTP ${response.status}`);
const bytes = await response.arrayBuffer();
const html = decodeJraHtml(bytes, response.headers.get("content-type"));
const targets = parseWin5TargetsFromHtml(html, date);
assert.equal(targets.length, 5, `JRA WIN5 target parse failed for ${date}: ${targets.length}`);
assert.deepEqual(targets.map((row) => row.leg), [1, 2, 3, 4, 5]);
assert.ok(targets.every((row) => row.raceDate === date && row.raceNo >= 1 && row.raceNo <= 12 && Number.isFinite(Date.parse(row.startTimeUtc))));
console.log(JSON.stringify({ status: "LIVE_WIN5_OFFICIAL_OK", date, targets: targets.map((row) => ({ leg: row.leg, venue: row.venue, raceNo: row.raceNo, startTimeJst: row.startTimeJst })) }));
