import type { Env, RaceRecord, RunnerRecord } from "./types";
import { COMPLETED_FEATURE_NAMES, COMPLETED_MODEL_SHA256, completedFeatureVector, loadCompletedFeatureStateForRace } from "./completed-feature-runtime";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";
import { completedCourseBets, chooseCompletedTwoTickets, normalizeCompletedWeights, type CompletedCourseBet } from "./completed-ticket-runtime";
import { fetchFastJraOfficialOddsForRace } from "./jra-official-odds-fetch";

export interface CompletedWorkerEnv extends Env {
  ASSETS: Fetcher;
}

type PublicBetRow = {
  course: string;
  betType: string;
  combination: string;
  stakeYen: number;
  assumedOdds: number | null;
  settlementStatus: string;
  sourcePredictionId: number | null;
};

type ModelMetadata = {
  modelVersion: string;
  sourceSha256: string;
  featureCount: number;
  treeCount: number;
  nodeCount: number;
};

export type CompletedLockResult = {
  raceId: string;
  status: "locked" | "already_locked";
  lockedAt: string | null;
  tickets: Array<{ betType: string; combination: string; officialOdds: number }>;
};

const MODEL_VERSION = "ten-year-completed-model";
const EXPECTED_COURSE_TOTAL: Record<string, number> = { "ライト": 2000, "スタンダード": 5000, "プレミアム": 10000 };
let modelPromise: Promise<CompletedModelRuntime> | null = null;

function assetRequest(path: string): Request {
  return new Request(`https://race-tantei-internal.invalid${path}`);
}

async function loadModel(env: CompletedWorkerEnv): Promise<CompletedModelRuntime> {
  modelPromise ??= (async () => {
    const [metadataResponse, modelResponse] = await Promise.all([
      env.ASSETS.fetch(assetRequest("/_internal/completed-model/metadata.json")),
      env.ASSETS.fetch(assetRequest("/_internal/completed-model/model.bin")),
    ]);
    if (!metadataResponse.ok || !modelResponse.ok) {
      throw new Error(`COMPLETED_MODEL_ASSET_MISSING:metadata=${metadataResponse.status}:model=${modelResponse.status}`);
    }
    const metadata = await metadataResponse.json<ModelMetadata>();
    if (metadata.modelVersion !== MODEL_VERSION || metadata.sourceSha256 !== COMPLETED_MODEL_SHA256 || metadata.featureCount !== COMPLETED_FEATURE_NAMES.length || metadata.treeCount !== 500) {
      throw new Error(`COMPLETED_MODEL_ASSET_IDENTITY_MISMATCH:${JSON.stringify(metadata)}`);
    }
    const runtime = loadCompletedModelRuntime(await modelResponse.arrayBuffer());
    if (runtime.featureCount !== 56 || runtime.treeCount !== 500 || runtime.nodeCount !== metadata.nodeCount) {
      throw new Error("COMPLETED_MODEL_RUNTIME_SHAPE_MISMATCH");
    }
    return runtime;
  })();
  return modelPromise;
}

function raceFromRow(row: Record<string, unknown>): RaceRecord {
  return {
    raceId: String(row.raceId), raceDate: String(row.raceDate), venue: String(row.venue),
    meetingNo: Number(row.meetingNo ?? 0), meetingDay: Number(row.meetingDay ?? 0), raceNo: Number(row.raceNo ?? 0),
    raceName: String(row.raceName ?? ""), conditions: row.conditions == null ? null : String(row.conditions),
    surface: row.surface == null ? null : String(row.surface), distanceM: row.distanceM == null ? null : Number(row.distanceM),
    direction: row.direction == null ? null : String(row.direction), startTimeJst: row.startTimeJst == null ? null : String(row.startTimeJst),
    startTimeUtc: row.startTimeUtc == null ? null : String(row.startTimeUtc), weather: row.weather == null ? null : String(row.weather),
    trackCondition: row.trackCondition == null ? null : String(row.trackCondition), entryUrl: String(row.entryUrl ?? ""), resultUrl: String(row.resultUrl ?? ""),
    status: String(row.status ?? "scheduled") as RaceRecord["status"],
  };
}

function runnerFromRow(row: Record<string, unknown>): RunnerRecord {
  return {
    horseNo: Number(row.horseNo), frameNo: row.frameNo == null ? null : Number(row.frameNo), horseName: String(row.horseName ?? ""),
    sexAge: row.sexAge == null ? null : String(row.sexAge), coatColor: row.coatColor == null ? null : String(row.coatColor),
    horseWeight: row.horseWeight == null ? null : Number(row.horseWeight), weightChange: row.weightChange == null ? null : Number(row.weightChange),
    jockey: row.jockey == null ? null : String(row.jockey), assignedWeight: row.assignedWeight == null ? null : Number(row.assignedWeight),
    trainer: row.trainer == null ? null : String(row.trainer), stable: row.stable == null ? null : String(row.stable),
    winOdds: row.winOdds == null ? null : Number(row.winOdds), popularity: row.popularity == null ? null : Number(row.popularity),
    runnerStatus: String(row.runnerStatus ?? "active") as RunnerRecord["runnerStatus"],
  };
}

export async function loadCompletedRaceBundle(db: D1Database, raceId: string): Promise<{ race: RaceRecord; runners: RunnerRecord[] }> {
  const raceResult = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_id=? LIMIT 1
  `).bind(raceId).all<Record<string, unknown>>();
  const row = raceResult.results?.[0];
  if (!row) throw new Error(`RACE_NOT_FOUND:${raceId}`);
  const race = raceFromRow(row);
  const runnerResult = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<Record<string, unknown>>();
  const runners = (runnerResult.results ?? []).map(runnerFromRow);
  return { race, runners };
}

async function existingRows(db: D1Database, raceId: string): Promise<PublicBetRow[]> {
  const result = await db.prepare(`
    SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,
           settlement_status AS settlementStatus,source_prediction_id AS sourcePredictionId
    FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination
  `).bind(raceId).all<PublicBetRow>();
  return (result.results ?? []).map((row) => ({ ...row, stakeYen: Number(row.stakeYen), assumedOdds: row.assumedOdds == null ? null : Number(row.assumedOdds), sourcePredictionId: row.sourcePredictionId == null ? null : Number(row.sourcePredictionId) }));
}

export function verifyCompletedLockedRows(raceId: string, rows: PublicBetRow[]): void {
  if (rows.length !== 6) throw new Error(`CANONICAL_LOCK_ROW_COUNT:${raceId}:${rows.length}`);
  const courses = new Map<string, PublicBetRow[]>();
  for (const row of rows) {
    if (row.sourcePredictionId !== -2) throw new Error(`CANONICAL_LOCK_SOURCE:${raceId}:${row.course}:${row.sourcePredictionId}`);
    const list = courses.get(row.course) ?? [];
    list.push(row); courses.set(row.course, list);
  }
  if (courses.size !== 3 || [...courses.keys()].some((course) => !(course in EXPECTED_COURSE_TOTAL))) {
    throw new Error(`CANONICAL_LOCK_COURSES:${raceId}:${[...courses.keys()].join(",")}`);
  }
  let identity: string | null = null;
  for (const [course, courseRows] of courses) {
    if (courseRows.length !== 2) throw new Error(`CANONICAL_LOCK_COURSE_COUNT:${raceId}:${course}:${courseRows.length}`);
    if (new Set(courseRows.map((row) => row.betType)).size !== 2) throw new Error(`CANONICAL_LOCK_DISTINCT_TYPES:${raceId}:${course}`);
    const total = courseRows.reduce((sum, row) => sum + row.stakeYen, 0);
    if (total !== EXPECTED_COURSE_TOTAL[course]) throw new Error(`CANONICAL_LOCK_STAKE:${raceId}:${course}:${total}`);
    const current = courseRows.map((row) => `${row.betType}:${row.combination}`).sort().join("|");
    if (identity == null) identity = current;
    else if (current !== identity) throw new Error(`CANONICAL_LOCK_TICKET_IDENTITY:${raceId}:${course}`);
  }
}

async function insertCanonicalRows(db: D1Database, raceId: string, rows: CompletedCourseBet[], lockedAt: string): Promise<void> {
  if (rows.length !== 6) throw new Error(`CANONICAL_INSERT_COUNT:${raceId}:${rows.length}`);
  const payload = rows.map((row) => [raceId, row.course, row.betType, row.combination, row.stakeYen, Number(row.assumedOdds.toFixed(6)), lockedAt, -2]);
  await db.prepare(`
    INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id,created_at)
    SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]'),json_extract(value,'$[2]'),json_extract(value,'$[3]'),
           json_extract(value,'$[4]'),json_extract(value,'$[5]'),NULL,'pending',json_extract(value,'$[6]'),json_extract(value,'$[7]'),CURRENT_TIMESTAMP
    FROM json_each(?)
    WHERE NOT EXISTS(SELECT 1 FROM rt_public_bets WHERE race_id=? LIMIT 1)
  `).bind(JSON.stringify(payload), raceId).run();
}

export async function lockCompletedRace(env: CompletedWorkerEnv, raceId: string, now = new Date()): Promise<CompletedLockResult> {
  const preexisting = await existingRows(env.DB, raceId);
  if (preexisting.length) {
    verifyCompletedLockedRows(raceId, preexisting);
    return {
      raceId, status: "already_locked", lockedAt: null,
      tickets: preexisting.filter((row) => row.course === "ライト").map((row) => ({ betType: row.betType, combination: row.combination, officialOdds: Number(row.assumedOdds ?? 0) })),
    };
  }

  const { race, runners } = await loadCompletedRaceBundle(env.DB, raceId);
  if (!race.entryUrl) throw new Error(`ENTRY_URL_MISSING:${raceId}`);
  if (race.status === "cancelled") throw new Error(`RACE_CANCELLED:${raceId}`);
  const active = runners.filter((runner) => (runner.runnerStatus || "active") === "active").sort((a, b) => a.horseNo - b.horseNo);
  if (active.length < 3) throw new Error(`ACTIVE_RUNNERS_TOO_FEW:${raceId}:${active.length}`);

  const [model, state, odds] = await Promise.all([
    loadModel(env),
    loadCompletedFeatureStateForRace(env.DB, race, active),
    fetchFastJraOfficialOddsForRace(race.entryUrl, { raceDate: race.raceDate, venue: race.venue, raceNo: race.raceNo }),
  ]);
  const raw = active.map((runner) => model.predict(completedFeatureVector(state, race, runner, active.length)));
  const weights = normalizeCompletedWeights(raw);
  const chosen = chooseCompletedTwoTickets(active.map((runner) => runner.horseNo), weights, odds.rows);
  const courseRows = completedCourseBets(chosen);
  const lockedAt = now.toISOString();
  await insertCanonicalRows(env.DB, raceId, courseRows, lockedAt);
  const written = await existingRows(env.DB, raceId);
  verifyCompletedLockedRows(raceId, written);
  return {
    raceId,
    status: "locked",
    lockedAt,
    tickets: chosen.map((row) => ({ betType: row.betType, combination: row.combination, officialOdds: row.officialOdds })),
  };
}
