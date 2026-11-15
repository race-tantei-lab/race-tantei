import {strict as assert} from "node:assert";
import {compareThree,preT15,type Race,type Bet} from "../src/v1/three-model-money-comparison.js";
import {restored716Estimate,restored716Tickets,
  RESTORED_RESEARCH_ROI_PCT,RESTORED_RESEARCH_SLA,
  RESTORED_RESEARCH_TRAINING_TICKETS} from "../src/v1/restored-716-money-policy.js";

const date="2026-11-15",venue="東京";
const races:Race[]=Array.from({length:5},(_,i)=>({
  raceId:date+"-tokyo-"+String(i+1).padStart(2,"0"),raceDate:date,
  venue,raceNo:i+1,raceName:"回帰テスト",
  surface:"芝",distanceM:1600,startTimeUtc:"2026-11-15T06:00:00Z",startTimeJst:"15:00"
}));
const original:Bet[]=races.flatMap(r=>[
  {raceId:r.raceId,betType:"単勝",combination:"3",stakeYen:1000,assumedOdds:2.5,
   lockedAt:"2026-11-15T04:30:00Z",settlementStatus:"pending",returnYen:null},
  {raceId:r.raceId,betType:"ワイド",combination:"3-7",stakeYen:1000,assumedOdds:5.8,
   lockedAt:"2026-11-15T04:30:00Z",settlementStatus:"pending",returnYen:null}
]);
const ids=races.map(x=>x.raceId);
assert.equal(RESTORED_RESEARCH_ROI_PCT,716.827267);
assert.equal(RESTORED_RESEARCH_SLA,3);
assert.ok(RESTORED_RESEARCH_TRAINING_TICKETS>1000);
const originalBefore=JSON.stringify(original);
const panels=compareThree(date,ids,races,original,[]);
assert.deepEqual(panels.map(x=>x.id),["current","cash6"]);
assert.deepEqual(panels.map(x=>x.selectedRaces),[5,3]);
const recovered=panels[1]!;
assert.ok(recovered.title.includes("716.83%"));
assert.equal(recovered.venues[0]!.races.filter(x=>x.status==="simulation").length,3);
assert.equal(recovered.venues[0]!.races.filter(x=>x.status==="skipped").length,2);
const slates=recovered.venues[0]!.races.filter(x=>x.status==="simulation");
for(const pick of slates){
  assert.equal(pick.tickets.length,2);
  assert.equal(pick.tickets.reduce((n,t)=>n+t.stakeYen,0),2000);
  assert.ok(pick.tickets.every(t=>t.stakeYen>=100&&t.stakeYen<=1900&&
    t.stakeYen%100===0&&t.settledReturnYen===null));
}
const expected=races.map((race,i)=>({
  id:race.raceId,
  score:restored716Tickets(race,original.slice(i*2,i*2+2)).priority
})).sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id))
 .slice(0,3).map(x=>x.id).sort();
assert.deepEqual(slates.map(x=>x.race.raceId).sort(),expected,
  "restore exact A+B ranking, not stake-weighted 6-month scoring");
const a=restored716Estimate(races[0]!,original[0]!);
const b=restored716Estimate(races[0]!,original[1]!);
assert.ok(Number.isFinite(a)&&a>0&&Number.isFinite(b)&&b>0);
const incomplete=compareThree(date,ids,races,original.slice(0,-2),[]);
assert.deepEqual(incomplete.map(x=>x.selectedRaces),[4,0]);
assert.ok(incomplete[1]!.venues[0]!.races.every(x=>x.status==="awaiting"));
const late=original.map(x=>({...x}));
late[0]!.lockedAt="2026-11-15T05:50:00Z";
const latePanels=compareThree(date,ids,races,late,[]);
assert.deepEqual(latePanels.map(x=>x.selectedRaces),[5,0]);
assert.equal(preT15("2026-11-15T05:00:00Z","2026-11-15T06:00:00Z",date,"15:00"),true);
assert.equal(preT15("2026-11-15T05:50:00Z","2026-11-15T06:00:00Z",date,"15:00"),false);
assert.throws(()=>restored716Estimate({...races[0]!,raceDate:"2027-01-02"},original[0]!),
  /YEAR_SPECIFIC_CASH_PRIOR_NOT_TRAINED/);
assert.equal(JSON.stringify(original),originalBefore,"no mutation of canonical original tickets");
console.log("RESTORED_716827_CASH_3_OF_5_T15_FINANCIAL_SAFETY_TEST_OK");
