import publicSite from "./public-site-entry-v5.js";
import type { Env } from "./v1/types.js";

type State = { code: "buy"|"hit"|"miss"|"pending"|"overdue"|"missing"; label: string; message: string | null };

function nowJst(now = new Date()): { date: string; minutes: number } {
  const d = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return {
    date: `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")}`,
    minutes: d.getUTCHours()*60+d.getUTCMinutes()
  };
}
function minutes(value: string|null): number|null {
  const m=String(value??"").match(/^(\d{1,2}):(\d{2})$/); return m?Number(m[1])*60+Number(m[2]):null;
}
function hm(total:number):string { const n=(total+1440)%1440; return `${String(Math.floor(n/60)).padStart(2,"0")}:${String(n%60).padStart(2,"0")}`; }

async function stateFor(db:D1Database,raceId:string,raceDate:string,startTime:string|null):Promise<State|null>{
  const now=nowJst(); if(raceDate!==now.date)return null;
  const bet=await db.prepare(`SELECT COUNT(*) AS n,SUM(CASE WHEN settlement_status='settled' THEN 1 ELSE 0 END) AS s,MAX(CASE WHEN settlement_status='settled' AND COALESCE(return_yen,0)>0 THEN 1 ELSE 0 END) AS h FROM rt_public_bets WHERE race_id=?`).bind(raceId).first<{n:number;s:number;h:number}>();
  const n=Number(bet?.n??0),s=Number(bet?.s??0),h=Number(bet?.h??0);
  if(n>0){
    if(s===n)return h>0?{code:"hit",label:"的中",message:null}:{code:"miss",label:"不的中",message:null};
    return {code:"buy",label:"買い目あり",message:"確定済みの買い目を表示しています。"};
  }
  const start=minutes(startTime);
  if(start===null)return {code:"pending",label:"判定中",message:"発走15分前までに買い目を確定します。"};
  const deadline=start-15;
  if(now.minutes<deadline)return {code:"pending",label:"判定中",message:`${hm(deadline)}までに買い目を確定します。`};
  if(now.minutes<start)return {code:"overdue",label:"買い目未確定",message:`${hm(deadline)}までに確定予定でしたが、まだ買い目が反映されていません。`};
  return {code:"missing",label:"買い目未生成",message:"このレースは買い目が生成されないまま発走時刻を過ぎています。見送り判定ではありません。"};
}

async function truthfulRaceDetail(request:Request,db:D1Database,response:Response):Promise<Response>{
  const path=new URL(request.url).pathname;
  if(!path.startsWith('/races/')||!response.ok||!response.headers.get('content-type')?.includes('text/html'))return response;
  try{
    const raceId=decodeURIComponent(path.slice('/races/'.length));
    const row=await db.prepare(`SELECT race_date AS raceDate,start_time_jst AS startTime FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<{raceDate:string;startTime:string|null}>();
    if(!row)return response;
    const state=await stateFor(db,raceId,row.raceDate,row.startTime); if(!state)return response;
    let html=await response.text();
    html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing)">[^<]*<\/span>/,`<span class="status ${state.code}">${state.label}</span>`);
    const replacement=state.message?`<div class="notice live-state-note">${state.message}</div>`:'';
    html=html.replace(/<div class="section-title"><h2>買い目<\/h2><span class="status [^"]+">[^<]*<\/span><\/div>(?:<div class="notice">[\s\S]*?<\/div>|<section class="panel"><p>このレースは購入対象に選ばれませんでした。<\/p><\/section>)/,`<div class="section-title"><h2>買い目</h2><span class="status ${state.code}">${state.label}</span></div>${replacement}`);
    const css=`<style>.status.overdue{background:#4a3b1d;color:#f6dda0;border:1px solid #725b28}.status.missing{background:#4a2528;color:#ffc3c3;border:1px solid #784047}.live-state-note{font-size:13px;padding:11px 13px}</style>`;
    html=html.replace('</head>',`${css}</head>`);
    const headers=new Headers(response.headers);headers.delete('content-length');
    return new Response(html,{status:response.status,headers});
  }catch{return response;}
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response('NOT_FOUND',{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    return truthfulRaceDetail(request,env.DB,response);
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
  }
} satisfies ExportedHandler<Env>;
