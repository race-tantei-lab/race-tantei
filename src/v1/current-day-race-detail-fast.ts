import { shell } from "./public-ui.js";

const PATH_VERSION = "current-day-detail-direct-batch-v1-20260921";
const COURSES = ["ライト","スタンダード","プレミアム"] as const;
const BUDGETS: Record<string, number> = {"ライト":2000,"スタンダード":5000,"プレミアム":10000};

type RaceRow = {
  raceId:string; raceDate:string; venue:string; raceNo:number; raceName:string|null;
  startTimeJst:string|null; startTimeUtc:string|null; surface:string|null; distanceM:number|null;
  conditions:string|null; weather:string|null; trackCondition:string|null; status:string|null;
};
type RunnerRow = {
  horseNo:number; horseName:string; sexAge:string|null; jockey:string|null; assignedWeight:number|null;
  trainer:string|null; horseWeight:number|null; weightChange:number|null; winOdds:number|null;
  popularity:number|null; runnerStatus:string|null; finishPosition:number|null; resultStatus:string|null;
};
type BetRow = {
  course:string; betType:string; combination:string; stakeYen:number; assumedOdds:number|null;
  returnYen:number|null; settlementStatus:string; sourcePredictionId:number|null; lockedAt:string|null;
};
type StateRow = { stateKey:string; value:string|null };
type SelectionPayload = { selected?: Array<{raceId?:unknown}> };
type Ticket = {
  betType?:unknown; combination?:unknown; horses?:unknown; predictedProbability?:unknown;
  officialOdds?:unknown; valueProduct?:unknown; score?:unknown;
};
type FinalPayload = { tickets?: Ticket[]; lockedAt?:unknown; generationStartedAt?:unknown };

function jstDate(now=new Date()):string {
  return new Date(now.getTime()+9*3600_000).toISOString().slice(0,10);
}
function esc(value:unknown):string {
  return String(value??"").replace(/[&<>"']/g,(ch)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]??ch));
}
function yen(value:unknown):string {
  const n=Number(value);
  return Number.isFinite(n)?Math.round(n).toLocaleString("ja-JP")+"円":"—";
}
function pct(value:unknown):string {
  const n=Number(value);
  return Number.isFinite(n)?(n*100).toFixed(n>=0.1?1:2)+"%":"—";
}
function clock15(startUtc:string|null):string|null {
  if(!startUtc)return null;
  const ms=Date.parse(startUtc);
  if(!Number.isFinite(ms))return null;
  return new Date(ms-15*60_000+9*3600_000).toISOString().slice(11,16);
}
function selectionState(raw:string|null,raceId:string):{has:boolean;selected:boolean} {
  if(!raw)return {has:false,selected:false};
  try {
    const parsed=JSON.parse(raw) as SelectionPayload;
    if(!Array.isArray(parsed.selected))return {has:false,selected:false};
    return {has:true,selected:parsed.selected.some((x)=>String(x?.raceId??"")===raceId)};
  } catch { return {has:false,selected:false}; }
}
function navHtml(raceId:string,venue:string,raceNo:number):string {
  const prefix=raceId.slice(0,-2);
  const prev=raceNo>1?prefix+String(raceNo-1).padStart(2,"0"):null;
  const next=raceNo<12?prefix+String(raceNo+1).padStart(2,"0"):null;
  return '<nav class="race-sequence-nav" aria-label="前後のレース">'
    +(prev?'<a href="/races/'+encodeURIComponent(prev)+'">← '+esc(venue)+' '+(raceNo-1)+'R</a>':'<span>← 前のレースなし</span>')
    +(next?'<a href="/races/'+encodeURIComponent(next)+'">'+esc(venue)+' '+(raceNo+1)+'R →</a>':'<span>次のレースなし →</span>')
    +'</nav>';
}
function statusView(race:RaceRow,bets:BetRow[],selection:{has:boolean;selected:boolean}) {
  const lower=String(race.status??"").toLowerCase();
  if(["cancelled","canceled","postponed"].includes(lower)) return {code:"skip",label:"中止",note:"このレースは中止・延期です。"};
  const finalRows=bets.filter((b)=>Number(b.sourcePredictionId)===-2).length;
  const allSettled=bets.length>0&&bets.every((b)=>b.settlementStatus==="settled");
  if(allSettled&&bets.some((b)=>Number(b.returnYen??0)>0)) return {code:"hit",label:"的中",note:"精算済み"};
  if(allSettled) return {code:"miss",label:"不的中",note:"精算済み"};
  if(finalRows===6) return {code:"buy",label:"買い目確定",note:"確定済み・以後変更なし"};
  if(selection.selected) {
    const dl=clock15(race.startTimeUtc);
    return {code:"target",label:"買い目対象・確定前",note:dl?dl+"までに確定":"確定前"};
  }
  if(selection.has) return {code:"skip",label:"見送り",note:"このレースは購入対象に選ばれていません。"};
  return {code:"pending",label:"判定中",note:"購入対象レースの判定前です。"};
}
function betHtml(bets:BetRow[]):string {
  if(!bets.length)return "";
  const blocks=COURSES.map((course,index)=>{
    const rows=bets.filter((b)=>b.course===course);
    if(!rows.length)return "";
    return '<div class="course-view" data-course="'+index+'" style="'+(index===0?"":"display:none")+'"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>'
      +rows.map((b)=>'<tr><td>'+esc(b.betType)+'</td><td><b>'+esc(b.combination)+'</b></td><td>'+(b.assumedOdds==null?"—":Number(b.assumedOdds).toFixed(1)+"倍")+'</td><td>'+yen(b.stakeYen)+'</td><td class="'+(Number(b.returnYen??0)>0?"plus":"")+'">'+(b.settlementStatus==="settled"?yen(b.returnYen??0):"—")+'</td></tr>').join("")
      +'</tbody></table></div></div>';
  }).join("");
  if(!blocks)return "";
  return '<div class="section-title"><h2>確定買い目</h2><span class="status buy">固定済み</span></div>'
    +'<div class="course-tabs">'+COURSES.map((c,i)=>'<button class="course-tab '+(i===0?"active":"")+'" data-course-tab="'+i+'">'+c+' '+yen(BUDGETS[c])+'</button>').join("")+'</div>'+blocks;
}
function reasonHtml(finalRaw:string|null,runners:RunnerRow[]):string {
  if(!finalRaw)return "";
  try {
    const parsed=JSON.parse(finalRaw) as FinalPayload;
    if(!Array.isArray(parsed.tickets)||parsed.tickets.length!==2)return "";
    const names=new Map(runners.map((r)=>[Number(r.horseNo),String(r.horseName||"")]));
    const cards=parsed.tickets.map((t)=>{
      const horses=Array.isArray(t.horses)?t.horses.map(Number).filter(Number.isFinite):[];
      const horseText=horses.map((n)=>n+"番 "+(names.get(n)||"")).join(" / ");
      return '<article class="reason-card"><div class="reason-head"><b>'+esc(t.betType)+' '+esc(t.combination)+'</b><span>'+esc(horseText)+'</span></div>'
        +'<div class="reason-metrics"><span>推定確率 <b>'+pct(t.predictedProbability)+'</b></span><span>JRA公式オッズ <b>'+Number(t.officialOdds||0).toFixed(1)+'倍</b></span></div>'
        +'<p>確定時に保存された予測とJRA公式オッズに基づく買い目です。</p></article>';
    }).join("");
    return '<section id="race-panel-reason" class="card reason-panel" data-race-panel="reason" hidden><div class="section-title"><h2>買い目の理由</h2></div>'+cards+'</section>';
  } catch { return ""; }
}
function runnerHtml(runners:RunnerRow[]):string {
  return '<section data-race-panel="horses" class="runner-panel"><div class="section-title"><h2>出走馬</h2><span class="muted">'+runners.length+'頭</span></div><div class="runner-table"><table><thead><tr><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>調教師</th><th>馬体重</th><th>単勝</th><th>人気</th><th>結果</th></tr></thead><tbody>'
    +runners.map((r)=>'<tr><td><span class="horse-no">'+Number(r.horseNo)+'</span></td><td><b>'+esc(r.horseName)+'</b></td><td>'+esc(r.sexAge??"—")+'</td><td>'+esc(r.jockey??"—")+(r.assignedWeight==null?"":'<br><span class="muted">'+Number(r.assignedWeight)+'kg</span>')+'</td><td>'+esc(r.trainer??"—")+'</td><td>'+(r.horseWeight==null?"—":Number(r.horseWeight)+'kg'+(r.weightChange==null?"":' ('+(Number(r.weightChange)>=0?"+":"")+Number(r.weightChange)+')'))+'</td><td>'+(r.winOdds==null?"—":Number(r.winOdds).toFixed(1)+"倍")+'</td><td>'+(r.popularity==null?"—":Number(r.popularity)+"番人気")+'</td><td>'+(r.finishPosition==null?esc(r.resultStatus??"—"):Number(r.finishPosition)+"着")+'</td></tr>').join("")
    +'</tbody></table></div></section>';
}
function styles():string {
  return '<style>.status.hit{background:#124b37;color:#bdf5dc;border:1px solid #287d5b}.status.miss{background:#4a2528;color:#ffc3c3;border:1px solid #784047}.status.target{background:#15483a;color:#baf4dd;border:1px solid #2d806c}.race-sequence-nav{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0 0 12px}.race-sequence-nav a,.race-sequence-nav span{padding:9px 10px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);font-size:12px;text-align:center}.race-final-note{padding:10px 12px;margin:-5px 0 14px;border:1px solid var(--line);border-radius:12px;background:var(--panel2);font-size:12px;color:var(--muted)}.race-detail-tabs{display:flex;gap:7px;margin:12px 0}.race-detail-tabs button{border:1px solid var(--line);border-radius:999px;background:var(--panel2);color:var(--text);padding:8px 11px;font:inherit}.race-detail-tabs button.active{border-color:var(--green);background:var(--green2)}.reason-panel{padding:14px}.reason-card{padding:12px 0;border-bottom:1px solid var(--line)}.reason-card:last-child{border-bottom:0}.reason-head{display:grid;gap:4px}.reason-head span,.reason-card p{font-size:11px;color:var(--muted);line-height:1.6}.reason-metrics{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.reason-metrics span{padding:6px 8px;border:1px solid var(--line);border-radius:9px;font-size:10px}.reason-metrics b{color:var(--green)}@media(max-width:760px){.race-sequence-nav a,.race-sequence-nav span{font-size:10px}.runner-table table{min-width:720px}}</style>';
}
function script():string {
  return '<script>(()=>{const buttons=[...document.querySelectorAll("[data-race-tab]")],panels=[...document.querySelectorAll("[data-race-panel]")];if(!buttons.length)return;function open(name){buttons.forEach(b=>b.classList.toggle("active",b.dataset.raceTab===name));panels.forEach(p=>p.hidden=p.getAttribute("data-race-panel")!==name)}buttons.forEach(b=>b.addEventListener("click",()=>open(b.dataset.raceTab||"bets")));open("bets")})();</script>';
}

export async function fastCurrentDayRaceDetailResponse(db:D1Database,raceId:string,now=new Date()):Promise<Response|null> {
  const raceDate=raceId.slice(0,10);
  if(!/^20\d{2}-\d{2}-\d{2}$/.test(raceDate)||raceDate!==jstDate(now))return null;

  const finalKey="worker_live_final:"+raceId;
  const selectionKey="final_daily_selection:"+raceDate;
  const results=await db.batch([
    db.prepare(`SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,surface,distance_m AS distanceM,conditions,weather,track_condition AS trackCondition,status FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId),
    db.prepare(`SELECT r.horse_no AS horseNo,r.horse_name AS horseName,r.sex_age AS sexAge,r.jockey,r.assigned_weight AS assignedWeight,r.trainer,r.horse_weight AS horseWeight,r.weight_change AS weightChange,r.win_odds AS winOdds,r.popularity,r.runner_status AS runnerStatus,x.finish_position AS finishPosition,x.result_status AS resultStatus FROM rt_runners r LEFT JOIN rt_results x ON x.race_id=r.race_id AND x.horse_no=r.horse_no WHERE r.race_id=? ORDER BY r.horse_no`).bind(raceId),
    db.prepare(`SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,return_yen AS returnYen,settlement_status AS settlementStatus,source_prediction_id AS sourcePredictionId,locked_at AS lockedAt FROM rt_public_bets WHERE race_id=? ORDER BY CASE course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 ELSE 3 END,id`).bind(raceId),
    db.prepare(`SELECT state_key AS stateKey,state_value AS value FROM rt_system_state WHERE state_key IN (?,?)`).bind(finalKey,selectionKey),
  ]);

  const race=((results[0].results??[])[0]??null) as RaceRow|null;
  if(!race)return null;
  race.raceNo=Number(race.raceNo); race.distanceM=race.distanceM==null?null:Number(race.distanceM);
  const runners=(results[1].results??[]).map((x)=>x as unknown as RunnerRow).map((r)=>({...r,horseNo:Number(r.horseNo),finishPosition:r.finishPosition==null?null:Number(r.finishPosition)}));
  const bets=(results[2].results??[]).map((x)=>x as unknown as BetRow).map((b)=>({...b,stakeYen:Number(b.stakeYen),assumedOdds:b.assumedOdds==null?null:Number(b.assumedOdds),returnYen:b.returnYen==null?null:Number(b.returnYen),sourcePredictionId:b.sourcePredictionId==null?null:Number(b.sourcePredictionId)}));
  const states=new Map((results[3].results??[]).map((x)=>x as unknown as StateRow).map((s)=>[String(s.stateKey),s.value] as const));
  const selection=selectionState(states.get(selectionKey)??null,raceId);
  const view=statusView(race,bets,selection);
  const meta=[race.raceDate.replaceAll("-","/"),race.venue,race.raceNo+"R",race.startTimeJst?race.startTimeJst+"発走":null,race.surface,race.distanceM?race.distanceM+"m":null,race.trackCondition].filter(Boolean).join("　");
  const reasons=reasonHtml(states.get(finalKey)??null,runners);
  const betsBlock=betHtml(bets);
  const hasReasons=Boolean(reasons);
  const tabNav='<nav class="race-detail-tabs"><button type="button" class="active" data-race-tab="bets">予想買い目</button>'+(hasReasons?'<button type="button" data-race-tab="reason">買い目の理由</button>':'')+'<button type="button" data-race-tab="horses">出走馬</button></nav>';
  const betsPanel='<section data-race-panel="bets">'+(betsBlock||'<div class="section-title"><h2>買い目</h2><span class="status '+view.code+'">'+view.label+'</span></div><div class="notice">'+esc(view.note)+'</div>')+'</section>';
  const body='<a class="back" href="/">← レース一覧へ</a>'+navHtml(raceId,race.venue,race.raceNo)
    +'<section class="hero today-hero"><div class="race-title"><span class="race-no">'+race.raceNo+'R</span><h1>'+esc(race.raceName||race.raceNo+"R")+'</h1><span class="status '+view.code+'">'+view.label+'</span></div><p>'+esc(meta)+'</p>'+(race.conditions?'<p>'+esc(race.conditions)+'</p>':'')+'</section>'
    +'<div class="race-final-note">'+esc(view.note)+'</div>'+tabNav+betsPanel+reasons+runnerHtml(runners);
  let html=shell(race.venue+race.raceNo+"R",body);
  html=html.replace("</head>",styles()+"</head>").replace("</body>",script()+"</body>");
  return new Response(html,{status:200,headers:{
    "content-type":"text/html; charset=utf-8",
    "cache-control":"no-store, max-age=0",
    "x-race-detail-path":PATH_VERSION,
    "x-race-ui-version":"ten-year-completed-public-v37-direct-current-detail-20260921",
    "x-content-type-options":"nosniff",
    "referrer-policy":"no-referrer"
  }});
}
