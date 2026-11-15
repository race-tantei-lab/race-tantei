import {strict as assert} from "node:assert";
import {fitIndependent,independentlyRankRaces,chooseIndependentTickets,canFreezeIndependent,independentCourseBets,settleIndependent,INDEPENDENT_SOURCE_VERSION,identicalTwoTicketPicks} from "../src/v1/independent-rolling-core.js";
import {identicalHomeUi,identicalDetailUi,snapshotStatus,summaryForDay} from "../src/independent-rolling-public.js";
import {NORMAL_HOME_SNAPSHOT} from "../src/normal-home-snapshot.js";

const date="2026-11-21";
const venues=["東京","京都","福島"];
const races=venues.flatMap(venue=>Array.from({length:12},(_,i)=>({
 raceId:date+"-"+(venue==="東京"?"tokyo":venue==="京都"?"kyoto":"fukushima")+"-"+String(i+1).padStart(2,"0"),
 raceDate:date,venue,raceNo:i+1,raceName:"レース"+(i+1),
 startTimeJst:"14:30",startTimeUtc:"2026-11-21T05:30:00Z",
 surface:i%2?"芝":"ダート",distanceM:i%2?1800:1400,
 entryUrl:"https://www.jra.go.jp/test",status:"scheduled"
})));
const f6=fitIndependent(date,"cash6",[]);
const f96=fitIndependent(date,"cash96",[]);
const six=independentlyRankRaces(date,"cash6",races,f6);
const ninety=independentlyRankRaces(date,"cash96",races,f96);
assert.equal(six.length,15,"6mo chooses its own 5 races per venue from all 12");
assert.equal(ninety.length,9,"96mo chooses its own 3 races per venue from all 12");
assert.ok(six.every(x=>races.some(r=>r.raceId===x.raceId)));
assert.ok(ninety.every(x=>races.some(r=>r.raceId===x.raceId)));
let missingProgramRejected=false;
try{independentlyRankRaces(date,"cash96",races.slice(1),f96);}catch(e){missingProgramRejected=String(e).includes("NOT_12");}
assert.ok(missingProgramRejected);
const hNos=[1,2,3,4];
const weights=[.5,.3,.15,.05];
const markets=[
 {betType:"単勝" as const,combination:"2",oddsMin:3.5,oddsMax:3.5},
 {betType:"単勝" as const,combination:"1",oddsMin:1.5,oddsMax:1.5},
 {betType:"ワイド" as const,combination:"1-2",oddsMin:2.6,oddsMax:3},
 {betType:"馬連" as const,combination:"1-2",oddsMin:6,oddsMax:6},
 {betType:"馬単" as const,combination:"1-2",oddsMin:11,oddsMax:11},
 {betType:"3連複" as const,combination:"1-2-3",oddsMin:18,oddsMax:18},
 {betType:"3連単" as const,combination:"1-2-3",oddsMin:40,oddsMax:40}
];
for(const mode of ["cash6","cash96"] as const){
 const chosen=chooseIndependentTickets(races[0],mode,mode==="cash6"?f6:f96,hNos,weights,markets);
 assert.equal(chosen.length,2);
 assert.ok(chosen[0].betType!==chosen[1].betType);
 // The canonical two combinations, regardless of their yen allocation, can
 // NEVER be emitted together when already known before the model locks.
 const clonedByStakeOnly=chosen.map(t=>({betType:t.betType,combination:t.combination,stakeYen:9999}));
 assert.equal(identicalTwoTicketPicks(chosen,clonedByStakeOnly),true);
 const ownInstead=chooseIndependentTickets(races[0],mode,mode==="cash6"?f6:f96,hNos,weights,markets,[clonedByStakeOnly]);
 assert.equal(ownInstead.length,2);
 assert.notEqual(ownInstead[0].betType,ownInstead[1].betType);
 assert.equal(identicalTwoTicketPicks(ownInstead,clonedByStakeOnly),false);
 assert.ok(ownInstead.some(t=>!clonedByStakeOnly.some(o=>o.betType===t.betType&&o.combination===t.combination)),
   "must change ticket type or horse combination, not just amount");
 const disallowAgain=chooseIndependentTickets(races[0],mode,mode==="cash6"?f6:f96,hNos,weights,markets,[clonedByStakeOnly,ownInstead]);
 assert.equal(identicalTwoTicketPicks(disallowAgain,clonedByStakeOnly),false);
 assert.equal(identicalTwoTicketPicks(disallowAgain,ownInstead),false);
 const orders=independentCourseBets(chosen);
 assert.equal(orders.length,6);
 for(const [course,sum] of [["ライト",2000],["スタンダード",5000],["プレミアム",10000]] as const){
   assert.equal(orders.filter(x=>x.course===course).reduce((a,b)=>a+b.stakeYen,0),sum);
 }
 const last="2026-11-21T05:14:59Z";
 assert.equal(canFreezeIndependent("2026-11-21T05:30:00Z",last,last),true);
 assert.equal(canFreezeIndependent("2026-11-21T05:30:00Z","2026-11-21T05:16:00Z","2026-11-21T05:16:00Z"),false);
 const final={
  date,mode,raceId:races[0].raceId,lockedAt:last,oddsFetchedAt:last,startTimeUtc:races[0].startTimeUtc,
  oddsSource:"jra-fast-official",sourceModel:INDEPENDENT_SOURCE_VERSION,
  tickets:chosen,courseBets:orders
 };
 const empty={selection:{date,mode,createdAt:last,sourceModel:INDEPENDENT_SOURCE_VERSION,trainingThrough:"2026-11-01",selected:[{raceId:races[0].raceId,venue:races[0].venue,raceNo:1,raceScore:1}]},
  finals:new Map([[races[0].raceId,final]]),races:[{...races[0],status:"scheduled"}],paid:new Map()};
 assert.equal(snapshotStatus(empty,races[0].raceId).code,"buy");
 const perf=summaryForDay(date,empty);
 assert.equal(perf.finalizedRaces,1);
 assert.equal(perf.settledRaces,0);
 assert.equal(perf.targetRaces,1);
 assert.ok(identicalHomeUi(NORMAL_HOME_SNAPSHOT,mode).includes('id="years"'));
 const output=identicalHomeUi(NORMAL_HOME_SNAPSHOT,mode);
 assert.ok(output.includes('id="months"')&&output.includes('id="dates"')&&output.includes('id="venues"')&&output.includes('id="races"'));
 assert.ok(output.includes("/models/"+(mode==="cash6"?"6m":"96m")+"/api/public/day?date="));
 assert.ok(output.includes('a.href="/models/'+(mode==="cash6"?"6m":"96m")+'/races/"'));
 assert.ok(!output.includes('研究用・収益予測')&&!output.includes('モデルの表示に必要な情報'));
 assert.ok(!output.includes('class="model-navigator"'),"no new custom navigator");
 const originalToday='<section class="card today-results"><div class="section-title"><h2>今日の結果</h2></div><div class="today-result-row"><strong>LEGACY_RESULTS_SHOULD_NOT_APPEAR</strong></div></section>';
 const withOriginalToday=NORMAL_HOME_SNAPSHOT.replace("</main>",originalToday+"</main>");
 const modelToday=identicalHomeUi(withOriginalToday,mode,undefined,summaryForDay(date,empty));
 assert.ok(!modelToday.includes("LEGACY_RESULTS_SHOULD_NOT_APPEAR"),"must not show canonical model's current-day ROI");
 assert.ok(modelToday.includes('class="today-result-row"'),"keep identical original result-row UI");

 const html='<!doctype html><html><head></head><body><main><header></header><section class="hero today-hero"><div class="race-title"><span class="status miss">不的中</span></div></section><section data-race-panel="bets"><div>WRONG ORIGINAL TICKET</div></section><section id="race-panel-reason" data-race-panel="reason" hidden><p>WRONG OLD REASON</p></section><section data-race-panel="horses">HORSES</section></main></body></html>';
 const render=identicalDetailUi(html,mode,races[0].raceId,empty);
 assert.ok(!render.includes("WRONG ORIGINAL TICKET"));
 assert.ok(!render.includes("WRONG OLD REASON"));
 assert.ok(render.includes("HORSES"));
 assert.ok(render.includes('data-course-tab="0"'));
 assert.ok(render.includes("1,800円"));
 assert.ok(render.includes("5,000円"));
 const settled=settleIndependent(final,[{betType:chosen[0].betType,combination:chosen[0].combination,payoutYen:200}],true);
 assert.ok(settled&&settled.stake===2000&&settled.paid===3600);
}
console.log("INDEPENDENT_MODEL_PRESTART_SELECTION_TWO_TICKETS_ANTI_CLONE_EXACT_ORIGINAL_UI_OK");
