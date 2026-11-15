/** Retrieve JRA official result URLs and exact JRA 100-yen payouts for every
 * 6m/96m independently selected race in one historical year.
 * This source is used ONLY for settlement, never for selection or pricing.
 */
import {readFile,writeFile,mkdir} from "node:fs/promises";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import {getArchiveResultUrls} from "../src/v1/three-month-archive.js";
import {fetchJraPage,pageLooksLikeResult,parseResultPage} from "../src/v1/jra.js";
import {parseDesktopPayouts} from "../src/v1/three-month-desktop.js";

const ROOT=join(dirname(fileURLToPath(import.meta.url)),"..");
const OUT=join(ROOT,"artifacts");
const year=String(process.env.AUDIT_YEAR||"2017");
if(!/^20(1[6-9]|2[0-6])$/.test(year))throw Error("BAD_RESEARCH_YEAR:"+year);
const raw=JSON.parse(await readFile(join(OUT,"independent-full-period-selections.json"),"utf8"));
const selected=new Set<string>();
for(const p of raw.modeResults)if(p.date.slice(0,4)===year)for(const x of p.selected)selected.add(x.raceId);
const limit=Number(process.env.AUDIT_LIMIT||"0");
if(limit>0){const ids=[...selected].slice(0,limit);selected.clear();ids.forEach(id=>selected.add(id));}
const venue=["","sapporo","hakodate","fukushima","niigata","tokyo","nakayama","chukyo","kyoto","hanshin","kokura"];
function parseId(url:string):string|null{
 const u=decodeURIComponent(url);
 const match=u.match(/pw01sde(?:10|01)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/i);
 if(!match)return null;
 const [,c,y,,,rn,ymd]=match;
 if(!venue[Number(c)])return null;
 return ymd.slice(0,4)+"-"+ymd.slice(4,6)+"-"+ymd.slice(6,8)+"-"+venue[Number(c)]+"-"+rn;
}
async function retry<T>(fn:()=>Promise<T>,title:string,n=4):Promise<T>{
 let last:unknown;
 for(let attempt=0;attempt<n;attempt++){
  try{return await fn();}
  catch(e){last=e;console.error("JRA_ARCHIVE_RETRY",title,attempt+1,String(e).slice(0,100));await new Promise(resolve=>setTimeout(resolve,900*(attempt+1)));}
 }
 throw new Error("JRA_ARCHIVE_FAILED:"+title+":"+String(last));
}
async function mapPool<T,R>(items:T[],limit:number,f:(x:T)=>Promise<R>):Promise<R[]>{
 const out:R[]=new Array(items.length);let i=0;
 await Promise.all(Array.from({length:Math.min(items.length,limit)},async()=>{for(;;){const j=i++;if(j>=items.length)break;out[j]=await f(items[j]);}}));
 return out;
}
const matched=new Map<string,string>(),monthFailures:any[]=[];
for(let month=1;month<=12;month++){
 const ym=year+String(month).padStart(2,"0");
 if(![...selected].some(id=>id.slice(0,4)+id.slice(5,7)===ym))continue;
 try{
  const links=await retry(()=>getArchiveResultUrls(ym),"month-"+ym,4);
  for(const link of links){
   const id=parseId(link);
   if(id&&selected.has(id))matched.set(id,link);
  }
  console.log("INDEPENDENT_YEAR_RESULT_DISCOVERY",JSON.stringify({ym,links:links.length,totalSelectedMatched:matched.size,expected:selected.size}));
 }catch(e){monthFailures.push({month:ym,error:String(e)});}
}
const records:any[]=[],resultFailures:any[]=[];
const ids=[...matched.keys()];
await mapPool(ids,6,async id=>{
 const url=matched.get(id)!;
 try{
  const page=await retry(()=>fetchJraPage(url),"race-"+id,3);
  if(!pageLooksLikeResult(page.html))throw Error("NOT_A_JRA_RESULT_PAGE");
  const parsed=parseResultPage(page.html,page.url);
  const payouts=parsed.payouts.length?parsed.payouts:parseDesktopPayouts(page.html);
  if(!payouts.length)throw Error("OFFICIAL_RESULTS_NO_PAYOUTS");
  records.push({raceId:id,race:{raceId:id,raceDate:id.slice(0,10),resultUrl:url},payouts});
 }catch(e){resultFailures.push({raceId:id,error:String(e)});}
});
records.sort((a,b)=>a.raceId.localeCompare(b.raceId));
const report={year,scope:"independent 6m/96m all selected races, original archival JRA results",
  source:"JRA_OFFICIAL_FINISHED_RESULTS",date:year,expected:selected.size,matched:matched.size,payoutRaces:records.length,
  monthFailures,resultFailures,missingIds:[...selected].filter(x=>!matched.has(x)),races:records};
await mkdir(OUT,{recursive:true});
await writeFile(join(OUT,"independent-year-result-"+year+".json"),JSON.stringify(report));
console.log("INDEPENDENT_YEAR_OFFICIAL_RESULTS",JSON.stringify({year,expected:selected.size,matched:matched.size,payoutRaces:records.length,missing:report.missingIds.slice(0,12),monthFailures:monthFailures.slice(0,6),resultFailures:resultFailures.slice(0,8)}));
if(records.length===0)throw Error("INDEPENDENT_YEAR_NO_OFFICIAL_RESULTS:"+year);
