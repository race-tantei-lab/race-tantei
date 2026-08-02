import { strict as assert } from "node:assert";
import { historyDateFromPath, renderRaceArchiveIndex } from "../src/v1/race-archive.js";

const html = renderRaceArchiveIndex([
  {
    raceDate: "2026-08-02",
    totalRaces: 36,
    venueCount: 3,
    venues: ["中京", "新潟", "札幌"],
    processedRaces: 36,
    selectedRaces: 15,
    hitRaces: 9
  },
  {
    raceDate: "2026-08-01",
    totalRaces: 36,
    venueCount: 3,
    venues: ["中京", "新潟", "札幌"],
    processedRaces: 36,
    selectedRaces: 15,
    hitRaces: 8
  },
  {
    raceDate: "2026-07-26",
    totalRaces: 36,
    venueCount: 3,
    venues: ["札幌", "新潟", "中京"],
    processedRaces: 24,
    selectedRaces: 10,
    hitRaces: 5
  }
]);

assert.ok(html.includes("全レース"));
assert.ok(html.includes("2026年8月"));
assert.ok(html.includes("2026年7月"));
assert.ok(html.includes('/history/2026-08-02'));
assert.ok(html.includes('/history/2026-08-01'));
assert.ok(html.includes('/history/2026-07-26'));
assert.equal((html.match(/class="archive-date"/g) ?? []).length, 3, "全開催日へのリンクを省略しない");
assert.equal(historyDateFromPath("/history/2026-08-02"), "2026-08-02");
assert.equal(historyDateFromPath("/history/not-a-date"), null);
assert.equal(historyDateFromPath("/races/2026-08-02"), null);

console.log("race-tantei archive navigation tests passed");
