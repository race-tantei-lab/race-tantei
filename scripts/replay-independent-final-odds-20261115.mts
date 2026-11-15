/** Replay the EXACT deployed cash6/cash96 selection + ticket decision methods.
 * Reads D1; Python exports retrospective official FINAL odds; no D1 writes.
 * Caveat: retrospective final odds are NOT pre-T15 odds and old state may
 * reflect retrospective stored horse weights; report as FINAL-ODDS REPLAY.
 */
import {readFile,writeFile,mkdir} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {dirname,join} from "node:path";
import {fitIndependent,independentlyRankRaces,chooseIndependentTickets,independentCourseBets,settleIndependent,type IndependentMode} from "../src/v1/independent-rolling-core.js";
import {oldSettled} from "../src/three-model-compare-page.js";
import {loadWorkerModel} from "../src/v1/completed-worker-live-lock.js";
import {completedFeatureVector,loadCompletedFeatureStateForRace} from "../src/v1/completed-feature-runtime.js";
import {normalizeCompletedWeights,type OfficialOddsRow} from "../src/v1/completed-ticket-runtime.js";

const root=join(dirname(fileURLToPath(import.meta.url)),"..");
const art=join(root,"artifacts");
const date=process.env.AUDIT_DATE || "2026-11-08";
const phase=process.argv[2];
const modes=["cash6","cash96"] as const;
const API="https://api.cloudflare.com/client/v4/accounts/"+process.env.CLOUDFLARE_ACCOUNT_ID+"/d1/database/"+process.env.CLOUDFLARE_D1_DATABASE_ID+"/query";
const token=process.env.CLOUDFLARE_API_TOKEN;
if(!token||!API||!/^20\d\d-\d\d-\d\d$/.test(date))throw Error("MISSING_AUDIT_CONFIG");
let sqlCount=0,recordsRead=0;
async function query(sql:string,params:unknown[]=[]):Promise<any[]>{
 if(/\b(INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE|CREATE)\b/i.test(sql))throw Error("READ_ONLY_SQL_ONLY");
 const res=await fetch(API,{method:"POST",headers:{"Authorization":"Bearer "+token,"content-type":"application/json"},body:JSON.stringify({sql,params})});
 if(!res.ok)throw Error("RETRO_D1_HTTP_"+res.status+":"+sql.slice(0,140));
 const data=await res.json() as {success:boolean;errors?:unknown;result?:Array<{results?:any[]}>};
 if(!data.success)throw Error("RETRO_D1_QUERY_FAILED:"+JSON.stringify(data.errors)+":"+sql.slice(0,140));
 const rows=data.result?.[0]?.results||[];
 sqlCount++;recordsRead+=rows.length;
 return rows;
}
class D1P{
 constructor(public sql:string,public values:unknown[]=[]){}
 bind(...args:unknown[]){return new D1P(this.sql,args);}
 async all(){return {results:await query(this.sql,this.values)};}
 async first(){return (await query(this.sql,this.values))[0]??null;}
}
const db={
 prepare:(sql:string)=>new D1P(sql),
 batch:async(stmts:D1P[])=>Promise.all(stmts.map(x=>x.all()))
} as unknown as D1Database;
type Race=Record<string,unknown>;
const raceSql="SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE race_date=? ORDER BY venue,race_no";
const horseSql="SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus FROM rt_runners WHERE race_id=? ORDER BY horse_no";

function makeQuotes(record:Record<string,any>):OfficialOddsRow[]{
 const nums=(record.horses||[]).map(Number).sort((a:number,b:number)=>a-b);
 const pairs:number[][]=[], orderedPairs:number[][]=[], triples:number[][]=[], orderedTriples:number[][]=[];
 for(const a of nums)for(const b of nums){
   if(b<=a)continue;
   pairs.push([a,b]);
 }
 for(const a of nums)for(const b of nums)if(a!==b)orderedPairs.push([a,b]);
 for(const a of nums)for(const b of nums)for(const c of nums)if(a<b&&b<c)triples.push([a,b,c]);
 for(const a of nums)for(const b of nums)for(const c of nums)if(a!==b&&a!==c&&b!==c)orderedTriples.push([a,b,c]);
 const markets:[string,number[][],string][]=[
  ["単勝",nums.map((n:number)=>[n]),"win"],
  ["ワイド",pairs,"wide"],
  ["馬連",pairs,"umaren"],
  ["馬単",orderedPairs,"umatan"],
  ["3連複",triples,"trio"],
  ["3連単",orderedTriples,"trifecta"],
 ];
 const rows:OfficialOddsRow[]=[];
 for(const [type,combos,key] of markets){
   const values=(record as any)[key]||[];
   if(values.length!==combos.length)throw Error("ODDS_MARKET_VECTOR_LENGTH_"+type+":"+record.raceId+":"+values.length+":"+combos.length);
   for(let i=0;i<combos.length;i++){
     const odd=Number(values[i]);
     if(Number.isFinite(odd)&&odd>=1)rows.push({betType:type as OfficialOddsRow["betType"],combination:combos[i].join("-"),oddsMin:odd,oddsMax:odd});
   }
 }
 return rows;
}
async function makePlan(){
 const races=await query(raceSql,[date]);
 const older=await oldSettled(db,date.slice(0,7));
 const selections={} as Record<IndependentMode,any[]>;
 for(const mode of modes){
   const fit=fitIndependent(date,mode,older);
   selections[mode]=independentlyRankRaces(date,mode,races as any,fit);
 }
 const ids=new Set(modes.flatMap(m=>selections[m].map(x=>x.raceId)));
 const model=await loadWorkerModel(db);
 const planned:any[]=[];const errors:any[]=[];
 for(const race of races){
   if(!ids.has(race.raceId))continue;
   try{
     const runners=(await query(horseSql,[race.raceId])).filter((x:any)=>(x.runnerStatus||"active")==="active");
     const iso=new Date(Date.parse(race.startTimeUtc)-20*60000).toISOString();
     const state=await loadCompletedFeatureStateForRace(db,race,runners,iso);
     const weights=normalizeCompletedWeights(runners.map((r:any)=>model.predict(completedFeatureVector(state,race,r,runners.length))));
     const payouts=await query("SELECT bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?",[race.raceId]);
     planned.push({raceId:race.raceId,race,horseNos:runners.map((r:any)=>Number(r.horseNo)),weights,payouts});
     console.log("RETRO_HORSE_FEATURES_OK",race.raceId,runners.length,weights.slice(0,4));
   }catch(e){
     errors.push({raceId:race.raceId,error:String(e)});
     console.error("RETRO_HORSE_FEATURES_FAIL",race.raceId,String(e));
   }
 }
 await mkdir(art,{recursive:true});
 const report={date,source:"deployed-cash6-cash96-source-functions",odds:"FINAL-not-Tminus15",
   models:selections,races:planned,errors,sqlCount,recordsRead};
 await writeFile(join(art,"independent-final-odds-plan.json"),JSON.stringify(report));
 console.log("INDEPENDENT_REPLAY_PLAN",JSON.stringify({date,chosen:Object.fromEntries(modes.map(m=>[m,selections[m].length])),unique:ids.size,featureRaces:planned.length,errors:errors.slice(0,8),sqlCount,recordsRead}));
 if(!planned.length)throw Error("NO_REPRODUCIBLE_HORSE_PROBABILITIES");
}
async function doSettle(){
 const plan=JSON.parse(await readFile(join(art,"independent-final-odds-plan.json"),"utf8"));
 const odds=JSON.parse(await readFile(join(art,"independent-retro-odds.json"),"utf8"));
 const older=await oldSettled(db,date.slice(0,7));
 const byRace=new Map<string,any>(odds.races.map((x:any)=>[x.raceId,x]));
 const byPlan=new Map<string,any>(plan.races.map((x:any)=>[x.raceId,x]));
 const summary:any={date,assumptions:["JRA official FINAL odds, not original T-15 odds","historical D1 runner feature snapshots replayed at race T-20","deployed independent ranking and two-ticket market combination functions","no original/canonical model ticket borrowing"],replays:{},originalSelectedCounts:Object.fromEntries(modes.map(x=>[x,plan.models[x].length])),oddsDownloaded:odds.races.length,oddsFailed:odds.errors,featureFailed:plan.errors};
 for(const mode of modes){
   const fit=fitIndependent(date,mode,older);
   const chosen=plan.models[mode];const bets:any[]=[];const fails:any[]=[];
   for(const sel of chosen){
     const p=byPlan.get(sel.raceId),row=byRace.get(sel.raceId);
     if(!p||!row){fails.push({raceId:sel.raceId,error:!p?"MISSING_HORSE_PROBABILITIES":"MISSING_JRA_FINAL_ODDS"});continue;}
     try{
       const quotes=makeQuotes(row),tickets=chooseIndependentTickets(p.race,mode,fit,p.horseNos,p.weights,quotes);
       const courseBets=independentCourseBets(tickets);
       const fake={date,mode,raceId:p.raceId,startTimeUtc:p.race.startTimeUtc,
         lockedAt:new Date(Date.parse(p.race.startTimeUtc)-20*60000).toISOString(),
         oddsFetchedAt:"retrospective-final-odds-not-prestart",sourceModel:"rolling-independent-cash-v1",
         oddsSource:"JRA_OFFICIAL_FINAL_RETROSPECTIVE",tickets,courseBets};
       const settled=settleIndependent(fake as any,p.payouts,true);
       if(!settled)throw Error("NOT_SETTLED");
       const ticketReturn=tickets.map((t,i)=>{
         const rate=p.payouts.find((q:any)=>q.betType===t.betType&&q.combination===t.combination)?.payoutYen||0;
         return Math.round(Number(rate)*courseBets.find((q:any)=>q.course==="ライト"&&q.betType===t.betType)?.stakeYen/100);
       });
       bets.push({raceId:sel.raceId,venue:p.race.venue,raceNo:p.race.raceNo,stake:2000,paid:settled.paid,hit:settled.hit,marketTypes:tickets.map(x=>x.betType),tickets:tickets.map(x=>({type:x.betType,combination:x.combination,odds:x.officialOdds})),ticketReturn,availableOdds:quotes.length});
       console.log("INDEPENDENT_FINAL_ODDS_TICKETS",mode,sel.raceId,tickets.map(x=>x.betType+":"+x.combination).join(","),"PAID",settled.paid);
     }catch(e){fails.push({raceId:sel.raceId,error:String(e)});console.error("INDEPENDENT_FINAL_ODDS_TICKETS_FAILED",mode,sel.raceId,String(e));}
   }
   const stake=bets.reduce((s,b)=>s+b.stake,0),paid=bets.reduce((s,b)=>s+b.paid,0);
   const largestTicket=Math.max(0,...bets.flatMap(b=>b.ticketReturn)),largestRace=Math.max(0,...bets.map(b=>b.paid));
   summary.replays[mode]={chosen:chosen.length,settled:bets.length,missing:fails,stakeYen:stake,returnYen:paid,profitYen:paid-stake,
     roiPct:stake?Number((paid/stake*100).toFixed(4)):null,
     roiWithoutLargestTicketPct:stake?Number(((paid-largestTicket)/stake*100).toFixed(4)):null,
     roiWithoutLargestRacePct:stake?Number(((paid-largestRace)/stake*100).toFixed(4)):null,
     hitRatePct:bets.length?Number((bets.filter(x=>x.hit).length/bets.length*100).toFixed(4)):null,
     bets};
 }
 await writeFile(join(art,"independent-final-odds-roi-result.json"),JSON.stringify(summary,null,2));
 console.log("INDEPENDENT_RETRO_FINAL_ODDS_ROI",JSON.stringify({date,modes:Object.fromEntries(modes.map(m=>[m,{chosen:summary.replays[m].chosen,settled:summary.replays[m].settled,stakeYen:summary.replays[m].stakeYen,returnYen:summary.replays[m].returnYen,roiPct:summary.replays[m].roiPct,roiWithoutLargestTicketPct:summary.replays[m].roiWithoutLargestTicketPct,hitRatePct:summary.replays[m].hitRatePct,missing:summary.replays[m].missing.slice(0,5)}]))}));
}
if(phase==="plan")await makePlan();
else if(phase==="settle")await doSettle();
else throw Error("USAGE: tsx scripts/replay-independent-final-odds-20261115.mts plan|settle");
