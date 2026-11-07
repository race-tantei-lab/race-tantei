import { strict as assert } from "node:assert";
import { shadowCompletedPortfolioResearch } from "../src/v1/completed-ticket-shadow-research.js";
import { chooseCompletedTwoTickets, type OfficialOddsRow } from "../src/v1/completed-ticket-runtime.js";

const horseNos = [1, 2, 3, 4];
const weights = [0.4, 0.3, 0.2, 0.1];
const rows: OfficialOddsRow[] = [
  {betType:"単勝", combination:"1", oddsMin:2, oddsMax:2},
  {betType:"単勝", combination:"2", oddsMin:3.5, oddsMax:3.5},
  {betType:"ワイド", combination:"1-2", oddsMin:2.1, oddsMax:2.7},
  {betType:"ワイド", combination:"1-3", oddsMin:4, oddsMax:5},
  {betType:"馬連", combination:"1-2", oddsMin:7, oddsMax:7},
  {betType:"馬単", combination:"1-2", oddsMin:12, oddsMax:12},
  {betType:"3連複", combination:"1-2-3", oddsMin:15, oddsMax:15},
  {betType:"3連単", combination:"1-2-3", oddsMin:38, oddsMax:38},
];
const copy = JSON.stringify(rows);
const canonical = chooseCompletedTwoTickets(horseNos, weights, rows);
const after = shadowCompletedPortfolioResearch(horseNos, weights, rows);
assert.equal(after.length, 2);
assert.deepEqual(after.map(x=>x.policy),["market_implied_only","market_blend_30pct_model"]);
for (const p of after) {
  assert.equal(p.tickets.length,2);
  assert.equal(new Set(p.tickets.map(t=>t.betType)).size,2);
  assert.ok(p.tickets.every(t=>Number.isFinite(t.score)&&t.officialOdds>=1&&t.rawModelProbability>0&&t.blendedProbability>0));
  const allSixTypes = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];
  assert.deepEqual(p.candidatesByType.map(t=>t.betType), allSixTypes,
    "shadow must make all six real official JRA types available for 15-pair prospective study");
  assert.equal(new Set(p.candidatesByType.map(t=>t.betType)).size,6);
  assert.ok(p.candidatesByType.every(t =>
    Number.isFinite(t.score) && t.officialOdds >= 1 &&
    t.rawModelProbability > 0 && t.blendedProbability > 0));
  const pairs: string[] = [];
  for (let a=0; a<p.candidatesByType.length; a+=1) {
    for (let b=a+1; b<p.candidatesByType.length; b+=1) {
      const first = p.candidatesByType[a]!;
      const second = p.candidatesByType[b]!;
      assert.ok(first.betType !== second.betType);
      pairs.push(first.betType+"+"+second.betType);
    }
  }
  assert.equal(pairs.length,15);
  assert.equal(new Set(pairs).size,15);
  for (const chosen of p.tickets) {
    assert.deepEqual(p.candidatesByType.find(t=>t.betType===chosen.betType),chosen,
      "existing shadow choices must remain unchanged and copied from exactly six immutable candidates");
  }
}
const single = after[0]!.tickets.find(x=>x.betType==="単勝");
assert.ok(single);
assert.ok(Math.abs(single!.blendedProbability-1/single!.officialOdds)<1e-12);
const check = after[1]!.tickets[0]!;
assert.ok(Math.abs(check.blendedProbability-(0.3*check.rawModelProbability+0.7*check.marketImpliedProbability))<1e-12);
assert.equal(JSON.stringify(rows), copy, "shadow research must never mutate official JRA odds");
assert.deepEqual(chooseCompletedTwoTickets(horseNos,weights,rows),canonical,
  "shadow policies must not alter canonical production two-ticket selection");
assert.ok(JSON.stringify(after).length < 8000,
  "six-type candidate shadows must remain compact and protect D1 state storage budget");
let invalidWeightsRejected = false;
try { shadowCompletedPortfolioResearch(horseNos,[0.9,0.3,0.2,0.1],rows); }
catch (error) { invalidWeightsRejected = String(error).includes("SHADOW_WEIGHTS_INVALID"); }
assert.ok(invalidWeightsRejected, "invalid probability weights must be refused by shadow");
const mismatched = rows.map(x=>({...x}));
mismatched.push({betType:"ワイド",combination:"2-1",oddsMin:20,oddsMax:20});
const other=shadowCompletedPortfolioResearch(horseNos,weights,mismatched);
assert.deepEqual(other,after, "invalid unordered combination must not pollute shadow research");
console.log("COMPLETED_SHADOW_CALIBRATION_OK",JSON.stringify({
  policies:after.map(x=>({policy:x.policy,tickets:x.tickets.map(t=>t.betType+":"+t.combination)})),
  canonicalBets:canonical.map(x=>x.betType+":"+x.combination),
}));
