function selectionKey(mode:IndependentMode,date:string):string{return "independent_selection:"+mode+":"+date;}
import {canFreezeIndependent,INDEPENDENT_SOURCE_VERSION,settleIndependent,type IndependentMode,type IndependentFinal,type IndependentSelection} from "./v1/independent-rolling-core.js";
import {modelNavigation,MODEL_SWITCH_CSS} from "./three-model-full-pages.js";

type RaceStatus={raceId:string;raceDate:string;venue:string;raceNo:number;status:string;startTimeUtc:string|null};
type Paid={raceId:string;betType:string;combination:string;payoutYen:number};
type DaySnapshot={selection:IndependentSelection|null;finals:Map<string,IndependentFinal>;races:RaceStatus[];paid:Map<string,Paid[]>};
const COURSES=["ライト","スタンダード","プレミアム"] as const;
const BUDGETS=[2000,5000,10000] as const;
function esc(x:unknown):string{return String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]||c));}
function yen(x:number):string{return Math.round(x).toLocaleString("ja-JP")+"円";}
function today():string{return new Date(Date.now()+9*3600_000).toISOString().slice(0,10);}
function validDate(date:string):boolean{return /^20\d{2}-\d{2}-\d{2}$/.test(date)&&!Number.isNaN(Date.parse(date+"T00:00:00Z"));}
function finalPrefix(mode:IndependentMode,date:string):string{return "independent_final:"+mode+":"+date+"-";}

export async function daySnapshot(db:D1Database,mode:IndependentMode,date:string):Promise<DaySnapshot>{
 if(!validDate(date))throw Error("INVALID_MODEL_DAY");
 const prefix=finalPrefix(mode,date);
 const [selection,finalRows,races,payouts]=await Promise.all([
   db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(selectionKey(mode,date)).first<{value:string}>(),
   db.prepare("SELECT state_key AS key,state_value AS value FROM rt_system_state WHERE state_key>=? AND state_key<?").bind(prefix,prefix+"~").all<{key:string;value:string}>(),
   db.prepare("SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,status,start_time_utc AS startTimeUtc FROM rt_races WHERE race_date=? ORDER BY venue,race_no").bind(date).all<RaceStatus>(),
   db.prepare("SELECT p.race_id AS raceId,p.bet_type AS betType,p.combination,p.payout_yen AS payoutYen FROM rt_payouts p JOIN rt_races r ON r.race_id=p.race_id WHERE r.race_date=?").bind(date).all<Paid>()
 ]);
 const selected=selection?.value?JSON.parse(selection.value) as IndependentSelection:null;
 const finals=new Map<string,IndependentFinal>();
 for(const x of finalRows.results||[]){
  try{
   const f=JSON.parse(x.value) as IndependentFinal;
   if(f.mode===mode&&f.date===date&&f.sourceModel===INDEPENDENT_SOURCE_VERSION&&
      canFreezeIndependent(f.startTimeUtc,f.oddsFetchedAt,f.lockedAt)&&
      f.courseBets.length===6&&f.tickets.length===2)finals.set(f.raceId,f);
  }catch{ /* ignore malformed immutable state; never show a broken wager */ }
 }
 const paid=new Map<string,Paid[]>();
 for(const p of payouts.results||[]){const arr=paid.get(p.raceId)||[];arr.push(p);paid.set(p.raceId,arr);}
 return {selection:selected?.sourceModel===INDEPENDENT_SOURCE_VERSION?selected:null,finals,races:races.results||[],paid};
}
function paidFor(d:DaySnapshot,raceId:string,course="ライト"){
 const final=d.finals.get(raceId),r=d.races.find(x=>x.raceId===raceId);
 if(!final||!r)return null;
 return settleIndependent(final,d.paid.get(raceId)||[],r.status==="finished"&&(d.paid.get(raceId)||[]).length>0,course);
}
export function snapshotStatus(d:DaySnapshot,raceId:string){
 const r=d.races.find(x=>x.raceId===raceId);
 const final=d.finals.get(raceId);
 if(final){
   const p=paidFor(d,raceId);
   if(p)return {code:p.hit?"hit":"miss",label:p.hit?"的中":"不的中",deadline:null};
   return {code:"buy",label:"買い目確定",deadline:null};
 }
 const ids=new Set(d.selection?.selected.map(x=>x.raceId)||[]);
 if(ids.has(raceId)){
   const start=Date.parse(String(r?.startTimeUtc||""));
   if(Number.isFinite(start)&&Date.now()>=start-15*60*1000)
     return {code:"none",label:"買い目未確定",deadline:null};
   return {code:"target",label:"買い目対象・確定前",deadline:"発走15分前までに確定"};
 }
 if(d.selection)return {code:"skip",label:"見送り",deadline:null};
 return {code:"pending",label:"判定中",deadline:null};
}
export function summaryForDay(date:string,d:DaySnapshot){
 const courses=COURSES.map(course=>{
  let finalizedRaces=0,settledRaces=0,hitRaces=0,stake=0,settledStakeYen=0,returnYen=0;
  for(const [raceId,final] of d.finals){
   const bets=final.courseBets.filter(x=>x.course===course);
   if(bets.length!==2)continue;
   finalizedRaces++;stake+=bets.reduce((a,b)=>a+b.stakeYen,0);
   const outcome=paidFor(d,raceId,course);
   if(outcome){settledRaces++;settledStakeYen+=outcome.stake;returnYen+=outcome.paid;if(outcome.hit)hitRaces++;}
  }
  return {course,finalizedRaces,settledRaces,hitRaces,refundRaces:0,finalizedStakeYen:stake,
   settledStakeYen,returnYen,pendingStakeYen:stake-settledStakeYen,
   profitYen:returnYen-settledStakeYen,roiPct:settledStakeYen?100*returnYen/settledStakeYen:null};
 });
 return {...courses[0],date,courses,targetRaces:d.selection?.selected.length||0};
}
export async function independentDayApi(db:D1Database,mode:IndependentMode,date:string,original:unknown):Promise<Response>{
 const day=await daySnapshot(db,mode,date);
 const raw=(original&&typeof original==="object"?original:{} ) as {races?:Array<Record<string,unknown>>};
 const races=(raw.races||[]).map(r=>({...r,publicState:snapshotStatus(day,String(r.raceId||""))}));
 return Response.json({...raw,ok:true,date,races,betStateAvailable:true},
 {headers:{"cache-control":"no-store, max-age=0","x-race-independent-model":mode}});
}
export async function independentPerformance(db:D1Database,mode:IndependentMode,date:string):Promise<Response>{
 const snap=await daySnapshot(db,mode,date);
 const summary=summaryForDay(date,snap);
 const prefix="independent_selection:"+mode+":";
 const rows=await db.prepare("SELECT state_key AS key FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key DESC LIMIT 30")
   .bind(prefix,prefix+"~").all<{key:string}>();
 const days:typeof summary[]=[];
 for(const row of rows.results||[]){
  const d=row.key.slice(prefix.length);
  if(!validDate(d))continue;
  days.push(d===date?summary:summaryForDay(d,await daySnapshot(db,mode,d)));
 }
 if(!days.some(x=>x.date===date))days.unshift(summary);
 return Response.json({ok:true,today:today(),summary,history:days,version:"independent-daily-performance-v1"},
  {headers:{"cache-control":"no-store, max-age=0"}});
}
type Aggregate={races:number;stake:number;paid:number};
function addAggregate(a:Aggregate,stake:number,paid:number):void{a.races++;a.stake+=stake;a.paid+=paid;}
function aggregateRow(a:Aggregate):string{return a.stake?(100*a.paid/a.stake).toFixed(1)+"%":"—";}
async function aggregateIndependent(db:D1Database,mode:IndependentMode){
 const prefix="independent_selection:"+mode+":";
 const keys=await db.prepare("SELECT state_key AS key FROM rt_system_state WHERE state_key>=? AND state_key<? ORDER BY state_key DESC LIMIT 60")
  .bind(prefix,prefix+"~").all<{key:string}>();
 const total:Aggregate={races:0,stake:0,paid:0};
 const months=new Map<string,Aggregate>(),venues=new Map<string,Aggregate>();
 for(const row of keys.results||[]){
  const date=row.key.slice(prefix.length);
  if(!validDate(date))continue;
  const snap=await daySnapshot(db,mode,date);
  for(const [id] of snap.finals){
   const p=paidFor(snap,id);
   if(!p)continue;
   addAggregate(total,p.stake,p.paid);
   const m=months.get(date.slice(0,7))||{races:0,stake:0,paid:0};
   addAggregate(m,p.stake,p.paid);months.set(date.slice(0,7),m);
   const venue=snap.races.find(r=>r.raceId===id)?.venue||"";
   if(venue){
    const v=venues.get(venue)||{races:0,stake:0,paid:0};
    addAggregate(v,p.stake,p.paid);venues.set(venue,v);
   }
  }
 }
 return {total,months,venues};
}
type AggregateSummary=Awaited<ReturnType<typeof aggregateIndependent>>;
function aggregateMarkup(a:AggregateSummary){
 const monthly=[...a.months].sort((x,y)=>y[0].localeCompare(x[0])).map(([month,row])=>
  '<div class="monthly-row"><b>'+esc(month.replace("-","/"))+'</b><span>'+row.races+'R</span><strong class="'+(row.paid>=row.stake?"plus":"minus")+'">'+aggregateRow(row)+'</strong></div>').join("");
 const metrics='<section class="metrics shared-roi"><details class="card metric"><summary><b>全体</b><strong>'+aggregateRow(a.total)+'</strong><small>'+a.total.races.toLocaleString("ja-JP")+'R　購入 '+yen(a.total.stake)+'　払戻 '+yen(a.total.paid)+'</small></summary><div class="monthly">'+monthly+'</div></details></section>';
 const venueCards=[...a.venues].sort((x,y)=>x[0].localeCompare(y[0],"ja")).map(([name,v])=>
  '<article class="venue-roi-card"><div class="venue-roi-head"><b>'+esc(name)+'</b><span>'+v.races+'R</span></div><strong class="venue-roi-value '+(v.paid>=v.stake?"venue-roi-plus":"venue-roi-minus")+'">'+aggregateRow(v)+'</strong></article>').join("");
 const venues='<div class="section-title venue-roi-title"><h2>会場別回収率</h2><span class="muted">'+a.total.races+'R</span></div><div class="venue-roi-rail shared-venue-roi">'+venueCards+'</div>';
 return {metrics,venues};
}
function footerCss(html:string):string{
 // The ORIGINAL UI stylesheet is preserved byte-for-byte; only the original
 // canonical three-model switcher stylesheet is added.
 return html.includes(".prediction-model-tabs{")?html:html.replace("</head>",MODEL_SWITCH_CSS+"</head>");
}
function sameModelNavigation(html:string,mode:IndependentMode,raceId?:string):string{
 const nav=modelNavigation(mode,undefined,raceId);
 const old=html.indexOf('<nav class="prediction-model-tabs"');
 if(old>=0){const end=html.indexOf("</nav>",old);if(end>old)return html.slice(0,old)+nav+html.slice(end+6);}
 return html.replace("</header>","</header>"+nav);
}
function replaceBlock(html:string,startMark:string,endMark:string,replacement:string):string{
 const a=html.indexOf(startMark);
 if(a<0)return html;
 const b=html.indexOf(endMark,a+startMark.length);
 if(b<0)return html;
 return html.slice(0,a)+replacement+html.slice(b);
}
export function identicalHomeUi(html:string,mode:IndependentMode,aggregation?:AggregateSummary):string{
 const base="/models/"+(mode==="cash6"?"6m":"96m");
 let out=sameModelNavigation(html,mode);
 out=footerCss(out);
 // The HTML/CSS, event handlers, button labels, chips, 12-race rail and
 // existing homepage layout are the SAME source as the canonical '/' screen.
 out=out.replaceAll('"/api/public/day?date="','"'+base+'/api/public/day?date="');
 out=out.replaceAll("'/api/public/daily-performance?date='","'"+base+"/api/public/daily-performance?date='");
 out=out.replaceAll('a.href="/races/"','a.href="'+base+'/races/"');
 // Never display legacy historical ROI as if it were this newly independent model.
 const displayed=aggregateMarkup(aggregation||{total:{races:0,stake:0,paid:0},months:new Map(),venues:new Map()});
 out=replaceBlock(out,'<section class="metrics shared-roi">','<div class="section-title venue-roi-title">',displayed.metrics);
 out=replaceBlock(out,'<div class="section-title venue-roi-title">','<section class="daily-performance-wrap"',displayed.venues);
 // Dynamic model performance is rendered by the identical original UI script.
 return out;
}
function courseBlock(final:IndependentFinal|null,view:ReturnType<typeof snapshotStatus>):string{
 if(!final)return '<div class="section-title"><h2>買い目</h2><span class="status '+esc(view.code)+'">'+esc(view.label)+'</span></div>';
 const blocks=COURSES.map((course,i)=>{
  const rows=final.courseBets.filter(b=>b.course===course);
  return '<div class="course-view" data-course="'+i+'" style="'+(i===0?"":"display:none")+'"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>'+
   rows.map(b=>'<tr><td>'+esc(b.betType)+'</td><td><b>'+esc(b.combination)+'</b></td><td>'+b.assumedOdds.toFixed(1)+'倍</td><td>'+yen(b.stakeYen)+'</td><td>—</td></tr>').join("")+
   '</tbody></table></div></div>';
 }).join("");
 return '<div class="section-title"><h2>確定買い目</h2><span class="status buy">固定済み</span></div>'+
 '<div class="course-tabs">'+COURSES.map((c,i)=>'<button type="button" class="course-tab '+(i===0?"active":"")+'" data-course-tab="'+i+'">'+c+' '+yen(BUDGETS[i])+'</button>').join("")+'</div>'+blocks;
}
function replaceSection(html:string,start:string,end:string,replacement:string):string{
 const a=html.indexOf(start),b=a<0?-1:html.indexOf(end,a+start.length);
 return a<0||b<0?html:html.slice(0,a)+replacement+html.slice(b+end.length);
}
export function identicalDetailUi(html:string,mode:IndependentMode,id:string,day:DaySnapshot):string{
 const base="/models/"+(mode==="cash6"?"6m":"96m");
 const final=day.finals.get(id)||null,view=snapshotStatus(day,id);
 let out=sameModelNavigation(html,mode,id);
 out=footerCss(out);
 out=out.replaceAll('href="/races/','href="'+base+'/races/');
 out=out.replaceAll('href="/"','href="'+base+'"');
 // Exact source detail tabs, horse table, carousel, header and CSS are retained.
 // The one substitution is canonical prediction data -> this model's immutable data.
 const mark='<section data-race-panel="bets">';
 if(out.includes(mark)){
  const a=out.indexOf(mark);
  const b=out.indexOf("</section>",a);
  if(b>a)out=out.slice(0,a)+mark+courseBlock(final,view)+"</section>"+out.slice(b+10);
 }else{
  // No bet panel means the canonical response was not a valid race detail.
  throw Error("CANONICAL_DETAIL_BET_PANEL_NOT_FOUND");
 }
 const reasonStart=out.indexOf('<section id="race-panel-reason"');
 if(reasonStart>=0){
   const end=out.indexOf("</section>",reasonStart);
   if(end>reasonStart){
     const reason='<section id="race-panel-reason" class="card reason-panel" data-race-panel="reason" hidden><div class="section-title"><h2>買い目の理由</h2></div>'+
       (final?'<p>直近'+(mode==="cash6"?"6":"96")+'か月の実績と発走前のJRA公式オッズから算出した買い目です。</p>':'<p>買い目未確定</p>')+'</section>';
     out=out.slice(0,reasonStart)+reason+out.slice(end+10);
   }
 }
 // Never leak the original model's additional research or ticket selection details.
 const high=out.indexOf('data-race-panel="high-return"');
 if(high>=0){
   const open=out.lastIndexOf("<section",high),end=out.indexOf("</section>",high);
   if(open>=0&&end>high)out=out.slice(0,open)+'<section data-race-panel="high-return" hidden></section>'+out.slice(end+10);
 }
 out=out.replace(/<button[^>]+data-race-tab="high-return"[^>]*>[\s\S]*?<\/button>/g,"");
 out=out.replace(/<p class="race-model-identity"[\s\S]*?<\/p>/g,"");
 // Model-specific status in the original hero.
 out=out.replace(/(<section class="hero[^"]*">[\s\S]*?<span class="status )[^"]*(">)((?:(?!<\/span>)[\s\S])*)(<\/span>)/,
   (_,a,b,_c,d)=>a+esc(view.code)+b+esc(view.label)+d);
 out=out.replace("</body>",'<script>(function(){document.querySelectorAll("[data-course-tab]").forEach(function(b){b.addEventListener("click",function(){var n=b.getAttribute("data-course-tab");document.querySelectorAll("[data-course-tab]").forEach(function(x){x.classList.toggle("active",x===b)});document.querySelectorAll("[data-course]").forEach(function(x){x.style.display=x.getAttribute("data-course")===n?"block":"none"})})})})();</script></body>');
 return out;
}
export async function independentDetailResponse(db:D1Database,mode:IndependentMode,id:string,original:Response):Promise<Response>{
 const day=await daySnapshot(db,mode,id.slice(0,10));
 const html=identicalDetailUi(await original.text(),mode,id,day);
 const headers=new Headers(original.headers);headers.delete("content-length");headers.set("x-race-independent-model",mode);
 return new Response(html,{status:original.status,headers});
}
export async function independentHomeResponse(db:D1Database,mode:IndependentMode,original:Response):Promise<Response>{
 const a=await aggregateIndependent(db,mode);
 const html=identicalHomeUi(await original.text(),mode,a);
 const headers=new Headers(original.headers);headers.delete("content-length");headers.set("x-race-independent-model",mode);
 return new Response(html,{status:original.status,headers});
}
