import {strict as assert} from "node:assert";
import {modelNavigation,MODEL_SWITCH_CSS,serveFullModel} from "../src/three-model-full-pages.js";
import {restored716Tickets} from "../src/v1/restored-716-money-policy.js";

const raceDate="2026-11-14";
const ids=Array.from({length:5},(_,i)=>raceDate+"-tokyo-"+String(i+1).padStart(2,"0"));
const races=Array.from({length:12},(_,i)=>({
  raceId:raceDate+"-tokyo-"+String(i+1).padStart(2,"0"),
  raceDate,venue:"東京",raceNo:i+1,raceName:"レース"+(i+1),
  surface:"芝",distanceM:1600,
  startTimeJst:"15:00",startTimeUtc:"2026-11-14T06:00:00Z"
}));
const bets=ids.flatMap(raceId=>[
 {raceId,betType:"単勝",combination:"3",stakeYen:1000,assumedOdds:2.5,
  lockedAt:"2026-11-14T03:00:00Z",settlementStatus:"settled",returnYen:0},
 {raceId,betType:"ワイド",combination:"3-7",stakeYen:1000,assumedOdds:5.8,
  lockedAt:"2026-11-14T03:00:00Z",settlementStatus:"settled",returnYen:5000},
]);
const selection=JSON.stringify({sourceModel:"ten-year-completed-model",selected:ids.map(raceId=>({raceId}))});
const queries:string[]=[];
const DB={
 prepare:(sql:string)=>({
   bind:(...args:unknown[])=>({
     first:async()=>{
       queries.push("FIRST "+sql.slice(0,45));
       assert.equal(args[0],"final_daily_selection:"+raceDate);
       return {value:selection};
     },
     all:async()=>{
       queries.push("ALL "+sql.slice(0,45));
       if(sql.includes("GROUP BY race_date,venue"))return {results:[{raceDate,venue:"東京",count:12}]};
       if(sql.includes("FROM rt_public_bets b JOIN rt_races r"))return {results:[]};
       if(sql.includes("FROM rt_public_bets WHERE race_id"))return {results:bets};
       if(sql.includes("FROM rt_races WHERE race_date"))return {results:races};
       if(sql.includes("FROM rt_runners r LEFT JOIN rt_results"))return {results:[
         {horseNo:3,horseName:"テストホース",sexAge:"牡3",jockey:"騎手",trainer:"厩舎",winOdds:2.5,finishPosition:1}
       ]};
       throw Error("UNEXPECTED_D1_SELECT "+sql);
     }
   })
 })
};
const env={DB} as unknown as Parameters<typeof serveFullModel>[1];
const nav=modelNavigation("cash6",raceDate,ids[0]);
assert.ok(nav.includes('aria-current="page"'));
assert.ok(!nav.includes("/models/96m/"));
assert.equal((nav.match(/data-prediction-model=/g)||[]).length,2);
assert.ok(nav.includes("/races/"+ids[0]));
assert.ok(MODEL_SWITCH_CSS.includes(".prediction-model-tabs"));
const six=await serveFullModel(new Request("https://race-tantei.test/models/6m?date="+raceDate),env,"cash6");
assert.equal(six.status,200);
assert.equal(six.headers.get("x-race-model-full-page"),"standalone-v3");
const h6=await six.text();
for(const text of ["716.83%研究モデル","現行モデル","年","月","日付","競馬場","レース1","レース12","参考予想"]){
  assert.ok(h6.includes(text),"missing "+text);
}
assert.ok(h6.includes('data-prediction-model="cash6" aria-current="page"'));
assert.equal((h6.match(/status buy/g)||[]).length,3);
assert.ok(h6.includes("100円単位"));
assert.ok(!h6.includes("過去96か月モデル"));
assert.ok(!h6.includes("/models/96m"));
for(const label of ["1. 年","2. 月","3. 日付","4. 会場","5. レース"]){
  assert.ok(h6.includes(label),"missing original navigator step "+label);
}
assert.ok(h6.includes('id="model-page-root"'));
assert.ok(h6.includes('data-model-filter="true"'));
assert.ok(h6.includes('data-model-rail="dates"'));
assert.ok(h6.includes('data-model-venue="東京"'));
assert.ok(h6.includes("history.pushState"),"research model controls must retain in-page browser navigation");
assert.ok(h6.includes("window.scrollTo(0,y)"),"filtering must preserve scroll position");
assert.ok(h6.includes('aria-busy'),"filtering must report updates accessibly");
assert.ok(h6.includes('role="status" hidden'),"filter errors stay inline");
assert.ok(h6.indexOf('5. レース')<h6.indexOf('data-model-race='),"race cards must be INSIDE original five-step navigator");

assert.equal((h6.match(/data-model-race=/g)||[]).length,12);
assert.ok(h6.includes("/models/6m/races/"+ids[0]));
const ranked=ids.map((id,i)=>({id,score:restored716Tickets(races[i]!,bets.slice(2*i,2*i+2)).priority}))
  .sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id));
const detailId=ranked[0]!.id;
const detail=await serveFullModel(new Request("https://race-tantei.test/models/6m/races/"+detailId),env,"cash6",detailId);
const hd=await detail.text();
for(const text of ["テストホース","買い目の理由","ライト","スタンダード","プレミアム","4,500円","9,000円","予想買い目"]){
  assert.ok(hd.includes(text),"missing race detail feature "+text);
}
assert.ok(!hd.includes("/models/96m/races/"));
assert.ok(hd.includes("/races/"+ids[0]));
assert.ok(queries.every(x=>x.startsWith("FIRST SELECT ")||x.startsWith("ALL SELECT ")),
  "all queries must be SELECT-only");
console.log("RESTORED_716827_FULL_PAGES_AND_DETAILS_READ_ONLY_TEST_OK",queries.length);
