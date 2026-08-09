import publicSite from "./public-site-entry-v11.js";
import type { Env } from "./v1/types.js";
import { getStaticCanonicalCoursePayouts, type CanonicalCoursePayouts } from "./v1/static-canonical-history.js";

const CUTOFF="2026-08-02";
const COURSES=["ライト","スタンダード","プレミアム"] as const;

type Course=typeof COURSES[number];

function yen(value:number):string{return `¥${Math.round(value).toLocaleString("ja-JP")}`;}
function isFrozenDate(value:unknown):boolean{return /^\d{4}-\d{2}-\d{2}$/.test(String(value??""))&&String(value)<=CUTOFF;}
function hit(p:CanonicalCoursePayouts):boolean{return COURSES.some(course=>Number(p[course]??0)>0);}

async function normalizeHistoricalDay(response:Response):Promise<Response>{
  if(!response.ok)return response;
  try{
    const data=await response.clone().json() as {date?:string;races?:Array<Record<string,any>>;[key:string]:any};
    const date=String(data.date??"");
    if(!isFrozenDate(date)||!Array.isArray(data.races))return response;
    const pairs=await Promise.all(data.races.map(async race=>{
      const raceId=String(race.raceId??"");
      return [raceId,await getStaticCanonicalCoursePayouts(raceId)] as const;
    }));
    const payouts=new Map(pairs);
    data.races=data.races.map(race=>{
      const raceId=String(race.raceId??"");
      const p=payouts.get(raceId)??null;
      const publicState={...(race.publicState??{})};
      delete publicState.payouts;
      publicState.deadline=null;
      if(p){
        const won=hit(p);
        publicState.code=won?"hit":"miss";
        publicState.label=won?"的中":"不的中";
        if(won)publicState.payouts=p;
      }else{
        publicState.code="skip";
        publicState.label="見送り";
      }
      return {...race,publicState};
    });
    const headers=new Headers(response.headers);headers.delete("content-length");headers.set("content-type","application/json; charset=utf-8");
    return new Response(JSON.stringify(data),{status:response.status,headers});
  }catch{return response;}
}

async function normalizeHistoricalDetail(request:Request,response:Response):Promise<Response>{
  const path=new URL(request.url).pathname;
  if(!path.startsWith("/races/")||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
  const raceId=decodeURIComponent(path.slice("/races/".length));
  if(!isFrozenDate(raceId.slice(0,10)))return response;
  try{
    const p=await getStaticCanonicalCoursePayouts(raceId);
    let html=await response.text();
    html=html.replace(/<div class="race-payout-summary">[\s\S]*?<\/div>/g,"");
    if(p){
      const won=hit(p);
      html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/g,`<span class="status ${won?"hit":"miss"}">${won?"的中":"不的中"}</span>`);
      if(won){
        const summary=`<div class="race-payout-summary"><strong>払戻</strong>${COURSES.map((course:Course)=>`<span>${course}<br><b>${yen(p[course])}</b></span>`).join("")}</div>`;
        html=html.replace(/(<section class="hero[\s\S]*?<\/section>)/,`$1${summary}`);
      }
    }else{
      html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/g,'<span class="status skip">見送り</span>');
    }
    const headers=new Headers(response.headers);headers.delete("content-length");
    return new Response(html,{status:response.status,headers});
  }catch{return response;}
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const path=new URL(request.url).pathname;
    let response=await publicSite.fetch(request,env,ctx);
    if(path==="/api/public/day")response=await normalizeHistoricalDay(response);
    response=await normalizeHistoricalDetail(request,response);
    return response;
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
  }
} satisfies ExportedHandler<Env>;
