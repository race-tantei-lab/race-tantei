import {
  COMPLETED_MODEL_SHA256,
  COMPLETED_MODEL_VERSION,
  completedFeatureVector,
  loadCompletedFeatureStateForRace,
} from "./completed-feature-runtime.js";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime.js";
import {
  COMPLETED_BET_ORDER,
  completedCombinationProbability,
  normalizeCompletedWeights,
  type CompletedBetType,
  type CompletedTicket,
} from "./completed-ticket-runtime.js";
import type { RaceRecord, RunnerRecord } from "./types.js";

const FINAL_PREFIX = "worker_live_final:";

type MetaRow = { key: string; value: string };
type ChunkRow = { seq: number; dataB64: string };
type PublicRow = { betType: string; combination: string; assumedOdds: number; courseCount: number };
type FinalPayload = {
  sourceModel?: string;
  modelSha256?: string;
  tickets?: CompletedTicket[];
};

export type FixedTicketEvidence = CompletedTicket & {
  horseNames: string[];
  evidenceSource: "fixed-snapshot" | "recomputed-from-public-lock";
};

let modelPromise: Promise<CompletedModelRuntime> | null = null;

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function loadModel(db: D1Database): Promise<CompletedModelRuntime> {
  if (modelPromise) return modelPromise;
  modelPromise = (async () => {
    const metaRows = await db.prepare("SELECT key,value FROM rt_ml_model_meta").all<MetaRow>();
    const meta = new Map((metaRows.results ?? []).map((row) => [row.key, row.value]));
    if (meta.get("ready") !== "1" || meta.get("modelVersion") !== COMPLETED_MODEL_VERSION || meta.get("sourceSha256") !== COMPLETED_MODEL_SHA256) throw new Error("FIXED_TICKET_EVIDENCE_MODEL_IDENTITY_INVALID");
    const generation = meta.get("generation") || "";
    const chunkCount = Number(meta.get("chunkCount") || 0), byteLength = Number(meta.get("byteLength") || 0);
    if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) throw new Error("FIXED_TICKET_EVIDENCE_MODEL_META_INVALID");
    const chunksResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ChunkRow>();
    const chunks = chunksResult.results ?? [];
    if (chunks.length !== chunkCount || chunks.some((row, index) => Number(row.seq) !== index)) throw new Error("FIXED_TICKET_EVIDENCE_MODEL_CHUNKS_INVALID");
    const parts = chunks.map((row) => decodeBase64(row.dataB64));
    const actualLength = parts.reduce((sum, row) => sum + row.byteLength, 0);
    if (actualLength !== byteLength) throw new Error("FIXED_TICKET_EVIDENCE_MODEL_BYTES_INVALID");
    const merged = new Uint8Array(byteLength);
    let offset = 0;
    for (const part of parts) { merged.set(part, offset); offset += part.byteLength; }
    return loadCompletedModelRuntime(merged.buffer);
  })().catch((error) => { modelPromise = null; throw error; });
  return modelPromise;
}

async function loadRace(db: D1Database, raceId: string): Promise<{ race: RaceRecord; runners: RunnerRecord[] }> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_id=? LIMIT 1
  `).bind(raceId).first<RaceRecord>();
  if (!race) throw new Error(`FIXED_TICKET_EVIDENCE_RACE_MISSING:${raceId}`);
  const runnerResult = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  const runners = (runnerResult.results ?? []).filter((runner) => (runner.runnerStatus || "active") === "active" && Number.isInteger(Number(runner.horseNo)));
  if (runners.length < 3) throw new Error(`FIXED_TICKET_EVIDENCE_RUNNERS_TOO_FEW:${raceId}:${runners.length}`);
  return { race, runners };
}

function validBetType(value: string): value is CompletedBetType {
  return (COMPLETED_BET_ORDER as readonly string[]).includes(value);
}

function namesFor(ticket: CompletedTicket, runners: RunnerRecord[]): string[] {
  const names = new Map(runners.map((runner) => [Number(runner.horseNo), String(runner.horseName || "")]));
  return ticket.horses.map((horseNo) => names.get(Number(horseNo)) || "");
}

async function finalSnapshot(db: D1Database, raceId: string, runners: RunnerRecord[]): Promise<FixedTicketEvidence[] | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${FINAL_PREFIX}${raceId}`).first<{ value: string }>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value) as FinalPayload;
    if (parsed.sourceModel !== COMPLETED_MODEL_VERSION || parsed.modelSha256 !== COMPLETED_MODEL_SHA256 || !Array.isArray(parsed.tickets) || parsed.tickets.length !== 2) return null;
    if (new Set(parsed.tickets.map((ticket) => ticket.betType)).size !== 2) return null;
    if (parsed.tickets.some((ticket) => !ticket.combination || !Number.isFinite(ticket.predictedProbability) || ticket.predictedProbability <= 0 || !Number.isFinite(ticket.officialOdds) || ticket.officialOdds <= 0 || !Number.isFinite(ticket.valueProduct) || !Number.isFinite(ticket.score))) return null;
    return parsed.tickets.map((ticket) => ({ ...ticket, horseNames: namesFor(ticket, runners), evidenceSource: "fixed-snapshot" as const }));
  } catch {
    return null;
  }
}

async function publicRows(db: D1Database, raceId: string): Promise<PublicRow[]> {
  const result = await db.prepare(`
    SELECT bet_type AS betType,combination,AVG(assumed_odds) AS assumedOdds,COUNT(DISTINCT course) AS courseCount
    FROM rt_public_bets WHERE race_id=? GROUP BY bet_type,combination ORDER BY bet_type,combination
  `).bind(raceId).all<PublicRow>();
  return (result.results ?? []).map((row) => ({ ...row, assumedOdds: Number(row.assumedOdds), courseCount: Number(row.courseCount) }));
}

function positionsForCombination(betType: CompletedBetType, combination: string, horseNos: number[]): { horses: number[]; positions: number[] } {
  const horses = combination.split("-").map(Number);
  const expected = betType === "単勝" ? 1 : (betType === "馬連" || betType === "ワイド" || betType === "馬単") ? 2 : 3;
  if (horses.length !== expected || horses.some((horse) => !Number.isInteger(horse))) throw new Error(`FIXED_TICKET_EVIDENCE_COMBINATION_INVALID:${betType}:${combination}`);
  const positions = horses.map((horse) => horseNos.indexOf(horse));
  if (positions.some((position) => position < 0) || new Set(positions).size !== positions.length) throw new Error(`FIXED_TICKET_EVIDENCE_HORSE_NOT_ACTIVE:${betType}:${combination}`);
  return { horses, positions };
}

async function recomputeFromPublicLock(db: D1Database, raceId: string, race: RaceRecord, runners: RunnerRecord[]): Promise<FixedTicketEvidence[]> {
  const rows = await publicRows(db, raceId);
  if (rows.length !== 2 || rows.some((row) => row.courseCount !== 3 || !validBetType(row.betType) || !Number.isFinite(row.assumedOdds) || row.assumedOdds <= 0)) throw new Error(`FIXED_TICKET_EVIDENCE_PUBLIC_SHAPE_INVALID:${raceId}:${rows.length}`);
  const state = await loadCompletedFeatureStateForRace(db, race, runners);
  const model = await loadModel(db);
  const horseNos = runners.map((runner) => Number(runner.horseNo));
  const weights = normalizeCompletedWeights(runners.map((runner) => model.predict(completedFeatureVector(state, race, runner, runners.length))));
  const names = new Map(runners.map((runner) => [Number(runner.horseNo), String(runner.horseName || "")]));
  return rows.map((row) => {
    const betType = row.betType as CompletedBetType;
    const parsed = positionsForCombination(betType, row.combination, horseNos);
    const predictedProbability = completedCombinationProbability(betType, parsed.positions, weights);
    const officialOdds = row.assumedOdds;
    const valueProduct = predictedProbability * officialOdds;
    const ticket: CompletedTicket = {
      betType,
      combination: row.combination,
      horses: parsed.horses,
      predictedProbability,
      officialOdds,
      valueProduct,
      score: Math.log(predictedProbability) + 0.4 * Math.log(officialOdds),
    };
    return { ...ticket, horseNames: ticket.horses.map((horseNo) => names.get(horseNo) || ""), evidenceSource: "recomputed-from-public-lock" as const };
  });
}

export async function loadFixedTicketEvidence(db: D1Database, raceId: string): Promise<FixedTicketEvidence[]> {
  const { race, runners } = await loadRace(db, raceId);
  const exact = await finalSnapshot(db, raceId, runners);
  if (exact) return exact;
  return recomputeFromPublicLock(db, raceId, race, runners);
}
