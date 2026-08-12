import publicSite from "./public-site-entry-v15.js";
import { TEN_YEAR_HISTORY_END, TEN_YEAR_HISTORY_START, tenYearCalendar, tenYearRaceMap, tenYearRacesOnDate, type TenYearRace } from "./v1/ten-year-history.js";
import { shell } from "./v1/public-ui.js";
import { escapeHtml, formatYen } from "./v1/utils.js";
import type { Env } from "./v1/types.js";

const COURSES=[
  {name:"ライト",budget:2000,scale:1},
  {name:"スタンダード",budget:5000,scale:2.5},
  {name:"プレミアム",budget:10000,scale:5}
] as const;

type CalendarRow={raceDate:string;venue:string;raceCount:number};

function json(value:unknown,status=200):Response{
  return new Response(JSON.stringify(value),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store, max-age=0"}});
}

function inArchive(date:string):boolean{return date>=TEN_YEAR_HISTORY_START&&date<=TEN_YEAR_HISTORY_END;}

async function liveCalendar(db:D1Database):Promise<CalendarRow[]>{
  try{
    const rows=await db.prepare(`SELECT race_date AS raceDate,venue,COUNT(*) AS raceCount FROM rt_races WHERE race_date>? GROUP BY race_date,venue ORDER BY race_date,venue`).bind(TEN_YEAR_HISTORY_END).all<CalendarRow>();
    return rows.results.map((r)=>({...r,raceCount:Number(r.raceCount)}));
  }catch{return [];}
}

async function fullCalendar(db:D1Database):Promise<CalendarRow[]>{
  return [...await tenYearCalendar(),...await liveCalendar(db)].sort((a,b)=>a.raceDate.localeCompare(b.raceDate)||a.venue.localeCompare(b.venue));
}

function archiveDayRow(r:TenYearRace){
  const selected=Array.isArray(r.tickets)&&r.tickets.length===2;
  return {
    raceId:r.raceId,raceDate:r.raceDate,venue:r.venue,raceNo:r.raceNo,raceName:r.raceName,startTimeJst:r.startTimeJst,startTimeUtc:null,
    surface:r.surface,distanceM:r.distanceM,status:"finished",
    publicState:{code:selected?"buy":"skip",label:selected?"買い目あり":"見送り",deadline:null}
  };
}

function historicalDay(date:string,rows:TenYearRace[]):Response{
  return json({ok:true,date,races:rows.map(archiveDayRow)});
}

function historicalRacePage(r:TenYearRace):string{
  const selected=Array.isArray(r.tickets)&&r.tickets.length===2;
  const meta=[r.raceDate.replaceAll("-","/"),r.venue,`${r.raceNo}R`,r.startTimeJst?`${r.startTimeJst}発走`:null,r.surface,r.distanceM?`${r.distanceM}m`:null].filter(Boolean).join("　");
  let bets="";
  if(selected&&r.tickets){
    const blocks=COURSES.map((course,idx)=>{
      const rows=r.tickets!.map((t)=>{
        const stake=course.budget/2;
        const ret=Math.round(t.returnLightYen*course.scale);
        return `<tr><td>${escapeHtml(t.betType)}</td><td>${escapeHtml(t.combination)}</td><td>${t.officialOdds.toFixed(1)}倍</td><td>${formatYen(stake)}</td><td class="${ret>0?"plus":""}">${formatYen(ret)}</td></tr>`;
      }).join("");
      const totalReturn=Math.round(r.tickets!.reduce((s,t)=>s+t.returnLightYen,0)*course.scale);
      return `<div class="course-view" data-course="${idx}" style="${idx===0?"":"display:none"}"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>${rows}</tbody></table></div><p class="muted">購入 ${formatYen(course.budget)} → 払戻 ${formatYen(totalReturn)}</p></div>`;
    }).join("");
    bets=`<div class="section-title"><h2>確定買い目</h2><span class="status buy">固定済み</span></div><div class="course-tabs">${COURSES.map((c,i)=>`<button class="chip${i===0?" active":""}" data-course-tab="${i}">${c.name}</button>`).join("")}</div>${blocks}`;
  }else{
    bets=`<section class="card"><h2>見送り</h2><p class="muted">このレースは完成モデルの買い目対象ではありません。</p></section>`;
  }
  const body=`<a class="back" href="/">← レース一覧へ</a><section class="hero"><div class="race-title"><span class="race-no">${r.raceNo}R</span><h1>${escapeHtml(r.raceName)}</h1><span class="status ${selected?"buy":"skip"}">${selected?"買い目あり":"見送り"}</span></div><p>${escapeHtml(meta)}</p></section>${bets}`;
  const script=`<script>document.querySelectorAll('[data-course-tab]').forEach(b=>b.addEventListener('click',()=>{const n=b.getAttribute('data-course-tab');document.querySelectorAll('[data-course-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('[data-course]').forEach(x=>x.style.display=x.getAttribute('data-course')===n?'block':'none';}));</script>`;
  return shell(`${r.venue}${r.raceNo}R`,body).replace("</body></html>",`${script}</body></html>`);
}

function injectCalendar(html:string,calendar:CalendarRow[]):string{
  const payload=JSON.stringify(calendar).replace(/</g,"\\u003c");
  return html.replace(/const calendar=\[[\s\S]*?\];const today=/,`const calendar=${payload};const today=`);
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    const url=new URL(request.url);const path=url.pathname;
    if(path==="/api/public/calendar")return json({ok:true,calendar:await fullCalendar(env.DB)});
    if(path==="/api/public/day"){
      const date=url.searchParams.get("date")??"";
      if(/^20\d{2}-\d{2}-\d{2}$/.test(date)&&inArchive(date))return historicalDay(date,await tenYearRacesOnDate(date));
    }
    if(path.startsWith("/races/")){
      const rid=decodeURIComponent(path.slice("/races/".length));const race=(await tenYearRaceMap()).get(rid);
      if(race)return new Response(historicalRacePage(race),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store, max-age=0","x-race-ui-version":"ten-year-completed-v16"}});
    }
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const upstream=await publicSite.fetch(request,env,ctx);
    if(path!=="/"||!upstream.ok||!upstream.headers.get("content-type")?.includes("text/html"))return upstream;
    try{
      const headers=new Headers(upstream.headers);headers.delete("content-length");headers.set("cache-control","no-store, max-age=0");headers.set("x-race-ui-version","ten-year-completed-v16");
      return new Response(injectCalendar(await upstream.text(),await fullCalendar(env.DB)),{status:upstream.status,headers});
    }catch{return upstream;}
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
