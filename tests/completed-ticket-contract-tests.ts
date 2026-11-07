import { strict as assert } from "node:assert";
import {
  COMPLETED_ODDS_SCORE_POWER,
  chooseCompletedTwoTickets,
  type OfficialOddsRow,
} from "../src/v1/completed-ticket-runtime.js";

// Freeze the production contract, not the retrospectively observed ROI:
// 1) per bet type keep ONLY raw probability × JRA odds top five;
// 2) rank those five by ln(p) + 0.4 ln(odds) + ln(recency);
// 3) choose exactly two distinct bet types.
assert.equal(COMPLETED_ODDS_SCORE_POWER, 0.4);

const horseNos = [1, 2, 3, 4, 5, 6];
const weights = [0.45, 0.20, 0.12, 0.09, 0.08, 0.06];
const singles = [1.01, 3, 5, 6, 7, 9].map((odds, index) => ({
  betType: "単勝" as const,
  combination: String(index + 1),
  oddsMin: odds,
  oddsMax: odds,
}));
const others: OfficialOddsRow[] = [
  {betType:"ワイド",combination:"5-6",oddsMin:1.1,oddsMax:1.1},
  {betType:"馬連",combination:"5-6",oddsMin:1.1,oddsMax:1.1},
  {betType:"馬単",combination:"5-6",oddsMin:1.1,oddsMax:1.1},
  {betType:"3連複",combination:"4-5-6",oddsMin:1.1,oddsMax:1.1},
  {betType:"3連単",combination:"4-5-6",oddsMin:1.1,oddsMax:1.1},
];
const rows = [...singles, ...others];
const before = JSON.stringify(rows);
const chosen = chooseCompletedTwoTickets(horseNos, weights, rows);
assert.equal(chosen.length, 2);
assert.equal(new Set(chosen.map((t) => t.betType)).size, 2);

const win = chosen.find((t) => t.betType === "単勝");
assert.ok(win, "strongest filtered ticket should still be a win bet");
assert.equal(win.combination, "2",
  "horse 1 has the highest raw score but is sixth by raw EV and MUST be excluded");
assert.ok(Math.abs(win.score - (Math.log(0.20) + 0.4 * Math.log(3))) < 1e-12);
assert.ok(Math.abs(win.valueProduct - 0.6) < 1e-12);

// Even a large recency modifier cannot smuggle a sixth raw-EV ticket into the candidate set.
const withRecency = chooseCompletedTwoTickets(horseNos, weights, rows,
  (type, odd) => type === "単勝" && odd === 1.01 ? 4 : 1);
assert.equal(withRecency.find((t) => t.betType === "単勝")?.combination, "2");
assert.equal(JSON.stringify(rows), before, "official odds must not be mutated");
console.log("FROZEN_MODEL_TICKET_CONTRACT_OK", JSON.stringify({chosen:chosen.map(t => t.betType+":"+t.combination)}));
