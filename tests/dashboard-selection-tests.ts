import { strict as assert } from "node:assert";
import { keepRecentRaceDays, markSelectedCards } from "../src/v1/phase-d-dashboard.js";

function liveOpenCard(raceNo: number): string {
  return `<a class="race-card" data-race-category="buy" href="/races/live-${raceNo}">
    <div class="race-top"><b>${raceNo}R</b><span class="status open">買い目確定</span></div>
    <div class="course-mini">ライト</div>
  </a>`;
}

function liveFinishedCard(raceNo: number): string {
  return `<a class="race-card" data-race-category="finished" href="/races/live-finished-${raceNo}">
    <div class="race-top"><b>${raceNo}R</b><span class="status hit">的中</span></div>
    <div class="course-result won">ライト</div>
  </a>`;
}

function historicalCard(raceNo: number): string {
  return `<a class="race-card" data-race-category="finished" href="/races/history-${raceNo}">
    <div class="race-top"><b>${raceNo}R</b><span class="status miss">不的中</span></div>
    <div class="retro">フェーズC遡及検証</div>
    <div class="course-result lost">ライト</div>
  </a>`;
}

function venuePanel(venue: string, cards: string[]): string {
  return `<section class="venue-panel" data-venue-panel="${venue}" hidden>
    <div class="race-rail">${cards.join("")}</div>
    <div class="no-races" hidden>該当なし</div>
  </section>`;
}

function selectedCards(html: string): string[] {
  return html.match(/<a class="race-card"[^>]*data-race-selected="true"[^>]*>[\s\S]*?<\/a>/g) ?? [];
}

const livePreferred = markSelectedCards(venuePanel("札幌", [
  liveOpenCard(1),
  liveOpenCard(2),
  liveFinishedCard(3),
  liveFinishedCard(4),
  liveFinishedCard(5),
  historicalCard(6),
  historicalCard(7),
  historicalCard(8),
  historicalCard(9),
  historicalCard(10)
]));
const livePreferredSelected = selectedCards(livePreferred);
assert.equal(livePreferredSelected.length, 5, "本番と過去検証を合計して会場5Rを超えてはいけない");
assert.ok(livePreferredSelected.every((card) => !card.includes("遡及検証")), "本番公開分を過去検証より優先する");

const historyFillsShortage = markSelectedCards(venuePanel("新潟", [
  liveOpenCard(1),
  liveFinishedCard(2),
  historicalCard(3),
  historicalCard(4),
  historicalCard(5),
  historicalCard(6),
  historicalCard(7)
]));
const filledSelected = selectedCards(historyFillsShortage);
assert.equal(filledSelected.length, 5, "本番公開分が5R未満なら過去検証から補完する");
assert.equal(filledSelected.filter((card) => card.includes("遡及検証")).length, 3);
assert.equal((historyFillsShortage.match(/data-race-selected="true"/g) ?? []).length, 5);

const twoVenues = markSelectedCards([
  venuePanel("中京", [liveOpenCard(1), liveOpenCard(2), liveOpenCard(3), liveOpenCard(4), liveOpenCard(5), historicalCard(6)]),
  venuePanel("札幌", [historicalCard(1), historicalCard(2), historicalCard(3), historicalCard(4), historicalCard(5), historicalCard(6)])
].join(""));
assert.equal((twoVenues.match(/data-race-selected="true"/g) ?? []).length, 10, "会場ごとに独立して5Rを選ぶ");

function dayPanel(date: string): string {
  return `<section class="day-panel" data-day-panel="${date}" hidden><div>${date}</div></section>`;
}

const compactHome = keepRecentRaceDays(`
  <nav class="day-tabs">
    <button type="button" data-day-tab="2026-08-02">8月2日</button>
    <button type="button" data-day-tab="2026-08-01">8月1日</button>
    <button type="button" data-day-tab="2026-07-26">7月26日</button>
  </nav>
  ${dayPanel("2026-08-02")}
  ${dayPanel("2026-08-01")}
  ${dayPanel("2026-07-26")}
  <footer class="footer">footer</footer>
`);
assert.ok(compactHome.includes("直近の選出レース"));
assert.ok(compactHome.includes('data-day-tab="2026-08-02"'));
assert.ok(compactHome.includes('data-day-tab="2026-08-01"'));
assert.ok(!compactHome.includes('data-day-tab="2026-07-26"'));
assert.ok(!compactHome.includes('data-day-panel="2026-07-26"'));
assert.equal((compactHome.match(/data-day-panel=/g) ?? []).length, 2, "ホームの日別詳細は直近2日だけに絞る");

console.log("race-tantei dashboard selection tests passed");
