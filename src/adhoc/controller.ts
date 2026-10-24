import type { Env } from "../v1/types.js";
import { adhocPage } from "./page.js";

/** Queue-only controller: never imports the normal model, finalization, or settlement paths. */
const ID = /^20\d{2}-\d{2}-\d{2}-(tokyo|kyoto|hanshin|nakayama|chukyo|niigata|fukushima|kokura|sapporo|hakodate)-\d{2}$/;
const REQUEST_LEAD_MS = 75 * 60_000;
const FINAL_LEAD_MS = 15 * 60_000;
interface RaceRow { raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string; startTimeUtc: string; startTimeJst: string | null; status: string }
interface RequestRow { raceId: string; status: string; resultJson: string | null; startTimeUtc: string; message: string | null }
function jstDay(offset = 0): string { return new Date(Date.now() + 9 * 3600000 + offset * 86400000).toISOString().slice(0,10); }
function validId(x: unknown): x is string { return typeof x === "string" && x.length < 80 && ID.test(x); }
function json(x: unknown, status=200, cache="no-store"): Response {
  return Response.json(x,{status,headers:{"cache-control":cache,"x-content-type-options":"nosniff","x-robots-tag":"noindex, nofollow"}});
}
function error(message: string, status=400): Response { return json({ok:false,message},status); }
function canRequest(r: RaceRow): boolean {
  return !["cancelled","canceled","postponed","finished"].includes(String(r.status || "").toLowerCase())
    && Number.isFinite(Date.parse(r.startTimeUtc))
    && Date.parse(r.startTimeUtc) - Date.now() >= REQUEST_LEAD_MS;
}
async function raceList(env: Env): Promise<Response> {
  const q="SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,start_time_utc AS startTimeUtc,start_time_jst AS startTimeJst,status FROM rt_races WHERE race_date IN (?,?) AND start_time_utc IS NOT NULL AND race_no BETWEEN 1 AND 12 AND lower(COALESCE(status,'scheduled')) NOT IN ('cancelled','canceled','postponed') ORDER BY race_date,venue,race_no LIMIT 90";
  const rows=await env.DB.prepare(q).bind(jstDay(),jstDay(1)).all<RaceRow>();
  return json({ok:true,maxPerRaceDate:3,races:(rows.results??[]).filter(r=>validId(r.raceId)).map(r=>({...r,accepting:canRequest(r)}))},200,"public, max-age=20");
}
function validResult(row: RequestRow): unknown | null {
  if(row.status!=="ready" || !row.resultJson)return null;
  try {
    const v=JSON.parse(row.resultJson) as {generatedAtUtc?:string;ranking?:unknown[];tickets?:Array<{betType:string}>};
    if(!v.generatedAtUtc || !(Date.parse(v.generatedAtUtc)<Date.parse(row.startTimeUtc)-FINAL_LEAD_MS))return null;
    if(!Array.isArray(v.ranking)||v.ranking.length<3||v.tickets?.length!==2||new Set(v.tickets.map(t=>t.betType)).size!==2)return null;
    return v;
  } catch { return null; }
}
async function status(env:Env,id:string):Promise<Response> {
  const q="SELECT race_id AS raceId,status,result_json AS resultJson,start_time_utc AS startTimeUtc,message FROM rt_adhoc_requests WHERE race_id=? LIMIT 1";
  const row=await env.DB.prepare(q).bind(id).first<RequestRow>();
  if(!row)return json({ok:true,raceId:id,status:"none"},200,"public, max-age=20");
  const result=validResult(row);
  if(result)return json({ok:true,raceId:id,status:"ready",result},200,"public, max-age=30");
  if(row.status==="ready")return json({ok:true,raceId:id,status:"failed",message:"生成時刻と買い目の検証に失敗したため非公開です。"});
  if(Date.now()>=Date.parse(row.startTimeUtc)-FINAL_LEAD_MS && ["queued","running"].includes(row.status))
    return json({ok:true,raceId:id,status:"expired",message:"発走15分前までに計算が完了しませんでした。"},200,"public, max-age=20");
  return json({ok:true,raceId:id,status:row.status,message:row.message},200,"public, max-age=20");
}
async function submit(request:Request,env:Env):Promise<Response> {
  if(request.headers.get("origin")!==new URL(request.url).origin)return error("サイト内から操作してください。",403);
  if(!request.headers.get("content-type")?.startsWith("application/json"))return error("JSON形式のみ受け付けます。",415);
  if(Number(request.headers.get("content-length")||0)>256)return error("指定データが大きすぎます。",413);
  let input: {raceId?:unknown};
  try{input=await request.json() as {raceId?:unknown};}catch{return error("入力を読み取れません。");}
  const id=input?.raceId;
  if(!validId(id))return error("レースIDが正しくありません。");
  const old=await env.DB.prepare("SELECT status FROM rt_adhoc_requests WHERE race_id=? LIMIT 1").bind(id).first<{status:string}>();
  if(old)return json({ok:true,raceId:id,status:old.status,deduplicated:true});
  const race=await env.DB.prepare("SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,start_time_utc AS startTimeUtc,status FROM rt_races WHERE race_id=? LIMIT 1").bind(id).first<RaceRow>();
  if(!race || ![jstDay(),jstDay(1)].includes(race.raceDate))return error("受付対象外の開催日です。",422);
  if(!canRequest(race))return error("発走75分前を過ぎたか、レースが終了しています。",422);
  const selection=await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind("final_daily_selection:"+race.raceDate).first<{value:string}>();
  try {
    const data=JSON.parse(selection?.value||"{}") as {selected?:Array<{raceId:string}>};
    if(data.selected?.some(x=>x.raceId===id))return error("通常の自動予想対象です。専用の予想ページをご利用ください。",409);
  }catch{return error("既存の自動選定との重複確認に失敗しました。",503);}
  const horses=await env.DB.prepare("SELECT count(*) AS total FROM rt_runners WHERE race_id=? AND COALESCE(runner_status,'active')='active'").bind(id).first<{total:number}>();
  if(Number(horses?.total||0)<3)return error("出走馬データが揃っていません。",503);
  try {
    // The isolated D1 trigger enforces a global per-race-date cap atomically.
    await env.DB.prepare("INSERT OR IGNORE INTO rt_adhoc_requests(race_id,race_date,venue,race_no,start_time_utc,status,requested_at) VALUES(?,?,?,?,?,'queued',CURRENT_TIMESTAMP)")
      .bind(id,race.raceDate,race.venue,race.raceNo,race.startTimeUtc).run();
    const created=await env.DB.prepare("SELECT status FROM rt_adhoc_requests WHERE race_id=? LIMIT 1").bind(id).first<{status:string}>();
    if(!created)return error("無料枠がいっぱいのため受付を終了しました。",429);
    return json({ok:true,raceId:id,status:created.status},202);
  }catch(e){
    console.error("ADHOC_SUBMISSION_REJECTED",String(e).slice(0,150));
    return error("無料枠上限か一時的な混雑により受付できません。通常予想には影響しません。",429);
  }
}
export async function routeAdhoc(request:Request,env:Env):Promise<Response|null>{
  const path=new URL(request.url).pathname;
  if(request.method==="GET" && ["/adhoc","/adhoc/"].includes(path))return adhocPage();
  if(!path.startsWith("/api/adhoc/"))return null;
  try{
    if(request.method==="GET" && path==="/api/adhoc/races")return await raceList(env);
    if(request.method==="GET" && path==="/api/adhoc/status"){
      const id=new URL(request.url).searchParams.get("raceId");
      return validId(id)?status(env,id):error("レースIDが正しくありません。");
    }
    if(request.method==="POST" && path==="/api/adhoc/request")return await submit(request,env);
    return error("存在しない操作です。",404);
  }catch(e){
    console.error("ADHOC_API_ERROR",String(e).slice(0,200));
    return error("指定予想は一時停止中です。通常の自動予想には影響しません。",503);
  }
}
