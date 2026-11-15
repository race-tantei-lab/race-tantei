/**
 * Fully separate current-like site screens for the 6m and 96m research methods.
 *
 * Shares the production original site's shell, styling, year -> month -> day
 * -> venue -> race navigation, race-detail course tabs and runner list.
 * No writes, no unlocked wager promotion, never claims the new models chose
 * different horses; they only adjust the two already-frozen ticket choices.
 */
import {shell} from "./v1/public-ui.js";
import {HOME_INTERACTION_SCRIPT} from "./three-model-navigation-client.js";
import {compareThree,type Panel,type ModelPick,type Race,type Bet,type PastBet,type MethodId}
  from "./v1/three-model-money-comparison.js";
import {addDays,normalizeDate,oldSettled} from "./three-model-compare-page.js";
import type {Env} from "./v1/types.js";

type ModelMode="cash6"|"cash96";
type State={value:string|null};
type Calendar={raceDate:string;venue:string;count:number};
type Horse={
 horseNo:number;horseName:string;sexAge:string|null;jockey:string|null;
 trainer:string|null;winOdds:number|null;finishPosition:number|null;
};
type Context={
 date:string;selected:boolean;selectionKnown:boolean;panel:Panel;
 races:Race[]; bets:Bet[];calendar:Calendar[];
};
function esc(x:unknown):string{
 return String(x??"").replace(/[&<>"']/g,c=>({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
 }[c]||c));
}
function yen(x:number):string{return Math.round(x).toLocaleString("ja-JP")+"円";}
const models:{id:MethodId;title:string;path:string}[]=[
 {id:"current",title:"現行モデル",path:"/"},
 {id:"cash6",title:"直近6か月モデル",path:"/models/6m"},
 {id:"cash96",title:"過去96か月モデル",path:"/models/96m"}
];
export function modelNavigation(id:MethodId,date?:string,raceId?:string):string{
 return '<nav class="prediction-model-tabs" aria-label="予想モデルを切り替える">'+
 models.map(x=>{
   const link=raceId
     ?(x.id==="current"?"/races/":x.path+"/races/")+encodeURIComponent(raceId)
     :x.path+(x.id==="current"||!date?"":"?date="+encodeURIComponent(date));
   return '<a href="'+link+'" data-prediction-model="'+x.id+'"'+
     (id===x.id?' aria-current="page" class="selected"':"")+'>'+x.title+'</a>';
 }).join("")+'</nav>';
}
export const MODEL_SWITCH_CSS='<style>'+
 '.prediction-model-tabs{display:flex;gap:8px;overflow:auto;scrollbar-width:thin;margin:8px 0 20px;padding:3px 0 7px}'+
 '.prediction-model-tabs a{flex:1 0 auto;text-align:center;border:1px solid #41556a;border-radius:12px;background:#112334;padding:12px 15px;color:#e5effa;text-decoration:none;font-size:13px;font-weight:800}'+
 '.prediction-model-tabs a.selected{background:#144d41;border-color:#51d0a5;color:#d3fff0}'+
 '@media(max-width:760px){.prediction-model-tabs a{padding:11px 8px;font-size:12px}}'+
 '</style>';
const STYLE='<style>'+
 '.model-lead{margin:10px 0 18px}.model-lead p{font-size:13px;color:var(--muted);line-height:1.75}'+
 '.model-inline-status{display:inline-block;padding:4px 9px;border-radius:9px;background:#19362e;border:1px solid #386858;color:#bcf5d9;font-size:11px}'+
 '.model-navigator{padding:14px;margin-bottom:14px}.model-navigator h2{font-size:18px;margin:0 0 10px}'+
 '.model-year-rail,.model-month-rail,.model-day-rail,.model-venue-rail{display:flex;gap:8px;overflow-x:auto;padding:7px 0}'+
 '.model-navigator a{flex:0 0 auto;padding:9px 12px;border-radius:999px;background:#0c1723;border:1px solid var(--line);font-weight:700;font-size:12px}'+
 '.model-navigator a.active{border-color:#54d0ae;background:#123d35;color:#cbffe7}'+
 '.model-day-total{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}'+
 '.model-day-total .panel{padding:14px}.model-day-total strong{font-size:22px;display:block;margin-top:4px}'+
 '.model-day-total small{color:var(--muted);font-size:11px}.model-day-total .loss{color:#ff9694}'+
 '.venue-section{margin:20px 0 12px}.venue-section h2{margin:0 0 10px;font-size:22px}'+
 '.model-race-card{display:flex;flex-direction:column;gap:9px}.model-race-card strong{font-size:15px}'+
 '.model-race-card .race-meta{font-size:11px}.model-ticket-mini{background:#17291f;border:1px solid #335847;border-radius:8px;padding:7px;font-size:12px}'+
 '.model-ticket-mini b{color:#d7fdea}.model-ticket-mini span{float:right;color:#cbefd9;font-weight:700}'+
 '.model-race-card .status{margin-top:auto;align-self:flex-start}.model-late{border-color:#7b5934!important}'+
 '.model-tickets{padding:12px 15px}.model-ticket-row{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:12px 0}'+
 '.model-ticket-row strong{font-size:18px;color:#bbf3df}.model-ticket-row small{display:block;color:var(--muted);font-size:12px}'+
 '.model-tabs{display:flex;gap:9px;margin:11px 0;overflow:auto}.model-tabs button{border-radius:999px;background:#101c29;color:#f3f8fa;border:1px solid var(--line);padding:10px 15px;white-space:nowrap;font:inherit}'+
 '.model-tabs button.active{background:#123d35;border-color:var(--green)}'+
 '.model-stats{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}.model-stats div{border:1px solid var(--line);border-radius:10px;padding:12px 15px}'+
 '.model-stats b{display:block;color:var(--green);font-size:21px}.model-stats small{font-size:11px;color:var(--muted)}'+
 '.model-flag{padding:12px;border:1px solid #7a6040;background:#2a2416;border-radius:12px;font-size:12px;line-height:1.8;color:#f0ddad;margin:15px 0}'+
 '@media(max-width:760px){.model-day-total{grid-template-columns:1fr 1fr}.model-day-total .panel{padding:10px}.model-day-total strong{font-size:18px}.race-rail .model-race-card{flex:0 0 234px}}'+
 '</style>';
const CAUTION='新モデルは現行モデルが選んだ馬券の購入金額・対象レースを変更する研究用の参考予想です。'+
 '独立した馬の予想モデルではなく、実際に購入した馬券でもありません。'+
 '2026年8月以降の検証では回収率200%を達成していません。';
const BUDGETS=[
 {name:"ライト",sum:2000},
 {name:"スタンダード",sum:5000},
 {name:"プレミアム",sum:10000}
] as const;
function renderDocument(title:string,content:string,script=""):Response{
 let html=shell(title,content);
 html=html.replace("</head>",MODEL_SWITCH_CSS+STYLE+"</head>");
 if(script)html=html.replace("</body>","<script>"+script+"</script></body>");
 return new Response(html,{status:200,headers:{
   "content-type":"text/html; charset=utf-8","cache-control":"no-store, max-age=0",
   "x-race-model-full-page":"standalone-v3","x-content-type-options":"nosniff"
 }});
}
function modePath(mode:ModelMode):string{return mode==="cash6"?"/models/6m":"/models/96m";}
function monthChoices(calendar:Calendar[],date:string):{years:string[];months:string[];days:string[];venues:string[]}{
 const currentYear=date.slice(0,4),currentMonth=date.slice(0,7);
 const dates=[...new Set(calendar.map(x=>x.raceDate))].sort();
 return {
   years:[...new Set(dates.map(x=>x.slice(0,4)))].sort().reverse(),
   months:[...new Set(dates.filter(x=>x.startsWith(currentYear)).map(x=>x.slice(0,7)))].sort().reverse(),
   days:dates.filter(x=>x.startsWith(currentMonth)).sort().reverse(),
   venues:[...new Set(calendar.filter(x=>x.raceDate===date).map(x=>x.venue))]
 };
}
function navigation(mode:ModelMode,c:Calendar[],date:string,venue:string,raceSections:string):string{
 const opts=monthChoices(c,date),base=modePath(mode);
 const currentYear=date.slice(0,4),currentMonth=date.slice(0,7);
 function anchor(value:string,label:string,active:boolean,extra="",venueValue?:string):string{
   return '<a href="'+base+'?date='+encodeURIComponent(value)+extra+'" data-model-filter="true"'+
     (venueValue?' data-model-venue="'+esc(venueValue)+'"':"")+
     ' class="chip'+(active?' active':'')+'"'+(active?' aria-current="true"':"")+'>'+esc(label)+'</a>';
 }
 function step(n:number,label:string,railName:string,content:string):string{
   return '<div class="nav-step"><p class="nav-label">'+n+'. '+label+'</p>'+
     '<div class="rail" data-model-rail="'+railName+'">'+(content||'<span class="muted">開催情報待ち</span>')+'</div></div>';
 }
 const firstDate=(prefix:string)=>[...new Set(c.map(x=>x.raceDate))]
   .filter(x=>x.startsWith(prefix)).sort().reverse()[0]||date;
 return '<div class="section-title"><h2 id="selected-date">'+esc(date.replace(/-/g,"/"))+' のレースを選ぶ</h2>'+
   '<span class="muted">横にスワイプできます</span></div>'+
   '<section class="card navigator model-navigator" aria-label="開催日と会場を選択">'+
   step(1,"年","years",opts.years.map(y=>anchor(firstDate(y),y+"年",y===currentYear)).join(""))+
   step(2,"月","months",opts.months.map(m=>anchor(firstDate(m),Number(m.slice(5))+"月",m===currentMonth)).join(""))+
   step(3,"日付","dates",opts.days.map(d=>anchor(d,Number(d.slice(8))+"日",d===date)).join(""))+
   step(4,"会場","venues",opts.venues.map(v=>anchor(date,v,v===venue,"&venue="+encodeURIComponent(v),v)).join(""))+
   '<div class="nav-step"><p class="nav-label">5. レース</p>'+
   (raceSections||'<div class="empty">この日の開催情報はまだありません。</div>')+
   '</div><p class="model-nav-error" role="status" hidden></p></section>';
}
function getPick(panel:Panel,race:Race):ModelPick|null{
 for(const venue of panel.venues){
   const found=venue.races.find(x=>x.race.raceId===race.raceId);
   if(found)return found;
 }
 return null;
}
function phase(pick:ModelPick|null,selected:boolean,known:boolean):{css:string;label:string;detail:string}{
 if(pick?.status==="simulation")return {css:"buy",label:"参考予想",detail:pick.detail};
 if(pick?.status==="skipped")return {css:"skip",label:"見送り",detail:pick.detail};
 if(pick?.status==="awaiting")return {css:"pending",label:"判定待ち",detail:pick.detail};
 if(!known)return {css:"pending",label:"選定前",detail:"本日の対象レース選定待ち"};
 return selected?{css:"pending",label:"確定待ち",detail:"現行モデルの買い目の確定待ち"}:
   {css:"skip",label:"見送り",detail:"現行モデルの選定対象外です"};
}
function scenarioPaid(bet:Bet,newStake:number):number|null{
 if(bet.settlementStatus!=="settled"||bet.returnYen===null||!Number.isFinite(Number(bet.returnYen))
    ||Number(bet.stakeYen)<=0)return null;
 return Math.round(Number(bet.returnYen)*newStake/Number(bet.stakeYen));
}
function dailyCash(panel:Panel,bets:Bet[]):{races:number;stake:number;paid:number;pending:number;hit:number}{
 const map=new Map<string,Bet[]>();
 for(const row of bets){const arr=map.get(row.raceId)||[];arr.push(row);map.set(row.raceId,arr);}
 let races=0,stake=0,paid=0,pending=0,hit=0;
 for(const v of panel.venues)for(const p of v.races){
   if(p.status!=="simulation"||p.tickets.length!==2)continue;
   const actual=map.get(p.race.raceId)||[];
   if(actual.length!==2){pending++;continue;}
   let sum=0,valid=true;
   for(const t of p.tickets){
     const b=actual.find(x=>x.betType===t.betType&&x.combination===t.combination);
     const receipt=b?scenarioPaid(b,t.stakeYen):null;
     if(receipt===null){valid=false;break;}
     sum+=receipt;
   }
   if(!valid){pending++;continue;}
   races++;stake+=2000;paid+=sum;if(sum>0)hit++;
 }
 return {races,stake,paid,pending,hit};
}
function cashHeader(panel:Panel,bets:Bet[]):string{
 const d=dailyCash(panel,bets);
 return '<div class="section-title"><h2>選択日の予想と参考収支</h2><span class="muted">実購入ではありません</span></div>'+
 '<div class="model-day-total">'+
 '<article class="panel"><small>対象レース</small><strong>'+panel.selectedRaces+'R</strong><small>判定待ち '+panel.awaitingRaces+'R</small></article>'+
 '<article class="panel"><small>精算確認済み・試算</small><strong>'+d.races+'R</strong><small>未精算 '+d.pending+'R</small></article>'+
 '<article class="panel"><small>精算済みのみの参考回収率</small><strong class="'+(d.paid<d.stake?"loss":"")+'">'+(d.stake?Number(100*d.paid/d.stake).toFixed(1)+"%":"—")+'</strong>'+
 '<small>'+(d.stake?yen(d.stake)+" → "+yen(d.paid):"未集計")+'</small></article>'+
 '</div>';
}
function card(race:Race,pick:ModelPick|null,selected:boolean,known:boolean,mode:ModelMode):string{
 const st=phase(pick,selected,known);
 const link=modePath(mode)+"/races/"+encodeURIComponent(race.raceId);
 const tickets=pick?.status==="simulation"?pick.tickets.map(t=>
   '<div class="model-ticket-mini"><b>'+esc(t.betType)+" "+esc(t.combination)+'</b>'+
   '<span>'+yen(t.stakeYen)+'</span></div>').join(""):"";
 return '<a href="'+link+'" class="race-card model-race-card'+(st.css==="pending"?" model-late":"")+'" data-model-race="'+esc(race.raceId)+'">'+
 '<div class="race-head"><span class="race-no">'+race.raceNo+'R</span><span class="race-time">'+esc(race.startTimeJst||"")+'</span></div>'+
 '<strong>'+esc(race.raceName||race.venue+" "+race.raceNo+"R")+'</strong>'+
 '<div class="race-meta">'+esc(race.surface||"")+(race.distanceM?race.distanceM+"m":"")+'</div>'+
 '<span class="status '+st.css+'">'+st.label+'</span>'+
 tickets+'<p class="race-meta">'+esc(st.detail)+'</p></a>';
}
async function loadCalendar(db:D1Database,last:string):Promise<Calendar[]>{
 const x=await db.prepare("SELECT race_date AS raceDate,venue,COUNT(*) AS count FROM rt_races "+
   "WHERE race_date>=? AND race_date<=? GROUP BY race_date,venue ORDER BY race_date DESC,venue LIMIT 250")
   .bind("2026-08-10",last).all<Calendar>();
 return x.results||[];
}
async function load(db:D1Database,date:string,mode:ModelMode):Promise<Context>{
 const [state,rr,bb]=await Promise.all([
   db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
     .bind("final_daily_selection:"+date).first<State>(),
   db.prepare("SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,"+
     "race_name AS raceName,surface,distance_m AS distanceM,start_time_jst AS startTimeJst,"+
     "start_time_utc AS startTimeUtc FROM rt_races WHERE race_date=? ORDER BY venue,race_no")
     .bind(date).all<Race>(),
   db.prepare("SELECT race_id AS raceId,bet_type AS betType,combination,stake_yen AS stakeYen,"+
     "assumed_odds AS assumedOdds,locked_at AS lockedAt,settlement_status AS settlementStatus,"+
     "return_yen AS returnYen FROM rt_public_bets WHERE race_id>=? AND race_id<? "+
     "AND source_prediction_id=-2 AND course='ライト' ORDER BY race_id,id")
     .bind(date+"-",addDays(date,1)+"-").all<Bet>()
 ]);
 const races=rr.results||[],bets=bb.results||[];
 let selectedIds:string[]=[];
 if(state?.value){
   const payload=JSON.parse(state.value) as {selected?:Array<{raceId?:unknown}>};
   if(!Array.isArray(payload.selected))throw Error("MALFORMED_FINAL_SELECTION");
   selectedIds=payload.selected.map(x=>String(x.raceId||"")).filter(Boolean);
   if(selectedIds.length!==new Set(selectedIds).size)throw Error("DUPLICATE_FINAL_SELECTION");
 }
 const older=state?.value?await oldSettled(db,date.slice(0,7)):[] as PastBet[];
 const all=compareThree(date,selectedIds,races,bets,older);
 const panel=all.find(x=>x.id===mode);
 if(!panel)throw Error("RESEARCH_MODEL_PANEL_MISSING");
 const calendar=await loadCalendar(db,addDays(new Date(Date.now()+9*3600_000).toISOString().slice(0,10),7));
 return {date,selected:Boolean(state?.value),selectionKnown:Boolean(state?.value),panel,races,bets,calendar};
}
function modeIntro(mode:ModelMode):{name:string,lead:string}{
 return mode==="cash6"
  ?{name:"直近6か月モデル",lead:"直近6か月の払戻・的中傾向を月初に学習。現行モデルの各会場5レース・2券種のうち、期待払戻が高い方に1,800円、他方に200円を配分"}
  :{name:"過去96か月モデル",lead:"過去96か月の払戻傾向を月初に学習。現行モデルの各会場5レースから予測収益上位3レースだけを選び、2券種を1,800円・200円で配分"};
}
function home(mode:ModelMode,ctx:Context,venueParam:string|null):Response{
 const {date,panel,races,calendar,bets}=ctx;
 const intro=modeIntro(mode);
 const venueOpts=[...new Set(races.map(x=>x.venue))];
 const venue=venueParam&&venueOpts.includes(venueParam)?venueParam:venueOpts[0]||"";
 const ids=new Set(panel.venues.flatMap(x=>x.races.map(y=>y.race.raceId)));
 const byVenue=venueOpts.map(v=>{
   const rows=races.filter(x=>x.venue===v);
   const shown=rows.filter(x=>ids.has(x.raceId)).length;
   return '<section class="venue-section" data-venue="'+esc(v)+'" id="venue-'+encodeURIComponent(v)+'"'+(v!==venue?' hidden':"")+'>'+
      '<div class="section-title"><h2>'+esc(v)+'競馬場</h2>'+
      '<span class="muted">'+shown+'レース候補 / 全'+rows.length+'レース</span></div>'+
      '<div class="race-rail">'+rows.map(x=>card(x,getPick(panel,x),ids.has(x.raceId),ctx.selectionKnown,mode)).join("")+'</div>'+
      '</section>';
 }).join("");
 const body='<div id="model-page-root">'+modelNavigation(mode,date)+
 '<section class="hero today-hero model-lead"><span class="today-pill">研究用・収益予測</span><h1>'+intro.name+'</h1>'+
 '<p>'+esc(intro.lead)+'</p></section>'+
 '<div class="model-flag">'+esc(CAUTION)+'</div>'+
 cashHeader(panel,bets)+
 navigation(mode,calendar,date,venue,byVenue)+
 '<div class="section-title"><h2>モデルについて</h2></div>'+
 '<section class="panel"><p>券種と馬番の組み合わせは現行モデルと共通です。'+
 '新モデルは買うレースと2券種への金額配分だけを予測します。'+
 '1レース2,000円を基準とし、スタンダード・プレミアムの配分は同じ比率で換算した参考額です。'+
 '上の回収率は精算できたレースだけの仮想購入額によるもので、本番の総合成績とは区別しています。</p></section></div>';
 return renderDocument(intro.name,body,HOME_INTERACTION_SCRIPT);
}
function runnerList(rows:Horse[]):string{
 return '<section class="panel"><div class="section-title"><h2>出走馬・着順</h2><span class="muted">'+rows.length+'頭</span></div>'+
 '<div class="runner-table"><table><thead><tr><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>調教師</th><th>単勝オッズ</th><th>着順</th></tr></thead>'+
 '<tbody>'+rows.map(x=>'<tr><td><span class="horse-no">'+x.horseNo+'</span></td>'+
 '<td><b>'+esc(x.horseName)+'</b></td><td>'+esc(x.sexAge||"—")+'</td>'+
 '<td>'+esc(x.jockey||"—")+'</td><td>'+esc(x.trainer||"—")+'</td>'+
 '<td>'+(x.winOdds==null?"—":Number(x.winOdds).toFixed(1)+"倍")+'</td>'+
 '<td>'+(x.finishPosition==null?"—":x.finishPosition+"着")+'</td></tr>').join("")+
 '</tbody></table></div></section>';
}
function ticketPanels(pick:ModelPick|null,ctx:Context):{html:string,summary:string}{
 if(!pick||pick.status!=="simulation"||pick.tickets.length!==2){
   return {html:'<div class="notice">'+esc(pick?.detail||"モデルの確定買い目がありません。")+'</div>',
           summary:'モデルの買い目待ち'};
 }
 let out="";
 let mini="";
 for(let i=0;i<BUDGETS.length;i++){
   const course=BUDGETS[i]!;
   const factor=course.sum/2000;
   const ticket=pick.tickets.map(x=>({...x,stakeYen:Math.round(x.stakeYen*factor)}));
   const actual=ctx.bets.filter(x=>x.raceId===pick.race.raceId);
   let returned=0,settled=true;
   const blocks=ticket.map(x=>{
     const b=actual.find(y=>y.betType===x.betType&&y.combination===x.combination);
     const scenario=b?scenarioPaid(b,x.stakeYen):null;
     if(scenario===null)settled=false;else returned+=scenario;
     return '<article class="model-ticket-row"><div><strong>'+esc(x.betType)+" "+esc(x.combination)+'</strong>'+
     '<small>保存済みオッズ '+x.assumedOdds.toFixed(1)+'倍 / 期待払戻指数 '+(x.expectedCashIndex??0).toFixed(3)+'</small></div>'+
     '<div><b>'+yen(x.stakeYen)+'</b>'+(scenario===null?"":'<small>仮想払戻 '+yen(scenario)+'</small>')+'</div></article>';
   }).join("");
   out+='<section data-course-view="'+i+'"'+(i===0?"":' hidden')+'>'+
     '<div class="model-stats"><div><small>参考購入金額</small><b>'+yen(course.sum)+'</b></div>'+
     '<div><small>精算結果を用いた仮想払戻</small><b>'+(settled?yen(returned):"結果待ち")+'</b></div>'+
     '<div><small>参考収支</small><b>'+(settled?yen(returned-course.sum):"—")+'</b></div></div>'+
     blocks+'</section>';
   if(i===0)mini=settled?"ライト参考回収率 "+(returned/course.sum*100).toFixed(1)+"%":"結果待ち";
 }
 const tabs='<div class="model-tabs" role="group" aria-label="予算を選択">'+BUDGETS.map((x,i)=>
   '<button type="button" data-course-tab="'+i+'"'+(i===0?' class="active"':'')+'>'+x.name+" "+yen(x.sum)+'</button>').join("")+'</div>';
 return {html:tabs+out,summary:mini};
}
async function detail(mode:ModelMode,ctx:Context,raceId:string,db:D1Database):Promise<Response>{
 const race=ctx.races.find(x=>x.raceId===raceId);
 if(!race)return renderDocument("対象レースなし",modelNavigation(mode,ctx.date,raceId)+
   '<section class="notice">このレースの情報は取得できません。</section>');
 const result=await db.prepare("SELECT r.horse_no AS horseNo,r.horse_name AS horseName,r.sex_age AS sexAge,"+
   "r.jockey,r.trainer,r.win_odds AS winOdds,x.finish_position AS finishPosition "+
   "FROM rt_runners r LEFT JOIN rt_results x ON x.race_id=r.race_id AND x.horse_no=r.horse_no "+
   "WHERE r.race_id=? ORDER BY r.horse_no").bind(raceId).all<Horse>();
 const pick=getPick(ctx.panel,race),selected=Boolean(pick);
 const status=phase(pick,selected,ctx.selectionKnown);
 const tickets=ticketPanels(pick,ctx);
 const intro=modeIntro(mode);
 const prev=ctx.races.find(x=>x.venue===race.venue&&x.raceNo===race.raceNo-1);
 const next=ctx.races.find(x=>x.venue===race.venue&&x.raceNo===race.raceNo+1);
 const link=modePath(mode);
 const back='<a class="back" href="'+link+'?date='+ctx.date+'&venue='+encodeURIComponent(race.venue)+'">← このモデルのレース一覧へ</a>';
 const neighbors='<div class="race-sequence-nav">'+
   (prev?'<a href="'+link+'/races/'+encodeURIComponent(prev.raceId)+'">← '+(race.raceNo-1)+'R</a>':'<span>前のレースなし</span>')+
   (next?'<a href="'+link+'/races/'+encodeURIComponent(next.raceId)+'">'+(race.raceNo+1)+'R →</a>':'<span>次のレースなし</span>')+'</div>';
 const body=modelNavigation(mode,ctx.date,raceId)+back+neighbors+
 '<section class="hero today-hero"><span class="model-inline-status">'+intro.name+'・参考予想</span>'+
 '<div class="race-title"><span class="race-no">'+race.raceNo+'R</span>'+
 '<h1>'+esc(race.raceName||race.venue+" "+race.raceNo+"R")+'</h1>'+
 '<span class="status '+status.css+'">'+status.label+'</span></div>'+
 '<p>'+esc(race.raceDate+" "+race.venue+" "+(race.startTimeJst||"時刻未定")+
   "発走 "+(race.surface||"")+" "+(race.distanceM||"")+"m")+'</p></section>'+
 '<div class="model-flag">'+esc(CAUTION)+'</div>'+
 '<section class="panel"><div class="section-title"><h2>予想買い目</h2></div>'+
 '<p class="muted">'+esc(status.detail)+'</p>'+tickets.html+'</section>'+
 '<section class="panel"><div class="section-title"><h2>買い目の理由</h2></div>'+
 '<p>月初時点で参照可能だった過去'+(mode==="cash6"?"6":"96")+
 'か月の払戻結果から、券種・オッズ帯・競馬場・距離・芝ダート・季節の関係を学習して予測しています。'+
 (mode==="cash96"?"同じ競馬場の5候補から予測払戻上位3レースを選びます。":"5候補のレースはすべて購入対象です。")+
 '馬の組み合わせ自体は現行モデルで確定したものです。学習の履歴オッズは発走15分前のJRA公式オッズとして完全に検証されていません。</p></section>'+
 runnerList(result.results||[]);
 const script='(function(){var btn=[].slice.call(document.querySelectorAll("[data-course-tab]"));'+
 'var panels=[].slice.call(document.querySelectorAll("[data-course-view]"));'+
 'btn.forEach(function(b){b.addEventListener("click",function(){var id=b.getAttribute("data-course-tab");'+
 'btn.forEach(function(t){t.classList.toggle("active",t===b)});'+
 'panels.forEach(function(p){p.hidden=p.getAttribute("data-course-view")!==id})})})})();';
 return renderDocument(race.venue+" "+race.raceNo+"R | "+intro.name,body,script);
}
export async function serveFullModel(request:Request,env:Env,mode:ModelMode,raceId?:string):Promise<Response>{
 const url=new URL(request.url),date=raceId?raceId.slice(0,10):normalizeDate(url.searchParams.get("date"));
 try{
   if(raceId&&!/^20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2}$/i.test(raceId)){
      return new Response("NOT_FOUND",{status:404});}
   if(date<"2026-08-10"||date>addDays(new Date(Date.now()+9*3600_000).toISOString().slice(0,10),7))
      return new Response("NOT_FOUND",{status:404});
   const ctx=await load(env.DB,date,mode);
   return raceId?await detail(mode,ctx,raceId,env.DB):home(mode,ctx,url.searchParams.get("venue"));
 }catch(e){
   console.error("FULL_MODEL_PUBLIC_READ_ONLY_FAILED",mode,date,e);
   const caution='<section class="notice">このモデルの表示に必要な情報を取得できません。'+
     '現行の予想と保存済みの買い目は変更されていません。</section>';
   return renderDocument(modeIntro(mode).name,modelNavigation(mode,date,raceId)+
     '<section class="hero"><h1>'+modeIntro(mode).name+'</h1></section>'+caution);
 }
}
