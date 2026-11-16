/**
 * Source-faithful per-venue month/year return on investment.
 *
 * Historical 2016-08-10..2026-08-09: immutable original 14,410-race archive.
 * Production 2026-08-10 onward: ONLY source_prediction_id=-2, ライト,
 * exactly 2 actually settled tickets, ¥2,000 total stake per race.
 *
 * A fresh D1 reconciliation of ALL production race results is stored daily
 * after 19:05 JST. The public API adds *only* results after that cutoff
 * through the current day, cached to protect the Cloudflare D1 free tier.
 * Recomputing the closed production segment prevents double counts and
 * corrects late settlements rather than indefinitely accumulating errors.
 */
import historicalJson from "./venue-period-history.json" with {type:"json"};
import type {Env} from "./types.js";

export const VENUE_PERIOD_VERSION="venue-period-roi-v1-canonical-light";
export const VENUE_PERIOD_STATE_KEY="public_venue_period_performance:v1";
export const VENUE_PERIOD_HISTORICAL_THROUGH="2026-08-09";
export const VENUE_PERIOD_LIVE_FROM="2026-08-10";

export type VenuePeriodTotals={
  venue:string; period:string; races:number; stakeYen:number; returnYen:number; roiPct:number;
};
type Compact=[string,string,number,number,number]; // venue, YYYY-MM, count, stake, paid
type Saved={
  version:string; closedThroughDate:string; updatedAt:string; months:Compact[];
};
type RaceRow={
  raceDate:string;raceId:string;venue:string;
  rowCount:number;settledRows:number;stakeYen:number;returnYen:number;
};
export type VenuePeriods={
  ok:true;version:string;basis:string;
  historicalThrough:string;liveFrom:string;closedThroughDate:string;
  asOfDate:string;updatedAt:string;closedUpdatedAt:string|null;
  historicalRaces:number;productionRaces:number;
  venues:string[];months:VenuePeriodTotals[];years:VenuePeriodTotals[];
};
const staticData=historicalJson as unknown as {
  schema:string;historicalThrough:string;liveFrom:string;
  total:{races:number;stakeYen:number;returnYen:number};
  venues:string[];months:Compact[];
};
if(staticData.schema!=="jra-venue-month-history-canonical-v1"
  ||staticData.historicalThrough!==VENUE_PERIOD_HISTORICAL_THROUGH
  ||staticData.liveFrom!==VENUE_PERIOD_LIVE_FROM
  ||staticData.total.races!==14410
  ||staticData.total.stakeYen!==28820000
  ||staticData.total.returnYen!==124401700){
  throw Error("VENUE_PERIOD_HISTORICAL_BASELINE_INVALID");
}
const HISTORICAL:ReadonlyArray<Compact>=staticData.months;
const VENUENAMES=staticData.venues;
let savedCache:{until:number;saved:Saved|null}|null=null;
let apiCache:{until:number;date:string;response:VenuePeriods}|null=null;
const SAVED_CACHE_MS=75_000,API_CACHE_MS=75_000;

function dateJst(now:Date):string{
  return new Date(now.getTime()+9*3600_000).toISOString().slice(0,10);
}
function prevDate(date:string):string{
  return new Date(Date.parse(date+"T00:00:00Z")-86400_000).toISOString().slice(0,10);
}
function due(now:Date):boolean{
  const jst=new Date(now.getTime()+9*3600_000);
  return jst.getUTCHours()===19 && jst.getUTCMinutes()>=5 && jst.getUTCMinutes()<=30;
}
function validateSaved(x:unknown):Saved|null{
  if(!x||typeof x!=="object")return null;
  const v=x as Record<string,unknown>;
  if(v.version!==VENUE_PERIOD_VERSION||typeof v.closedThroughDate!=="string"
    ||!/^\d{4}-\d{2}-\d{2}$/.test(v.closedThroughDate)
    ||v.closedThroughDate<VENUE_PERIOD_HISTORICAL_THROUGH
    ||typeof v.updatedAt!=="string"||!Array.isArray(v.months))return null;
  const months:Compact[]=[];
  for(const item of v.months){
    if(!Array.isArray(item)||item.length!==5
      ||typeof item[0]!=="string"||!VENUENAMES.includes(item[0])
      ||typeof item[1]!=="string"||!/^\d{4}-\d{2}$/.test(item[1])
      ||item[1]<VENUE_PERIOD_LIVE_FROM.slice(0,7)
      ||item.slice(2).some(n=>typeof n!=="number"||!Number.isSafeInteger(n)||n<0))return null;
    months.push(item as Compact);
  }
  return {version:VENUE_PERIOD_VERSION,closedThroughDate:v.closedThroughDate,
    updatedAt:v.updatedAt,months};
}
async function readSaved(db:D1Database):Promise<Saved|null>{
  if(savedCache&&savedCache.until>Date.now())return savedCache.saved;
  const item=await db.prepare(
    "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1"
  ).bind(VENUE_PERIOD_STATE_KEY).first<{value:string}>();
  let value:Saved|null=null;
  if(item?.value){
    try{value=validateSaved(JSON.parse(item.value));}catch{value=null;}
  }
  savedCache={until:Date.now()+SAVED_CACHE_MS,saved:value};
  return value;
}
async function readRows(db:D1Database,afterDate:string,throughDate:string):Promise<RaceRow[]>{
  if(afterDate>=throughDate)return [];
  const sql="SELECT r.race_date AS raceDate,b.race_id AS raceId,r.venue AS venue,"+
    " COUNT(*) AS rowCount,"+
    " SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,"+
    " COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS stakeYen,"+
    " COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen"+
    " FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id"+
    " WHERE r.race_date>? AND r.race_date<=?"+
    " AND b.course='ライト' AND b.source_prediction_id=-2"+
    " GROUP BY r.race_date,b.race_id,r.venue ORDER BY r.race_date,b.race_id";
  const result=await db.prepare(sql).bind(afterDate,throughDate).all<RaceRow>();
  return (result.results??[]).map(row=>({
    raceDate:String(row.raceDate),raceId:String(row.raceId),venue:String(row.venue),
    rowCount:Number(row.rowCount),settledRows:Number(row.settledRows),
    stakeYen:Number(row.stakeYen),returnYen:Number(row.returnYen)
  }));
}
export function acceptedProductionRows(rows:RaceRow[]):Compact[]{
  const byMonth=new Map<string,Compact>();
  for(const row of rows){
    if(row.rowCount!==2||row.settledRows!==2||row.stakeYen!==2000||
       !Number.isFinite(row.returnYen)||row.returnYen<0||
       row.raceDate<VENUE_PERIOD_LIVE_FROM||!VENUENAMES.includes(row.venue))continue;
    const month=row.raceDate.slice(0,7),key=row.venue+"|"+month;
    let value=byMonth.get(key);
    if(!value){value=[row.venue,month,0,0,0];byMonth.set(key,value);}
    value[2]++;value[3]+=row.stakeYen;value[4]+=row.returnYen;
  }
  return [...byMonth.values()].sort((a,b)=>a[0].localeCompare(b[0],"ja")||a[1].localeCompare(b[1]));
}
function mergeMonths(groups:ReadonlyArray<Compact>[]):Compact[]{
  const result=new Map<string,Compact>();
  for(const source of groups)for(const item of source){
    const key=item[0]+"|"+item[1];
    const old=result.get(key);
    if(old){old[2]+=item[2];old[3]+=item[3];old[4]+=item[4];}
    else result.set(key,[...item] as Compact);
  }
  return [...result.values()];
}
function summarize(groups:Compact[],periodType:"month"|"year"):VenuePeriodTotals[]{
  const sums=new Map<string,Compact>();
  for(const row of groups){
    const period=periodType==="year"?row[1].slice(0,4):row[1];
    for(const venue of [row[0],"全会場"]){
      const key=venue+"|"+period;
      const out=sums.get(key);
      if(out){out[2]+=row[2];out[3]+=row[3];out[4]+=row[4];}
      else sums.set(key,[venue,period,row[2],row[3],row[4]]);
    }
  }
  return [...sums.values()].map((r)=>({
    venue:r[0],period:r[1],races:r[2],stakeYen:r[3],
    returnYen:r[4],roiPct:r[3]?r[4]/r[3]*100:0
  })).sort((a,b)=>
    a.venue.localeCompare(b.venue,"ja")||b.period.localeCompare(a.period));
}
export function buildVenuePeriods(
  closed:ReadonlyArray<Compact>,ongoing:ReadonlyArray<Compact>,
  closedThroughDate:string,updatedAt:string,closedUpdatedAt:string|null
):VenuePeriods{
  const all=mergeMonths([HISTORICAL,closed,ongoing]);
  const production=mergeMonths([closed,ongoing]);
  const productionRaces=production.reduce((n,r)=>n+r[2],0);
  return {
    ok:true,version:VENUE_PERIOD_VERSION,
    basis:"ten-year-backtest-plus-production-light-settled-complete-pairs",
    historicalThrough:VENUE_PERIOD_HISTORICAL_THROUGH,
    liveFrom:VENUE_PERIOD_LIVE_FROM,
    closedThroughDate,asOfDate:dateJst(new Date(updatedAt)),updatedAt,
    closedUpdatedAt,historicalRaces:staticData.total.races,productionRaces,
    venues:["全会場",...VENUENAMES],
    months:summarize(all,"month"),years:summarize(all,"year")
  };
}

/** Rebuild from the *entire* production ledger to reconcile late corrections.
 * Runs at most once daily in the 19:05-19:30 JST scheduled window.
 * No D1 reads on other 5-minute cron ticks. */
export async function refreshVenuePeriodsIfDue(env:Env,now=new Date()):Promise<{
  status:"outside_window"|"up_to_date"|"updated";closedThroughDate:string;months:number
}>{
  if(!due(now))return {status:"outside_window",closedThroughDate:"",months:0};
  const today=dateJst(now),yesterday=prevDate(today);
  const old=await readSaved(env.DB);
  if(old&&old.closedThroughDate>=yesterday&&old.updatedAt.slice(0,10)===now.toISOString().slice(0,10)){
    return {status:"up_to_date",closedThroughDate:old.closedThroughDate,months:old.months.length};
  }
  const rows=await readRows(env.DB,VENUE_PERIOD_HISTORICAL_THROUGH,yesterday);
  const months=acceptedProductionRows(rows);
  const next:Saved={
    version:VENUE_PERIOD_VERSION,closedThroughDate:yesterday,
    updatedAt:now.toISOString(),months
  };
  await env.DB.prepare(
    "INSERT INTO rt_system_state(state_key,state_value,updated_at)"+
    " VALUES(?,?,CURRENT_TIMESTAMP)"+
    " ON CONFLICT(state_key) DO UPDATE SET"+
    " state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP"
  ).bind(VENUE_PERIOD_STATE_KEY,JSON.stringify(next)).run();
  savedCache={until:Date.now()+SAVED_CACHE_MS,saved:next};
  apiCache=null;
  return {status:"updated",closedThroughDate:yesterday,months:months.length};
}

/** Live endpoint never writes D1 and never counts an incomplete race as 0 return. */
export async function venuePeriodResponse(db:D1Database,now=new Date()):Promise<Response>{
  const today=dateJst(now);
  if(apiCache&&apiCache.until>Date.now()&&apiCache.date===today){
    return responseJson(apiCache.response);
  }
  const stored=await readSaved(db);
  const closedThrough=stored?.closedThroughDate??VENUE_PERIOD_HISTORICAL_THROUGH;
  const ongoingRows=await readRows(db,closedThrough,today);
  const data=buildVenuePeriods(stored?.months??[],acceptedProductionRows(ongoingRows),
    closedThrough,now.toISOString(),stored?.updatedAt??null);
  apiCache={until:Date.now()+API_CACHE_MS,date:today,response:data};
  return responseJson(data);
}
function responseJson(data:VenuePeriods):Response{
  return Response.json(data,{headers:{
    "cache-control":"public, max-age=60, stale-while-revalidate=30",
    "x-race-venue-roi":VENUE_PERIOD_VERSION
  }});
}
