/** Pure source-faithful 2017–2026 independent race selection over frozen archive.
 * Deliberately no returns, tickets, outcome-based race-selection filtering or D1.
 */
import archiveBase64 from "../src/v1/ten-year-history-data/index.js";
import {gunzipSync,gzipSync} from "node:zlib";
import {writeFile,mkdir} from "node:fs/promises";
import {fitIndependent,independentlyRankRaces,type IndependentMode,type IndependentRace} from "../src/v1/independent-rolling-core.js";
const raw=JSON.parse(gunzipSync(Buffer.from(archiveBase64,"base64")).toString()) as {races:any[][]};
const days=new Map<string,IndependentRace[]>();
for(const [rid,date,venue,raceNo,name,start,surface,distance] of raw.races){
 if(date<"2017-01-01"||date>"2026-08-09")continue;
 const hhmm=String(start||"").match(/^\d\d?:\d\d/);
 const startUtc=hhmm?new Date(Date.parse(date+"T"+hhmm[0]+":00+09:00")).toISOString():null;
 const r:IndependentRace={raceId:rid,raceDate:date,venue,raceNo:Number(raceNo),raceName:name||null,
  startTimeUtc:startUtc,startTimeJst:start||null,surface:surface||null,distanceM:Number(distance||0)};
 const group=days.get(date)||[];group.push(r);days.set(date,group);
}
const modes=["cash6","cash96"] as const;
const cache=new Map<string,ReturnType<typeof fitIndependent>>();
const selected:{date:string;mode:IndependentMode;raceId:string;venue:string;raceNo:number;raceScore:number}[]=[];
const failures:{date:string;mode:IndependentMode;error:string}[]=[];
const perYear:Record<string,Record<string,{venueDays:number;selected:number;failedDates:number}>>={};
for(const [date,races] of [...days].sort((a,b)=>a[0].localeCompare(b[0]))){
 const year=date.slice(0,4); perYear[year]??={};
 for(const mode of modes){
  perYear[year][mode]??={venueDays:0,selected:0,failedDates:0};
  const venues=new Set(races.map(r=>r.venue));
  // All deployed modes enforce exactly 12 per venue; no partial race repair.
  const valid=[...venues].every(v=>races.filter(x=>x.venue===v).length===12);
  if(!valid){perYear[year][mode].failedDates++;failures.push({date,mode,error:"INCOMPLETE_12_RACE_PROGRAM"});continue;}
  try{
   const k=mode+":"+date.slice(0,7);
   let fit=cache.get(k);
   if(!fit){fit=fitIndependent(date,mode,[]);cache.set(k,fit);}
   const results=independentlyRankRaces(date,mode,races,fit);
   selected.push(...results.map(p=>({date,mode,...p})));
   perYear[year][mode].venueDays+=venues.size;
   perYear[year][mode].selected+=results.length;
  }catch(e){perYear[year][mode].failedDates++;failures.push({date,mode,error:String(e)});}
 }
}
await mkdir("artifacts",{recursive:true});
await writeFile("artifacts/independent-2017-2026-selection.json.gz",gzipSync(Buffer.from(JSON.stringify({start:"2017-01-01",end:"2026-08-09",selected,failures,perYear}),"utf8")));
console.log("FULL_PERIOD_INDEPENDENT_RACE_SELECTION",JSON.stringify({sourceRaces:raw.races.length,days:days.size,cacheFitted:cache.size,selected: selected.length,
 byYear:perYear,failedDates:failures.length,sampleErrors:failures.slice(0,9)}));
