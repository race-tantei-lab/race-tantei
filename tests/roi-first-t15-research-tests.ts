import { strict as assert } from "node:assert";
import { researchRoiFirstPair } from "../src/v1/roi-first-t15-research.js";
import { chooseCompletedTwoTickets, type OfficialOddsRow } from "../src/v1/completed-ticket-runtime.js";

const horseNos=[1,2,3,4];
const weights=[0.4,0.3,0.2,0.1];
const official: OfficialOddsRow[]=[
 {betType:"単勝",combination:"1",oddsMin:2.5,oddsMax:2.5},
 {betType:"単勝",combination:"2",oddsMin:3.4,oddsMax:3.4},
 {betType:"ワイド",combination:"1-2",oddsMin:2.2,oddsMax:2.8},
 {betType:"ワイド",combination:"1-3",oddsMin:3.8,oddsMax:4.8},
 {betType:"馬連",combination:"1-2",oddsMin:6,oddsMax:6},
 {betType:"馬単",combination:"1-2",oddsMin:13,oddsMax:13},
 {betType:"3連複",combination:"1-2-3",oddsMin:14,oddsMax:14},
 {betType:"3連単",combination:"1-2-3",oddsMin:32,oddsMax:32},
];
const before=JSON.stringify(official);
const canonical=chooseCompletedTwoTickets(horseNos,weights,official);
const chosen=researchRoiFirstPair(horseNos,weights,official,
  "2026-11-08T09:45:00+09:00","2026-11-08T10:00:00+09:00");
assert.ok(chosen);
assert.equal(chosen!.researchOnly,true);
assert.equal(chosen!.selectionBeforeT15,true);
assert.equal(chosen!.stakeYen,2000);
assert.equal(chosen!.ticket1.stakeYen+chosen!.ticket2.stakeYen,2000);
assert.notEqual(chosen!.ticket1.betType,chosen!.ticket2.betType);
assert.ok(chosen!.estimatedPairedHitPct>=20);
assert.ok(chosen!.estimatedRoiPct>0);
assert.equal(chosen!.estimationStatus,"UNCALIBRATED_PL_PROBABILITY_HYPOTHESIS_NOT_REAL_JRA_ROI");
assert.equal(JSON.stringify(official),before);
assert.deepEqual(chooseCompletedTwoTickets(horseNos,weights,official),canonical,
  "research EV scoring must never modify public model/canonical bets");
assert.equal(researchRoiFirstPair(horseNos,weights,official.filter(x=>x.betType!=="馬連"),
  "2026-11-08T09:44:00+09:00","2026-11-08T10:00:00+09:00"),null);
assert.throws(()=>researchRoiFirstPair(horseNos,weights,official,
  "2026-11-08T09:46:00+09:00","2026-11-08T10:00:00+09:00"),
  /UNVERIFIED_OFFICIAL_PRE_T15_ODDS_TIMESTAMP/);
assert.throws(()=>researchRoiFirstPair(horseNos,weights,official,"2026-11-08T09:45:00",
   "2026-11-08T10:00:00+09:00"),/UNVERIFIED_OFFICIAL_PRE_T15_ODDS_TIMESTAMP/);
assert.throws(()=>researchRoiFirstPair(horseNos,weights,[...official,official[0]!],
   "2026-11-08T09:45:00+09:00","2026-11-08T10:00:00+09:00"),/DUPLICATED_OFFICIAL_ODDS_ROW/);
assert.throws(()=>researchRoiFirstPair(horseNos,[0.5,0.3,0.3,0.1],official,
   "2026-11-08T09:45:00+09:00","2026-11-08T10:00:00+09:00"),/UNCALIBRATED_MODEL_PROBABILITIES_INVALID/);
console.log("RESEARCH_ROI_FIRST_T15_ALL_SIX_TYPES_PAIRED_OK",JSON.stringify({
  selected:chosen!.ticket1.betType+"+"+chosen!.ticket2.betType,
  estimatedHitPct:chosen!.estimatedPairedHitPct,
  estimatedRoiPct:chosen!.estimatedRoiPct,
  actuallyRealizedRoi:"NOT_EVALUATED",
}));
