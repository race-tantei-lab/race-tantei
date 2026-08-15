import { COMPLETED_MODEL_SHA256, COMPLETED_MODEL_VERSION, completedFeatureVector, loadCompletedFeatureStateForRace } from "./completed-feature-runtime";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";
import {
  COMPLETED_COURSE_STAKES,
  chooseCompletedTwoTickets,
  completedCourseBets,
  normalizeCompletedWeights,
  type CompletedCourseBet,
  type CompletedTicket,
} from "./completed-ticket-runtime";
import { fetchFastJraOfficialOddsForRace, type OfficialOddsRow } from "./jra-official-odds-fetch";
import type { Env, RaceRecord, RunnerRecord } from "./types";

const SELECTION_PREFIX = "final_daily_selection:";
const AUDIT_PREFIX = "worker_live_lock:";
const PREVIEW_PREFIX = "worker_live_preview:";
const FINAL_PREFIX = "worker_live_final:";
const PREVIEW_OPEN_MS = 45 * 60 * 1000;
const FINALIZE_OPEN_MS = 17 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;
const PREVIEW_HISTORY = 3;
const PREVIEW_VERSION = 1;
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
  oddsFetchedAt: string;
  oddsSource: string;
  oddsSnapshotSha256: string;
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
  refreshedPreviewRaceIds: string[];
  previewAvailableRaceIds: string[];
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
  const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();
  const rows = chunkResult.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("WORKER_MODEL_CHUNKS_INCOMPLETE");
  const decoded = rows.map((row) => decodeBase64(row.dataB64));
  const actualBytes = decoded.reduce((sum, row) => sum + row.byteLength, 0);
  if (actualBytes !== byteLength) throw new Error(`WORKER_MODEL_BYTE_LENGTH_MISMATCH:${actualBytes}:${byteLength}`);
  const merged = new Uint8Array(byteLength);
  let offset = 0;
  for (const row of decoded) { merged.set(row, offset); offset += row.byteLength; }
  return loadCompletedModelRuntime(merged.buffer);
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

function validSnapshot(snapshot: PreviewSnapshot, raceId: string): boolean {
  if (snapshot.version !== PREVIEW_VERSION || snapshot.raceId !== raceId) return false;
  if (snapshot.sourceModel !== COMPLETED_MODEL_VERSION || snapshot.modelSha256 !== COMPLETED_MODEL_SHA256) return false;
  if (!Number.isFinite(Date.parse(snapshot.generatedAt)) || !Number.isFinite(Date.parse(snapshot.oddsFetchedAt))) return false;
  if (!snapshot.oddsSource || !/^[0-9a-f]{64}$/.test(snapshot.oddsSnapshotSha256)) return false;
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

async function savePreview(db: D1Database, snapshot: PreviewSnapshot): Promise<void> {
  if (!validSnapshot(snapshot, snapshot.raceId)) throw new Error(`WORKER_PREVIEW_INVALID:${snapshot.raceId}`);
  const existing = await loadPreviewEnvelope(db, snapshot.raceId);
  const prior = existing?.snapshots.filter((row) => row.oddsSnapshotSha256 !== snapshot.oddsSnapshotSha256 || row.generatedAt !== snapshot.generatedAt) ?? [];
  const envelope: PreviewEnvelope = { version: PREVIEW_VERSION, raceId: snapshot.raceId, snapshots: [snapshot, ...prior].slice(0, PREVIEW_HISTORY) };
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
  const { race, runners } = await loadRace(db, raceId);
  if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
  const startMs = Date.parse(race.startTimeUtc);
  if (!Number.isFinite(startMs) || startMs <= now.getTime()) throw new Error(`WORKER_REFUSES_POST_START_PREVIEW:${raceId}`);
  if (!race.entryUrl) throw new Error(`WORKER_ENTRY_URL_MISSING:${raceId}`);

  const state = await loadCompletedFeatureStateForRace(db, race, runners);
  const vectors = runners.map((runner) => completedFeatureVector(state, race, runner, runners.length));
  const raw = vectors.map((vector) => model.predict(vector));
  const weights = normalizeCompletedWeights(raw);
  const fetched = await fetchFastJraOfficialOddsForRace(race.entryUrl, { raceDate: race.raceDate, venue: race.venue, raceNo: race.raceNo });
  const oddsFetchedAt = iso();
  const tickets = chooseCompletedTwoTickets(runners.map((runner) => Number(runner.horseNo)), weights, fetched.rows);
  const courseBets = completedCourseBets(tickets);
  const snapshot: PreviewSnapshot = {
    version: PREVIEW_VERSION,
    raceId,
    sourceModel: COMPLETED_MODEL_VERSION,
    modelSha256: COMPLETED_MODEL_SHA256,
    generatedAt: iso(),
    oddsFetchedAt,
    oddsSource: fetched.source,
    oddsSnapshotSha256: await sha256Hex(canonicalOddsRows(fetched.rows)),
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
    oddsFetchedAt: snapshot.oddsFetchedAt,
    oddsSource: snapshot.oddsSource,
    oddsSnapshotSha256: snapshot.oddsSnapshotSha256,
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
    refreshedPreviewRaceIds: [],
    previewAvailableRaceIds: [],
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

export async function runCompletedWorkerLiveLock(env: Env, now = new Date()): Promise<Audit> {
  const date = jstDate(now);
  const selection = await loadSelection(env.DB, date);
  if (!selection) {
    const audit = emptyAudit(date, "selection_missing");
    audit.checkedAt = iso(now);
    await saveAudit(env.DB, audit);
    return audit;
  }
  const ids = validateSelection(selection);
  const beforeStates = await Promise.all(ids.map(async (raceId) => isStrictComplete(await publicBetRows(env.DB, raceId))));
  const completeBefore = beforeStates.filter(Boolean).length;
  const lockedByWorker: string[] = [];
  const refreshedPreviewRaceIds: string[] = [];
  const finalizedFromFreshRaceIds: string[] = [];
  const finalizedFromFallbackRaceIds: string[] = [];
  const latePromotedRaceIds: string[] = [];
  const notYetInWindowRaceIds: string[] = [];
  const alreadyStartedIncompleteRaceIds: string[] = [];
  const errors: Array<{ raceId: string; error: string }> = [];
  let model: CompletedModelRuntime | null = null;

  for (const raceId of ids) {
    const existing = await publicBetRows(env.DB, raceId);
    if (isStrictComplete(existing)) continue;
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
      const remaining = Date.parse(race.startTimeUtc) - now.getTime();
      if (remaining <= 0) { alreadyStartedIncompleteRaceIds.push(raceId); continue; }
      if (remaining > PREVIEW_OPEN_MS) { notYetInWindowRaceIds.push(raceId); continue; }

      if (remaining <= DEADLINE_MS) {
        const fallback = await latestPreview(env.DB, raceId);
        if (!fallback) throw new Error(`WORKER_DEADLINE_PREVIEW_MISSING:${raceId}`);
        await commitSnapshot(env.DB, raceId, fallback, now, "deadline_watchdog");
        lockedByWorker.push(raceId);
        finalizedFromFallbackRaceIds.push(raceId);
        latePromotedRaceIds.push(raceId);
        continue;
      }

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, now);
        refreshedPreviewRaceIds.push(raceId);
      } catch (error) {
        errors.push({ raceId, error: errorText(error) });
      }

      if (remaining <= FINALIZE_OPEN_MS) {
        const chosen = fresh ?? await latestPreview(env.DB, raceId);
        if (!chosen) throw new Error(`WORKER_FINALIZE_PREVIEW_MISSING:${raceId}`);
        await commitSnapshot(env.DB, raceId, chosen, now, fresh ? "fresh" : "last_good");
        lockedByWorker.push(raceId);
        if (fresh) finalizedFromFreshRaceIds.push(raceId);
        else finalizedFromFallbackRaceIds.push(raceId);
      }
    } catch (error) {
      errors.push({ raceId, error: errorText(error) });
    }
  }

  const previewAvailableRaceIds: string[] = [];
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
        const remaining = Date.parse(race.startTimeUtc) - now.getTime();
        if (remaining <= DEADLINE_MS) deadlineBreachRaceIds.add(raceId);
      }
    } catch {
      deadlineBreachRaceIds.add(raceId);
    }
  }
  const completeAfter = ids.length - incompleteRaceIds.length;
  const breaches = [...deadlineBreachRaceIds];
  const audit: Audit = {
    status: breaches.length ? "deadline_breach" : errors.length ? "retrying" : "ok",
    checkedAt: iso(now),
    date,
    sourceModel: COMPLETED_MODEL_VERSION,
    selectedRaceCount: ids.length,
    completeBefore,
    completeAfter,
    lockedByWorker,
    refreshedPreviewRaceIds,
    previewAvailableRaceIds,
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
