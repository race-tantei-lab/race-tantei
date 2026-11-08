import {strict as assert} from "node:assert";
import {highReturnResearchView} from "../src/v1/high-return-research-view.js";

const start="2026-11-08T01:00:00Z";
const observed="2026-11-08T00:30:00Z";
const base={
  oddsFetchedAt:observed,
  roiFirstResearch:{
    policy:"roi_first_jra_official_model_ev_v1",researchOnly:true,
    notActualJraRoi:true,minimumModeledHitPct:20,
    modeledTwoTicketHitPct:31.2,modeledExpectedRoiPct:112.4,
    stakeYen:2000,oddsFetchedAt:observed,startTimeUtc:start,
    tickets:[
      {betType:"馬単",combination:"1-2",stakeYen:1900,
       conservativeOfficialOdds:6,modelProbability:.15,expectedReturnPerYen:.9},
      {betType:"単勝",combination:"1",stakeYen:100,
       conservativeOfficialOdds:2,modelProbability:.4,expectedReturnPerYen:.8}
    ]
  }
};
const show=highReturnResearchView(JSON.stringify(base),start);
assert.ok(show.includes("高配当シミュレーション"));
assert.ok(show.includes("11,400円"));
assert.ok(show.includes("570%"));
assert.ok(show.includes("理論期待回収率"));
assert.ok(show.includes("実現見込みや期待回収率500%を示すものではありません"));
assert.ok(!show.includes("実際に購入"));
const without=(changes:Record<string,unknown>)=>highReturnResearchView(JSON.stringify({
  ...base,roiFirstResearch:{...base.roiFirstResearch,...changes}
}),start);
assert.ok(!without({researchOnly:false}).includes("11,400円"));
assert.ok(!without({oddsFetchedAt:"2026-11-08T00:48:00Z"}).includes("11,400円"));
assert.ok(!without({tickets:[base.roiFirstResearch.tickets[0],base.roiFirstResearch.tickets[0]]}).includes("11,400円"));
assert.ok(!without({modeledTwoTicketHitPct:18}).includes("11,400円"));
assert.ok(!highReturnResearchView(null,start).includes("11,400円"));
assert.ok(!highReturnResearchView(JSON.stringify(base),"2026-11-08T00:40:00Z").includes("11,400円"));
console.log("HIGH_RETURN_SHADOW_READONLY_PROVENANCE_TESTS_OK");
