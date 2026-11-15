/** Exact deployed 6m / 96m independent ranking on completed Aug-Nov 2026 D1 races.
 * Cache only genuine prior-month original cash observations; never current-month
 * settlement to select the current date.
 */
import {gunzipSync} from "node:zlib";
import {readFile,writeFile} from "node:fs/promises";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import {fitIndependent,independentlyRankRaces,type IndependentMode} from "../src/v1/independent-rolling-core.js";
const root=join(dirname(fileURLToPath(import.meta.url)),"..");
const art=join(root,"artifacts");
const source=JSON.parse(gunzipSync(await readFile(join(art,"independent-late-2026-d1.json.gz"))).toString("utf8"));
const byDate=new Map<string,any[]>();
for(const b of source.races){
 const r=b.race;
 const arr=byDate.get(r.raceDate)||[];arr.push(r);byDate.set(r.raceDate,arr);
}
const results:any[]=[],failures:any[]=[];
for(const [date,races] of [...byDate].sort((a,b)=>a[0].localeCompare(b[0]))){
 for(const mode of ["cash6","cash96"] as const){
  try{
   const fit=fitIndependent(date,mode,source.pastOriginalSettled);
   const selected=independentlyRankRaces(date,mode,races,fit);
   results.push({date,mode,selected});
  }catch(e){failures.push({date,mode,numberOfRaces:races.length,error:String(e)});}
 }
}
const chosen=new Set(results.flatMap(r=>r.selected.map((s:any)=>s.raceId)));
const output={period:source.start+".."+source.end,modeResults:results,excluded:failures,chosen:chosen.size,completeRaceDates:byDate.size,all2026Races:source.races.length};
await writeFile(join(art,"independent-late-2026-selections.json"),JSON.stringify(output));
console.log("INDEPENDENT_2026_AUG_NOV_SELECTIONS",JSON.stringify({dates:byDate.size,races:source.races.length,chosen:chosen.size,cash6:results.filter(r=>r.mode==="cash6").reduce((a,r)=>a+r.selected.length,0),cash96:results.filter(r=>r.mode==="cash96").reduce((a,r)=>a+r.selected.length,0),excluded:failures.slice(0,10)}));
if(chosen.size<100)throw Error("TOO_FEW_2026_LATE_INDEPENDENT_RACES");
