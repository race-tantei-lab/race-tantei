import {strict as assert} from "node:assert";
import {modelNavigation,MODEL_SWITCH_CSS,serveFullModel} from "../src/three-model-full-pages.js";

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
assert.ok(nav.includes("/models/96m/races/"+ids[0]));
assert.ok(nav.includes("/races/"+ids[0]));
assert.ok(MODEL_SWITCH_CSS.includes(".prediction-model-tabs"));
const six=await serveFullModel(new Request("https://race-tantei.test/models/6m?date="+raceDate),env,"cash6");
assert.equal(six.status,200);
assert.equal(six.headers.get("x-race-model-full-page"),"standalone-v2");
const h6=await six.text();
for(const text of ["直近6か月モデル","過去96か月モデル","現行モデル","年","月","日付","競馬場","レース1","レース12","1,800円","200円","参考予想"]){
  assert.ok(h6.includes(text),"missing "+text);
}
assert.ok(h6.includes('data-prediction-model="cash6" aria-current="page"'));
assert.equal((h6.match(/data-model-race=/g)||[]).length,12);
assert.ok(h6.includes("/models/6m/races/"+ids[0]));
const ninety=await serveFullModel(new Request("https://race-tantei.test/models/96m?date="+raceDate),env,"cash96");
const h96=await ninety.text();
assert.ok(h96.includes('data-prediction-model="cash96" aria-current="page"'));
assert.ok(h96.includes("3R"));
assert.equal((h96.match(/data-model-race=/g)||[]).length,12);
assert.equal((h96.match(/参考予想<\/span>/g)||[]).length,3);
const detail=await serveFullModel(new Request("https://race-tantei.test/models/6m/races/"+ids[0]),env,"cash6",ids[0]);
const hd=await detail.text();
for(const text of ["テストホース","買い目の理由","ライト","スタンダード","プレミアム","4,500円","9,000円","予想買い目"]){
  assert.ok(hd.includes(text),"missing race detail feature "+text);
}
assert.ok(hd.includes("/models/96m/races/"+ids[0]));
assert.ok(hd.includes("/races/"+ids[0]));
assert.ok(queries.every(x=>x.startsWith("FIRST SELECT ")||x.startsWith("ALL SELECT ")),
  "all queries must be SELECT-only");
console.log("THREE_FULL_MODEL_HOMES_AND_RACE_DETAILS_SAME_UI_NAV_AND_READ_ONLY_TEST_OK",queries.length);
