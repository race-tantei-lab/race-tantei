import publicSite from "./public-site-entry-v16.js";
import { tenYearRaceMap, tenYearRacesOnDate, type TenYearRace } from "./v1/ten-year-history.js";
import { shell } from "./v1/public-ui.js";
import { escapeHtml, formatYen } from "./v1/utils.js";
import type { Env } from "./v1/types.js";

const COURSES=[
  {name:"ライト",budget:2000,scale:1},
  {name:"スタンダード",budget:5000,scale:2.5},
  {name:"プレミアム",budget:10000,scale:5}
] as const;
const RUNNER_BASE="https://raw.githubusercontent.com/race-tantei-lab/race-tantei/main/data/ten-year-runners";

type RawRunner=[
  horseNo:number,frameNo:number,horseName:string|null,sexAge:string|null,assignedWeight:number|null,
  jockey:string|null,trainer:string|null,horseWeight:number|null,weightChange:number|null,popularity:number|null,
  winOdds:number|null,finishPosition:number|null,timeText:string|null,final3f:number|null,runnerStatus:string|null
];
type RawMonth=[raceId:string,runners:RawRunner[]][];

const monthCache=new Map<string,Promise<Map<string,RawRunner[]>>>();
function json(value:unknown,status=200):Response{return new Response(JSON.stringify(value),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store, max-age=0"}});}

function resultState(r:TenYearRace):{code:"buy"|"lose"|"skip";label:"的中"|"不的中"|"見送り"}{
  if(!Array.isArray(r.tickets)||r.tickets.length!==2)return {code:"skip",label:"見送り"};
  const ret=r.tickets.reduce((s,t)=>s+Number(t.returnLightYen||0),0);
  return ret>0?{code:"buy",label:"的中"}:{code:"lose",label:"不的中"};
}

async function monthRunners(month:string):Promise<Map<string,RawRunner[]>>{
  let p=monthCache.get(month);
  if(!p){
    p=(async()=>{
      const res=await fetch(`${RUNNER_BASE}/${month}.json.gz`,{headers:{"accept":"application/octet-stream"}});
      if(!res.ok)throw new Error(`RUNNER_ASSET_HTTP_${res.status}`);
      const bytes=new Uint8Array(await res.arrayBuffer());
      const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      const rows=JSON.parse(await new Response(stream).text()) as RawMonth;
      return new Map(rows.map(([rid,runners])=>[String(rid),runners]));
    })();
    monthCache.set(month,p);
  }
  return p;
}
async function raceRunners(r:TenYearRace):Promise<RawRunner[]>{return (await monthRunners(r.raceDate.slice(0,7))).get(r.raceId)??[];}

function archiveDayRow(r:TenYearRace){
  const state=resultState(r);
  return {raceId:r.raceId,raceDate:r.raceDate,venue:r.venue,raceNo:r.raceNo,raceName:r.raceName,startTimeJst:r.startTimeJst,startTimeUtc:null,surface:r.surface,distanceM:r.distanceM,status:"finished",publicState:{code:state.code,label:state.label,deadline:null}};
}

function runnerTable(rows:RawRunner[]):string{
  if(!rows.length)return `<section class="card"><h2>出走馬</h2><p class="muted">馬情報を取得できませんでした。</p></section>`;
  const body=[...rows].sort((a,b)=>a[0]-b[0]).map((r)=>{
    const [horseNo,frameNo,horseName,sexAge,assignedWeight,jockey,trainer,horseWeight,weightChange,popularity,,finishPosition,,,runnerStatus]=r;
    const weight=horseWeight==null?"—":`${horseWeight}kg${weightChange==null?"":` (${weightChange>=0?"+":""}${weightChange})`}`;
    const finish=runnerStatus&&runnerStatus!=="active"?escapeHtml(runnerStatus):finishPosition==null?"—":`${finishPosition}着`;
    return `<tr><td>${finish}</td><td>${frameNo||"—"}</td><td><b>${horseNo}</b></td><td>${escapeHtml(horseName??"—")}</td><td>${escapeHtml(sexAge??"—")}</td><td>${assignedWeight??"—"}</td><td>${escapeHtml(jockey??"—")}</td><td>${escapeHtml(trainer??"—")}</td><td>${weight}</td><td>${popularity??"—"}</td></tr>`;
  }).join("");
  return `<section class="card"><h2>出走馬・結果</h2><div class="runner-table"><table><thead><tr><th>着順</th><th>枠</th><th>馬番</th><th>馬名</th><th>性齢</th><th>斤量</th><th>騎手</th><th>調教師</th><th>馬体重</th><th>人気</th></tr></thead><tbody>${body}</tbody></table></div></section>`;
}

async function historicalRacePage(r:TenYearRace):Promise<string>{
  const state=resultState(r);const selected=Array.isArray(r.tickets)&&r.tickets.length===2;
  const meta=[r.raceDate.replaceAll("-","/"),r.venue,`${r.raceNo}R`,r.startTimeJst?`${r.startTimeJst}発走`:null,r.surface,r.distanceM?`${r.distanceM}m`:null].filter(Boolean).join("　");
  let bets="";
  if(selected&&r.tickets){
    const blocks=COURSES.map((course,idx)=>{
      const trs=r.tickets!.map((t)=>{const stake=course.budget/2;const ret=Math.round(t.returnLightYen*course.scale);return `<tr><td>${escapeHtml(t.betType)}</td><td>${escapeHtml(t.combination)}</td><td>${t.officialOdds.toFixed(1)}倍</td><td>${formatYen(stake)}</td><td class="${ret>0?"plus":""}">${formatYen(ret)}</td></tr>`;}).join("");
      const totalReturn=Math.round(r.tickets!.reduce((s,t)=>s+t.returnLightYen,0)*course.scale);
      return `<div class="course-view" data-course="${idx}" style="${idx===0?"":"display:none"}"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>${trs}</tbody></table></div><p class="muted">購入 ${formatYen(course.budget)} → 払戻 ${formatYen(totalReturn)}</p></div>`;
    }).join("");
    bets=`<div class="section-title"><h2>確定買い目</h2><span class="status ${state.code}">${state.label}</span></div><div class="course-tabs">${COURSES.map((c,i)=>`<button class="chip${i===0?" active":""}" data-course-tab="${i}">${c.name}</button>`).join("")}</div>${blocks}`;
  }else bets=`<section class="card"><h2>見送り</h2><p class="muted">このレースは完成モデルの買い目対象ではありません。</p></section>`;
  const runners=runnerTable(await raceRunners(r));
  const body=`<a class="back" href="/">← レース一覧へ</a><section class="hero"><div class="race-title"><span class="race-no">${r.raceNo}R</span><h1>${escapeHtml(r.raceName)}</h1><span class="status ${state.code}">${state.label}</span></div><p>${escapeHtml(meta)}</p></section>${bets}${runners}`;
  const script=`<script>document.querySelectorAll('[data-course-tab]').forEach(b=>b.addEventListener('click',()=>{const n=b.getAttribute('data-course-tab');document.querySelectorAll('[data-course-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('[data-course]').forEach(x=>x.style.display=x.getAttribute('data-course')===n?'block':'none';}));</script>`;
  return shell(`${r.venue}${r.raceNo}R`,body).replace("</body></html>",`${script}</body></html>`);
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    const url=new URL(request.url);const path=url.pathname;
    if(path==="/api/public/day"){
      const date=url.searchParams.get("date")??"";
      if(/^20\d{2}-\d{2}-\d{2}$/.test(date)&&date>="2016-08-10"&&date<="2026-08-09")return json({ok:true,date,races:(await tenYearRacesOnDate(date)).map(archiveDayRow)});
    }
    if(path.startsWith("/races/")){
      const rid=decodeURIComponent(path.slice("/races/".length));const race=(await tenYearRaceMap()).get(rid);
      if(race)return new Response(await historicalRacePage(race),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store, max-age=0","x-race-ui-version":"ten-year-completed-v17"}});
    }
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    if(!response.ok)return response;
    const headers=new Headers(response.headers);headers.set("x-race-ui-version","ten-year-completed-v17");headers.delete("content-length");
    return new Response(response.body,{status:response.status,headers});
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
