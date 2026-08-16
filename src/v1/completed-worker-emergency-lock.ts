import { COMPLETED_MODEL_SHA256, COMPLETED_MODEL_VERSION, completedFeatureVector, loadCompletedFeatureStateForRace } from "./completed-feature-runtime.js";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime.js";
import { completedRecencyBetFactor, loadCompletedRecencyLearning } from "./completed-recency-learning.js";
import { chooseCompletedProbabilityFallbackTickets, emergencyRunnerWeights } from "./completed-ticket-fallback.js";
import { COMPLETED_COURSE_STAKES, completedCourseBets, normalizeCompletedWeights } from "./completed-ticket-runtime.js";
import type { Env, RaceRecord, RunnerRecord } from "./types.js";

const SELECTION_PREFIX = "final_daily_selection:";
const FINAL_PREFIX = "worker_live_final:";
const AUDIT_PREFIX = "worker_emergency_lock:";
const DEADLINE_MS = 15 * 60 * 1000;
const LATE_LIMIT_MS = 14 * 60 * 1000;
const COURSES = Object.keys(COMPLETED_COURSE_STAKES) as Array<keyof typeof COMPLETED_COURSE_STAKES>;

type SelectionPayload = {
  sourceModel?: string;
  resultDataUsedForTargetDay?: boolean;
  selected?: Array<{ raceId?: string; venue?: string; raceNo?: number }>;
};
type PublicBetRow = { course: string; betType: string; combination: string; stakeYen: number; settlementStatus: string; sourcePredictionId: number | null };
type ModelMetaRow = { key: string; value: string };
type ModelChunkRow = { seq: number; dataB64: string };

export type EmergencyLockAudit = {
  status: "ok" | "locked" | "error";
  checkedAt: string;
  date: string;
  lockedRaceIds: string[];
  skippedAlreadyLockedRaceIds: string[];
  skippedOutsideWindowRaceIds: string[];
  errors: Array<{ raceId: string; error: string }>;
};

function iso(now = new Date()): string { return now.toISOString(); }
function jstDate(now = new Date()): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }
function errorText(error: unknown): string { return error instanceof Error ? `${error.name}:${error.message}` : String(error); }

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {
  const metaResult = await db.prepare("SELECT key,value FROM rt_ml_model_meta").all<ModelMetaRow>();
  const meta = new Map((metaResult.results ?? []).map((row) => [row.key, row.value]));
  if (meta.get("ready") !== "1" || meta.get("modelVersion") !== COMPLETED_MODEL_VERSION || meta.get("sourceSha256") !== COMPLETED_MODEL_SHA256) {
    throw new Error("EMERGENCY_MODEL_IDENTITY_INVALID");
  }
  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) throw new Error("EMERGENCY_MODEL_META_INVALID");
  const result = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq")
    .bind(generation).all<ModelChunkRow>();
  const rows = result.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("EMERGENCY_MODEL_CHUNKS_INVALID");
  const decoded = rows.map((row) => decodeBase64(row.dataB64));
  if (decoded.reduce((sum, row) => sum + row.byteLength, 0) !== byteLength) throw new Error("EMERGENCY_MODEL_LENGTH_INVALID");
  const merged = new Uint8Array(byteLength);
  let offset = 0;
  for (const row of decoded) { merged.set(row, offset); offset += row.byteLength; }
  return loadCompletedModelRuntime(merged.buffer);
}

async function loadSelection(db: D1Database, date: string): Promise<string[]> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`).first<{ value: string }>();
  if (!row?.value) return [];
  const parsed = JSON.parse(row.value) as SelectionPayload;
  if (parsed.sourceModel !== COMPLETED_MODEL_VERSION || parsed.resultDataUsedForTargetDay !== false || !Array.isArray(parsed.selected)) return [];
  return parsed.selected.map((item) => String(item.raceId || "")).filter(Boolean);
}

async function loadRace(db: D1Database, raceId: string): Promise<{ race: RaceRecord; runners: RunnerRecord[] }> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_id=? LIMIT 1
  `).bind(raceId).first<RaceRecord>();
  if (!race) throw new Error(`EMERGENCY_RACE_MISSING:${raceId}`);
  const rows = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  const runners = (rows.results ?? []).filter((runner) => (runner.runnerStatus || "active") === "active" && Number.isInteger(Number(runner.horseNo)));
  if (runners.length < 3) throw new Error(`EMERGENCY_RUNNERS_TOO_FEW:${raceId}:${runners.length}`);
  return { race, runners };
}

async function publicRows(db: D1Database, raceId: string): Promise<PublicBetRow[]> {
  const result = await db.prepare(`
    SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,settlement_status AS settlementStatus,source_prediction_id AS sourcePredictionId
    FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination
  `).bind(raceId).all<PublicBetRow>();
  return result.results ?? [];
}

function strictComplete(rows: PublicBetRow[]): boolean {
  if (rows.length !== 6) return false;
  const signatures: string[] = [];
  for (const course of COURSES) {
    const current = rows.filter((row) => row.course === course);
    const stakes = COMPLETED_COURSE_STAKES[course];
    if (current.length !== 2 || new Set(current.map((row) => row.betType)).size !== 2) return false;
    if (current.some((row) => Number(row.sourcePredictionId) !== -2)) return false;
    if (current.reduce((sum, row) => sum + Number(row.stakeYen), 0) !== stakes[0] + stakes[1]) return false;
    signatures.push(current.map((row) => `${row.betType}\u0001${row.combination}`).sort().join("\u0002"));
  }
  return new Set(signatures).size === 1;
}

async function buildFallback(db: D1Database, race: RaceRecord, runners: RunnerRecord[], now: Date) {
  const horseNos = runners.map((runner) => Number(runner.horseNo));
  let weightSource = "model";
  let weights: number[];
  let factor: ((betType: Parameters<typeof completedRecencyBetFactor>[1], odds: number) => number) | undefined;
  let learningAudit: unknown = null;
  try {
    const model = await loadWorkerModel(db);
    const cutoff = iso(now);
    const state = await loadCompletedFeatureStateForRace(db, race, runners, cutoff);
    const base = normalizeCompletedWeights(runners.map((runner) => model.predict(completedFeatureVector(state, race, runner, runners.length))));
    try {
      const learning = await loadCompletedRecencyLearning(db, race, runners, cutoff);
      weights = normalizeCompletedWeights(base.map((value, index) => value * learning.runnerFactors[index]));
      factor = (betType, odds) => completedRecencyBetFactor(learning, betType, race.venue, odds);
      learningAudit = learning.audit;
    } catch {
      weights = base;
    }
  } catch {
    weightSource = "runner_odds_or_uniform";
    weights = emergencyRunnerWeights(runners.map((runner) => runner.winOdds));
  }
  const tickets = chooseCompletedProbabilityFallbackTickets(horseNos, weights, factor);
  return { tickets, courseBets: completedCourseBets(tickets), weightSource, learningAudit };
}

async function commitFallback(db: D1Database, raceId: string, race: RaceRecord, runners: RunnerRecord[], now: Date): Promise<void> {
  const existing = await publicRows(db, raceId);
  if (strictComplete(existing)) return;
  if (existing.some((row) => Number(row.sourcePredictionId) !== -2 || row.settlementStatus !== "pending")) throw new Error(`EMERGENCY_UNSAFE_PARTIAL:${raceId}`);
  const fallback = await buildFallback(db, race, runners, now);
  const lockedAt = iso(now);
  const statements: D1PreparedStatement[] = [];
  if (existing.length) statements.push(db.prepare("DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'").bind(raceId));
  for (const bet of fallback.courseBets) {
    statements.push(db.prepare(`
      INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id)
      VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)
    `).bind(raceId, bet.course, bet.betType, bet.combination, bet.stakeYen, 1, lockedAt));
  }
  statements.push(db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${FINAL_PREFIX}${raceId}`, JSON.stringify({
    status: "locked",
    raceId,
    lockedAt,
    finalizedFrom: "probability_fallback_emergency",
    sourceModel: COMPLETED_MODEL_VERSION,
    modelSha256: COMPLETED_MODEL_SHA256,
    fallbackWeightSource: fallback.weightSource,
    oddsMode: "probability_fallback",
    oddsAvailable: false,
    oddsFetchedAt: null,
    oddsSource: null,
    onlineLearning: fallback.learningAudit,
    tickets: fallback.tickets,
  })));
  await db.batch(statements);
  if (!strictComplete(await publicRows(db, raceId))) throw new Error(`EMERGENCY_POST_WRITE_GATE_FAILED:${raceId}`);
}

async function saveAudit(db: D1Database, audit: EmergencyLockAudit): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${AUDIT_PREFIX}${audit.date}`, JSON.stringify(audit)).run();
}

export async function runCompletedWorkerEmergencyLock(env: Env, now = new Date()): Promise<EmergencyLockAudit> {
  const date = jstDate(now);
  const ids = await loadSelection(env.DB, date);
  const audit: EmergencyLockAudit = { status: "ok", checkedAt: iso(now), date, lockedRaceIds: [], skippedAlreadyLockedRaceIds: [], skippedOutsideWindowRaceIds: [], errors: [] };
  for (const raceId of ids) {
    try {
      const current = await publicRows(env.DB, raceId);
      if (strictComplete(current)) { audit.skippedAlreadyLockedRaceIds.push(raceId); continue; }
      const { race, runners } = await loadRace(env.DB, raceId);
      if (!race.startTimeUtc) throw new Error(`EMERGENCY_START_TIME_MISSING:${raceId}`);
      const remaining = Date.parse(race.startTimeUtc) - now.getTime();
      // Never manufacture a late pre-race prediction. The emergency writer is
      // allowed only inside the same T-15..T-14 recovery window as the canonical
      // GitHub backup. Anything later remains an auditable SLA failure.
      if (!(remaining <= DEADLINE_MS && remaining > LATE_LIMIT_MS)) { audit.skippedOutsideWindowRaceIds.push(raceId); continue; }
      await commitFallback(env.DB, raceId, race, runners, now);
      audit.lockedRaceIds.push(raceId);
    } catch (error) {
      audit.errors.push({ raceId, error: errorText(error) });
    }
  }
  audit.status = audit.errors.length ? "error" : audit.lockedRaceIds.length ? "locked" : "ok";
  await saveAudit(env.DB, audit);
  return audit;
}
