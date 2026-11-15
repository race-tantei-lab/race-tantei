import { strict as assert } from "node:assert";
import { cashFeatureKeys,compareThree,fitPreviousCash,preT15,scoreCash,
  type Race,type Bet,type PastBet } from "../src/v1/three-model-money-comparison.js";

const date="2026-11-15",venue="東京";
const races:Race[]=Array.from({length:5},(_,i)=>({
  raceId:date+"-tokyo-"+String(i+1).padStart(2,"0"),raceDate:date,
  venue,raceNo:i+1,raceName:"回帰テスト",
  surface:"芝",distanceM:1600,startTimeUtc:"2026-11-15T06:00:00Z",
  startTimeJst:"15:00"
}));
const original:Bet[]=races.flatMap(r=>[
 {raceId:r.raceId,betType:"単勝",combination:"3",stakeYen:1000,assumedOdds:2.5,
  lockedAt:"2026-11-15T04:30:00Z",settlementStatus:"pending",returnYen:null},
 {raceId:r.raceId,betType:"ワイド",combination:"3-7",stakeYen:1000,assumedOdds:5.8,
  lockedAt:"2026-11-15T04:30:00Z",settlementStatus:"pending",returnYen:null},
]);
const ids=races.map(x=>x.raceId);
const input=compareThree(date,ids,races,original,[]);
assert.deepEqual(input.map(x=>x.selectedRaces),[5,5,3],
  "show all five current and six-month, select 3/5 for 96-month");
assert.deepEqual(input.map(x=>x.trainingTickets>0),[false,true,true]);
const six=input[1]!;
assert.ok(six.venues[0]!.races.every(x=>x.tickets.length===2&&
  x.tickets.reduce((s,t)=>s+t.stakeYen,0)===2000));
assert.ok(six.venues[0]!.races.every(x=>x.tickets.some(t=>t.stakeYen===1800)&&
  x.tickets.some(t=>t.stakeYen===200)));
assert.ok(six.venues[0]!.races.every(x=>x.tickets.every(t=>t.settledReturnYen===null)),
  "no hypothetical stake is displayed as actual settled return");
assert.equal(input[2]!.venues[0]!.races.filter(x=>x.status==="simulation").length,3);
assert.equal(input[2]!.venues[0]!.races.filter(x=>x.status==="skipped").length,2);
const partial=compareThree(date,ids,races,original.slice(0,-2),[]);
assert.equal(partial[0]!.selectedRaces,4);
assert.equal(partial[2]!.selectedRaces,0);
assert.ok(partial[2]!.venues[0]!.races.every(x=>x.status==="awaiting"),
  "96-month method must not choose only the known 4 races");
const late=original.map(x=>({...x}));
late[0]!.lockedAt="2026-11-15T05:00:00Z";
const withLate=compareThree(date,ids,races,late,[]);
assert.equal(withLate[0]!.selectedRaces,5,"existing original picks remain untouched");
assert.equal(withLate[1]!.selectedRaces,4,"late bets are not called new T15 forecasts");
assert.equal(withLate[2]!.selectedRaces,0);
assert.equal(preT15("2026-11-15T05:00:00Z","2026-11-15T06:00:00Z",date,"15:00"),true);
assert.equal(preT15("2026-11-15T05:50:00Z","2026-11-15T06:00:00Z",date,"15:00"),false);
const keys=cashFeatureKeys(races[0]!,original[0]!);
assert.equal(keys.length,9);
assert.equal(keys[0],JSON.stringify(["type","単勝"]));
const source=fitPreviousCash("2026-11",6,"hit_cash",[]);
const currentPair:PastBet[]=original.slice(0,2).map(x=>({
  ...x,...races[0]!,settlementStatus:"settled",returnYen:1000
}));
assert.equal(fitPreviousCash("2026-11",6,"hit_cash",currentPair).seen,source.seen,
  "same-month cash cannot leak into 2026-11 forecast");
const previous:PastBet[]=currentPair.map(x=>({
  ...x,raceId:"2026-10-31-tokyo-01",raceDate:"2026-10-31",
  lockedAt:"2026-10-31T04:30:00Z",startTimeUtc:"2026-10-31T06:00:00Z",
  startTimeJst:"15:00",
}));
assert.equal(fitPreviousCash("2026-11",6,"hit_cash",previous).seen,source.seen+2);
const scores=scoreCash(races[0]!,original[0]!,source);
assert.ok(Number.isFinite(scores.cash)&&scores.cash>0&&scores.hit>0&&scores.hit<1);
const originalBefore=JSON.stringify(original);
compareThree(date,ids,races,original,previous);
assert.equal(JSON.stringify(original),originalBefore,"comparison must never mutate actual original tickets");
console.log("THREE_MODEL_SIDE_BY_SIDE_ORIGINAL_6MONTH_96MONTH_CASH_SAFETY_OK");
