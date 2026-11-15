/** Model-identical race selection for every archived 2016-2026 venue-day.
 * Does not claim payout ROI until independent tickets use REAL JRA odds.
 */
import {gunzipSync} from "node:zlib";
import {writeFile,mkdir} from "node:fs/promises";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import source from "../src/v1/ten-year-history-data/index.js";
import {fitIndependent,independentlyRankRaces,type IndependentMode,type IndependentRace} from "../src/v1/independent-rolling-core.js";
const root=join(dirname(fileURLToPath(import.meta.url)),"..");
const rows=JSON.parse(gunzipSync(Buffer.from(source,"base64")).toString()) as {start:string;end:string;races:any[]};
const all=new Map<string,IndependentRace[]>();
for(const x of rows.races){
 const [raceId,raceDate,venue,raceNo,raceName,startTimeJst,surface,distanceM]=x;
 const st=String(startTimeJst).slice(0,5);
 const dateTime=raceDate+"T"+st+":00+09:00";
 const parsed=Date.parse(dateTime);
 if(!Number.isFinite(parsed))throw Error("BAD_ARCHIVED_RACE_TIME:"+raceId+":"+dateTime);
 const race:IndependentRace={raceId,raceDate,venue,raceNo, raceName,surface,distanceM,startTimeUtc:new Date(parsed).toISOString(),startTimeJst:st};
 const d=all.get(raceDate)||[];d.push(race);all.set(raceDate,d);
}
const fitCache=new Map<string,ReturnType<typeof fitIndependent>>();
const results:{date:string;mode:IndependentMode;selected:any[]}[]=[];
const failures:any[]=[];
for(const [date,rs] of all){
 if(date<"2016-08-10"||date>"2026-08-09")continue;
 for(const mode of ["cash6","cash96"] as const){
   const k=date.slice(0,7)+":"+mode;
   let fit=fitCache.get(k);
   if(!fit){fit=fitIndependent(date,mode,[]);fitCache.set(k,fit);}
   try{
     const selected=independentlyRankRaces(date,mode,rs,fit);
     results.push({date,mode,selected});
   }catch(e){failures.push({date,mode,reason:String(e),races:rs.length});}
 }
}
const years:any={};for(const row of results){
 const yr=row.date.slice(0,4),r=years[yr]||{cash6:{venueDays:0,chosenRaces:0},cash96:{venueDays:0,chosenRaces:0}};
 const unit=r[row.mode];unit.venueDays+=row.selected.length/(row.mode==="cash6"?5:3);unit.chosenRaces+=row.selected.length;
 years[yr]=r;
}
await mkdir(join(root,"artifacts"),{recursive:true});
await writeFile(join(root,"artifacts/independent-full-period-selections.json"),JSON.stringify({start:rows.start,end:rows.end,archiveRaces:rows.races.length,modeResults:results,excluded:failures,years}));
console.log("INDEPENDENT_FULL_PERIOD_RACE_SELECTION",JSON.stringify({archiveRaces:rows.races.length,dates:all.size,months:fitCache.size,years,rows:results.length,excluded:failures.length,sampleExcluded:failures.slice(0,8)}));
if(results.length<1200)throw Error("UNEXPECTED_FULL_PERIOD_RACE_SELECTION_COVERAGE:"+results.length);
