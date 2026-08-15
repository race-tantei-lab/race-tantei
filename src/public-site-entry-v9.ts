import publicSite from "./public-site-entry-v8.js";
import type { Env } from "./v1/types.js";
import { fetchJraPage, parseResultPage } from "./v1/jra.js";

const UNORDERED = new Set(["ワイド","馬連","3連複"]);

type PendingRace = {raceId:string;entryUrl:string;resultUrl:string|null;sourceResultUrl:string|null};
type PendingBet = {id:number;raceId:string;betType:string;combination:string;stakeYen:number;refunds:string|null;settlementStatus:string;currentReturnYen:number|null};

function canonical(betType:string,combination:string):string{
  const nums=(combination.match(/\d{1,2}/g)??[]).map(Number);
  if(UNORDERED.has(betType))nums.sort((a,b)=>a-b);
  return nums.join("-");
}

function jraRaceKey(url:string):string|null{
  try{
    const cname=decodeURIComponent(new URL(url).searchParams.get("CNAME")??"");
    const m=cname.match(/(?:pw|sw)01(?:dde01|sde01|sde10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})\//i);
    return m?m.slice(1,7).join(":"):null;
  }catch{return null;}
}

function isSameRaceResultUrl(url:string,targetKey:string):boolean{
  try{
    const cname=decodeURIComponent(new URL(url).searchParams.get("CNAME")??"");
    return /(?:pw|sw)01sde(?:01|10)/i.test(cname)&&jraRaceKey(url)===targetKey;
  }catch{return false;}
}

function decodeHref(value:string):string{
  return value.replace(/&amp;/g,"&").replace(/&#38;/g,"&").replace(/&quot;/g,'"').replace(/&#39;/g,"'");
}

function matchingResultUrl(entryHtml:string,entryUrl:string):string|null{
  const targetKey=jraRaceKey(entryUrl);if(!targetKey)return null;
  const matches:string[]=[];
  for(const match of entryHtml.matchAll(/href=["']([^"']*accessS\.html[^"']*)["']/gi)){
    try{
      const href=new URL(decodeHref(match[1]??""),entryUrl).href;
      if(isSameRaceResultUrl(href,targetKey))matches.push(href);
    }catch{/* next link */}
  }
  if(!matches.length)return null;
  // Current-day JRA result pages are exposed as sde01 and already contain result rows and payouts.
  // Prefer the exact same-race sde01 link discovered from the live entry page; never synthesize its checksum.
  return matches.find(url=>/(?:pw|sw)01sde01/i.test(decodeURIComponent(new URL(url).searchParams.get("CNAME")??"")))??matches[0]??null;
}

async function resolveOfficialResultUrl(race:PendingRace):Promise<string|null>{
  // Always rediscover the result link from the target race's current entry page. Stored URLs may carry a stale
  // checksum or, historically, may have been an unrelated result link discovered elsewhere in the entry HTML.
  const entry=await fetchJraPage(race.entryUrl);
  return matchingResultUrl(entry.html,entry.url);
}

async function neededBetTypes(db:D1Database,raceId:string):Promise<string[]>{
  const rows=await db.prepare(`
    SELECT DISTINCT bet_type AS betType
    FROM rt_public_bets
    WHERE race_id=?
      AND (settlement_status='pending' OR (settlement_status='settled' AND COALESCE(return_yen,0)=0))
  `).bind(raceId).all<{betType:string}>();
  return rows.results.map(row=>row.betType).filter(Boolean);
}

async function existingPayoutTypes(db:D1Database,raceId:string):Promise<Set<string>>{
  const rows=await db.prepare(`SELECT DISTINCT bet_type AS betType FROM rt_payouts WHERE race_id=?`).bind(raceId).all<{betType:string}>();
  return new Set(rows.results.map(row=>row.betType));
}

async function syncFinishedPayouts(db:D1Database):Promise<void>{
  try{
    const q=await db.prepare(`
      SELECT DISTINCT r.race_id AS raceId,r.entry_url AS entryUrl,r.result_url AS resultUrl,s.result_url AS sourceResultUrl
      FROM rt_races r
      JOIN rt_public_bets b ON b.race_id=r.race_id
      LEFT JOIN rt_race_sources s ON s.race_id=r.race_id AND s.entry_url=r.entry_url
      WHERE r.race_date>='2026-08-09'
        AND r.race_date>=date('now','-14 days')
        AND r.status='finished'
        AND r.entry_url IS NOT NULL
        AND (b.settlement_status='pending' OR (b.settlement_status='settled' AND COALESCE(b.return_yen,0)=0))
      ORDER BY r.race_date,r.venue,r.race_no
    `).all<PendingRace>();
    for(const race of q.results){
      const needed=await neededBetTypes(db,race.raceId);if(!needed.length)continue;
      const existing=await existingPayoutTypes(db,race.raceId);
      if(needed.every(type=>existing.has(type)))continue;
      try{
        const resultUrl=await resolveOfficialResultUrl(race);if(!resultUrl)continue;
        const page=await fetchJraPage(resultUrl);
        const result=parseResultPage(page.html,page.url);
        if(result.race.raceId!==race.raceId)continue;
        const payouts=result.payouts;
        const parsedTypes=new Set(payouts.map(p=>p.betType));
        if(!payouts.length||!needed.every(type=>parsedTypes.has(type)))continue;
        const statements=[
          db.prepare(`DELETE FROM rt_payouts WHERE race_id=?`).bind(race.raceId),
          ...payouts.map(p=>db.prepare(`
            INSERT INTO rt_payouts(race_id,bet_type,combination,payout_yen,popularity,updated_at)
            VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
          `).bind(race.raceId,p.betType,p.combination,p.payoutYen,p.popularity)),
          db.prepare(`
            UPDATE rt_races
            SET result_url=?, refund_horse_nos_json=?, result_updated_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE race_id=?
          `).bind(page.url,JSON.stringify(result.refundHorseNos),race.raceId),
          db.prepare(`UPDATE rt_race_sources SET result_url=?,updated_at=CURRENT_TIMESTAMP WHERE race_id=? AND entry_url=?`).bind(page.url,race.raceId,race.entryUrl)
        ];
        await db.batch(statements);
      }catch{/* identity/availability failures retry next request/cron */}
    }
  }catch{/* retry */}
}

async function settleFinishedBets(db:D1Database):Promise<void>{
  try{
    const q=await db.prepare(`
      SELECT b.id,b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,
             r.refund_horse_nos_json AS refunds,b.settlement_status AS settlementStatus,b.return_yen AS currentReturnYen
      FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date>='2026-08-09'
        AND r.race_date>=date('now','-14 days')
        AND r.status='finished'
        AND (b.settlement_status='pending' OR (b.settlement_status='settled' AND COALESCE(b.return_yen,0)=0))
      ORDER BY b.race_id,b.id
    `).all<PendingBet>();
    const byRace=new Map<string,PendingBet[]>();
    for(const b of q.results){const rows=byRace.get(b.raceId)??[];rows.push(b);byRace.set(b.raceId,rows);}
    for(const [raceId,bets] of byRace){
      const pq=await db.prepare(`SELECT bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?`).bind(raceId).all<{betType:string;combination:string;payoutYen:number}>();
      if(!pq.results.length)continue;
      const payoutTypes=new Set(pq.results.map(p=>p.betType));
      const payoutMap=new Map(pq.results.map(p=>[`${p.betType}:${canonical(p.betType,p.combination)}`,Number(p.payoutYen)]));
      let refunds=new Set<number>();try{refunds=new Set((JSON.parse(bets[0]?.refunds??"[]") as number[]).map(Number));}catch{/* empty */}
      const updates=[];
      for(const b of bets){
        const horses=(b.combination.match(/\d{1,2}/g)??[]).map(Number);
        let returned:number|null=null;
        if(horses.some(h=>refunds.has(h))){
          returned=Number(b.stakeYen);
        }else{
          const key=`${b.betType}:${canonical(b.betType,b.combination)}`;
          if(b.settlementStatus==='pending'){
            if(!payoutTypes.has(b.betType))continue;
            returned=Math.round(Number(b.stakeYen)/100*(payoutMap.get(key)??0));
          }else if(payoutMap.has(key)){
            returned=Math.round(Number(b.stakeYen)/100*Number(payoutMap.get(key)));
          }else{
            continue;
          }
        }
        if(returned===null)continue;
        const current=b.currentReturnYen===null?null:Number(b.currentReturnYen);
        if(b.settlementStatus==='settled'&&current===returned)continue;
        updates.push(db.prepare(`UPDATE rt_public_bets SET settlement_status='settled',return_yen=? WHERE id=?`).bind(returned,b.id));
      }
      if(updates.length)await db.batch(updates);
    }
  }catch{/* retry */}
}

async function syncAndSettle(db:D1Database):Promise<void>{await syncFinishedPayouts(db);await settleFinishedBets(db);}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const path=new URL(request.url).pathname;
    if(path==="/api/public/day"||path.startsWith("/races/"))ctx.waitUntil(syncAndSettle(env.DB));
    return publicSite.fetch(request,env,ctx);
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
    await syncAndSettle(env.DB);
  }
} satisfies ExportedHandler<Env>;