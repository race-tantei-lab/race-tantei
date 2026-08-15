import { fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "./jra";
import type { RaceRecord, RunnerRecord } from "./types";

const BODY_WEIGHT_STATE_PREFIX = "worker_body_weight:";
const BODY_WEIGHT_STATE_VERSION = 1;
const MIN_BODY_WEIGHT_KG = 250;
const MAX_BODY_WEIGHT_KG = 750;

type BodyWeightState = {
  version: 1;
  status: "ready";
  raceId: string;
  source: "jra_entry_direct";
  fetchedAt: string;
  snapshotSha256: string;
  activeRunnerCount: number;
  weights: Array<{ horseNo: number; horseName: string; horseWeight: number; weightChange: number | null }>;
};

export type CompletedBodyWeightEvidence = {
  ready: boolean;
  source: "jra_entry_direct" | "d1_existing" | "unavailable";
  fetchedAt: string | null;
  snapshotSha256: string | null;
  activeRunnerCount: number;
  error: string | null;
};

function normalizeName(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, "").trim();
}

function validBodyWeight(value: unknown): value is number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= MIN_BODY_WEIGHT_KG && parsed <= MAX_BODY_WEIGHT_KG;
}

export function completedBodyWeightsReady(runners: RunnerRecord[]): boolean {
  const active = runners.filter((runner) => (runner.runnerStatus || "active") === "active");
  return active.length >= 3 && active.every((runner) => validBodyWeight(runner.horseWeight));
}

function canonicalWeights(runners: RunnerRecord[]): string {
  return JSON.stringify(
    runners
      .filter((runner) => (runner.runnerStatus || "active") === "active")
      .map((runner) => [
        Number(runner.horseNo),
        normalizeName(runner.horseName),
        Number(runner.horseWeight),
        runner.weightChange == null ? null : Number(runner.weightChange),
      ] as const)
      .sort((a, b) => a[0] - b[0]),
  );
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function loadAllRunners(db: D1Database, raceId: string): Promise<RunnerRecord[]> {
  const result = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  return result.results ?? [];
}

async function loadSavedState(db: D1Database, raceId: string): Promise<BodyWeightState | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${BODY_WEIGHT_STATE_PREFIX}${raceId}`)
    .first<{ value: string }>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value) as BodyWeightState;
    if (parsed.version !== BODY_WEIGHT_STATE_VERSION || parsed.status !== "ready" || parsed.raceId !== raceId) return null;
    if (parsed.source !== "jra_entry_direct" || !Number.isFinite(Date.parse(parsed.fetchedAt)) || !/^[0-9a-f]{64}$/.test(parsed.snapshotSha256)) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function saveReadyState(db: D1Database, state: BodyWeightState): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${BODY_WEIGHT_STATE_PREFIX}${state.raceId}`, JSON.stringify(state)).run();
}

function evidenceFromState(state: BodyWeightState, error: string | null = null): CompletedBodyWeightEvidence {
  return {
    ready: true,
    source: "jra_entry_direct",
    fetchedAt: state.fetchedAt,
    snapshotSha256: state.snapshotSha256,
    activeRunnerCount: state.activeRunnerCount,
    error,
  };
}

async function existingEvidence(runners: RunnerRecord[], error: string | null = null): Promise<CompletedBodyWeightEvidence> {
  const active = runners.filter((runner) => (runner.runnerStatus || "active") === "active");
  if (!completedBodyWeightsReady(runners)) {
    return { ready: false, source: "unavailable", fetchedAt: null, snapshotSha256: null, activeRunnerCount: active.length, error };
  }
  return {
    ready: true,
    source: "d1_existing",
    fetchedAt: null,
    snapshotSha256: await sha256Hex(canonicalWeights(runners)),
    activeRunnerCount: active.length,
    error,
  };
}

async function directRefresh(db: D1Database, race: RaceRecord): Promise<BodyWeightState> {
  if (!race.entryUrl) throw new Error(`BODY_WEIGHT_ENTRY_URL_MISSING:${race.raceId}`);
  const current = await loadAllRunners(db, race.raceId);
  if (current.length < 3) throw new Error(`BODY_WEIGHT_RUNNERS_MISSING:${race.raceId}:${current.length}`);
  const currentByNo = new Map(current.map((runner) => [Number(runner.horseNo), runner]));

  const page = await fetchJraPage(race.entryUrl);
  if (!pageLooksLikeEntry(page.html)) throw new Error(`BODY_WEIGHT_ENTRY_SIGNATURE_MISSING:${race.raceId}`);
  const bundle = parseEntryPage(page.html, page.url);
  if (
    bundle.race.raceId !== race.raceId ||
    bundle.race.raceDate !== race.raceDate ||
    bundle.race.venue !== race.venue ||
    Number(bundle.race.raceNo) !== Number(race.raceNo)
  ) {
    throw new Error(`BODY_WEIGHT_RACE_IDENTITY_MISMATCH:${race.raceId}:${bundle.race.raceId}`);
  }

  const parsedByNo = new Map(bundle.runners.map((runner) => [Number(runner.horseNo), runner]));
  for (const runner of current.filter((row) => (row.runnerStatus || "active") === "active")) {
    const parsed = parsedByNo.get(Number(runner.horseNo));
    if (!parsed || normalizeName(parsed.horseName) !== normalizeName(runner.horseName)) {
      throw new Error(`BODY_WEIGHT_RUNNER_IDENTITY_MISMATCH:${race.raceId}:${runner.horseNo}`);
    }
  }

  const parsedActive = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
  if (parsedActive.length < 3) throw new Error(`BODY_WEIGHT_ACTIVE_RUNNERS_TOO_FEW:${race.raceId}:${parsedActive.length}`);
  for (const runner of parsedActive) {
    const currentRunner = currentByNo.get(Number(runner.horseNo));
    if (!currentRunner || normalizeName(currentRunner.horseName) !== normalizeName(runner.horseName)) {
      throw new Error(`BODY_WEIGHT_PARSED_RUNNER_NOT_IN_D1:${race.raceId}:${runner.horseNo}`);
    }
    if (!validBodyWeight(runner.horseWeight)) {
      throw new Error(`BODY_WEIGHT_NOT_PUBLISHED_YET:${race.raceId}:${runner.horseNo}`);
    }
  }

  const statements: D1PreparedStatement[] = [];
  for (const runner of bundle.runners) {
    const currentRunner = currentByNo.get(Number(runner.horseNo));
    if (!currentRunner || normalizeName(currentRunner.horseName) !== normalizeName(runner.horseName)) continue;
    statements.push(db.prepare(`
      UPDATE rt_runners SET
        horse_weight=COALESCE(?,horse_weight),
        weight_change=CASE WHEN ? IS NULL THEN weight_change ELSE ? END,
        runner_status=?,updated_at=CURRENT_TIMESTAMP
      WHERE race_id=? AND horse_no=?
    `).bind(
      runner.horseWeight,
      runner.horseWeight,
      runner.weightChange,
      runner.runnerStatus,
      race.raceId,
      runner.horseNo,
    ));
  }
  if (!statements.length) throw new Error(`BODY_WEIGHT_NO_MATCHED_RUNNERS:${race.raceId}`);
  await db.batch(statements);

  const verified = await loadAllRunners(db, race.raceId);
  if (!completedBodyWeightsReady(verified)) throw new Error(`BODY_WEIGHT_POST_WRITE_INCOMPLETE:${race.raceId}`);
  const active = verified.filter((runner) => (runner.runnerStatus || "active") === "active");
  const fetchedAt = new Date().toISOString();
  const state: BodyWeightState = {
    version: BODY_WEIGHT_STATE_VERSION,
    status: "ready",
    raceId: race.raceId,
    source: "jra_entry_direct",
    fetchedAt,
    snapshotSha256: await sha256Hex(canonicalWeights(verified)),
    activeRunnerCount: active.length,
    weights: active.map((runner) => ({
      horseNo: Number(runner.horseNo),
      horseName: String(runner.horseName),
      horseWeight: Number(runner.horseWeight),
      weightChange: runner.weightChange == null ? null : Number(runner.weightChange),
    })),
  };
  await saveReadyState(db, state);
  return state;
}

export async function refreshCompletedRaceBodyWeights(
  db: D1Database,
  race: RaceRecord,
  options: { attempts?: number; forceRefresh?: boolean } = {},
): Promise<CompletedBodyWeightEvidence> {
  const attempts = Math.max(1, Math.min(3, Math.trunc(options.attempts ?? 1)));
  const current = await loadAllRunners(db, race.raceId);
  const saved = await loadSavedState(db, race.raceId);
  if (!options.forceRefresh && saved && completedBodyWeightsReady(current)) return evidenceFromState(saved);

  let lastError: string | null = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return evidenceFromState(await directRefresh(db, race));
    } catch (error) {
      lastError = error instanceof Error ? `${error.name}:${error.message}` : String(error);
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }

  const after = await loadAllRunners(db, race.raceId);
  if (saved && completedBodyWeightsReady(after)) return evidenceFromState(saved, lastError);
  return existingEvidence(after, lastError);
}
