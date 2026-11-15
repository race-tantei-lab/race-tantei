/**
 * /models — compare THREE honest daily model outputs on the live site.
 * Read-only D1. A failure here must never affect / or an existing /races.
 * New cash methods transform locked existing 2-market combinations;
 * no user-visible claims of independently predicted new horses or live ROI.
 */
import type {Env} from "./v1/types.js";
import {compareThree,type Race,type Bet,type PastBet,type Panel} from "./v1/three-model-money-comparison.js";

type SelectState={value:string|null};
function esc(x:unknown):string{
  return String(x??"").replace(/[&<>"']/g,ch=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]||ch));
}
function yen(x:number):string{return Math.round(x).toLocaleString("ja-JP")+"円";}
function nowJST():string{return new Date(Date.now()+9*3600_000).toISOString().slice(0,10);}
function addDays(date:string,n:number):string{
  return new Date(Date.parse(date+"T00:00:00Z")+n*86400000).toISOString().slice(0,10);
}
function normalizeDate(raw:string|null):string{
  const now=nowJST(),candidate=raw&&/^20\d{2}-\d{2}-\d{2}$/.test(raw)?raw:now;
  const unix=Date.parse(candidate+"T00:00:00Z");
  if(!Number.isFinite(unix)||new Date(unix).toISOString().slice(0,10)!==candidate||
     candidate<"2026-08-10"||candidate>addDays(now,7))return now;
  return candidate;
}
function fmtStatus(x:string):string{
  return x==="actual"?"本番":x==="simulation"?"参考予想":x==="skipped"?"見送り":"判定待ち";
}
function modelTitle(id:string):string{
  return id==="cash6"?"直近6か月":id==="cash96"?"過去96か月":"現行";
}
function venueHtml(p:Panel,venue:string):string{
  const section=p.venues.find(v=>v.venue===venue);
  if(!section)return '<div class="no-data">選定レースなし</div>';
  return section.races.map(item=>{
    const cls=item.status;
    const heading='<div class="race-line"><a href="/races/'+encodeURIComponent(item.race.raceId)+'"><b>'
      +item.race.raceNo+'R</b> '+esc(item.race.raceName||"レース")+'</a><span class="model-status '+cls+'">'+fmtStatus(cls)+'</span></div>';
    const tickets=item.tickets.length?'<div class="model-tickets">'+item.tickets.map(x=>
      '<div class="model-ticket"><b>'+esc(x.betType)+' <span>'+esc(x.combination)+'</span></b>'+
      '<strong>'+yen(x.stakeYen)+'</strong><small>記録オッズ '+Number(x.assumedOdds).toFixed(1)+'倍</small></div>'
    ).join("")+'</div>':'';
    return '<article class="model-race '+cls+'">'+heading+tickets+
      '<p class="race-detail">'+esc(item.detail)+'</p></article>';
  }).join("");
}
function page(date:string,panels:Panel[]|null,notice:string|null):string{
  const venues=[...new Set((panels?.[0]?.venues||[]).map(x=>x.venue))];
  const months=date.slice(0,7);
  const cards=panels?venues.map(venue=>
    '<section class="venue-group"><h2>'+esc(venue)+'競馬場</h2><div class="model-grid">'+
    panels.map(p=>'<section class="model-column" data-model="'+esc(p.id)+'">'+
      '<header><h3>'+esc(p.title)+'</h3><p>'+esc(p.description)+'</p>'+
      '<span class="kind">'+(p.hypothetical?"研究・参考予測":"実際の公開買い目")+'</span></header>'+
      '<div class="races">'+venueHtml(p,venue)+'</div></section>').join("")+
    '</div></section>').join(""):'';
  const summary=panels?'<section class="summary" aria-label="モデルの概要"><div class="summary-grid">'+
    panels.map(p=>'<div><h3>'+esc(p.title)+'</h3><strong>'+p.selectedRaces+'R</strong>'+
      '<p>予想待ち '+p.awaitingRaces+'R</p></div>').join("")+'</div></section>':'';
  return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'+
  '<meta name="theme-color" content="#0b1020"><title>3つの予想モデル比較｜レース探偵</title>'+
  '<style>:root{color-scheme:dark;--bg:#0b1019;--surface:#141c29;--border:#324052;--text:#f1f5fa;--muted:#b4c1cf;--mint:#8de4c9}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans JP",sans-serif;line-height:1.6}main{max-width:1200px;margin:0 auto;padding:16px}a{color:#96dacf;text-decoration:none}h1,h2,h3,p{margin:0}h1{font-size:clamp(23px,4vw,35px)}h2{font-size:21px;margin-bottom:14px}h3{font-size:16px}nav{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0 25px}nav a:first-child{font-size:19px;font-weight:800;color:#fff}nav a:last-child{font-size:14px}.hero{background:linear-gradient(120deg,#1a2938,#12352d);border:1px solid #416e66;border-radius:18px;padding:23px}.hero p{color:#d1e1df;margin:7px 0 0}.controls{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:15px 0}.controls input,.controls button{font:inherit;border-radius:10px;padding:9px 12px;background:#1a2635;color:#fff;border:1px solid var(--border)}.controls button{cursor:pointer;background:#285d52;font-weight:700}.notice{border:1px solid #896943;background:#332818;border-radius:12px;padding:13px 15px;margin:15px 0}.summary{margin:20px 0}.summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.summary-grid>div,.model-column{border:1px solid var(--border);background:var(--surface);border-radius:15px;padding:14px}.summary strong{font-size:24px}.summary p{font-size:12px;color:var(--muted)}.venue-group{margin:28px 0}.model-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start}.model-column{padding:0;overflow:hidden}.model-column header{padding:16px;background:#1b2634;border-bottom:1px solid var(--border)}.model-column header p{font-size:12px;color:var(--muted);min-height:36px;margin-top:5px}.kind{display:inline-block;margin-top:8px;font-size:11px;border:1px solid #526c6e;border-radius:100px;padding:2px 8px}.races{padding:11px;display:grid;gap:10px}.model-race{border-radius:12px;border:1px solid #374454;padding:10px;background:#101925}.model-race.simulation{border-color:#326359}.model-race.awaiting,.model-race.skipped{opacity:.82}.race-line{display:flex;gap:7px;justify-content:space-between;align-items:flex-start}.race-line a{font-size:14px;color:#fff;font-weight:650}.model-status{border-radius:6px;border:1px solid #536679;font-size:10px;padding:2px 5px;white-space:nowrap}.model-status.simulation{border-color:#3d8a73;color:#a8ebca}.model-tickets{display:grid;gap:5px;margin:10px 0}.model-ticket{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;font-size:13px;padding:7px 5px;background:#1b2634;border-radius:7px}.model-ticket strong{color:var(--mint)}.model-ticket small{color:var(--muted);width:100%}.race-detail{font-size:11px;color:var(--muted)}.footnote{margin:25px 0;color:var(--muted);font-size:12px;padding:15px;border-top:1px solid var(--border)}@media(max-width:800px){main{padding:12px}.model-grid{grid-template-columns:1fr}.summary-grid{gap:7px}.summary-grid>div{padding:10px}.summary h3{font-size:12px}.summary strong{font-size:19px}.model-column header p{min-height:0}}@media(prefers-reduced-motion:no-preference){a:hover{text-decoration:underline}}</style></head><body>'+
  '<main><nav><a href="/">レース探偵</a><a href="/adhoc">指定レース予想</a></nav>'+
  '<section class="hero"><h1>3つの予想モデルを比較</h1><p>現行の買い目と、直近6か月・過去96か月の収益学習モデルを同じ会場・同じレースで比較します。</p></section>'+
  '<form class="controls" action="/models" method="GET"><label for="target-date">開催日</label><input id="target-date" type="date" name="date" value="'+esc(date)+'" min="2026-08-10" max="'+esc(addDays(nowJST(),7))+'"><button type="submit">表示する</button></form>'+
  '<section class="notice"><strong>新しい2モデルは参考予想です。</strong> <span>独立した馬予想器ではありません。現行の確定馬券を基に購入額と購入レースを変更します。過去の高回収率は8月以降に再現されていません。予想結果の事前確定や実際の購入を意味しません。</span></section>'+
  (notice?'<section class="notice" role="status">'+esc(notice)+'</section>':"")+
  summary+(cards||'<section class="notice">'+(panels?"この日に選定された会場・レースはありません。":"データ取得状況を確認してください。")+'</section>')+
  '<div class="footnote">比較対象はライトコース相当・1レース2,000円。現行モデルの実購入記録は変更しません。新方式の表示は試算であり、発走15分前に買い目を固定した独立実績ではありません。'+
  '学習は対象月より前のデータだけを使用します。保存済みの過去オッズは発走15分前のJRA公式オッズとして完全検証されていません。2026/8〜11の参考比較では両新モデルとも回収率200%未達です。</div></main></body></html>';
}
async function oldSettled(db:D1Database,month:string):Promise<PastBet[]>{
  const start="2026-08-10-",end=month+"-01-";
  // A bounded, read-only indexed race-ID range. Never download all 2016–26
  // history on a web request; 2016–Aug09 is a generated, bundled JSON prior.
  const out:PastBet[]=[];
  if(end<=start)return out;
  const limit=450;
  for(let offset=0;offset<3600;offset+=limit){
    const r=await db.prepare(
      "SELECT b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,"+
      "b.assumed_odds AS assumedOdds,b.locked_at AS lockedAt,b.return_yen AS returnYen,"+
      "b.settlement_status AS settlementStatus,r.race_date AS raceDate,r.venue,"+
      "r.race_no AS raceNo,r.race_name AS raceName,r.surface,r.distance_m AS distanceM,"+
      "r.start_time_utc AS startTimeUtc,r.start_time_jst AS startTimeJst "+
      "FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id "+
      "WHERE b.race_id>=? AND b.race_id<? AND b.course='ライト' "+
      "AND b.source_prediction_id=-2 AND b.settlement_status='settled' "+
      "ORDER BY b.race_id,b.id LIMIT ? OFFSET ?"
    ).bind(start,end,limit,offset).all<PastBet>();
    const items=r.results||[];
    out.push(...items);
    if(items.length<limit)return out;
  }
  throw Error("PAST_LIVE_CASH_PAGING_LIMIT_REACHED");
}
export async function threeModelPage(request:Request,env:Env):Promise<Response>{
  const date=normalizeDate(new URL(request.url).searchParams.get("date"));
  try{
    const key="final_daily_selection:"+date;
    const [state,racesResponse,betsResponse]=await Promise.all([
      env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
        .bind(key).first<SelectState>(),
      env.DB.prepare("SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,"+
        "race_name AS raceName,surface,distance_m AS distanceM,start_time_utc AS startTimeUtc,"+
        "start_time_jst AS startTimeJst FROM rt_races WHERE race_date=? ORDER BY venue,race_no")
        .bind(date).all<Race>(),
      env.DB.prepare("SELECT race_id AS raceId,bet_type AS betType,combination,stake_yen AS stakeYen,"+
        "assumed_odds AS assumedOdds,locked_at AS lockedAt,settlement_status AS settlementStatus,"+
        "return_yen AS returnYen FROM rt_public_bets WHERE race_id>=? AND race_id<? "+
        "AND course='ライト' AND source_prediction_id=-2 ORDER BY race_id,id")
        .bind(date+"-",addDays(date,1)+"-").all<Bet>(),
    ]);
    if(!state?.value)return new Response(page(date,null,"この日の確定選定はまだ公開されていません。"),{
      status:200,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
    const selection=JSON.parse(state.value) as {sourceModel?:string;selected?:Array<{raceId?:unknown}>};
    if(!Array.isArray(selection.selected))throw Error("INVALID_FROZEN_SELECTED_ARRAY");
    const frozen=selection.selected.map(x=>String(x.raceId||"")).filter(Boolean);
    if(frozen.length!==new Set(frozen).size)throw Error("DUPLICATE_FROZEN_SELECTION");
    const past=await oldSettled(env.DB,date.slice(0,7));
    const models=compareThree(date,frozen,racesResponse.results||[],betsResponse.results||[],past);
    const note=models.every(x=>x.selectedRaces===0)
      ?"確定した2券種の買い目がまだありません。現行モデルの確定後に比較が表示されます。":null;
    return new Response(page(date,models,note),{status:200,
      headers:{"content-type":"text/html; charset=utf-8",
        "cache-control":"no-store","x-race-three-models":"research-comparison-v1"}});
  }catch(error){
    console.error("THREE_MODEL_READ_ONLY_COMPARE_FAILED",date,error);
    return new Response(page(date,null,"現在、3モデルの比較データを取得できません。既存の予想画面には影響ありません。"),{
      status:200,headers:{"content-type":"text/html; charset=utf-8",
        "cache-control":"no-store","x-race-three-models":"read-only-unavailable"}});
  }
}
