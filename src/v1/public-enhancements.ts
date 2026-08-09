import { getPublicBets, type PublicBetRow } from "./public-history-db.js";
import { escapeHtml, formatYen } from "./utils.js";

const COURSE_NAMES=["ライト","スタンダード","プレミアム"] as const;
const COURSE_BUDGETS=[2000,5000,10000] as const;

function jstDateKey(date=new Date()):string{
  const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(date);
  const get=(type:string)=>parts.find(p=>p.type===type)?.value??"";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function settledState(raceDate:string,status:string|undefined,hasBets:boolean,hit:boolean):{code:string;label:string;deadline:null}|null{
  if(!hasBets)return null;
  const settled=raceDate<jstDateKey()||status==="finished";
  if(settled)return {code:hit?"hit":"miss",label:hit?"的中":"不的中",deadline:null};
  return {code:"buy",label:"買い目あり",deadline:null};
}

async function betStates(db:D1Database,raceIds:string[]):Promise<Map<string,{hit:boolean}>>{
  if(!raceIds.length)return new Map();
  const placeholders=raceIds.map(()=>'?').join(',');
  const rows=await db.prepare(`SELECT race_id AS raceId,MAX(CASE WHEN COALESCE(return_yen,0)>0 THEN 1 ELSE 0 END) AS hit FROM rt_public_bets WHERE race_id IN (${placeholders}) GROUP BY race_id`).bind(...raceIds).all<{raceId:string;hit:number}>();
  return new Map(rows.results.map(r=>[r.raceId,{hit:Number(r.hit)>0}]));
}

function tables(bets:PublicBetRow[],state:{code:string;label:string}):string{
  const blocks=COURSE_NAMES.map((name,idx)=>{
    const rows=bets.filter(b=>b.course===name);
    const trs=rows.map(t=>`<tr><td>${escapeHtml(t.betType)}</td><td>${escapeHtml(t.combination)}</td><td>${t.assumedOdds===null?"—":Number(t.assumedOdds).toFixed(1)+"倍"}</td><td>${formatYen(t.stakeYen)}</td><td class="${Number(t.returnYen??0)>0?"plus":""}">${t.settlementStatus==="settled"?formatYen(Number(t.returnYen??0)):"—"}</td></tr>`).join("");
    return `<div class="course-view" data-course="${idx}" style="${idx===0?"":"display:none"}"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>${trs}</tbody></table></div></div>`;
  }).join("");
  return `<div class="section-title"><h2>確定買い目</h2><span class="status ${state.code}">${state.label}</span></div><div class="course-tabs">${COURSE_NAMES.map((name,idx)=>`<button class="course-tab ${idx===0?"active":""}" data-course-tab="${idx}">${name} ${formatYen(COURSE_BUDGETS[idx])}</button>`).join("")}</div>${blocks}<details class="bet-note"><summary>買い目のルール</summary><div>確定した買い目・購入額は結果後も変更しません。終了レースは将来の改善材料にのみ使います。</div></details>`;
}

function injectStyles(html:string):string{
  const css=`<style>.status.hit{background:#dcfce7;color:#166534;border-color:#86efac}.status.miss{background:#fee2e2;color:#991b1b;border-color:#fecaca}.bet-note{margin-top:10px;padding:10px 12px;border:1px solid #e5e7eb;border-radius:12px;background:#fff}.bet-note summary{cursor:pointer;font-weight:700;font-size:13px}.bet-note div{margin-top:8px;color:#6b7280;font-size:12px;line-height:1.6}</style>`;
  return html.includes('</head>')?html.replace('</head>',`${css}</head>`):css+html;
}

async function enhanceDay(request:Request,db:D1Database,response:Response):Promise<Response>{
  if(!response.ok)return response;
  const data=await response.json() as {ok?:boolean;races?:Array<Record<string,unknown>>};
  const races=Array.isArray(data.races)?data.races:[];
  const ids=races.map(r=>String(r.raceId??'')).filter(Boolean);
  const states=await betStates(db,ids);
  for(const race of races){
    const raceId=String(race.raceId??'');const s=states.get(raceId);if(!s)continue;
    const state=settledState(String(race.raceDate??''),String(race.status??''),true,s.hit);
    if(state)race.publicState=state;
  }
  const headers=new Headers(response.headers);headers.set('content-type','application/json; charset=utf-8');headers.delete('content-length');
  return new Response(JSON.stringify(data),{status:response.status,headers});
}

async function enhanceRace(request:Request,db:D1Database,response:Response):Promise<Response>{
  if(!response.ok)return response;
  const raceId=decodeURIComponent(new URL(request.url).pathname.slice('/races/'.length));
  const bets=await getPublicBets(db,raceId);if(!bets.length)return response;
  const raceDate=raceId.slice(0,10);const hit=bets.some(b=>Number(b.returnYen??0)>0);const state=settledState(raceDate,'',true,hit)??{code:'buy',label:'買い目あり',deadline:null};
  let html=await response.text();
  const missing=/\<div class="section-title"\>\<h2\>確定買い目\<\/h2\>\<span class="status buy"\>買い目あり\<\/span\>\<\/div\>\<div class="notice"\>[\s\S]*?\<\/div\>/;
  if(missing.test(html))html=html.replace(missing,tables(bets,state));
  html=html.replace(/<section class="panel" style="margin-top:12px"><h3>買い目について<\/h3>[\s\S]*?<\/section>/g,`<details class="bet-note"><summary>買い目のルール</summary><div>確定した買い目・購入額は結果後も変更しません。終了レースは将来の改善材料にのみ使います。</div></details>`);
  html=html.replace(/<span class="status (?:buy|skip)">(?:買い目あり|固定済み|見送り)<\/span>/g,`<span class="status ${state.code}">${state.label}</span>`);
  html=injectStyles(html);
  const headers=new Headers(response.headers);headers.set('content-type','text/html; charset=utf-8');headers.delete('content-length');
  return new Response(html,{status:response.status,headers});
}

export async function enhancePublicResponse(request:Request,db:D1Database,response:Response):Promise<Response>{
  const path=new URL(request.url).pathname;
  if(path==='/api/public/day')return enhanceDay(request,db,response);
  if(path.startsWith('/races/'))return enhanceRace(request,db,response);
  return response;
}
