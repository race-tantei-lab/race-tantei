import publicSite from "./public-site-entry-v7.js";
import type { Env } from "./v1/types.js";
import { FROZEN_PUBLIC_METRICS, FROZEN_PUBLIC_MONTHLY, type FrozenMetric, type FrozenMonthlyMetric } from "./v1/frozen-public-data.js";
import { getStaticCanonicalCoursePayouts, type CanonicalCoursePayouts } from "./v1/static-canonical-history.js";

const COURSES = ["ライト","スタンダード","プレミアム"] as const;
type Course = typeof COURSES[number];
type RaceSettlement = { hasBets:boolean; settled:boolean; payouts:CanonicalCoursePayouts };
type CurrentMetric = { course:Course; settledRaces:number; stakeYen:number; returnYen:number };

function yen(value:number):string{return `¥${Math.round(value).toLocaleString("ja-JP")}`;}
function esc(value:unknown):string{return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]??ch));}
function canonicalCombination(betType:string,combination:string):string{
  const nums=(combination.match(/\d{1,2}/g)??[]).map(Number);
  if(["ワイド","馬連","3連複"].includes(betType))nums.sort((a,b)=>a-b);
  return nums.join("-");
}

async function settlePublicBets(db:D1Database):Promise<void>{
  try{
    const pending=await db.prepare(`
      SELECT b.id,b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,
             r.refund_horse_nos_json AS refunds
      FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
      WHERE b.settlement_status='pending' AND r.status='finished' AND r.race_date>='2026-08-09'
      ORDER BY b.race_id,b.id
    `).all<{id:number;raceId:string;betType:string;combination:string;stakeYen:number;refunds:string}>();
    if(!pending.results.length)return;
    const raceIds=[...new Set(pending.results.map(x=>x.raceId))];
    const payoutMaps=new Map<string,Map<string,number>>();
    for(const raceId of raceIds){
      const q=await db.prepare(`SELECT bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?`).bind(raceId).all<{betType:string;combination:string;payoutYen:number}>();
      if(!q.results.length)continue;
      payoutMaps.set(raceId,new Map(q.results.map(x=>[`${x.betType}:${canonicalCombination(x.betType,x.combination)}`,Number(x.payoutYen)])));
    }
    const statements=[];
    for(const bet of pending.results){
      const payoutMap=payoutMaps.get(bet.raceId);if(!payoutMap)continue;
      let refunds=new Set<number>();try{refunds=new Set((JSON.parse(bet.refunds||"[]") as number[]).map(Number));}catch{/* empty */}
      const horses=(bet.combination.match(/\d{1,2}/g)??[]).map(Number);
      const returned=horses.some(h=>refunds.has(h))?Number(bet.stakeYen):Math.round(Number(bet.stakeYen)/100*(payoutMap.get(`${bet.betType}:${canonicalCombination(bet.betType,bet.combination)}`)??0));
      statements.push(db.prepare(`UPDATE rt_public_bets SET settlement_status='settled',return_yen=? WHERE id=? AND settlement_status='pending'`).bind(returned,bet.id));
    }
    if(statements.length)await db.batch(statements);
  }catch{/* next cron/request retries */}
}

async function d1SettlementMap(db:D1Database,raceIds:string[]):Promise<Map<string,RaceSettlement>>{
  const out=new Map<string,RaceSettlement>();if(!raceIds.length)return out;
  const placeholders=raceIds.map(()=>"?").join(",");
  try{
    const q=await db.prepare(`
      SELECT race_id AS raceId,course,COUNT(*) AS rows,
             SUM(CASE WHEN settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
             SUM(CASE WHEN settlement_status='settled' THEN COALESCE(return_yen,0) ELSE 0 END) AS returnYen
      FROM rt_public_bets WHERE race_id IN (${placeholders})
      GROUP BY race_id,course
    `).bind(...raceIds).all<{raceId:string;course:string;rows:number;settledRows:number;returnYen:number}>();
    const temp=new Map<string,{rows:number;settledRows:number;courses:Set<string>;payouts:CanonicalCoursePayouts}>();
    for(const row of q.results){
      const item=temp.get(row.raceId)??{rows:0,settledRows:0,courses:new Set<string>(),payouts:{ライト:0,スタンダード:0,プレミアム:0}};
      item.rows+=Number(row.rows);item.settledRows+=Number(row.settledRows);item.courses.add(row.course);
      if(COURSES.includes(row.course as Course))item.payouts[row.course as Course]=Number(row.returnYen??0);
      temp.set(row.raceId,item);
    }
    for(const [raceId,item] of temp)out.set(raceId,{hasBets:item.rows>0,settled:item.rows>0&&item.rows===item.settledRows&&item.courses.size===3,payouts:item.payouts});
  }catch{/* no public rows yet */}
  return out;
}

async function augmentDay(response:Response,db:D1Database):Promise<Response>{
  if(!response.ok)return response;
  try{
    const data=await response.clone().json() as {races?:Array<Record<string,any>>;[k:string]:any};
    if(!Array.isArray(data.races))return response;
    const ids=data.races.map(r=>String(r.raceId??"")).filter(Boolean);
    const d1=await d1SettlementMap(db,ids);
    const staticPairs=await Promise.all(ids.map(async id=>[id,await getStaticCanonicalCoursePayouts(id)] as const));
    const statics=new Map(staticPairs.filter((x):x is readonly [string,CanonicalCoursePayouts]=>x[1]!==null));
    data.races=data.races.map(race=>{
      const raceId=String(race.raceId??"");const current={...(race.publicState??{})};
      const live=d1.get(raceId);const payouts=live?.settled?live.payouts:statics.get(raceId)??null;
      if(payouts){
        const hit=COURSES.some(c=>payouts[c]>0);current.code=hit?"hit":"miss";current.label=hit?"的中":"不的中";current.deadline=null;
        if(hit)current.payouts=payouts;
      }else if(live?.hasBets&&!live.settled){current.code="buy";current.label="買い目あり";current.deadline=null;}
      return {...race,publicState:current};
    });
    const headers=new Headers(response.headers);headers.delete("content-length");headers.set("content-type","application/json; charset=utf-8");
    return new Response(JSON.stringify(data),{status:response.status,headers});
  }catch{return response;}
}

async function aug9Metrics(db:D1Database):Promise<Map<Course,CurrentMetric>>{
  const out=new Map<Course,CurrentMetric>();
  try{
    const q=await db.prepare(`
      SELECT course,COUNT(DISTINCT race_id) AS settledRaces,COALESCE(SUM(stake_yen),0) AS stakeYen,COALESCE(SUM(return_yen),0) AS returnYen
      FROM rt_public_bets WHERE race_id LIKE '2026-08-09-%' AND settlement_status='settled'
      GROUP BY course
    `).all<CurrentMetric>();
    for(const row of q.results)if(COURSES.includes(row.course as Course))out.set(row.course as Course,{course:row.course as Course,settledRaces:Number(row.settledRaces),stakeYen:Number(row.stakeYen),returnYen:Number(row.returnYen)});
  }catch{/* zero */}
  return out;
}

function mergedMetrics(current:Map<Course,CurrentMetric>):FrozenMetric[]{
  return FROZEN_PUBLIC_METRICS.map(row=>{const add=current.get(row.course);const settledRaces=row.settledRaces+(add?.settledRaces??0);const stakeYen=row.stakeYen+(add?.stakeYen??0);const returnYen=row.returnYen+(add?.returnYen??0);return {...row,settledRaces,stakeYen,returnYen,roiPct:stakeYen?returnYen/stakeYen*100:0};});
}
function mergedMonthly(current:Map<Course,CurrentMetric>):FrozenMonthlyMetric[]{
  return FROZEN_PUBLIC_MONTHLY.map(row=>{
    if(row.month!=="2026-08")return row;const add=current.get(row.course);const settledRaces=row.settledRaces+(add?.settledRaces??0);const stakeYen=row.stakeYen+(add?.stakeYen??0);const returnYen=row.returnYen+(add?.returnYen??0);return {...row,settledRaces,stakeYen,returnYen,roiPct:stakeYen?returnYen/stakeYen*100:0};
  });
}
function monthlyRows(course:Course,rows:FrozenMonthlyMetric[]):string{return rows.filter(r=>r.course===course).map(r=>`<div class="monthly-row"><b>${esc(r.month.replace("-","/"))}</b><span>${r.settledRaces}R　${yen(r.stakeYen)} → ${yen(r.returnYen)}</span><strong class="${r.roiPct>=100?"plus":"minus"}">${r.roiPct.toFixed(1)}%</strong></div>`).join("");}
function metricHtml(metrics:FrozenMetric[],monthly:FrozenMonthlyMetric[]):string{return `<section class="metrics">${metrics.map(r=>`<details class="card metric"><summary><b>${r.course}</b><strong>${r.roiPct.toFixed(1)}%</strong><small>${r.settledRaces}R　購入 ${yen(r.stakeYen)}　払戻 ${yen(r.returnYen)}</small></summary><div class="monthly">${monthlyRows(r.course,monthly)}</div></details>`).join("")}</section>`;}

function enhanceHomeHtml(html:string,metrics:FrozenMetric[],monthly:FrozenMonthlyMetric[]):string{
  let out=html.replace(/<section class="metrics">[\s\S]*?<\/section>/,metricHtml(metrics,monthly));
  const css=`<style>.race-payout{margin-top:6px;padding-top:6px;border-top:1px solid #334155;font-size:10px;line-height:1.45;color:#bdf5dc}.race-payout b{display:block;color:#ecfdf5;margin-bottom:2px}.race-payout span{display:block;white-space:nowrap}.race-payout-summary{display:grid;grid-template-columns:auto repeat(3,minmax(0,1fr));gap:6px;align-items:center;margin:8px 0;padding:9px 10px;border:1px solid #287d5b;border-radius:11px;background:#102f27;font-size:11px}.race-payout-summary strong{color:#bdf5dc}.race-payout-summary span{text-align:center}@media(max-width:760px){.race-payout-summary{grid-template-columns:1fr 1fr}.race-payout-summary strong{grid-column:1/-1}}</style>`;
  const script=`<script>(()=>{async function decoratePayouts(){try{const rail=document.getElementById('races');if(!rail||typeof selectedDate==='undefined')return;const res=await fetch('/api/public/day?date='+encodeURIComponent(selectedDate));const data=await res.json();const map=new Map((data.races||[]).map(r=>[r.raceId,r]));rail.querySelectorAll('.race-card').forEach(card=>{card.querySelector('.race-payout')?.remove();let id='';try{id=decodeURIComponent(new URL(card.href).pathname.replace(/^\\/races\\//,''));}catch{}const p=map.get(id)?.publicState?.payouts;if(!p)return;const box=document.createElement('div');box.className='race-payout';box.innerHTML='<b>払戻</b><span>ライト '+Number(p['ライト']||0).toLocaleString('ja-JP')+'円</span><span>スタンダード '+Number(p['スタンダード']||0).toLocaleString('ja-JP')+'円</span><span>プレミアム '+Number(p['プレミアム']||0).toLocaleString('ja-JP')+'円</span>';card.append(box);});}catch{}}if(typeof loadRaces==='function'){const original=loadRaces;loadRaces=async function(){await original();await decoratePayouts();};}setTimeout(decoratePayouts,250);})();</script>`;
  out=out.replace("</head>",`${css}</head>`).replace("</body>",`${script}</body>`);return out;
}

async function racePayouts(db:D1Database,raceId:string):Promise<CanonicalCoursePayouts|null>{
  const d1=await d1SettlementMap(db,[raceId]);const live=d1.get(raceId);if(live?.settled)return live.payouts;return getStaticCanonicalCoursePayouts(raceId);
}
async function enhanceRaceDetail(request:Request,response:Response,db:D1Database):Promise<Response>{
  const path=new URL(request.url).pathname;if(!path.startsWith('/races/')||!response.ok||!response.headers.get('content-type')?.includes('text/html'))return response;
  try{
    const raceId=decodeURIComponent(path.slice('/races/'.length));const payouts=await racePayouts(db,raceId);if(!payouts)return response;
    const hit=COURSES.some(c=>payouts[c]>0);let html=await response.text();
    html=html.replace(/<span class="status (?:buy|skip|pending|hit|miss|overdue|missing|target)">[^<]*<\/span>/g,`<span class="status ${hit?'hit':'miss'}">${hit?'的中':'不的中'}</span>`);
    if(hit){const summary=`<div class="race-payout-summary"><strong>払戻</strong>${COURSES.map(c=>`<span>${c}<br><b>${yen(payouts[c])}</b></span>`).join('')}</div>`;html=html.replace(/(<section class="hero[\s\S]*?<\/section>)/,`$1${summary}`);}
    const headers=new Headers(response.headers);headers.delete('content-length');return new Response(html,{status:response.status,headers});
  }catch{return response;}
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response('NOT_FOUND',{status:404});
    const url=new URL(request.url);const path=url.pathname;
    if(path==='/api/public/day')await settlePublicBets(env.DB);
    let response=await publicSite.fetch(request,env,ctx);
    if(path==='/api/public/day')response=await augmentDay(response,env.DB);
    if(path==='/'){
      try{const current=await aug9Metrics(env.DB);const headers=new Headers(response.headers);headers.delete('content-length');return new Response(enhanceHomeHtml(await response.text(),mergedMetrics(current),mergedMonthly(current)),{status:response.status,headers});}catch{return response;}
    }
    response=await enhanceRaceDetail(request,response,env.DB);
    return response;
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
    await settlePublicBets(env.DB);
  }
} satisfies ExportedHandler<Env>;
