import publicSite from "./public-site-entry-v6.js";
import type { Env } from "./v1/types.js";

const AUG9_SELECTED = new Set([
  "2026-08-09-chukyo-01","2026-08-09-chukyo-05","2026-08-09-chukyo-08","2026-08-09-chukyo-11","2026-08-09-chukyo-12",
  "2026-08-09-niigata-01","2026-08-09-niigata-03","2026-08-09-niigata-04","2026-08-09-niigata-11","2026-08-09-niigata-12",
  "2026-08-09-sapporo-01","2026-08-09-sapporo-02","2026-08-09-sapporo-05","2026-08-09-sapporo-06","2026-08-09-sapporo-09",
]);

function jstMinutes(now = new Date()): number {
  const d = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}
function parseTime(value: unknown): number | null {
  const m = String(value ?? "").match(/^(\d{1,2}):(\d{2})$/);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}
function clock(total: number): string {
  const n = (total + 1440) % 1440;
  return `${String(Math.floor(n / 60)).padStart(2,"0")}:${String(n % 60).padStart(2,"0")}`;
}

function targetState(race: Record<string, any>): Record<string, any> {
  const current = race.publicState ?? {};
  const raceId = String(race.raceId ?? "");
  if (current.code === "hit" || current.code === "miss" || current.code === "buy") return current;
  if (!AUG9_SELECTED.has(raceId)) return { code:"skip", label:"見送り", deadline:null };
  const start = parseTime(race.startTimeJst);
  if (start === null) return { code:"target", label:"買い目対象", deadline:"発走15分前までに買い目確定" };
  const deadline = start - 15;
  const now = jstMinutes();
  if (now < deadline) return { code:"target", label:"買い目対象", deadline:`${clock(deadline)}までに買い目確定` };
  if (now < start) return { code:"overdue", label:"買い目未確定", deadline:`${clock(deadline)}までに確定予定（未反映）` };
  return { code:"missing", label:"買い目未生成", deadline:null };
}

async function fixDayApi(response: Response): Promise<Response> {
  if (!response.ok) return response;
  try {
    const data = await response.clone().json() as {date?:string;races?:Array<Record<string,any>>;[k:string]:any};
    if (data.date !== "2026-08-09" || !Array.isArray(data.races)) return response;
    data.races = data.races.map(race => ({...race, publicState: targetState(race)}));
    const headers = new Headers(response.headers); headers.delete("content-length"); headers.set("content-type","application/json; charset=utf-8");
    return new Response(JSON.stringify(data), {status:response.status, headers});
  } catch { return response; }
}

async function fixRaceDetail(request:Request,response:Response):Promise<Response>{
  const path=new URL(request.url).pathname;
  if(!path.startsWith("/races/2026-08-09-")||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
  try{
    const raceId=decodeURIComponent(path.slice("/races/".length));
    let html=await response.text();
    if(!AUG9_SELECTED.has(raceId)){
      html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/g,'<span class="status skip">見送り</span>');
      html=html.replace(/<div class="section-title"><h2>買い目<\/h2>[\s\S]*?(?=<div class="section-title"><h2>出走馬|<div class="section-title"><h2>出走馬)/, '<div class="section-title"><h2>買い目</h2><span class="status skip">見送り</span></div><section class="panel compact-bet-note"><p>前日に固定した5レースの対象外です。</p></section>');
    } else {
      const m=html.match(/(\d{1,2}):(\d{2})発走/); const start=m?Number(m[1])*60+Number(m[2]):null;
      const deadline=start===null?null:start-15; const now=jstMinutes();
      let code="target",label="買い目対象",message=deadline===null?"発走15分前までに買い目を確定します。":`${clock(deadline)}までに買い目を確定します。`;
      if(start!==null&&now>=deadline!&&now<start){code="overdue";label="買い目未確定";message=`${clock(deadline!)}までに確定予定でしたが、まだ反映されていません。`;}
      if(start!==null&&now>=start){code="missing";label="買い目未生成";message="前日選定では購入対象でしたが、買い目が固定されないまま発走時刻を過ぎています。";}
      if(!/class="status (?:buy|hit|miss)"/.test(html)){
        html=html.replace(/<span class="status (?:skip|pending|overdue|missing|target)">[^<]*<\/span>/g,`<span class="status ${code}">${label}</span>`);
        html=html.replace(/<div class="section-title"><h2>買い目<\/h2>[\s\S]*?(?=<div class="section-title"><h2>出走馬|<div class="section-title"><h2>出走馬)/,`<div class="section-title"><h2>買い目</h2><span class="status ${code}">${label}</span></div><div class="notice compact-bet-note">${message}</div>`);
      }
    }
    html=html.replace("</head>",`<style>.status.target{background:#15483a;color:#baf4dd;border:1px solid #2d806c}.compact-bet-note{padding:9px 12px!important;margin:6px 0!important;font-size:12px!important}.compact-bet-note p{margin:0!important}</style></head>`);
    const headers=new Headers(response.headers);headers.delete("content-length");return new Response(html,{status:response.status,headers});
  }catch{return response;}
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const path=new URL(request.url).pathname;
    let response=await publicSite.fetch(request,env,ctx);
    if(path==="/api/public/day"&&new URL(request.url).searchParams.get("date")==="2026-08-09") response=await fixDayApi(response);
    response=await fixRaceDetail(request,response);
    return response;
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
