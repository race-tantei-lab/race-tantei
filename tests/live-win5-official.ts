import { strict as assert } from "node:assert";
import { decodeJraHtml } from "../src/v1/jra-official-odds.js";
import { WIN5_PAGE_URL } from "../src/v1/completed-win5.js";
import { parseWin5TargetIdentitiesFromHtml } from "../src/v1/win5-official-target-repair.js";

function jstNow(now = new Date()): { date: string; hour: number } {
  const shifted = new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString();
  return { date: shifted.slice(0, 10), hour: Number(shifted.slice(11, 13)) };
}

const now = jstNow();
const date = now.date;
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
const targets = parseWin5TargetIdentitiesFromHtml(html, date);

// The current JRA target-list table publishes venue/race identities, but does
// not publish each race start time in the same row. Production hydrates those
// exact five identities from the already-synced official race table in D1.
if (targets.length === 0 && now.hour >= 18) {
  console.log(JSON.stringify({ status: "LIVE_WIN5_OFFICIAL_AFTER_HOURS", date, jstHour: now.hour, targetCount: 0 }));
} else {
  assert.equal(targets.length, 5, `JRA WIN5 target identity parse failed for ${date}: ${targets.length}`);
  assert.deepEqual(targets.map((row) => row.leg), [1, 2, 3, 4, 5]);
  assert.ok(targets.every((row) => row.raceDate === date && row.raceNo >= 1 && row.raceNo <= 12 && row.venue.length > 0));
  assert.equal(new Set(targets.map((row) => `${row.venue}:${row.raceNo}`)).size, 5);
  console.log(JSON.stringify({ status: "LIVE_WIN5_OFFICIAL_OK", date, targets: targets.map((row) => ({ leg: row.leg, venue: row.venue, raceNo: row.raceNo })) }));
}
