import {oldSettled} from "./three-model-compare-page.js";
import {fitIndependent,independentlyRankRaces,chooseIndependentTickets,independentCourseBets,canFreezeIndependent,INDEPENDENT_SOURCE_VERSION,type IndependentMode,type IndependentRace,type IndependentFinal,type IndependentSelection} from "./v1/independent-rolling-core.js";
import {loadWorkerModel} from "./v1/completed-worker-live-lock.js";
import {loadCompletedFeatureStateForRace,completedFeatureVector} from "./v1/completed-feature-runtime.js";
import {normalizeCompletedWeights} from "./v1/completed-ticket-runtime.js";
import {fetchFastJraOfficialOddsForRace} from "./v1/jra-official-odds-fetch.js";
import {shouldRunOnJraRaceDay} from "./v1/race-day-gate.js";
import type {Env,RaceRecord,RunnerRecord} from "./v1/types.js";

type RollingEnv=Env&{INDEPENDENT_MODEL_MODE?:string};
const SEL_PREFIX="independent_selection:";
const FINAL_PREFIX="independent_final:";
const JST_OFFSET=9*60*60*1000;
const MINUTES=60*1000;
const OPEN_MINUTES=90;
const MIN_LOCK_MINUTES=16;

function dateJST(now:Date):string{return new Date(now.getTime()+JST_OFFSET).toISOString().slice(0,10);}
function hourJST(now:Date):number{return Number(new Date(now.getTime()+JST_OFFSET).toISOString().slice(11,13));}
export function selectionKey(mode:IndependentMode,date:string):string{return SEL_PREFIX+mode+":"+date;}
export function finalKey(mode:IndependentMode,id:string):string{return FINAL_PREFIX+mode+":"+id;}
export function isIndependentMode(x:unknown):x is IndependentMode{return x==="cash6"||x==="cash96";}

async function scheduledRaces(db:D1Database,date:string):Promise<IndependentRace[]>{
 const r=await db.prepare(
 "SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,"+
 "surface,distance_m AS distanceM,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,"+
 "entry_url AS entryUrl,status FROM rt_races WHERE race_date=? ORDER BY venue,race_no"
 ).bind(date).all<IndependentRace>();
 return r.results||[];
}
async function freezeSelection(db:D1Database,mode:IndependentMode,date:string,now:Date):Promise<IndependentSelection|null>{
 const key=selectionKey(mode,date);
 const old=await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
   .bind(key).first<{value:string}>();
 if(old?.value)return JSON.parse(old.value) as IndependentSelection;
 if(hourJST(now)<8)return null;
 const races=await scheduledRaces(db,date);
 if(!races.length)return null;
 // Never select a previous result or open a model only after races started.
 const firstStart=Math.min(...races.map(r=>Date.parse(String(r.startTimeUtc||""))));
 if(!Number.isFinite(firstStart)||now.getTime()>firstStart-15*MINUTES)return null;
 if(races.some(r=>!r.entryUrl||!r.startTimeUtc||r.status==="cancelled"))return null;
 const older=await oldSettled(db,date.slice(0,7));
 const fit=fitIndependent(date,mode,older);
 const selected=independentlyRankRaces(date,mode,races,fit);
 const payload:IndependentSelection={
   date,mode,createdAt:now.toISOString(),sourceModel:INDEPENDENT_SOURCE_VERSION,
   trainingThrough:date.slice(0,7)+"-01",selected
 };
 await db.prepare("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO NOTHING")
   .bind(key,JSON.stringify(payload)).run();
 const authoritative=await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
   .bind(key).first<{value:string}>();
 if(!authoritative?.value)throw Error("INDEPENDENT_SELECTION_FREEZE_FAILED");
 const frozen=JSON.parse(authoritative.value) as IndependentSelection;
 if(frozen.mode!==mode||frozen.date!==date||frozen.sourceModel!==INDEPENDENT_SOURCE_VERSION)throw Error("INDEPENDENT_SELECTION_INVALID");
 return frozen;
}

async function loadRace(db:D1Database,id:string):Promise<{race:RaceRecord;runners:RunnerRecord[]}>{
 const [rr,hs]=await db.batch([
  db.prepare("SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE race_id=? LIMIT 1").bind(id),
  db.prepare("SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus FROM rt_runners WHERE race_id=? ORDER BY horse_no").bind(id)
 ]);
 const race=(rr.results||[])[0] as RaceRecord|undefined;
 if(!race||!race.entryUrl||!race.startTimeUtc)throw Error("INDEPENDENT_RACE_NOT_READY:"+id);
 const runners=((hs.results||[]) as RunnerRecord[]).filter(r=>(r.runnerStatus||"active")==="active");
 if(runners.length<3)throw Error("INDEPENDENT_RUNNERS_NOT_READY:"+id);
 return {race,runners};
}
async function lockSingle(db:D1Database,mode:IndependentMode,id:string,now:Date):Promise<boolean>{
 const {race,runners}=await loadRace(db,id);
 const deadline=Date.parse(race.startTimeUtc)-15*MINUTES;
 if(!Number.isFinite(deadline)||Date.now()>deadline||now.getTime()>deadline)throw Error("INDEPENDENT_T15_DEADLINE_PASSED");
 const fit=fitIndependent(race.raceDate,mode,await oldSettled(db,race.raceDate.slice(0,7)));
 const model=await loadWorkerModel(db);
 const state=await loadCompletedFeatureStateForRace(db,race,runners,now.toISOString());
 const vectors=runners.map(r=>completedFeatureVector(state,race,r,runners.length));
 const weights=normalizeCompletedWeights(vectors.map(v=>model.predict(v)));
 const fetched=await fetchFastJraOfficialOddsForRace(race.entryUrl,{raceDate:race.raceDate,venue:race.venue,raceNo:race.raceNo});
 const finishedAt=new Date().toISOString();
 if(!canFreezeIndependent(race.startTimeUtc,finishedAt,finishedAt))throw Error("INDEPENDENT_T15_FETCH_OVERRAN");
 const tickets=chooseIndependentTickets(race,mode,fit,runners.map(r=>Number(r.horseNo)),weights,fetched.rows);
 const courseBets=independentCourseBets(tickets);
 const final:IndependentFinal={
  date:race.raceDate,mode,raceId:id,lockedAt:finishedAt,oddsFetchedAt:finishedAt,
  startTimeUtc:race.startTimeUtc,oddsSource:fetched.source,sourceModel:INDEPENDENT_SOURCE_VERSION,
  tickets,courseBets
 };
 await db.prepare("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO NOTHING")
  .bind(finalKey(mode,id),JSON.stringify(final)).run();
 const r=await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=?")
  .bind(finalKey(mode,id)).first<{value:string}>();
 if(!r?.value)throw Error("INDEPENDENT_FINAL_NOT_PERSISTED");
 const frozen=JSON.parse(r.value) as IndependentFinal;
 if(!canFreezeIndependent(frozen.startTimeUtc,frozen.oddsFetchedAt,frozen.lockedAt)||
     frozen.tickets.length!==2||frozen.courseBets.length!==6)throw Error("INDEPENDENT_SAVED_FINAL_INVALID");
 return true;
}

export async function independentTick(env:RollingEnv,mode:IndependentMode,now=new Date()):Promise<Record<string,unknown>>{
 const date=dateJST(now);
 const selection=await freezeSelection(env.DB,mode,date,now);
 if(!selection)return {mode,date,status:"not_ready"};
 const candidates=selection.selected.filter(x=>x.raceId.startsWith(date+"-"));
 if(!candidates.length)return {mode,date,status:"no_targets"};
 const times=await env.DB.prepare(
   "SELECT race_id AS raceId,start_time_utc AS startTimeUtc FROM rt_races WHERE race_date=?"
 ).bind(date).all<{raceId:string;startTimeUtc:string|null}>();
 const timeMap=new Map((times.results||[]).map(x=>[x.raceId,Date.parse(String(x.startTimeUtc||""))]));
 const keys=candidates.map(x=>finalKey(mode,x.raceId));
 const existing=await env.DB.prepare(
   "SELECT state_key AS stateKey FROM rt_system_state WHERE state_key IN (SELECT value FROM json_each(?))"
 ).bind(JSON.stringify(keys)).all<{stateKey:string}>();
 const done=new Set((existing.results||[]).map(x=>x.stateKey));
 const eligible=candidates.filter(x=>{
   if(done.has(finalKey(mode,x.raceId)))return false;
   const start=timeMap.get(x.raceId)||NaN,remain=start-now.getTime();
   return Number.isFinite(start)&&remain>=MIN_LOCK_MINUTES*MINUTES&&remain<=OPEN_MINUTES*MINUTES;
 }).sort((a,b)=>(timeMap.get(a.raceId)||0)-(timeMap.get(b.raceId)||0));
 if(!eligible.length)return {mode,date,status:"no_race_in_window",selected:candidates.length,finalized:done.size};
 const target=eligible[0];
 try{
   await lockSingle(env.DB,mode,target.raceId,now);
   return {mode,date,status:"frozen",raceId:target.raceId};
 }catch(error){
   console.error("INDEPENDENT_MODEL_GENERATION_FAILED",mode,target.raceId,error);
   return {mode,date,status:"retry_before_deadline",raceId:target.raceId,error:String(error)};
 }
}
export default {
 async fetch():Promise<Response>{return new Response("NOT_FOUND",{status:404});},
 async scheduled(controller:ScheduledController,env:RollingEnv):Promise<void>{
   const mode=env.INDEPENDENT_MODEL_MODE;
   if(!isIndependentMode(mode))throw Error("MISSING_INDEPENDENT_MODE");
   const now=Number.isFinite(controller.scheduledTime)?new Date(controller.scheduledTime):new Date();
   const day=await shouldRunOnJraRaceDay(now);
   if(!day.shouldRun)return;
   const result=await independentTick(env,mode,new Date());
   console.log("INDEPENDENT_ROLLING_TICK",JSON.stringify(result));
 }
} satisfies ExportedHandler<RollingEnv>;
