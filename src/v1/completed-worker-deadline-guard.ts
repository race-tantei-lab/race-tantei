import { COMPLETED_MODEL_SHA256, COMPLETED_MODEL_VERSION } from "./completed-feature-runtime.js";
import { ensureCompletedFinalImmutability } from "./completed-final-invariants.js";
import { COMPLETED_COURSE_STAKES, type CompletedCourseBet, type CompletedTicket } from "./completed-ticket-runtime.js";
import type { Env } from "./types.js";

const SELECTION_PREFIX = "final_daily_selection:";
const PREVIEW_PREFIX = "worker_live_preview:";
const FINAL_PREFIX = "worker_live_final:";
const AUDIT_PREFIX = "worker_deadline_guard:";
export const DEADLINE_GUARD_MS = 15 * 60 * 1000;
export const DEADLINE_GUARD_ARM_MS = 20 * 60 * 1000;
const MAX_OFFICIAL_PREVIEW_AGE_MS = 60 * 60 * 1000;
const COURSES = Object.keys(COMPLETED_COURSE_STAKES) as Array<keyof typeof COMPLETED_COURSE_STAKES>;

type SelectionPayload = { sourceModel?: string; resultDataUsedForTargetDay?: boolean; selected?: Array<{ raceId?: string; venue?: string; raceNo?: number }> };
type RaceStartRow = { raceId: string; startTimeUtc: string | null };
type RaceIdentityRow = { raceDate: string; startTimeUtc: string | null };
type PublicBetRow = { course: string; betType: string; combination: string; stakeYen: number; settlementStatus: string; sourcePredictionId: number | null };
type CachedOfficialPreview = {
  version?: number; raceId?: string; sourceModel?: string; modelSha256?: string; generatedAt?: string;
  bodyWeightApplied?: boolean; bodyWeightSnapshot?: { fetchedAt?: string; sourceUrl?: string; snapshotSha256?: string; activeRunners?: unknown[] } | null;
  bodyWeightError?: string | null; oddsFetchedAt?: string; oddsSource?: string; oddsSnapshotSha256?: string;
  onlineLearning?: unknown; runnerRecencyFactors?: unknown; tickets?: CompletedTicket[]; courseBets?: CompletedCourseBet[];
};
type PreviewEnvelope = { version?: number; raceId?: string; snapshots?: CachedOfficialPreview[] };
export type DeadlineEnsureResult = { status: "locked" | "already_locked" | "outside_window" | "not_selected" | "preview_missing"; raceId: string; remainingMs: number };
export type DeadlineGuardAudit = {
  status: "ok" | "locked" | "error"; checkedAt: string; date: string; orderedSelectedRaceIds: string[]; dueRaceIds: string[];
  lockedRaceIds: string[]; lockedOfficialPreviewRaceIds: string[]; lockedProbabilityFallbackRaceIds: string[];
  skippedAlreadyLockedRaceIds: string[]; skippedOutsideWindowRaceIds: string[]; errors: Array<{ raceId: string; error: string }>;
};

function iso(now = new Date()): string { return now.toISOString(); }
function jstDate(now = new Date()): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }
function errorText(error: unknown): string { return error instanceof Error ? `${error.name}:${error.message}` : String(error); }
// Cloudflare invokes the production cron once per minute. Arming five minutes before the public T-15 deadline absorbs both the
// per-minute Worker cron and the independent five-minute live-tick backup so
// the official-odds snapshot is already immutable by T-15.
export function shouldDeadlineGuardLock(remainingMs: number): boolean { return Number.isFinite(remainingMs) && remainingMs > 0 && remainingMs <= DEADLINE_GUARD_ARM_MS; }

async function loadSelection(db: D1Database, date: string): Promise<string[]> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${SELECTION_PREFIX}${date}`).first<{ value: string }>();
  if (!row?.value) throw new Error(`DEADLINE_GUARD_SELECTION_MISSING:${date}`);
  const parsed = JSON.parse(row.value) as SelectionPayload;
  if (parsed.sourceModel !== COMPLETED_MODEL_VERSION || parsed.resultDataUsedForTargetDay !== false || !Array.isArray(parsed.selected) || !parsed.selected.length) throw new Error(`DEADLINE_GUARD_SELECTION_INVALID:${date}`);
  const ids = parsed.selected.map((item) => String(item.raceId || "")).filter(Boolean);
  if (!ids.length || new Set(ids).size !== ids.length) throw new Error(`DEADLINE_GUARD_SELECTION_IDS_INVALID:${date}`);
  return ids;
}

async function orderSelectedRaceIds(db: D1Database, date: string, ids: string[]): Promise<string[]> {
  const rows = await db.prepare("SELECT race_id AS raceId,start_time_utc AS startTimeUtc FROM rt_races WHERE race_date=?").bind(date).all<RaceStartRow>();
  const startById = new Map((rows.results ?? []).map((row) => [String(row.raceId), Date.parse(String(row.startTimeUtc || ""))]));
  return [...ids].sort((a,b) => {
    const av = Number.isFinite(startById.get(a)) ? Number(startById.get(a)) : Number.POSITIVE_INFINITY;
    const bv = Number.isFinite(startById.get(b)) ? Number(startById.get(b)) : Number.POSITIVE_INFINITY;
    return av-bv || a.localeCompare(b);
  });
}

async function publicRows(db: D1Database, raceId: string): Promise<PublicBetRow[]> {
  const result = await db.prepare(`SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,settlement_status AS settlementStatus,source_prediction_id AS sourcePredictionId FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination`).bind(raceId).all<PublicBetRow>();
  return result.results ?? [];
}

function strictComplete(rows: PublicBetRow[]): boolean {
  if (rows.length !== 6) return false;
  const signatures: string[] = [];
  for (const course of COURSES) {
    const current=rows.filter((row)=>row.course===course); const stakes=COMPLETED_COURSE_STAKES[course];
    if (current.length!==2 || new Set(current.map((row)=>row.betType)).size!==2) return false;
    if (current.some((row)=>Number(row.sourcePredictionId)!==-2)) return false;
    if (current.reduce((sum,row)=>sum+Number(row.stakeYen),0)!==stakes[0]+stakes[1]) return false;
    signatures.push(current.map((row)=>`${row.betType}\u0001${row.combination}`).sort().join("\u0002"));
  }
  return new Set(signatures).size===1;
}

function validOfficialPreview(snapshot: CachedOfficialPreview, raceId: string, now: Date): snapshot is CachedOfficialPreview & { tickets: CompletedTicket[]; courseBets: CompletedCourseBet[]; generatedAt: string; oddsFetchedAt: string; oddsSource: string; oddsSnapshotSha256: string } {
  if (snapshot.version!==1 || snapshot.raceId!==raceId || snapshot.sourceModel!==COMPLETED_MODEL_VERSION || snapshot.modelSha256!==COMPLETED_MODEL_SHA256) return false;
  const generatedMs=Date.parse(String(snapshot.generatedAt||"")); const oddsMs=Date.parse(String(snapshot.oddsFetchedAt||""));
  if (!Number.isFinite(generatedMs)||!Number.isFinite(oddsMs)||generatedMs>now.getTime()+5_000||oddsMs>now.getTime()+5_000||now.getTime()-generatedMs>MAX_OFFICIAL_PREVIEW_AGE_MS) return false;
  if (snapshot.oddsSource!=="jra-fast-official" && snapshot.oddsSource!=="jra-crawl-official") return false;
  if (!/^[0-9a-f]{64}$/.test(String(snapshot.oddsSnapshotSha256||""))) return false;
  if (!Array.isArray(snapshot.tickets)||snapshot.tickets.length!==2||new Set(snapshot.tickets.map((row)=>row.betType)).size!==2) return false;
  if (snapshot.tickets.some((row)=>!row.combination||!Number.isFinite(Number(row.officialOdds))||Number(row.officialOdds)<=0||!Number.isFinite(Number(row.predictedProbability))||Number(row.predictedProbability)<=0)) return false;
  if (!Array.isArray(snapshot.courseBets)||snapshot.courseBets.length!==6) return false;
  const signatures:string[]=[];
  for (const course of COURSES) {
    const rows=snapshot.courseBets.filter((row)=>row.course===course); const stakes=COMPLETED_COURSE_STAKES[course];
    if (rows.length!==2||new Set(rows.map((row)=>row.betType)).size!==2||rows.reduce((sum,row)=>sum+Number(row.stakeYen),0)!==stakes[0]+stakes[1]) return false;
    if (rows.some((row)=>!Number.isFinite(Number(row.assumedOdds))||Number(row.assumedOdds)<=0||!row.combination)) return false;
    signatures.push(rows.map((row)=>`${row.betType}\u0001${row.combination}`).sort().join("\u0002"));
  }
  return new Set(signatures).size===1;
}

async function latestOfficialPreview(db: D1Database, raceId: string, now: Date) {
  const row=await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${PREVIEW_PREFIX}${raceId}`).first<{value:string}>();
  if (!row?.value) return null;
  try { const parsed=JSON.parse(row.value) as PreviewEnvelope; if (parsed.version!==1||parsed.raceId!==raceId||!Array.isArray(parsed.snapshots)) return null; return parsed.snapshots.find((snapshot)=>validOfficialPreview(snapshot,raceId,now))??null; } catch { return null; }
}

async function commitCourseBets(db: D1Database, raceId: string, courseBets: CompletedCourseBet[], finalPayload: Record<string,unknown>, now: Date): Promise<void> {
  const existing=await publicRows(db,raceId); if (strictComplete(existing)) return;
  if (existing.some((row)=>Number(row.sourcePredictionId)!==-2||row.settlementStatus!=="pending")) throw new Error(`DEADLINE_GUARD_UNSAFE_PARTIAL:${raceId}`);
  const lockedAt=iso(now); const statements:D1PreparedStatement[]=[];
  if (existing.length) statements.push(db.prepare("DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'").bind(raceId));
  for (const bet of courseBets) statements.push(db.prepare(`INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)`).bind(raceId,bet.course,bet.betType,bet.combination,bet.stakeYen,Number(bet.assumedOdds),lockedAt));
  statements.push(db.prepare(`INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP`).bind(`${FINAL_PREFIX}${raceId}`,JSON.stringify({...finalPayload,status:"locked",raceId,lockedAt,sourceModel:COMPLETED_MODEL_VERSION,modelSha256:COMPLETED_MODEL_SHA256})));
  await db.batch(statements); if (!strictComplete(await publicRows(db,raceId))) throw new Error(`DEADLINE_GUARD_POST_WRITE_GATE_FAILED:${raceId}`);
}

async function commitOfficialPreview(db: D1Database, raceId: string, snapshot: CachedOfficialPreview & { tickets: CompletedTicket[]; courseBets: CompletedCourseBet[]; generatedAt: string; oddsFetchedAt: string; oddsSource: string; oddsSnapshotSha256: string }, now: Date): Promise<void> {
  const body=snapshot.bodyWeightSnapshot;
  await commitCourseBets(db,raceId,snapshot.courseBets,{finalizedFrom:"persistent_official_deadline_guard",previewGeneratedAt:snapshot.generatedAt,bodyWeightApplied:snapshot.bodyWeightApplied===true,bodyWeightFetchedAt:body?.fetchedAt??null,bodyWeightSource:body?.sourceUrl??null,bodyWeightSnapshotSha256:body?.snapshotSha256??null,bodyWeights:body?.activeRunners??null,bodyWeightError:snapshot.bodyWeightError??null,oddsMode:"official_cached_deadline_guard",oddsAvailable:true,oddsFetchedAt:snapshot.oddsFetchedAt,oddsSource:snapshot.oddsSource,oddsSnapshotSha256:snapshot.oddsSnapshotSha256,onlineLearning:snapshot.onlineLearning??null,runnerRecencyFactors:snapshot.runnerRecencyFactors??null,tickets:snapshot.tickets},now);
}

export async function ensureCompletedRaceFinalAtDeadline(env: Env, raceId: string, now = new Date()): Promise<DeadlineEnsureResult> {
  await ensureCompletedFinalImmutability(env.DB);
  if (strictComplete(await publicRows(env.DB,raceId))) return {status:"already_locked",raceId,remainingMs:Number.NaN};
  const race=await env.DB.prepare("SELECT race_date AS raceDate,start_time_utc AS startTimeUtc FROM rt_races WHERE race_id=? LIMIT 1").bind(raceId).first<RaceIdentityRow>();
  if (!race) throw new Error(`DEADLINE_GUARD_RACE_MISSING:${raceId}`);
  const selected=await loadSelection(env.DB,race.raceDate); if (!selected.includes(raceId)) return {status:"not_selected",raceId,remainingMs:Number.NaN};
  const startMs=Date.parse(String(race.startTimeUtc||"")); if (!Number.isFinite(startMs)) throw new Error(`DEADLINE_GUARD_START_TIME_INVALID:${raceId}`);
  const remainingMs=startMs-now.getTime(); if (!shouldDeadlineGuardLock(remainingMs)) return {status:"outside_window",raceId,remainingMs};
  const official=await latestOfficialPreview(env.DB,raceId,now); if (!official) return {status:"preview_missing",raceId,remainingMs};
  await commitOfficialPreview(env.DB,raceId,official,now); return {status:"locked",raceId,remainingMs};
}

async function saveAudit(db:D1Database,audit:DeadlineGuardAudit):Promise<void>{ await db.prepare(`INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP`).bind(`${AUDIT_PREFIX}${audit.date}`,JSON.stringify(audit)).run(); }

export async function runCompletedWorkerDeadlineGuard(env: Env, now = new Date()): Promise<DeadlineGuardAudit> {
  await ensureCompletedFinalImmutability(env.DB);
  const date=jstDate(now); const rawIds=await loadSelection(env.DB,date); const ids=await orderSelectedRaceIds(env.DB,date,rawIds);
  const audit:DeadlineGuardAudit={status:"ok",checkedAt:iso(now),date,orderedSelectedRaceIds:ids,dueRaceIds:[],lockedRaceIds:[],lockedOfficialPreviewRaceIds:[],lockedProbabilityFallbackRaceIds:[],skippedAlreadyLockedRaceIds:[],skippedOutsideWindowRaceIds:[],errors:[]};
  for (const raceId of ids) {
    try {
      if (strictComplete(await publicRows(env.DB,raceId))) { audit.skippedAlreadyLockedRaceIds.push(raceId); continue; }
      const start=await env.DB.prepare("SELECT start_time_utc AS startTimeUtc FROM rt_races WHERE race_id=? LIMIT 1").bind(raceId).first<{startTimeUtc:string|null}>();
      const startMs=Date.parse(String(start?.startTimeUtc||"")); if (!Number.isFinite(startMs)) throw new Error(`DEADLINE_GUARD_START_TIME_INVALID:${raceId}`);
      const remaining=startMs-now.getTime(); if (!shouldDeadlineGuardLock(remaining)) { audit.skippedOutsideWindowRaceIds.push(raceId); continue; }
      audit.dueRaceIds.push(raceId);
      const result=await ensureCompletedRaceFinalAtDeadline(env,raceId,now);
      if (result.status==="locked"||result.status==="already_locked") { audit.lockedRaceIds.push(raceId); audit.lockedOfficialPreviewRaceIds.push(raceId); }
      else if (result.status==="preview_missing") throw new Error(`DEADLINE_GUARD_PREVIEW_MISSING:${raceId}`);
      else throw new Error(`DEADLINE_GUARD_UNEXPECTED_STATUS:${raceId}:${result.status}`);
    } catch(error) { audit.errors.push({raceId,error:errorText(error)}); }
  }
  audit.status=audit.errors.length?"error":audit.lockedRaceIds.length?"locked":"ok"; await saveAudit(env.DB,audit); return audit;
}
