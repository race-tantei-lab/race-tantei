import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import {
  inferNov2026PayoutHurdleResearch, nov2026RawModelPredictions,
  type PayoutHurdleAsset
} from "../src/v1/nov2026-payout-hurdle-runtime.js";
import type { OfficialOddsRow,CompletedBetType } from "../src/v1/completed-ticket-runtime.js";

const model=JSON.parse(readFileSync("src/v1/nov2026-payout-hurdle-model.json","utf8")) as PayoutHurdleAsset;
const fixture=JSON.parse(readFileSync("tests/fixtures/nov2026-model-parity.json","utf8")) as {
  rows:{runner:number[];ticket:number[]}[];
  expected:Record<"rankerRaw"|"top3Probability"|"ticketHitProbability"|"conditionalPayoutMultiple",number[]>;
};
assert.equal(model.notProductionValidated,true);
assert.equal(model.horseFeatureCount,56);
assert.equal(model.ticketFeatureCount,40);
assert.deepEqual([model.ranker.length,model.top3.trees.length,model.hit.trees.length,model.paid.trees.length],[190,120,110,115]);
for(let i=0;i<fixture.rows.length;i++){
  const row=fixture.rows[i]!;
  const out=nov2026RawModelPredictions(model,row.runner,row.ticket);
  for(const key of ["rankerRaw","top3Probability","ticketHitProbability","conditionalPayoutMultiple"] as const){
    const expected=fixture.expected[key][i]!;
    assert.ok(Math.abs(out[key]-expected)<=1e-9*Math.max(1,Math.abs(expected)),
      `Frozen Python-vs-TS parity mismatch ${key}, i=${i}, got=${out[key]}, expected=${expected}`);
  }
}
const types:CompletedBetType[]=["単勝","ワイド","馬連","馬単","3連複","3連単"];
const mock:PayoutHurdleAsset={
  name:"unit-research-model",trainThrough:"2025-12-28",evalPeriod:"2026-01-01..2026-08-09",
  notProductionValidated:true,horseFeatureCount:56,ticketFeatureCount:40,
  ranker:[[[1,0]]],top3:{baseline:0,trees:[]},
  hit:{baseline:0,trees:[]},paid:{baseline:1,trees:[]},
  priors:Object.fromEntries(types.map(t=>[t,{hitPrior:0.3,wonReturnPrior:4}]))
};
const rows:OfficialOddsRow[]=[];
for(let a=1;a<=4;a++){
  rows.push({betType:"単勝",combination:String(a),oddsMin:2,oddsMax:2});
  for(let b=a+1;b<=4;b++){
    for(const betType of ["馬連","ワイド"] as CompletedBetType[])
      rows.push({betType,combination:`${a}-${b}`,oddsMin:4,oddsMax:4});
    for(const x of [[a,b],[b,a]])
      rows.push({betType:"馬単",combination:x.join("-"),oddsMin:7,oddsMax:7});
    for(let c=b+1;c<=4;c++){
      rows.push({betType:"3連複",combination:`${a}-${b}-${c}`,oddsMin:9,oddsMax:9});
      for(const x of [[a,b,c],[a,c,b],[b,a,c],[b,c,a],[c,a,b],[c,b,a]])
        rows.push({betType:"3連単",combination:x.join("-"),oddsMin:20,oddsMax:20});
    }
  }
}
const input=Array.from({length:4},()=>Array(56).fill(0));
const bet=inferNov2026PayoutHurdleResearch(mock,[1,2,3,4],input,5,rows);
assert.ok(bet,"valid full six-market pre-result synthetic test should produce candidates");
assert.equal(bet!.researchOnly,true);
assert.equal(bet!.notValidatedForwardInNovember2026,true);
assert.equal(bet!.tickets.length,2);
assert.equal(new Set(bet!.tickets.map(t=>t.betType)).size,2);
assert.equal(bet!.tickets.reduce((s,t)=>s+t.stakeYen,0),2000);
assert.ok(bet!.tickets.every(t=>t.officialOdds>=1&&t.learnedHitProbability>0));
assert.equal(inferNov2026PayoutHurdleResearch(mock,[1,2,3,4],input,5,
  rows.filter(row=>row.betType!=="3連単")),null,"missing JRA market must fail closed");
assert.equal(inferNov2026PayoutHurdleResearch(mock,[1,1,3,4],input,5,rows),null);
console.log("NOV2026_EXACT_MODEL_TREES_PYTHON_PARITY_AND_SIX_MARKET_SHADOW_OK");
