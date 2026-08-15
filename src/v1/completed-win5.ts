import { bodyWeightSnapshotMatchesRunners, resolveOfficialBodyWeights } from "./bodyweight-refresh";
import { COMPLETED_MODEL_SHA256, COMPLETED_MODEL_VERSION, completedFeatureVector, loadCompletedFeatureStateForRace } from "./completed-feature-runtime";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";
import { loadCompletedRecencyLearning, neutralCompletedRecencyLearning, type CompletedRecencyAudit } from "./completed-recency-learning";
import { normalizeCompletedWeights } from "./completed-ticket-runtime";
import { decodeJraHtml, jraPageText } from "./jra-official-odds";
import type { Env, RaceRecord, RunnerRecord } from "./types";

export const WIN5_PAGE_URL = "https://www.jra.go.jp/kouza/win5/info/racelist.html";
export const WIN5_VERSION = 1 as const;
export const WIN5_LOCK_MINUTES = 15;
const TARGET_PREFIX = "win5:targets:";
const PREVIEW_PREFIX = "win5:preview:";
const FINAL_PREFIX = "win5:final:";
const TARGET_CACHE_MS = 10 * 60 * 1000;
const BODY_WEIGHT_OPEN_MS = 80 * 60 * 1000;
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

type ModelMetaRow = { key: string; value: string };
type ModelChunkRow = { seq: number; dataB64: string };
type StateRow = { value: string };

export type Win5Target = {
  leg: 1 | 2 | 3 | 4 | 5;
  raceDate: string;
  venue: string;
  raceNo: number;
  startTimeJst: string;
  startTimeUtc: string;
  raceId?: string;
  raceName?: string;
};

export type Win5TargetCache = {
  version: 1;
  date: string;
  fetchedAt: string;
  sourceUrl: string;
  targets: Win5Target[];
};

export type Win5RunnerProbability = {
  horseNo: number;
  horseName: string;
  probability: number;
  winOdds: number | null;
};

export type Win5RacePrediction = {
  leg: 1 | 2 | 3 | 4 | 5;
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string;
  startTimeUtc: string;
  bodyWeightApplied: boolean;
  bodyWeightError: string | null;
  onlineLearning: CompletedRecencyAudit;
  runners: Win5RunnerProbability[];
};

export type Win5ProfileName = "堅実" | "標準" | "一撃";

export type Win5ProfileLeg = {
  leg: 1 | 2 | 3 | 4 | 5;
  raceId: string;
  venue: string;
  raceNo: number;
  selected: Win5RunnerProbability[];
  coverageProbability: number;
};

export type Win5Profile = {
  name: Win5ProfileName;
  maxPoints: number;
  maxBudgetYen: number;
  points: number;
  purchaseYen: number;
  estimatedFiveLegHitProbability: number;
  legs: Win5ProfileLeg[];
};

export type Win5Snapshot = {
  version: 1;
  date: string;
  sourceModel: string;
  modelSha256: string;
  generatedAt: string;
  locked: boolean;
  lockedAt: string | null;
  finalizedFrom: "fresh" | "last_good" | null;
  lockDeadlineUtc: string;
  firstRaceStartUtc: string;
  targetFetchedAt: string;
  targetSourceUrl: string;
  races: Win5RacePrediction[];
  profiles: Win5Profile[];
};

export type Win5PublicState = {
  date: string;
  status: "final" | "preview" | "targets_only" | "targets_missing";
  targets: Win5Target[];
  targetFetchedAt: string | null;
  targetSourceUrl: string;
  snapshot: Win5Snapshot | null;
};

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function jstDate(now: Date): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstDateTimeToUtc(date: string, hour: number, minute: number): string {
  return new Date(`${date}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+09:00`).toISOString();
}

function startTimeJst(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function stateKey(prefix: string, date: string): string { return `${prefix}${date}`; }

async function loadJsonState<T>(db: D1Database, key: string): Promise<T | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(key).first<StateRow>();
  if (!row?.value) return null;
  try { return JSON.parse(row.value) as T; } catch { return null; }
}

async function saveJsonState(db: D1Database, key: string, value: unknown): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(key, JSON.stringify(value)).run();
}

export function parseWin5TargetsFromHtml(pageHtml: string, date: string): Win5Target[] {
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(date)) return [];
  const month = Number(date.slice(5, 7));
  const day = Number(date.slice(8, 10));
  const marker = `${month}月${day}日`;
  const text = jraPageText(pageHtml);
  const markerIndex = text.indexOf(marker);
  if (markerIndex < 0) return [];
  const nextDate = text.slice(markerIndex + marker.length).search(/\n\d{1,2}月\d{1,2}日/);
  const sectionEnd = nextDate < 0 ? Math.min(text.length, markerIndex + 5000) : markerIndex + marker.length + nextDate;
  const section = text.slice(markerIndex, sectionEnd);
  const pattern = new RegExp(`(${VENUES})\\s*(\\d{1,2})R[\\s\\S]{0,160}?(\\d{1,2})時(\\d{2})分`, "g");
  const found: Array<Omit<Win5Target, "leg">> = [];
  const seen = new Set<string>();
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(section)) !== null && found.length < 5) {
    const venue = match[1];
    const raceNo = Number(match[2]);
    const hour = Number(match[3]);
    const minute = Number(match[4]);
    if (raceNo < 1 || raceNo > 12 || hour < 9 || hour > 17 || minute < 0 || minute > 59) continue;
    const signature = `${venue}:${raceNo}`;
    if (seen.has(signature)) continue;
    seen.add(signature);
    found.push({ raceDate: date, venue, raceNo, startTimeJst: startTimeJst(hour, minute), startTimeUtc: jstDateTimeToUtc(date, hour, minute) });
  }
  if (found.length !== 5) return [];
  return found.map((target, index) => ({ ...target, leg: (index + 1) as 1 | 2 | 3 | 4 | 5 }));
}

async function fetchOfficialTargets(date: string, now: Date): Promise<Win5TargetCache> {
  const response = await fetch(WIN5_PAGE_URL, {
    headers: {
      "User-Agent": USER_AGENT,
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ja-JP,ja;q=0.9",
      "Cache-Control": "no-cache",
      "Referer": "https://www.jra.go.jp/",
    },
    redirect: "follow",
  });
  if (!response.ok) throw new Error(`WIN5_TARGET_HTTP_${response.status}`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 4_000_000) throw new Error("WIN5_TARGET_BODY_TOO_LARGE");
  const html = decodeJraHtml(bytes, response.headers.get("content-type"));
  const targets = parseWin5TargetsFromHtml(html, date);
  if (targets.length !== 5) throw new Error(`WIN5_TARGET_PARSE_FAILED:${date}:${targets.length}`);
  return { version: WIN5_VERSION, date, fetchedAt: now.toISOString(), sourceUrl: response.url || WIN5_PAGE_URL, targets };
}

function validTargetCache(value: Win5TargetCache | null, date: string): value is Win5TargetCache {
  return Boolean(value && value.version === 1 && value.date === date && value.targets.length === 5 && value.targets.every((row, index) => row.leg === index + 1 && row.raceDate === date));
}

export async function resolveWin5Targets(db: D1Database, date: string, now = new Date(), forceRefresh = false): Promise<Win5TargetCache | null> {
  const key = stateKey(TARGET_PREFIX, date);
  const cached = await loadJsonState<Win5TargetCache>(db, key);
  const freshEnough = validTargetCache(cached, date) && now.getTime() - Date.parse(cached.fetchedAt) < TARGET_CACHE_MS;
  if (!forceRefresh && freshEnough) return cached;
  try {
    const fetched = await fetchOfficialTargets(date, now);
    await saveJsonState(db, key, fetched);
    return fetched;
  } catch (error) {
    console.error("WIN5_TARGET_REFRESH_FAILED", date, errorText(error));
    return validTargetCache(cached, date) ? cached : null;
  }
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {
  const metaResult = await db.prepare("SELECT key,value FROM rt_ml_model_meta").all<ModelMetaRow>();
  const meta = new Map((metaResult.results ?? []).map((row) => [row.key, row.value]));
  if (meta.get("ready") !== "1") throw new Error("WIN5_MODEL_NOT_READY");
  if (meta.get("modelVersion") !== COMPLETED_MODEL_VERSION || meta.get("sourceSha256") !== COMPLETED_MODEL_SHA256) throw new Error("WIN5_MODEL_IDENTITY_MISMATCH");
  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) throw new Error("WIN5_MODEL_META_INVALID");
  const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();
  const rows = chunkResult.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("WIN5_MODEL_CHUNKS_INCOMPLETE");
  const decoded = rows.map((row) => decodeBase64(row.dataB64));
  const actualBytes = decoded.reduce((sum, row) => sum + row.byteLength, 0);
  if (actualBytes !== byteLength) throw new Error(`WIN5_MODEL_BYTE_LENGTH_MISMATCH:${actualBytes}:${byteLength}`);
  const merged = new Uint8Array(byteLength);
  let offset = 0;
  for (const row of decoded) { merged.set(row, offset); offset += row.byteLength; }
  return loadCompletedModelRuntime(merged.buffer);
}

async function loadRaceByTarget(db: D1Database, target: Win5Target): Promise<{ race: RaceRecord; runners: RunnerRecord[] }> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_date=? AND venue=? AND race_no=? LIMIT 1
  `).bind(target.raceDate, target.venue, target.raceNo).first<RaceRecord>();
  if (!race) throw new Error(`WIN5_RACE_NOT_FOUND:${target.raceDate}:${target.venue}:${target.raceNo}`);
  const result = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(race.raceId).all<RunnerRecord>();
  const runners = (result.results ?? []).filter((runner) => (runner.runnerStatus || "active") === "active" && Number.isInteger(Number(runner.horseNo)));
  if (runners.length < 3) throw new Error(`WIN5_ACTIVE_RUNNERS_TOO_FEW:${race.raceId}:${runners.length}`);
  return { race, runners };
}

async function scoreRace(db: D1Database, model: CompletedModelRuntime, target: Win5Target, now: Date): Promise<Win5RacePrediction> {
  let loaded = await loadRaceByTarget(db, target);
  let bodyWeightApplied = false;
  let bodyWeightError: string | null = null;
  const startMs = Date.parse(loaded.race.startTimeUtc || target.startTimeUtc);
  if (Number.isFinite(startMs) && startMs > now.getTime() && startMs - now.getTime() <= BODY_WEIGHT_OPEN_MS) {
    try {
      const snapshot = await resolveOfficialBodyWeights(db, loaded.race, loaded.runners, now);
      loaded = await loadRaceByTarget(db, target);
      bodyWeightApplied = bodyWeightSnapshotMatchesRunners(snapshot, loaded.runners);
      if (!bodyWeightApplied) bodyWeightError = `WIN5_BODYWEIGHT_INPUT_MISMATCH:${loaded.race.raceId}`;
    } catch (error) {
      bodyWeightError = errorText(error);
    }
  }
  const cutoffUtc = now.toISOString();
  const state = await loadCompletedFeatureStateForRace(db, loaded.race, loaded.runners, cutoffUtc);
  const raw = loaded.runners.map((runner) => model.predict(completedFeatureVector(state, loaded.race, runner, loaded.runners.length)));
  const base = normalizeCompletedWeights(raw);
  let learning;
  try {
    learning = await loadCompletedRecencyLearning(db, loaded.race, loaded.runners, cutoffUtc);
  } catch (error) {
    learning = neutralCompletedRecencyLearning(loaded.runners, cutoffUtc, errorText(error));
  }
  const weights = normalizeCompletedWeights(base.map((probability, index) => probability * learning.runnerFactors[index]));
  const runners = loaded.runners.map((runner, index) => ({
    horseNo: Number(runner.horseNo),
    horseName: String(runner.horseName || ""),
    probability: weights[index],
    winOdds: runner.winOdds == null || !Number.isFinite(Number(runner.winOdds)) ? null : Number(runner.winOdds),
  })).sort((a, b) => (b.probability - a.probability) || (a.horseNo - b.horseNo));
  return {
    leg: target.leg,
    raceId: loaded.race.raceId,
    raceDate: loaded.race.raceDate,
    venue: loaded.race.venue,
    raceNo: loaded.race.raceNo,
    raceName: loaded.race.raceName || `${loaded.race.raceNo}R`,
    startTimeJst: target.startTimeJst,
    startTimeUtc: loaded.race.startTimeUtc || target.startTimeUtc,
    bodyWeightApplied,
    bodyWeightError,
    onlineLearning: learning.audit,
    runners,
  };
}

export function optimizeWin5Profile(races: Win5RacePrediction[], name: Win5ProfileName, maxPoints: number): Win5Profile {
  if (races.length !== 5 || !Number.isInteger(maxPoints) || maxPoints < 1) throw new Error("WIN5_OPTIMIZER_INPUT_INVALID");
  const cumulative = races.map((race) => {
    if (race.runners.length < 1) throw new Error(`WIN5_OPTIMIZER_EMPTY_RACE:${race.raceId}`);
    const limit = Math.min(8, race.runners.length, maxPoints);
    const out: number[] = [];
    let sum = 0;
    for (let k = 1; k <= limit; k += 1) { sum += race.runners[k - 1].probability; out.push(sum); }
    return out;
  });
  let best: { ks: number[]; points: number; hit: number } | null = null;
  const walk = (leg: number, points: number, hit: number, ks: number[]): void => {
    if (leg === 5) {
      if (!best || hit > best.hit + 1e-15 || (Math.abs(hit - best.hit) <= 1e-15 && points < best.points)) best = { ks: ks.slice(), points, hit };
      return;
    }
    for (let k = 1; k <= cumulative[leg].length; k += 1) {
      const nextPoints = points * k;
      if (nextPoints > maxPoints) break;
      ks.push(k);
      walk(leg + 1, nextPoints, hit * cumulative[leg][k - 1], ks);
      ks.pop();
    }
  };
  walk(0, 1, 1, []);
  if (!best) throw new Error("WIN5_OPTIMIZER_NO_SOLUTION");
  const chosen = best as { ks: number[]; points: number; hit: number };
  return {
    name,
    maxPoints,
    maxBudgetYen: maxPoints * 100,
    points: chosen.points,
    purchaseYen: chosen.points * 100,
    estimatedFiveLegHitProbability: chosen.hit,
    legs: races.map((race, index) => ({
      leg: race.leg,
      raceId: race.raceId,
      venue: race.venue,
      raceNo: race.raceNo,
      selected: race.runners.slice(0, chosen.ks[index]),
      coverageProbability: cumulative[index][chosen.ks[index] - 1],
    })),
  };
}

function profileSet(races: Win5RacePrediction[]): Win5Profile[] {
  return [
    optimizeWin5Profile(races, "堅実", 200),
    optimizeWin5Profile(races, "標準", 100),
    optimizeWin5Profile(races, "一撃", 50),
  ];
}

export function win5LockDeadlineMs(targets: Win5Target[]): number {
  if (targets.length !== 5) throw new Error("WIN5_TARGET_COUNT_INVALID");
  const first = Math.min(...targets.map((row) => Date.parse(row.startTimeUtc)));
  if (!Number.isFinite(first)) throw new Error("WIN5_FIRST_START_INVALID");
  return first - WIN5_LOCK_MINUTES * 60 * 1000;
}

async function generateSnapshot(db: D1Database, cache: Win5TargetCache, now: Date): Promise<Win5Snapshot> {
  const model = await loadWorkerModel(db);
  const races: Win5RacePrediction[] = [];
  for (const target of cache.targets) races.push(await scoreRace(db, model, target, now));
  const firstRaceStartMs = Math.min(...races.map((race) => Date.parse(race.startTimeUtc)));
  const deadlineMs = win5LockDeadlineMs(cache.targets);
  if (!Number.isFinite(firstRaceStartMs) || !Number.isFinite(deadlineMs)) throw new Error("WIN5_TIMING_INVALID");
  return {
    version: WIN5_VERSION,
    date: cache.date,
    sourceModel: COMPLETED_MODEL_VERSION,
    modelSha256: COMPLETED_MODEL_SHA256,
    generatedAt: now.toISOString(),
    locked: false,
    lockedAt: null,
    finalizedFrom: null,
    lockDeadlineUtc: new Date(deadlineMs).toISOString(),
    firstRaceStartUtc: new Date(firstRaceStartMs).toISOString(),
    targetFetchedAt: cache.fetchedAt,
    targetSourceUrl: cache.sourceUrl,
    races,
    profiles: profileSet(races),
  };
}

function validSnapshot(snapshot: Win5Snapshot | null, date: string): snapshot is Win5Snapshot {
  if (!snapshot || snapshot.version !== 1 || snapshot.date !== date || snapshot.sourceModel !== COMPLETED_MODEL_VERSION || snapshot.modelSha256 !== COMPLETED_MODEL_SHA256) return false;
  if (snapshot.races.length !== 5 || snapshot.profiles.length !== 3) return false;
  if (!Number.isFinite(Date.parse(snapshot.generatedAt)) || !Number.isFinite(Date.parse(snapshot.lockDeadlineUtc))) return false;
  return snapshot.profiles.every((profile) => profile.legs.length === 5 && profile.points >= 1 && profile.points <= profile.maxPoints && profile.purchaseYen === profile.points * 100);
}

async function savePreview(db: D1Database, snapshot: Win5Snapshot): Promise<void> {
  if (!validSnapshot(snapshot, snapshot.date) || snapshot.locked) throw new Error("WIN5_PREVIEW_INVALID");
  await saveJsonState(db, stateKey(PREVIEW_PREFIX, snapshot.date), snapshot);
}

async function lockSnapshot(db: D1Database, snapshot: Win5Snapshot, now: Date, finalizedFrom: "fresh" | "last_good"): Promise<Win5Snapshot> {
  const existing = await loadJsonState<Win5Snapshot>(db, stateKey(FINAL_PREFIX, snapshot.date));
  if (validSnapshot(existing, snapshot.date) && existing.locked) return existing;
  if (!validSnapshot(snapshot, snapshot.date)) throw new Error("WIN5_FINAL_INPUT_INVALID");
  const final: Win5Snapshot = { ...snapshot, locked: true, lockedAt: now.toISOString(), finalizedFrom };
  await saveJsonState(db, stateKey(FINAL_PREFIX, snapshot.date), final);
  const saved = await loadJsonState<Win5Snapshot>(db, stateKey(FINAL_PREFIX, snapshot.date));
  if (!validSnapshot(saved, snapshot.date) || !saved.locked) throw new Error("WIN5_FINAL_SAVE_VERIFY_FAILED");
  return saved;
}

function previewCadenceMs(msUntilFirstRace: number): number {
  if (msUntilFirstRace <= 20 * 60 * 1000) return 60 * 1000;
  if (msUntilFirstRace <= 2 * 60 * 60 * 1000) return 10 * 60 * 1000;
  return 30 * 60 * 1000;
}

export async function runCompletedWin5Scheduled(env: Env, now = new Date()): Promise<Win5PublicState> {
  const date = jstDate(now);
  const final = await loadJsonState<Win5Snapshot>(env.DB, stateKey(FINAL_PREFIX, date));
  if (validSnapshot(final, date) && final.locked) {
    const cache = await resolveWin5Targets(env.DB, date, now, false);
    return { date, status: "final", targets: cache?.targets ?? final.races.map((race) => ({ leg: race.leg, raceDate: race.raceDate, venue: race.venue, raceNo: race.raceNo, startTimeJst: race.startTimeJst, startTimeUtc: race.startTimeUtc, raceId: race.raceId, raceName: race.raceName })), targetFetchedAt: cache?.fetchedAt ?? final.targetFetchedAt, targetSourceUrl: cache?.sourceUrl ?? final.targetSourceUrl, snapshot: final };
  }
  const cache = await resolveWin5Targets(env.DB, date, now, false);
  if (!cache) return { date, status: "targets_missing", targets: [], targetFetchedAt: null, targetSourceUrl: WIN5_PAGE_URL, snapshot: null };
  const firstStartMs = Math.min(...cache.targets.map((row) => Date.parse(row.startTimeUtc)));
  const deadlineMs = win5LockDeadlineMs(cache.targets);
  const nowMs = now.getTime();
  let preview = await loadJsonState<Win5Snapshot>(env.DB, stateKey(PREVIEW_PREFIX, date));
  if (!validSnapshot(preview, date) || preview.locked) preview = null;

  if (nowMs >= deadlineMs && nowMs < firstStartMs) {
    try {
      const freshCache = await resolveWin5Targets(env.DB, date, now, true) ?? cache;
      const fresh = await generateSnapshot(env.DB, freshCache, now);
      const locked = await lockSnapshot(env.DB, fresh, now, "fresh");
      return { date, status: "final", targets: freshCache.targets, targetFetchedAt: freshCache.fetchedAt, targetSourceUrl: freshCache.sourceUrl, snapshot: locked };
    } catch (error) {
      console.error("WIN5_FINAL_FRESH_FAILED", date, errorText(error));
      if (preview) {
        const locked = await lockSnapshot(env.DB, preview, now, "last_good");
        return { date, status: "final", targets: cache.targets, targetFetchedAt: cache.fetchedAt, targetSourceUrl: cache.sourceUrl, snapshot: locked };
      }
    }
  }

  if (nowMs < firstStartMs) {
    const cadence = previewCadenceMs(firstStartMs - nowMs);
    const stale = !preview || nowMs - Date.parse(preview.generatedAt) >= cadence;
    if (stale) {
      try {
        preview = await generateSnapshot(env.DB, cache, now);
        await savePreview(env.DB, preview);
      } catch (error) {
        console.error("WIN5_PREVIEW_FAILED", date, errorText(error));
      }
    }
  }
  return { date, status: preview ? "preview" : "targets_only", targets: cache.targets, targetFetchedAt: cache.fetchedAt, targetSourceUrl: cache.sourceUrl, snapshot: preview };
}

export async function loadWin5PublicState(db: D1Database, date: string): Promise<Win5PublicState> {
  const final = await loadJsonState<Win5Snapshot>(db, stateKey(FINAL_PREFIX, date));
  if (validSnapshot(final, date) && final.locked) {
    const cache = await loadJsonState<Win5TargetCache>(db, stateKey(TARGET_PREFIX, date));
    return { date, status: "final", targets: validTargetCache(cache, date) ? cache.targets : final.races.map((race) => ({ leg: race.leg, raceDate: race.raceDate, venue: race.venue, raceNo: race.raceNo, startTimeJst: race.startTimeJst, startTimeUtc: race.startTimeUtc, raceId: race.raceId, raceName: race.raceName })), targetFetchedAt: validTargetCache(cache, date) ? cache.fetchedAt : final.targetFetchedAt, targetSourceUrl: validTargetCache(cache, date) ? cache.sourceUrl : final.targetSourceUrl, snapshot: final };
  }
  const preview = await loadJsonState<Win5Snapshot>(db, stateKey(PREVIEW_PREFIX, date));
  const cache = await loadJsonState<Win5TargetCache>(db, stateKey(TARGET_PREFIX, date));
  const targets = validTargetCache(cache, date) ? cache.targets : [];
  if (validSnapshot(preview, date) && !preview.locked) return { date, status: "preview", targets, targetFetchedAt: validTargetCache(cache, date) ? cache.fetchedAt : preview.targetFetchedAt, targetSourceUrl: validTargetCache(cache, date) ? cache.sourceUrl : preview.targetSourceUrl, snapshot: preview };
  if (targets.length === 5) return { date, status: "targets_only", targets, targetFetchedAt: cache!.fetchedAt, targetSourceUrl: cache!.sourceUrl, snapshot: null };
  return { date, status: "targets_missing", targets: [], targetFetchedAt: null, targetSourceUrl: WIN5_PAGE_URL, snapshot: null };
}
