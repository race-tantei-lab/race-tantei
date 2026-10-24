/**
 * On-demand prediction runner. Runs ONLY in GitHub Actions, NEVER in a Cloudflare Worker.
 * Existing canonical selections, bets, finalization and ROI records are read-only.
 * Every generated prediction is committed to rt_adhoc_requests only before T-15.
 */
import { createHash } from "node:crypto";
import { completedFeatureVector, loadCompletedFeatureStateForRace, COMPLETED_MODEL_SHA256 } from "../dist-test/src/v1/completed-feature-runtime.js";
import { loadCompletedModelRuntime } from "../dist-test/src/v1/completed-model-runtime.js";
import { completedRecencyBetFactor, loadCompletedRecencyLearning } from "../dist-test/src/v1/completed-recency-learning.js";
import { normalizeCompletedWeights, chooseCompletedTwoTickets } from "../dist-test/src/v1/completed-ticket-runtime.js";
import { fetchFastJraOfficialOddsForRace } from "../dist-test/src/v1/jra-official-odds-fetch.js";
import { fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";

const ACCOUNT="3c6d1826b573b2e68cb13ec37e9e8ade";
const DATABASE="949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const TOKEN=process.env.CLOUDFLARE_API_TOKEN;
if(!TOKEN)throw Error("CLOUDFLARE_API_TOKEN_MISSING");
const API="https://api.cloudflare.com/client/v4/accounts/"+ACCOUNT+"/d1/database/"+DATABASE+"/query";
const MAX_BEFORE_ROWS=2_500_000;
const MAX_JOB_ROWS=200_000;
const D1_TIMEOUT_MS=35000;
const DEADLINE_MS=900_000;
const sha256=data=>createHash("sha256").update(data).digest("hex");
let rowsRead=0;
let quoteAllowedWrites=false;
function checkSql(sql){
  const first=sql.trim().toUpperCase();
  if(/^(SELECT|WITH)\b/.test(first))return;
  if(quoteAllowedWrites && /^UPDATE RT_ADHOC_REQUESTS\b/.test(first))return;
  throw Error("CANONICAL_D1_WRITE_BLOCKED");
}
async function execute(sql,params=[]){
  checkSql(sql);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),D1_TIMEOUT_MS);
  try {
    const res=await fetch(API,{method:"POST",headers:{"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"},body:JSON.stringify({sql,params}),signal:controller.signal});
    const data=await res.json();
    if(!res.ok||!data.success)throw Error("D1_QUERY_REJECTED_"+res.status+":"+JSON.stringify(data.errors).slice(0,130));
    const item=data.result?.[0];
    if(!item)throw Error("D1_NO_RESULT");
    const read=Number(item.meta?.rows_read);
    if(!Number.isFinite(read))throw Error("D1_USAGE_META_MISSING");
    rowsRead+=read;
    if(rowsRead>MAX_JOB_ROWS)throw Error("ADHOC_QUERY_BUDGET_EXCEEDED:"+rowsRead);
    return item;
  } finally {clearTimeout(timer);}
}
async function sql(q,params=[]){return (await execute(q,params)).results||[];}
function database(){
  return {
    prepare(q){let args=[];return {
      bind(...values){args=values;return this;},
      async all(){return {results:await sql(q,args)};},
      async first(){return (await sql(q,args))[0]||null;},
    }},
    async batch(statements){return await Promise.all(statements.map(s=>s.all()));},
  };
}
async function checkAccountBudget(){
  const day=new Date().toISOString().slice(0,10);
  const q='query { viewer { accounts(filter:{accountTag:"'+ACCOUNT+'"}) { d1AnalyticsAdaptiveGroups(limit:20,filter:{date_geq:"'+day+'",date_leq:"'+day+'"}) { dimensions {date databaseId} sum {rowsRead rowsWritten} } } } }';
  const res=await fetch("https://api.cloudflare.com/client/v4/graphql",{method:"POST",headers:{"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"},body:JSON.stringify({query:q})});
  const json=await res.json();
  if(!res.ok||json.errors?.length)throw Error("D1_QUOTA_OBSERVABILITY_UNAVAILABLE");
  const accounts=json.data?.viewer?.accounts||[];
  if(!accounts.length)throw Error("D1_ACCOUNT_QUOTA_UNAVAILABLE");
  const found=accounts[0].d1AnalyticsAdaptiveGroups?.find(x=>x.dimensions?.databaseId===DATABASE);
  if(!found)throw Error("D1_DAILY_METRICS_MISSING");
  const used=Number(found.sum?.rowsRead);
  if(!Number.isFinite(used))throw Error("D1_ROWS_READ_METRIC_MISSING");
  if(used>=MAX_BEFORE_ROWS)throw Error("DAILY_D1_HEADROOM_TOO_LOW:"+used);
  console.log("ADHOC_D1_BUDGET",JSON.stringify({used,maxBefore:MAX_BEFORE_ROWS,perJobMax:MAX_JOB_ROWS}));
}
function hardDeadline(start){const ms=Date.parse(start)-DEADLINE_MS;if(!Number.isFinite(ms))throw Error("RACE_TIME_INVALID");return ms;}
function assertBefore(ms){if(Date.now()>=ms)throw Error("T15_DEADLINE_REACHED");}
async function updateOnlyAdhoc(sqlText,params){
  quoteAllowedWrites=true;
  try {return await execute(sqlText,params);}finally{quoteAllowedWrites=false;}
}
async function claim(raceId){
  const result=await updateOnlyAdhoc("UPDATE rt_adhoc_requests SET status='running',claimed_at=CURRENT_TIMESTAMP,attempts=attempts+1 WHERE race_id=? AND status='queued' AND unixepoch('now')<unixepoch(start_time_utc)-900",[raceId]);
  return Number(result.meta?.changes||0)===1;
}
async function setError(raceId,message,expired=false){
  await updateOnlyAdhoc("UPDATE rt_adhoc_requests SET status=?,message=?,completed_at=CURRENT_TIMESTAMP WHERE race_id=? AND status='running'",[expired?"expired":"failed",String(message).slice(0,180),raceId]);
}
async function getRace(raceId){
  const race=(await sql("SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE race_id=? LIMIT 1",[raceId]))[0];
  if(!race)throw Error("RACE_NOT_FOUND");
  const runners=await sql("SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus FROM rt_runners WHERE race_id=? ORDER BY horse_no",[raceId]);
  const active=runners.filter(x=>(x.runnerStatus||"active")==="active");
  if(active.length<3)throw Error("ACTIVE_RUNNERS_MISSING");
  return {race,runners:active};
}
async function checkNotSelected(raceId,date){
  const state=(await sql("SELECT state_value AS val FROM rt_system_state WHERE state_key=? LIMIT 1",["final_daily_selection:"+date]))[0];
  const selection=JSON.parse(String(state?.val||"{}"));
  if(selection.selected?.some(x=>x.raceId===raceId))throw Error("ALREADY_CANONICALLY_SELECTED");
}
async function officialInputs(race,runners,cutoffMs){
  // Use official pre-race JRA entry, not post-race result pages.
  assertBefore(cutoffMs);
  if(!race.entryUrl?.startsWith("https://"))throw Error("OFFICIAL_ENTRY_MISSING");
  const page=await fetchJraPage(race.entryUrl);
  if(!pageLooksLikeEntry(page.html))throw Error("OFFICIAL_ENTRY_PAGE_NOT_AVAILABLE");
  const bundle=parseEntryPage(page.html,page.url);
  if(bundle.race.raceId!==race.raceId)throw Error("OFFICIAL_RACE_ID_MISMATCH");
  const byNo=new Map(bundle.runners.map(r=>[Number(r.horseNo),r]));
  if(runners.some(x=>!byNo.has(Number(x.horseNo))))throw Error("OFFICIAL_HORSES_MISMATCH");
  const latest=bundle.runners.filter(r=>(r.runnerStatus||"active")==="active");
  if(latest.length!==runners.length)throw Error("OFFICIAL_ACTIVE_COUNT_MISMATCH");
  if(bundle.race.weather)race.weather=bundle.race.weather;
  if(bundle.race.trackCondition)race.trackCondition=bundle.race.trackCondition;
  if(bundle.race.direction)race.direction=bundle.race.direction;
  for(const r of runners){
    const fresh=byNo.get(Number(r.horseNo));
    if(Number.isInteger(Number(fresh.horseWeight)) && Number(fresh.horseWeight)>=250 && Number(fresh.horseWeight)<=700){
      r.horseWeight=Number(fresh.horseWeight);
      r.weightChange=fresh.weightChange==null?null:Number(fresh.weightChange);
    }
  }
  return runners.every(r=>Number.isInteger(Number(r.horseWeight))&&Number(r.horseWeight)>=250);
}
async function modelRuntime(){
  const m=new Map((await sql("SELECT key,value FROM rt_ml_model_meta")).map(r=>[r.key,r.value]));
  if(m.get("ready")!=="1"||m.get("modelVersion")!=="ten-year-completed-model"||m.get("sourceSha256")!==COMPLETED_MODEL_SHA256)throw Error("PRODUCTION_MODEL_IDENTITY_MISMATCH");
  const generation=m.get("generation"),count=Number(m.get("chunkCount")),size=Number(m.get("byteLength"));
  if(!generation||count<1||count>50||size<40||size>20_000_000)throw Error("MODEL_META_INVALID");
  const chunks=[];
  for(let i=0;i<count;i++){
    const rows=await sql("SELECT data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? AND seq=?",[generation,i]);
    if(rows.length!==1)throw Error("MODEL_CHUNK_MISSING_"+i);
    chunks.push(Buffer.from(rows[0].dataB64,"base64"));
  }
  const bytes=Buffer.concat(chunks);
  if(bytes.length!==size||sha256(bytes)!==m.get("binarySha256"))throw Error("MODEL_BINARY_HASH_MISMATCH");
  const runtime=loadCompletedModelRuntime(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
  if(runtime.featureCount!==56||runtime.treeCount!==500)throw Error("MODEL_SHAPE_UNEXPECTED");
  return runtime;
}
async function predict(raceId,startUtc){
  const cutoffMs=hardDeadline(startUtc);
  assertBefore(cutoffMs);
  const {race,runners}=await getRace(raceId);
  if(race.startTimeUtc!==startUtc)throw Error("OFFICIAL_RACE_TIME_CHANGED");
  if(["cancelled","canceled","postponed","finished"].includes(String(race.status||"").toLowerCase()))throw Error("RACE_NO_LONGER_OPEN");
  await checkNotSelected(raceId,race.raceDate);
  const startPrediction=new Date(); // Exact as-of cutoff: no future results.
  const bodyApplied=await officialInputs(race,runners,cutoffMs);
  if(!bodyApplied)throw Error("JRA_OFFICIAL_BODYWEIGHT_NOT_AVAILABLE");
  // Do not load a 3MB model or scan history until all six JRA odds types exist.
  // Next cron retries as an independent read-only attempt when data appears.
  const fetched=await fetchFastJraOfficialOddsForRace(race.entryUrl,{raceDate:race.raceDate,venue:race.venue,raceNo:race.raceNo});
  if(!["jra-fast-official","jra-crawl-official"].includes(fetched.source))throw Error("JRA_OFFICIAL_ODDS_SOURCE_NOT_AVAILABLE");
  const kinds=new Set(fetched.rows.map(x=>x.betType));
  if(["単勝","ワイド","馬連","馬単","3連複","3連単"].some(k=>!kinds.has(k)))throw Error("JRA_OFFICIAL_ODDS_NOT_ALL_PUBLISHED");
  const model=await modelRuntime();
  const state=await loadCompletedFeatureStateForRace(database(),race,runners,startPrediction.toISOString());
  const vectors=runners.map(r=>completedFeatureVector(state,race,r,runners.length));
  const raw=vectors.map(v=>model.predict(v));
  const base=normalizeCompletedWeights(raw);
  const learning=await loadCompletedRecencyLearning(database(),race,runners,startPrediction.toISOString());
  const weights=normalizeCompletedWeights(base.map((w,i)=>w*learning.runnerFactors[i]));
  assertBefore(cutoffMs);
  const tickets=chooseCompletedTwoTickets(runners.map(r=>Number(r.horseNo)),weights,fetched.rows,(type,odds)=>completedRecencyBetFactor(learning,type,race.venue,odds));
  if(tickets.length!==2||tickets[0].betType===tickets[1].betType)throw Error("TWO_DIFFERENT_TYPES_REQUIRED");
  // An incomplete or late result is never published, even if computation succeeded.
  const generatedAtUtc=new Date().toISOString();
  assertBefore(cutoffMs);
  return {
    schemaVersion:1,raceId,raceDate:race.raceDate,venue:race.venue,raceNo:race.raceNo,raceName:race.raceName,
    modelVersion:"ten-year-completed-model",modelSha256:COMPLETED_MODEL_SHA256,predictionPolicy:"completed-recency-v3-consistent-p02",
    generatedAtUtc,generatedAtJst:new Date(generatedAtUtc).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo",hour12:false}),
    officialBodyWeightApplied:bodyApplied,officialOddsSource:fetched.source,learningVersion:learning.audit.version,
    ranking:runners.map((r,i)=>({horseNo:Number(r.horseNo),horseName:r.horseName,winProbability:weights[i]})),
    tickets:tickets.map(t=>({betType:t.betType,combination:t.combination,officialOdds:t.officialOdds,predictedProbability:t.predictedProbability,score:t.score})),
  };
}
async function main(){
  // We do not charge a model load on empty schedule ticks.
  const requests=await sql("SELECT race_id AS raceId,start_time_utc AS startTimeUtc,race_date AS raceDate,attempts FROM rt_adhoc_requests WHERE status='queued' AND unixepoch('now')>=unixepoch(start_time_utc)-3300 AND unixepoch('now')<unixepoch(start_time_utc)-900 ORDER BY start_time_utc,requested_at,race_id LIMIT 1");
  if(!requests.length){console.log("ADHOC_QUEUE_EMPTY");return;}
  const task=requests[0];
  if(!await claim(task.raceId)){console.log("ADHOC_QUEUE_CLAIM_SKIPPED");return;}
  try {
    assertBefore(hardDeadline(task.startTimeUtc));
    await checkAccountBudget();
    const result=await predict(task.raceId,task.startTimeUtc);
    assertBefore(hardDeadline(task.startTimeUtc));
    const update=await updateOnlyAdhoc("UPDATE rt_adhoc_requests SET status='ready',result_json=?,message=NULL,completed_at=CURRENT_TIMESTAMP WHERE race_id=? AND status='running' AND unixepoch('now')<unixepoch(start_time_utc)-900",[JSON.stringify(result),task.raceId]);
    if(Number(update.meta?.changes||0)!==1)throw Error("T15_SAFE_COMMIT_REJECTED");
    console.log("ADHOC_PREDICTION_COMPLETE",JSON.stringify({raceId:task.raceId,types:result.tickets.map(t=>t.betType),bodyweight:result.officialBodyWeightApplied,rowsRead,asOf:result.generatedAtUtc}));
  }catch(err){
    const reason=String(err?.message||err).slice(0,165);
    console.error("ADHOC_PREDICTION_FAILED",JSON.stringify({raceId:task.raceId,reason,rowsRead}));
    const expired=Date.now()>=hardDeadline(task.startTimeUtc);
    const recoverable=/(?:JRA_|BODYWEIGHT|OFFICIAL_ODDS|OFFICIAL_ENTRY_PAGE|ODDS_MISSING|fetch failed|network|HTTP 5\\d\\d)/i.test(reason);
    try {
      if(!expired && recoverable && Number(task.attempts)<7) {
        await updateOnlyAdhoc("UPDATE rt_adhoc_requests SET status='queued',message=? WHERE race_id=? AND status='running' AND unixepoch('now')<unixepoch(start_time_utc)-900",[reason.slice(0,120),task.raceId]);
        console.log("ADHOC_RETRY_QUEUED",JSON.stringify({raceId:task.raceId,reason,attempts:Number(task.attempts)+1}));
      } else {
        await setError(task.raceId,reason,expired);
      }
    } catch(e){console.error("ADHOC_ERROR_STATE_FAILED",String(e).slice(0,150));}
    // Do not fail scheduled GitHub runs for a user-level quota/deadline rejection.
    process.exitCode=1;
  }
}
await main();
