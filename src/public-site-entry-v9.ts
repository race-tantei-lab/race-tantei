import publicSite from "./public-site-entry-v8.js";
import type { Env } from "./v1/types.js";
import { fetchJraPage } from "./v1/jra.js";
import { htmlToLines } from "./v1/utils.js";

const UNORDERED = new Set(["ワイド","馬連","3連複"]);

type PendingRace = {raceId:string;resultUrl:string|null};
type PendingBet = {id:number;raceId:string;betType:string;combination:string;stakeYen:number;refunds:string|null};
type Payout = {betType:string;combination:string;payoutYen:number;popularity:number|null};

function normalizeCombination(value:string):string|null{
  const normalized=value.replace(/[‐‑–—−ー→、,]/g,"-").replace(/\s+/g,"").replace(/[^0-9-]/g,"").replace(/-+/g,"-").replace(/^-|-$/g,"");
  return /^\d{1,2}(?:-\d{1,2}){0,2}$/.test(normalized)?normalized:null;
}

function parsePayoutText(html:string):Payout[]{
  const text=htmlToLines(html).join(" ").replace(/３/g,"3").replace(/\s+/g," ");
  const marker=text.match(/払戻金\s+単勝\s+/);if(!marker||marker.index===undefined)return[];
  let segment=text.slice(marker.index);
  const ends=[segment.indexOf("・ 勝馬投票"),segment.indexOf("勝馬の紹介")].filter(x=>x>0);if(ends.length)segment=segment.slice(0,Math.min(...ends));
  const typeMatches=[...segment.matchAll(/(?:^|\s)(単勝|複勝|枠連|ワイド|馬連|馬単|3連複|3連単)(?=\s)/g)];
  const out:Payout[]=[];
  typeMatches.forEach((tm,idx)=>{
    const betType=tm[1]??"";const start=(tm.index??0)+tm[0].length;const end=idx+1<typeMatches.length?(typeMatches[idx+1].index??segment.length):segment.length;const chunk=segment.slice(start,end);
    const arity=betType==="単勝"||betType==="複勝"?1:["枠連","ワイド","馬連","馬単"].includes(betType)?2:3;
    const combo=`\\d{1,2}${arity>1?`(?:-\\d{1,2}){${arity-1}}`:""}`;
    const re=new RegExp(`(${combo})\\s+([0-9,]+)\\s*円(?:\\s+(\\d+)\\s*番人気)?`,"g");
    for(const m of chunk.matchAll(re)){const combination=normalizeCombination(m[1]??"");if(!combination)continue;out.push({betType,combination,payoutYen:Number((m[2]??"0").replace(/,/g,"")),popularity:m[3]?Number(m[3]):null});}
  });
  const unique=new Map<string,Payout>();for(const p of out)unique.set(`${p.betType}:${p.combination}`,p);return[...unique.values()];
}

function canonical(betType:string,combination:string):string{
  const nums=(combination.match(/\d{1,2}/g)??[]).map(Number);if(UNORDERED.has(betType))nums.sort((a,b)=>a-b);return nums.join("-");
}

async function pendingBetTypes(db:D1Database,raceId:string):Promise<string[]>{
  const rows=await db.prepare(`SELECT DISTINCT bet_type AS betType FROM rt_public_bets WHERE race_id=? AND settlement_status='pending'`).bind(raceId).all<{betType:string}>();
  return rows.results.map(row=>row.betType).filter(Boolean);
}

async function existingPayoutTypes(db:D1Database,raceId:string):Promise<Set<string>>{
  const rows=await db.prepare(`SELECT DISTINCT bet_type AS betType FROM rt_payouts WHERE race_id=?`).bind(raceId).all<{betType:string}>();
  return new Set(rows.results.map(row=>row.betType));
}

async function syncFinishedPayouts(db:D1Database):Promise<void>{
  try{
    const q=await db.prepare(`
      SELECT DISTINCT r.race_id AS raceId,r.result_url AS resultUrl
      FROM rt_races r JOIN rt_public_bets b ON b.race_id=r.race_id
      WHERE r.race_date>='2026-08-09' AND r.status='finished' AND b.settlement_status='pending' AND r.result_url IS NOT NULL
      ORDER BY r.race_date,r.venue,r.race_no
    `).all<PendingRace>();
    for(const race of q.results){
      if(!race.resultUrl)continue;
      const needed=await pendingBetTypes(db,race.raceId);if(!needed.length)continue;
      const existing=await existingPayoutTypes(db,race.raceId);
      if(needed.every(type=>existing.has(type)))continue;
      try{
        const page=await fetchJraPage(race.resultUrl);const payouts=parsePayoutText(page.html);const parsedTypes=new Set(payouts.map(p=>p.betType));
        if(!payouts.length||!needed.every(type=>parsedTypes.has(type)))continue;
        const statements=payouts.map(p=>db.prepare(`
          INSERT INTO rt_payouts(race_id,bet_type,combination,payout_yen,popularity,updated_at)
          VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(race_id,bet_type,combination) DO UPDATE SET payout_yen=excluded.payout_yen,popularity=excluded.popularity,updated_at=CURRENT_TIMESTAMP
        `).bind(race.raceId,p.betType,p.combination,p.payoutYen,p.popularity));
        if(statements.length)await db.batch(statements);
      }catch{/* retry next request/cron */}
    }
  }catch{/* retry */}
}

async function settleFinishedBets(db:D1Database):Promise<void>{
  try{
    const q=await db.prepare(`
      SELECT b.id,b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,r.refund_horse_nos_json AS refunds
      FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date>='2026-08-09' AND r.status='finished' AND b.settlement_status='pending'
      ORDER BY b.race_id,b.id
    `).all<PendingBet>();
    const byRace=new Map<string,PendingBet[]>();for(const b of q.results){const rows=byRace.get(b.raceId)??[];rows.push(b);byRace.set(b.raceId,rows);}
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
        if(horses.some(h=>refunds.has(h)))returned=Number(b.stakeYen);
        else if(payoutTypes.has(b.betType))returned=Math.round(Number(b.stakeYen)/100*(payoutMap.get(`${b.betType}:${canonical(b.betType,b.combination)}`)??0));
        if(returned!==null)updates.push(db.prepare(`UPDATE rt_public_bets SET settlement_status='settled',return_yen=? WHERE id=? AND settlement_status='pending'`).bind(returned,b.id));
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
    if(path==="/api/public/day"||path.startsWith("/races/"))await syncAndSettle(env.DB);
    return publicSite.fetch(request,env,ctx);
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
    await syncAndSettle(env.DB);
  }
} satisfies ExportedHandler<Env>;
