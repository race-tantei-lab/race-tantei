import { strict as assert } from "node:assert";
import { chooseNov2026PayoutHurdleLiveTickets, NOV2026_TICKET_MODEL_VERSION } from "../src/v1/nov2026-live-ticket-adapter.js";
import type { CompletedBetType,OfficialOddsRow } from "../src/v1/completed-ticket-runtime.js";

const runners=[1,2,3,4,5];
const vectors=runners.map(()=>Array.from({length:56},(_,i)=>i===0?5:i===1?0:0));
const types:CompletedBetType[]=["単勝","ワイド","馬連","馬単","3連複","3連単"];
const combinations=(nums:number[],k:number):number[][]=>{
  const out:number[][]=[];
  const rec=(start:number,a:number[]):void=>{
    if(a.length===k){out.push(a);return;}
    for(let i=start;i<nums.length;i++)rec(i+1,[...a,nums[i]!]);
  };rec(0,[]);return out;
};
const permutations=(nums:number[],k:number):number[][]=>{
  const out:number[][]=[];
  const rec=(a:number[]):void=>{
    if(a.length===k){out.push(a);return;}
    for(const n of nums)if(!a.includes(n))rec([...a,n]);
  };rec([]);return out;
};
const odds:OfficialOddsRow[]=[];
for(const type of types){
  const samples=type==="単勝"?runners.map(n=>[n]):type==="ワイド"||type==="馬連"?combinations(runners,2):
    type==="3連複"?combinations(runners,3):permutations(runners,type==="馬単"?2:3);
  for(const ns of samples)odds.push({betType:type,combination:ns.join("-"),oddsMin:10,oddsMax:10});
}
const start="2026-11-08T04:00:00Z",pre="2026-11-08T02:00:00Z",late="2026-11-08T03:50:00Z";
assert.equal(chooseNov2026PayoutHurdleLiveTickets(runners,vectors,5,odds,late,start),null,
  "research model must not supply official bets after T15");
assert.equal(chooseNov2026PayoutHurdleLiveTickets(runners,vectors,5,
  odds.filter(row=>row.betType!=="3連単"),pre,start),null,
  "missing official six-market quotes must fail closed");
assert.equal(chooseNov2026PayoutHurdleLiveTickets([1,1,3,4,5],vectors,5,odds,pre,start),null);
const choice=chooseNov2026PayoutHurdleLiveTickets(runners,vectors,5,odds,pre,start);
if(choice){
  assert.equal(choice.ticketSelectionModel,NOV2026_TICKET_MODEL_VERSION);
  assert.equal(new Set(choice.tickets.map(t=>t.betType)).size,2);
  assert.equal(choice.courseBets.length,6);
  for(const [course,total] of [["ライト",2000],["スタンダード",5000],["プレミアム",10000]] as const){
    const pair=choice.courseBets.filter(t=>t.course===course);
    assert.equal(pair.reduce((sum,t)=>sum+t.stakeYen,0),total);
    assert.ok(pair.every(t=>t.stakeYen>0&&t.stakeYen%100===0));
    assert.deepEqual(pair.map(t=>t.betType),choice.tickets.map(t=>t.betType));
    assert.ok(pair.every(t=>t.assumedOdds===10));
  }
}
console.log("NOV2026_OFFICIAL_T15_MODEL_ADAPTER_SAFETY_OK",choice?.ticketSelectionModel??"MODELED_20PCT_GATE_NO_CHOICE");
