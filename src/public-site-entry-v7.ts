import publicSite from "./public-site-entry-v6.js";
import type { Env } from "./v1/types.js";

const AUG9_SELECTED = new Set([
  "2026-08-09-chukyo-01","2026-08-09-chukyo-05","2026-08-09-chukyo-07","2026-08-09-chukyo-08","2026-08-09-chukyo-11",
  "2026-08-09-niigata-01","2026-08-09-niigata-03","2026-08-09-niigata-07","2026-08-09-niigata-11","2026-08-09-niigata-12",
  "2026-08-09-sapporo-01","2026-08-09-sapporo-02","2026-08-09-sapporo-05","2026-08-09-sapporo-06","2026-08-09-sapporo-09",
]);
const AUG9_SYNC_RESUME_UTC = Date.parse("2026-08-09T09:35:00Z"); // 18:35 JST, after all corrected live locks.
const COURSE_NAMES = ["ライト","スタンダード","プレミアム"] as const;

type LiveBet = {course:string;betType:string;combination:string;stakeYen:number;assumedOdds:number|null;returnYen:number|null;settlementStatus:string};

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch] ?? ch));
}
function yen(value:number):string{return `¥${Math.round(value).toLocaleString("ja-JP")}`;}
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

async function liveRaceIds(db:D1Database):Promise<Set<string>>{
  try{
    const q=await db.prepare("SELECT DISTINCT race_id AS raceId FROM rt_public_bets WHERE race_id LIKE '2026-08-09-%'").all<{raceId:string}>();
    return new Set(q.results.map(x=>String(x.raceId)));
  }catch{return new Set();}
}
async function liveBets(db:D1Database,raceId:string):Promise<LiveBet[]>{
  try{
    const q=await db.prepare(`SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,return_yen AS returnYen,settlement_status AS settlementStatus FROM rt_public_bets WHERE race_id=? ORDER BY CASE course WHEN 'ライト' THEN 0 WHEN 'スタンダード' THEN 1 ELSE 2 END,id`).bind(raceId).all<LiveBet>();
    return q.results.map(x=>({...x,stakeYen:Number(x.stakeYen),assumedOdds:x.assumedOdds===null?null:Number(x.assumedOdds),returnYen:x.returnYen===null?null:Number(x.returnYen)}));
  }catch{return [];}
}

function targetState(race: Record<string, any>, locked:Set<string>): Record<string, any> {
  const current = race.publicState ?? {};
  const raceId = String(race.raceId ?? "");
  if (locked.has(raceId) || current.code === "hit" || current.code === "miss" || current.code === "buy") return {code:"buy",label:"買い目あり",deadline:null};
  if (!AUG9_SELECTED.has(raceId)) return { code:"skip", label:"見送り", deadline:null };
  const start = parseTime(race.startTimeJst);
  if (start === null) return { code:"target", label:"買い目対象", deadline:"発走15分前までに買い目確定" };
  const deadline = start - 15;
  const now = jstMinutes();
  if (now < deadline) return { code:"target", label:"買い目対象", deadline:`${clock(deadline)}までに買い目確定` };
  if (now < start) return { code:"overdue", label:"買い目未確定", deadline:`${clock(deadline)}までに確定予定（未反映）` };
  return { code:"missing", label:"買い目未生成", deadline:null };
}

async function fixDayApi(response: Response, db:D1Database): Promise<Response> {
  if (!response.ok) return response;
  try {
    const data = await response.clone().json() as {date?:string;races?:Array<Record<string,any>>;[k:string]:any};
    if (data.date !== "2026-08-09" || !Array.isArray(data.races)) return response;
    const locked=await liveRaceIds(db);
    data.races = data.races.map(race => ({...race, publicState: targetState(race,locked)}));
    const headers = new Headers(response.headers); headers.delete("content-length"); headers.set("content-type","application/json; charset=utf-8");
    return new Response(JSON.stringify(data), {status:response.status, headers});
  } catch { return response; }
}

function liveBetHtml(rows:LiveBet[]):string{
  const blocks=COURSE_NAMES.map((course,idx)=>{
    const bets=rows.filter(x=>x.course===course);
    const body=bets.map(x=>`<tr><td>${esc(x.betType)}</td><td>${esc(x.combination)}</td><td>${x.assumedOdds===null?"—":`${x.assumedOdds.toFixed(1)}倍`}</td><td>${yen(x.stakeYen)}</td><td class="${Number(x.returnYen??0)>0?"plus":""}">${x.settlementStatus==="settled"?yen(Number(x.returnYen??0)):"—"}</td></tr>`).join("");
    return `<div class="live-course" data-live-course="${idx}" style="${idx===0?"":"display:none"}"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
  }).join("");
  const tabs=COURSE_NAMES.map((name,idx)=>`<button type="button" class="live-course-tab${idx===0?" active":""}" data-live-tab="${idx}">${name}</button>`).join("");
  return `<div class="section-title"><h2>確定買い目</h2><span class="status buy">固定済み</span></div><div class="live-course-tabs">${tabs}</div>${blocks}`;
}

async function fixRaceDetail(request:Request,response:Response,db:D1Database):Promise<Response>{
  const path=new URL(request.url).pathname;
  if(!path.startsWith("/races/2026-08-09-")||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
  try{
    const raceId=decodeURIComponent(path.slice("/races/".length));
    let html=await response.text();
    const rows=await liveBets(db,raceId);
    if(rows.length>0){
      const replacement=liveBetHtml(rows);
      html=html.replace(/<div class="section-title"><h2>(?:確定)?買い目<\/h2>[\s\S]*?(?=<div class="section-title"><h2>出走馬)/,replacement);
      html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/,'<span class="status buy">買い目あり</span>');
      html=html.replace("</body>",`<script>document.querySelectorAll('[data-live-tab]').forEach(b=>b.addEventListener('click',()=>{const i=b.getAttribute('data-live-tab');document.querySelectorAll('[data-live-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('[data-live-course]').forEach(x=>x.style.display=x.getAttribute('data-live-course')===i?'block':'none');}));</script></body>`);
    }else if(!AUG9_SELECTED.has(raceId)){
      html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/g,'<span class="status skip">見送り</span>');
      html=html.replace(/<div class="section-title"><h2>買い目<\/h2>[\s\S]*?(?=<div class="section-title"><h2>出走馬)/, '<div class="section-title"><h2>買い目</h2><span class="status skip">見送り</span></div><section class="panel compact-bet-note"><p>前日に固定した5レースの対象外です。</p></section>');
    } else {
      const m=html.match(/(\d{1,2}):(\d{2})発走/); const start=m?Number(m[1])*60+Number(m[2]):null;
      const deadline=start===null?null:start-15; const now=jstMinutes();
      let code="target",label="買い目対象",message=deadline===null?"発走15分前までに買い目を確定します。":`${clock(deadline)}までに買い目を確定します。`;
      if(start!==null&&now>=deadline!&&now<start){code="overdue";label="買い目未確定";message=`${clock(deadline!)}までに確定予定でしたが、まだ反映されていません。`;}
      if(start!==null&&now>=start){code="missing";label="買い目未生成";message="前日選定では購入対象でしたが、買い目が固定されないまま発走時刻を過ぎています。";}
      if(!/class="status (?:buy|hit|miss)"/.test(html)){
        html=html.replace(/<span class="status (?:skip|pending|overdue|missing|target)">[^<]*<\/span>/g,`<span class="status ${code}">${label}</span>`);
        html=html.replace(/<div class="section-title"><h2>買い目<\/h2>[\s\S]*?(?=<div class="section-title"><h2>出走馬)/,`<div class="section-title"><h2>買い目</h2><span class="status ${code}">${label}</span></div><div class="notice compact-bet-note">${message}</div>`);
      }
    }
    html=html.replace("</head>",`<style>.status.target{background:#15483a;color:#baf4dd;border:1px solid #2d806c}.compact-bet-note{padding:9px 12px!important;margin:6px 0!important;font-size:12px!important}.compact-bet-note p{margin:0!important}.live-course-tabs{display:flex;gap:6px;margin:8px 0}.live-course-tab{flex:1;padding:8px;border-radius:9px;border:1px solid #334155;background:#111827;color:#cbd5e1;font-weight:700}.live-course-tab.active{background:#e5e7eb;color:#111827}</style></head>`);
    const headers=new Headers(response.headers);headers.delete("content-length");return new Response(html,{status:response.status,headers});
  }catch{return response;}
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const path=new URL(request.url).pathname;
    let response=await publicSite.fetch(request,env,ctx);
    if(path==="/api/public/day"&&new URL(request.url).searchParams.get("date")==="2026-08-09") response=await fixDayApi(response,env.DB);
    response=await fixRaceDetail(request,response,env.DB);
    return response;
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    // A malformed entry parser was overwriting validated race-program metadata during live locks.
    // Freeze the destructive sync only until all 2026-08-09 lock deadlines pass; resume automatically afterward.
    if(Date.now()<AUG9_SYNC_RESUME_UTC)return;
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
  }
} satisfies ExportedHandler<Env>;
