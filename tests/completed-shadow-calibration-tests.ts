import { strict as assert } from "node:assert";
import { shadowCompletedPortfolioResearch } from "../src/v1/completed-ticket-shadow-research.js";
import { roiFirstOfficialShadow } from "../src/v1/roi-first-shadow-research.js";
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
// Missing one JRA official market cannot be fabricated. Keep prior
// research tickets unchanged and let the all-15-pair auditor reject the
// incomplete six-type cohort; do not disable real finalization.
const incompleteOdds=rows.filter(x=>x.betType!=="3連単");
const beforeIncomplete=shadowCompletedPortfolioResearch(horseNos,weights,incompleteOdds);
assert.equal(beforeIncomplete.length,2);
assert.ok(beforeIncomplete.every(p=>p.tickets.length===2));
assert.ok(beforeIncomplete.every(p=>p.candidatesByType.length===5));
assert.ok(beforeIncomplete.every(p=>!p.candidatesByType.some(x=>x.betType==="3連単")));
assert.deepEqual(chooseCompletedTwoTickets(horseNos,weights,rows),canonical,
  "missing official shadow market must not change original public ticket selection");
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
// ROI-first research uses *only* the real official market snapshot and the
// same pre-result probabilities; it must never change original public tickets.
const roi = roiFirstOfficialShadow(horseNos,weights,rows,
  "2026-11-08T09:15:00+09:00","2026-11-08T09:30:00+09:00");
assert.ok(roi,"six present official markets must yield a legal candidate");
assert.equal(roi!.policy,"roi_first_jra_official_model_ev_v1");
assert.equal(roi!.researchOnly,true);
assert.equal(roi!.notActualJraRoi,true);
assert.equal(roi!.minimumModeledHitPct,20);
assert.ok(roi!.modeledTwoTicketHitPct>=20);
assert.equal(roi!.stakeYen,2000);
assert.equal(roi!.tickets.length,2);
assert.ok(roi!.tickets[0].betType!==roi!.tickets[1].betType);
assert.equal(roi!.tickets[0].stakeYen+roi!.tickets[1].stakeYen,2000);
assert.ok(roi!.tickets.every(t=>t.stakeYen>=100&&t.stakeYen%100===0&&t.conservativeOfficialOdds>=1));
assert.ok(roi!.modeledExpectedRoiPct>0);
assert.equal(roiFirstOfficialShadow(horseNos,weights,rows.filter(x=>x.betType!=="3連単"),
  "2026-11-08T09:15:00+09:00","2026-11-08T09:30:00+09:00"),null,
  "no fake official odds for missing JRA market");
assert.equal(roiFirstOfficialShadow(horseNos,weights,rows,
  "2026-11-08T09:16:00+09:00","2026-11-08T09:30:00+09:00"),null,
  "late pre-T15 generation is rejected");
assert.equal(roiFirstOfficialShadow(horseNos,weights,rows,
  "2026-11-08T09:15:00","2026-11-08T09:30:00+09:00"),null,
  "ambiguous timezone is rejected");
assert.equal(JSON.stringify(rows), copy);
assert.deepEqual(chooseCompletedTwoTickets(horseNos,weights,rows),canonical,
  "ROI shadow must not affect canonical public purchases");
console.log("COMPLETED_SHADOW_CALIBRATION_OK",JSON.stringify({
  policies:after.map(x=>({policy:x.policy,tickets:x.tickets.map(t=>t.betType+":"+t.combination)})),
  canonicalBets:canonical.map(x=>x.betType+":"+x.combination),
}));
