import {
  bodyWeightSnapshotMatchesRunners,
  refreshOfficialBodyWeights,
  resolveOfficialBodyWeights,
  type OfficialBodyWeightSnapshot,
} from "./bodyweight-refresh";
import { COMPLETED_MODEL_SHA256, COMPLETED_MODEL_VERSION, completedFeatureVector, loadCompletedFeatureStateForRace } from "./completed-feature-runtime";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";
import { completedRecencyBetFactor, loadCompletedRecencyLearning, neutralCompletedRecencyLearning, type CompletedRecencyAudit, type CompletedRunnerRecencyDetail } from "./completed-recency-learning";
import {
  COMPLETED_COURSE_STAKES,
  chooseCompletedTwoTickets,
  completedCourseBets,
  normalizeCompletedWeights,
  type CompletedCourseBet,
  type CompletedTicket,
} from "./completed-ticket-runtime";
import { fetchFastJraOfficialOddsForRace, type OfficialOddsRow } from "./jra-official-odds-fetch";
import { ensureCompletedFinalImmutability } from "./completed-final-invariants";
import type { Env, RaceRecord, RunnerRecord } from "./types";

const SELECTION_PREFIX = "final_daily_selection:";
const AUDIT_PREFIX = "worker_live_lock:";
const PREVIEW_PREFIX = "worker_live_preview:";
const FINAL_PREFIX = "worker_live_final:";
const BODY_WEIGHT_REFRESH_OPEN_MS = 100 * 60 * 1000;
const PREVIEW_OPEN_MS = 90 * 60 * 1000;
const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;
const NORMAL_LOCK_MS = 25 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;
const EARLY_PREVIEW_REFRESH_MS = 10 * 60 * 1000;
const MID_PREVIEW_REFRESH_MS = 5 * 60 * 1000;
const NEAR_PREVIEW_REFRESH_MS = 4 * 60 * 1000;
const PREVIEW_HISTORY = 3;
const PREVIEW_VERSION = 1;
const OFFICIAL_ODDS_SOURCES = new Set(["jra-fast-official", "jra-crawl-official"]);
const COURSES = Object.keys(COMPLETED_COURSE_STAKES) as Array<keyof typeof COMPLETED_COURSE_STAKES>;

type SelectionRow = { raceId?: string; venue?: string; raceNo?: number };
type SelectionPayload = {
  sourceModel?: string;
  resultDataUsedForTargetDay?: boolean;
  selected?: SelectionRow[];
};

type PublicBetRow = {
  course: string;
  betType: string;
  combination: string;
  stakeYen: number;
  settlementStatus: string;
  sourcePredictionId: number | null;
};

type ModelMetaRow = { key: string; value: string };
type ModelChunkRow = { seq: number; dataB64: string };

type PreviewSnapshot = {
  version: 1;
  raceId: string;
  sourceModel: string;
  modelSha256: string;
  generatedAt: string;
  bodyWeightApplied?: boolean;
  bodyWeightSnapshot?: OfficialBodyWeightSnapshot | null;
  bodyWeightError?: string | null;
  oddsFetchedAt: string;
  oddsSource: string;
  oddsSnapshotSha256: string;
  onlineLearning?: CompletedRecencyAudit;
  runnerRecencyFactors?: CompletedRunnerRecencyDetail[];
  tickets: CompletedTicket[];
  courseBets: CompletedCourseBet[];
};

type PreviewEnvelope = {
  version: 1;
  raceId: string;
  snapshots: PreviewSnapshot[];
};

type Audit = {
  status: string;
  checkedAt: string;
  date: string;
  sourceModel: string;
  selectedRaceCount: number;
  completeBefore: number;
  completeAfter: number;
  lockedByWorker: string[];
  refreshedBodyWeightRaceIds: string[];
  bodyWeightPendingRaceIds: string[];
  bodyWeightBreachRaceIds: string[];
  refreshedPreviewRaceIds: string[];
  previewAvailableRaceIds: string[];
  previewMissingUrgentRaceIds: string[];
  finalizedFromFreshRaceIds: string[];
  finalizedFromFallbackRaceIds: string[];
  latePromotedRaceIds: string[];
  protectedRaceIds: string[];
  incompleteRaceIds: string[];
  deadlineBreachRaceIds: string[];
  notYetInWindowRaceIds: string[];
  alreadyStartedIncompleteRaceIds: string[];
  errors: Array<{ raceId: string; error: string }>;
};

function iso(now = new Date()): string {
  return now.toISOString();
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function canonicalOddsRows(rows: OfficialOddsRow[]): string {
  return JSON.stringify(
    rows
      .map((row) => [row.betType, row.combination, Number(row.oddsMin), Number(row.oddsMax)] as const)
      .sort((a, b) => `${a[0]}\u0001${a[1]}`.localeCompare(`${b[0]}\u0001${b[1]}`)),
  );
}

let cachedWorkerModel: { identity: string; runtime: CompletedModelRuntime } | null = null;

async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {
  const metaResult = await db.prepare("SELECT key,value FROM rt_ml_model_meta").all<ModelMetaRow>();
  const meta = new Map((metaResult.results ?? []).map((row) => [row.key, row.value]));
  if (meta.get("ready") !== "1") throw new Error("WORKER_MODEL_NOT_READY");
  if (meta.get("modelVersion") !== COMPLETED_MODEL_VERSION || meta.get("sourceSha256") !== COMPLETED_MODEL_SHA256) {
    throw new Error("WORKER_MODEL_IDENTITY_MISMATCH");
  }
  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) {
    throw new Error("WORKER_MODEL_META_INVALID");
  }
  const identity = `${generation}:${COMPLETED_MODEL_SHA256}:${byteLength}:${chunkCount}`;
  if (cachedWorkerModel?.identity === identity) return cachedWorkerModel.runtime;
  const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();
  const rows = chunkResult.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("WORKER_MODEL_CHUNKS_INCOMPLETE");
  const decoded = rows.map((row) => decodeBase64(row.dataB64));
  const actualBytes = decoded.reduce((sum, row) => sum + row.byteLength, 0);
  if (actualBytes !== byteLength) throw new Error(`WORKER_MODEL_BYTE_LENGTH_MISMATCH:${actualBytes}:${byteLength}`);
  const merged = new Uint8Array(byteLength);
  let offset = 0;
  for (const row of decoded) { merged.set(row, offset); offset += row.byteLength; }
  const runtime = loadCompletedModelRuntime(merged.buffer);
  cachedWorkerModel = { identity, runtime };
  return runtime;
}

function validateSelection(payload: SelectionPayload): string[] {
  if (payload.sourceModel !== COMPLETED_MODEL_VERSION) throw new Error(`WORKER_SELECTION_MODEL_INVALID:${payload.sourceModel}`);
  if (payload.resultDataUsedForTargetDay !== false) throw new Error("WORKER_SELECTION_TARGET_RESULT_LEAK");
  if (!Array.isArray(payload.selected) || !payload.selected.length) throw new Error("WORKER_SELECTION_EMPTY");
  const counts = new Map<string, number>();
  const ids: string[] = [];
  for (const row of payload.selected) {
    const raceId = String(row.raceId || "");
    const venue = String(row.venue || "");
    if (!raceId || !venue) throw new Error("WORKER_SELECTION_ROW_INVALID");
    ids.push(raceId);
    counts.set(venue, (counts.get(venue) ?? 0) + 1);
  }
  if (new Set(ids).size !== ids.length || counts.size < 2 || [...counts.values()].some((count) => count !== 5)) {
    throw new Error(`WORKER_SELECTION_NOT_FIVE_PER_VENUE:${JSON.stringify(Object.fromEntries(counts))}`);
  }
  return ids;
}

async function loadSelection(db: D1Database, date: string): Promise<SelectionPayload | null> {
  const result = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${SELECTION_PREFIX}${date}`).first<{ value: string }>();
  if (!result?.value) return null;
  return JSON.parse(result.value) as SelectionPayload;
}

async function loadRace(db: D1Database, raceId: string): Promise<{ race: RaceRecord; runners: RunnerRecord[] }> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_id=? LIMIT 1
  `).bind(raceId).first<RaceRecord>();
  if (!race) throw new Error(`WORKER_RACE_NOT_FOUND:${raceId}`);
  const runnerResult = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  const runners = (runnerResult.results ?? []).filter((runner) => (runner.runnerStatus || "active") === "active" && Number.isInteger(Number(runner.horseNo)));
  if (runners.length < 3) throw new Error(`WORKER_ACTIVE_RUNNERS_TOO_FEW:${raceId}:${runners.length}`);
  return { race, runners };
}

async function publicBetRows(db: D1Database, raceId: string): Promise<PublicBetRow[]> {
  const result = await db.prepare(`
    SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,settlement_status AS settlementStatus,source_prediction_id AS sourcePredictionId
    FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination
  `).bind(raceId).all<PublicBetRow>();
  return result.results ?? [];
}

function isStrictComplete(rows: PublicBetRow[]): boolean {
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

function validBodyWeightSnapshot(snapshot: OfficialBodyWeightSnapshot | null | undefined, raceId: string): boolean {
  if (!snapshot || snapshot.version !== 1 || snapshot.raceId !== raceId) return false;
  if (!Number.isFinite(Date.parse(snapshot.fetchedAt)) || !snapshot.sourceUrl || !/^[0-9a-f]{64}$/.test(snapshot.snapshotSha256)) return false;
  if (!Array.isArray(snapshot.activeRunners) || snapshot.activeRunners.length < 3) return false;
  const ids = new Set<number>();
  for (const row of snapshot.activeRunners) {
    const horseNo = Number(row.horseNo);
    const weight = Number(row.horseWeight);
    if (!Number.isInteger(horseNo) || horseNo <= 0 || ids.has(horseNo) || !Number.isInteger(weight) || weight < 250 || weight > 700) return false;
    if (row.weightChange != null && (!Number.isInteger(Number(row.weightChange)) || Math.abs(Number(row.weightChange)) > 100)) return false;
    ids.add(horseNo);
  }
  return true;
}

function snapshotHasOfficialBodyWeight(snapshot: PreviewSnapshot): boolean {
  return snapshot.bodyWeightApplied === true && validBodyWeightSnapshot(snapshot.bodyWeightSnapshot, snapshot.raceId);
}

function validSnapshot(snapshot: PreviewSnapshot, raceId: string): boolean {
  if (snapshot.version !== PREVIEW_VERSION || snapshot.raceId !== raceId) return false;
  if (snapshot.sourceModel !== COMPLETED_MODEL_VERSION || snapshot.modelSha256 !== COMPLETED_MODEL_SHA256) return false;
  if (!Number.isFinite(Date.parse(snapshot.generatedAt)) || !Number.isFinite(Date.parse(snapshot.oddsFetchedAt))) return false;
  if (snapshot.bodyWeightApplied === true && !validBodyWeightSnapshot(snapshot.bodyWeightSnapshot, raceId)) return false;
  if (!OFFICIAL_ODDS_SOURCES.has(snapshot.oddsSource) || !/^[0-9a-f]{64}$/.test(snapshot.oddsSnapshotSha256)) return false;
  if (!Array.isArray(snapshot.tickets) || snapshot.tickets.length !== 2 || new Set(snapshot.tickets.map((ticket) => ticket.betType)).size !== 2) return false;
  if (snapshot.tickets.some((ticket) => !ticket.combination || !Number.isFinite(ticket.officialOdds) || ticket.officialOdds <= 0 || !Number.isFinite(ticket.predictedProbability) || ticket.predictedProbability <= 0)) return false;
  if (!Array.isArray(snapshot.courseBets) || snapshot.courseBets.length !== 6) return false;
  const ticketSignature = snapshot.tickets.map((ticket) => `${ticket.betType}\u0001${ticket.combination}`).sort().join("\u0002");
  const signatures: string[] = [];
  for (const course of COURSES) {
    const rows = snapshot.courseBets.filter((row) => row.course === course);
    const stakes = COMPLETED_COURSE_STAKES[course];
    if (rows.length !== 2 || new Set(rows.map((row) => row.betType)).size !== 2) return false;
    if (rows.reduce((sum, row) => sum + Number(row.stakeYen), 0) !== stakes[0] + stakes[1]) return false;
    if (rows.some((row) => !Number.isFinite(row.assumedOdds) || row.assumedOdds <= 0)) return false;
    signatures.push(rows.map((row) => `${row.betType}\u0001${row.combination}`).sort().join("\u0002"));
  }
  return signatures.every((signature) => signature === ticketSignature);
}

async function loadPreviewEnvelope(db: D1Database, raceId: string): Promise<PreviewEnvelope | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${PREVIEW_PREFIX}${raceId}`).first<{ value: string }>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value) as PreviewEnvelope;
    if (parsed.version !== PREVIEW_VERSION || parsed.raceId !== raceId || !Array.isArray(parsed.snapshots)) return null;
    const snapshots = parsed.snapshots.filter((snapshot) => validSnapshot(snapshot, raceId)).slice(0, PREVIEW_HISTORY);
    return snapshots.length ? { version: PREVIEW_VERSION, raceId, snapshots } : null;
  } catch {
    return null;
  }
}

async function latestPreview(db: D1Database, raceId: string): Promise<PreviewSnapshot | null> {
  return (await loadPreviewEnvelope(db, raceId))?.snapshots[0] ?? null;
}

async function latestOfficialBodyWeightPreview(db: D1Database, raceId: string): Promise<PreviewSnapshot | null> {
  return (await loadPreviewEnvelope(db, raceId))?.snapshots.find(snapshotHasOfficialBodyWeight) ?? null;
}

function previewRefreshIntervalMs(remainingMs: number): number {
  if (remainingMs > 45 * 60_000) return EARLY_PREVIEW_REFRESH_MS;
  if (remainingMs > 30 * 60_000) return MID_PREVIEW_REFRESH_MS;
  return NEAR_PREVIEW_REFRESH_MS;
}

function previewIsFreshEnough(snapshot: PreviewSnapshot, remainingMs: number, now: Date): boolean {
  const generatedMs = Date.parse(snapshot.generatedAt);
  if (!Number.isFinite(generatedMs)) return false;
  return now.getTime() - generatedMs < previewRefreshIntervalMs(remainingMs);
}

async function savePreview(db: D1Database, snapshot: PreviewSnapshot): Promise<void> {
  if (!validSnapshot(snapshot, snapshot.raceId)) throw new Error(`WORKER_PREVIEW_INVALID:${snapshot.raceId}`);
  const existing = await loadPreviewEnvelope(db, snapshot.raceId);
  const prior = existing?.snapshots.filter((row) => row.oddsSnapshotSha256 !== snapshot.oddsSnapshotSha256 || row.generatedAt !== snapshot.generatedAt) ?? [];
  const candidates = [snapshot, ...prior];
  let snapshots = candidates.slice(0, PREVIEW_HISTORY);
  const official = candidates.find(snapshotHasOfficialBodyWeight);
  if (official && !snapshots.includes(official)) snapshots = [...snapshots.slice(0, PREVIEW_HISTORY - 1), official];
  const envelope: PreviewEnvelope = { version: PREVIEW_VERSION, raceId: snapshot.raceId, snapshots };
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${PREVIEW_PREFIX}${snapshot.raceId}`, JSON.stringify(envelope)).run();
  const saved = await latestPreview(db, snapshot.raceId);
  if (!saved || saved.generatedAt !== snapshot.generatedAt || saved.oddsSnapshotSha256 !== snapshot.oddsSnapshotSha256) {
    throw new Error(`WORKER_PREVIEW_SAVE_VERIFY_FAILED:${snapshot.raceId}`);
  }
}

async function generatePreview(db: D1Database, model: CompletedModelRuntime, raceId: string, now: Date): Promise<PreviewSnapshot> {
  const initial = await loadRace(db, raceId);
  const race = initial.race;
  if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
  const startMs = Date.parse(race.startTimeUtc);
  if (!Number.isFinite(startMs) || startMs <= now.getTime()) throw new Error(`WORKER_REFUSES_POST_START_PREVIEW:${raceId}`);
  if (!race.entryUrl) throw new Error(`WORKER_ENTRY_URL_MISSING:${raceId}`);

  let bodyWeightSnapshot: OfficialBodyWeightSnapshot | null = null;
  let bodyWeightError: string | null = null;
  try {
    bodyWeightSnapshot = await resolveOfficialBodyWeights(db, race, initial.runners, now);
  } catch (error) {
    bodyWeightError = errorText(error);
  }

  const refreshed = await loadRace(db, raceId);
  if (bodyWeightSnapshot && !bodyWeightSnapshotMatchesRunners(bodyWeightSnapshot, refreshed.runners)) {
    bodyWeightError = `WORKER_BODYWEIGHT_FEATURE_INPUT_MISMATCH:${raceId}`;
    bodyWeightSnapshot = null;
  }

  const learningCutoff = iso(now);
  const state = await loadCompletedFeatureStateForRace(db, refreshed.race, refreshed.runners, learningCutoff);
  const vectors = refreshed.runners.map((runner) => completedFeatureVector(state, refreshed.race, runner, refreshed.runners.length));
  const raw = vectors.map((vector) => model.predict(vector));
  const baseWeights = normalizeCompletedWeights(raw);
  let learning;
  try {
    learning = await loadCompletedRecencyLearning(db, refreshed.race, refreshed.runners, learningCutoff);
  } catch (error) {
    learning = neutralCompletedRecencyLearning(refreshed.runners, learningCutoff, errorText(error));
  }
  const weights = normalizeCompletedWeights(baseWeights.map((value, index) => value * learning.runnerFactors[index]));
  const fetched = await fetchFastJraOfficialOddsForRace(refreshed.race.entryUrl, { raceDate: refreshed.race.raceDate, venue: refreshed.race.venue, raceNo: refreshed.race.raceNo });
  const oddsFetchedAt = iso();
  const tickets = chooseCompletedTwoTickets(
    refreshed.runners.map((runner) => Number(runner.horseNo)),
    weights,
    fetched.rows,
    (betType, odds) => completedRecencyBetFactor(learning, betType, refreshed.race.venue, odds),
  );
  const courseBets = completedCourseBets(tickets);
  const snapshot: PreviewSnapshot = {
    version: PREVIEW_VERSION,
    raceId,
    sourceModel: COMPLETED_MODEL_VERSION,
    modelSha256: COMPLETED_MODEL_SHA256,
    generatedAt: iso(),
    bodyWeightApplied: Boolean(bodyWeightSnapshot),
    bodyWeightSnapshot,
    bodyWeightError,
    oddsFetchedAt,
    oddsSource: fetched.source,
    oddsSnapshotSha256: await sha256Hex(canonicalOddsRows(fetched.rows)),
    onlineLearning: learning.audit,
    runnerRecencyFactors: learning.runnerDetails,
    tickets,
    courseBets,
  };
  if (!validSnapshot(snapshot, raceId)) throw new Error(`WORKER_GENERATED_PREVIEW_GATE_FAILED:${raceId}`);
  await savePreview(db, snapshot);
  return snapshot;
}

async function commitSnapshot(db: D1Database, raceId: string, snapshot: PreviewSnapshot, now: Date, finalizedFrom: "fresh" | "last_good" | "deadline_watchdog"): Promise<void> {
  if (!validSnapshot(snapshot, raceId)) throw new Error(`WORKER_FINAL_SNAPSHOT_INVALID:${raceId}`);
  const { race } = await loadRace(db, raceId);
  if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
  const startMs = Date.parse(race.startTimeUtc);
  if (!Number.isFinite(startMs) || startMs <= now.getTime()) throw new Error(`WORKER_REFUSES_POST_START_LOCK:${raceId}`);

  const existing = await publicBetRows(db, raceId);
  if (isStrictComplete(existing)) return;
  if (existing.length && existing.some((row) => Number(row.sourcePredictionId) !== -2 || row.settlementStatus !== "pending")) {
    throw new Error(`WORKER_UNSAFE_PARTIAL_ROWS:${raceId}`);
  }

  const lockedAt = iso(now);
  const hasBodyWeight = snapshotHasOfficialBodyWeight(snapshot);
  const bodyWeightSnapshot = hasBodyWeight ? snapshot.bodyWeightSnapshot as OfficialBodyWeightSnapshot : null;
  const statements: D1PreparedStatement[] = [];
  if (existing.length) statements.push(db.prepare("DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'").bind(raceId));
  for (const bet of snapshot.courseBets) {
    statements.push(db.prepare(`
      INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id)
      VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)
    `).bind(raceId, bet.course, bet.betType, bet.combination, bet.stakeYen, Number(bet.assumedOdds.toFixed(6)), lockedAt));
  }
  statements.push(db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${FINAL_PREFIX}${raceId}`, JSON.stringify({
    status: "locked",
    raceId,
    lockedAt,
    finalizedFrom,
    sourceModel: COMPLETED_MODEL_VERSION,
    modelSha256: COMPLETED_MODEL_SHA256,
    previewGeneratedAt: snapshot.generatedAt,
    bodyWeightApplied: hasBodyWeight,
    bodyWeightFetchedAt: bodyWeightSnapshot?.fetchedAt ?? null,
    bodyWeightSource: bodyWeightSnapshot?.sourceUrl ?? null,
    bodyWeightSnapshotSha256: bodyWeightSnapshot?.snapshotSha256 ?? null,
    bodyWeights: bodyWeightSnapshot?.activeRunners ?? null,
    bodyWeightError: snapshot.bodyWeightError ?? null,
    oddsFetchedAt: snapshot.oddsFetchedAt,
    oddsSource: snapshot.oddsSource,
    oddsSnapshotSha256: snapshot.oddsSnapshotSha256,
    onlineLearning: snapshot.onlineLearning ?? null,
    runnerRecencyFactors: snapshot.runnerRecencyFactors ?? null,
    tickets: snapshot.tickets,
  })));
  await db.batch(statements);
  const saved = await publicBetRows(db, raceId);
  if (!isStrictComplete(saved)) throw new Error(`WORKER_POST_WRITE_GATE_FAILED:${raceId}`);
}

async function saveAudit(db: D1Database, audit: Audit): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${AUDIT_PREFIX}${audit.date}`, JSON.stringify(audit)).run();
}

function emptyAudit(date: string, status: string): Audit {
  return {
    status,
    checkedAt: iso(),
    date,
    sourceModel: COMPLETED_MODEL_VERSION,
    selectedRaceCount: 0,
    completeBefore: 0,
    completeAfter: 0,
    lockedByWorker: [],
    refreshedBodyWeightRaceIds: [],
    bodyWeightPendingRaceIds: [],
    bodyWeightBreachRaceIds: [],
    refreshedPreviewRaceIds: [],
    previewAvailableRaceIds: [],
    previewMissingUrgentRaceIds: [],
    finalizedFromFreshRaceIds: [],
    finalizedFromFallbackRaceIds: [],
    latePromotedRaceIds: [],
    protectedRaceIds: [],
    incompleteRaceIds: [],
    deadlineBreachRaceIds: [],
    notYetInWindowRaceIds: [],
    alreadyStartedIncompleteRaceIds: [],
    errors: [],
  };
}

async function orderLiveRaceIdsByStart(db: D1Database, date: string, ids: string[]): Promise<string[]> {
  const result = await db.prepare("SELECT race_id AS raceId,start_time_utc AS startTimeUtc FROM rt_races WHERE race_date=?").bind(date).all<{ raceId: string; startTimeUtc: string | null }>();
  const starts = new Map((result.results ?? []).map((row) => [String(row.raceId), Date.parse(String(row.startTimeUtc || ""))]));
  return [...ids].sort((a,b) => { const av=Number.isFinite(starts.get(a))?Number(starts.get(a)):Number.POSITIVE_INFINITY; const bv=Number.isFinite(starts.get(b))?Number(starts.get(b)):Number.POSITIVE_INFINITY; return av-bv || a.localeCompare(b); });
}

export async function runCompletedWorkerLiveLock(env: Env, now = new Date()): Promise<Audit> {
  const date = jstDate(now);
  await ensureCompletedFinalImmutability(env.DB);
  const selection = await loadSelection(env.DB, date);
  if (!selection) {
    const audit = emptyAudit(date, "selection_missing");
    audit.checkedAt = iso(now);
    await saveAudit(env.DB, audit);
    return audit;
  }
  const selectedIds = await orderLiveRaceIdsByStart(env.DB, date, validateSelection(selection));
  const activeResult = await env.DB.prepare(`
    SELECT race_id AS raceId FROM rt_races
    WHERE race_date=? AND start_time_utc>? AND start_time_utc<=?
  `).bind(date, iso(now), iso(new Date(now.getTime() + BODY_WEIGHT_REFRESH_OPEN_MS))).all<{ raceId: string }>();
  const activeSet = new Set((activeResult.results ?? []).map((row) => String(row.raceId)));
  const ids = selectedIds.filter((raceId) => activeSet.has(raceId));
  const beforeStates = await Promise.all(ids.map(async (raceId) => isStrictComplete(await publicBetRows(env.DB, raceId))));
  const completeBefore = beforeStates.filter(Boolean).length;
  const lockedByWorker: string[] = [];
  const refreshedBodyWeightRaceIds = new Set<string>();
  const bodyWeightPendingRaceIds = new Set<string>();
  const bodyWeightBreachRaceIds = new Set<string>();
  const refreshedPreviewRaceIds: string[] = [];
  const finalizedFromFreshRaceIds: string[] = [];
  const finalizedFromFallbackRaceIds: string[] = [];
  const latePromotedRaceIds: string[] = [];
  const notYetInWindowRaceIds: string[] = [];
  const alreadyStartedIncompleteRaceIds: string[] = [];
  const errors: Array<{ raceId: string; error: string }> = [];
  let model: CompletedModelRuntime | null = null;
  let generatedThisTick = 0;

  for (const raceId of ids) {
    const existing = await publicBetRows(env.DB, raceId);
    if (isStrictComplete(existing)) continue;
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
      const startMs = Date.parse(race.startTimeUtc);
      const raceNow = new Date();
      const remaining = startMs - raceNow.getTime();
      if (remaining <= 0) { alreadyStartedIncompleteRaceIds.push(raceId); continue; }
      if (remaining > BODY_WEIGHT_REFRESH_OPEN_MS) { notYetInWindowRaceIds.push(raceId); continue; }

      // From T-100 to T-90 we only refresh official body weight data. From
      // T-90 onward we repeatedly generate official-JRA-odds previews, so one
      // transient JRA/cron failure cannot leave us with no last-good snapshot.
      if (remaining > PREVIEW_OPEN_MS) {
        try {
          await refreshOfficialBodyWeights(env.DB, race, raceNow);
          refreshedBodyWeightRaceIds.add(raceId);
        } catch {
          bodyWeightPendingRaceIds.add(raceId);
        }
        continue;
      }

      // T-15 is an assertion boundary, never a recovery window. New preview
      // generation or final creation is forbidden once the boundary is reached.
      if (remaining <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_HARD_T15_MISSED:${raceId}` });
        continue;
      }

      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > NORMAL_LOCK_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) {
        continue;
      }
      if (remaining <= NORMAL_LOCK_MS && existingPreview) {
        const commitNow = new Date();
        if (startMs - commitNow.getTime() <= DEADLINE_MS) {
          errors.push({ raceId, error: `WORKER_STORED_PREVIEW_COMMIT_CROSSED_T15:${raceId}` });
          continue;
        }
        if (!snapshotHasOfficialBodyWeight(existingPreview)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, existingPreview, commitNow, "last_good");
        lockedByWorker.push(raceId);
        finalizedFromFallbackRaceIds.push(raceId);
        continue;
      }
      if (generatedThisTick >= 1 && remaining > NORMAL_LOCK_MS) continue;

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, new Date());
        generatedThisTick += 1;
        refreshedPreviewRaceIds.push(raceId);
        if (snapshotHasOfficialBodyWeight(fresh)) refreshedBodyWeightRaceIds.add(raceId);
        else bodyWeightPendingRaceIds.add(raceId);
      } catch (error) {
        errors.push({ raceId, error: errorText(error) });
      }

      // Normal finalization happens by T-25. If the newest fetch failed, use
      // the durable last-good official preview instead of waiting until T-15.
      const commitNow = new Date();
      const remainingAfterGeneration = startMs - commitNow.getTime();
      if (remainingAfterGeneration <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_GENERATION_CROSSED_T15:${raceId}` });
        continue;
      }
      if (remainingAfterGeneration <= NORMAL_LOCK_MS) {
        const stored = fresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);
        if (!stored) throw new Error(`WORKER_T25_PREVIEW_MISSING:${raceId}`);
        if (!snapshotHasOfficialBodyWeight(stored)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, stored, commitNow, fresh ? "fresh" : "last_good");
        lockedByWorker.push(raceId);
        if (fresh) finalizedFromFreshRaceIds.push(raceId);
        else finalizedFromFallbackRaceIds.push(raceId);
      }
    } catch (error) {
      errors.push({ raceId, error: errorText(error) });
    }
  }

  const previewAvailableRaceIds: string[] = [];
  const previewMissingUrgentRaceIds: string[] = [];
  const protectedRaceIds: string[] = [];
  const incompleteRaceIds: string[] = [];
  const deadlineBreachRaceIds = new Set<string>(latePromotedRaceIds);
  for (const raceId of ids) {
    const complete = isStrictComplete(await publicBetRows(env.DB, raceId));
    if (complete) {
      protectedRaceIds.push(raceId);
      continue;
    }
    incompleteRaceIds.push(raceId);
    const preview = await latestPreview(env.DB, raceId);
    if (preview) {
      previewAvailableRaceIds.push(raceId);
      protectedRaceIds.push(raceId);
    }
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (race.startTimeUtc) {
        const remaining = Date.parse(race.startTimeUtc) - Date.now();
        if (!preview && remaining > DEADLINE_MS && remaining <= PREVIEW_REQUIRED_MS) previewMissingUrgentRaceIds.push(raceId);
        if (remaining <= DEADLINE_MS) deadlineBreachRaceIds.add(raceId);
      }
    } catch {
      deadlineBreachRaceIds.add(raceId);
    }
  }
  const completeAfter = ids.length - incompleteRaceIds.length;
  const breaches = [...deadlineBreachRaceIds];
  const bodyWeightBreaches = [...bodyWeightBreachRaceIds];
  const audit: Audit = {
    status: breaches.length ? "deadline_breach" : previewMissingUrgentRaceIds.length ? "preview_critical" : bodyWeightBreaches.length ? "body_weight_breach" : errors.length ? "retrying" : "ok",
    checkedAt: iso(now),
    date,
    sourceModel: COMPLETED_MODEL_VERSION,
    selectedRaceCount: selectedIds.length,
    completeBefore,
    completeAfter,
    lockedByWorker,
    refreshedBodyWeightRaceIds: [...refreshedBodyWeightRaceIds],
    bodyWeightPendingRaceIds: [...bodyWeightPendingRaceIds],
    bodyWeightBreachRaceIds: bodyWeightBreaches,
    refreshedPreviewRaceIds,
    previewAvailableRaceIds,
    previewMissingUrgentRaceIds,
    finalizedFromFreshRaceIds,
    finalizedFromFallbackRaceIds,
    latePromotedRaceIds,
    protectedRaceIds,
    incompleteRaceIds,
    deadlineBreachRaceIds: breaches,
    notYetInWindowRaceIds,
    alreadyStartedIncompleteRaceIds,
    errors,
  };
  await saveAudit(env.DB, audit);
  return audit;
}
