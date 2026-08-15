import { fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "./jra";
import type { RaceRecord, RunnerRecord } from "./types";

const SNAPSHOT_PREFIX = "worker_bodyweight_snapshot:";
const SNAPSHOT_VERSION = 1 as const;
const MIN_HORSE_WEIGHT_KG = 250;
const MAX_HORSE_WEIGHT_KG = 700;

export type OfficialBodyWeightRunner = {
  horseNo: number;
  horseWeight: number;
  weightChange: number | null;
};

export type OfficialBodyWeightSnapshot = {
  version: 1;
  raceId: string;
  fetchedAt: string;
  sourceUrl: string;
  snapshotSha256: string;
  activeRunners: OfficialBodyWeightRunner[];
};

type StoredStateRow = { value: string };
type KnownRunnerRow = {
  horseNo: number;
  horseWeight: number | null;
  weightChange: number | null;
  runnerStatus: string | null;
};

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function normalizedActiveRows(rows: OfficialBodyWeightRunner[]): OfficialBodyWeightRunner[] {
  return rows
    .map((row) => ({
      horseNo: Number(row.horseNo),
      horseWeight: Number(row.horseWeight),
      weightChange: row.weightChange == null ? null : Number(row.weightChange),
    }))
    .sort((a, b) => a.horseNo - b.horseNo);
}

function validHorseWeight(value: unknown): value is number {
  const weight = Number(value);
  return Number.isInteger(weight) && weight >= MIN_HORSE_WEIGHT_KG && weight <= MAX_HORSE_WEIGHT_KG;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function snapshotHash(rows: OfficialBodyWeightRunner[]): Promise<string> {
  return sha256Hex(JSON.stringify(normalizedActiveRows(rows).map((row) => [row.horseNo, row.horseWeight, row.weightChange])));
}

function candidateEntryUrls(rawUrl: string): string[] {
  const urls: string[] = [];
  const add = (value: string) => { if (value && !urls.includes(value)) urls.push(value); };
  add(rawUrl);
  try {
    const parsed = new URL(rawUrl);
    for (const host of ["sp.jra.jp", "www.jra.go.jp", "jra.jp"]) {
      const candidate = new URL(parsed.toString());
      candidate.hostname = host;
      add(candidate.toString());
    }
  } catch {
    // fetchJraPage will emit the canonical validation error for the original URL.
  }
  return urls;
}

async function knownRunners(db: D1Database, raceId: string): Promise<KnownRunnerRow[]> {
  const result = await db.prepare(`
    SELECT horse_no AS horseNo,horse_weight AS horseWeight,weight_change AS weightChange,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<KnownRunnerRow>();
  return result.results ?? [];
}

function activeKnown(rows: KnownRunnerRow[]): KnownRunnerRow[] {
  return rows.filter((row) => (row.runnerStatus || "active") === "active" && Number.isInteger(Number(row.horseNo)));
}

function validSnapshotShape(snapshot: OfficialBodyWeightSnapshot, raceId: string): boolean {
  if (snapshot.version !== SNAPSHOT_VERSION || snapshot.raceId !== raceId) return false;
  if (!Number.isFinite(Date.parse(snapshot.fetchedAt)) || !snapshot.sourceUrl || !/^[0-9a-f]{64}$/.test(snapshot.snapshotSha256)) return false;
  if (!Array.isArray(snapshot.activeRunners) || snapshot.activeRunners.length < 3) return false;
  const horseNos = new Set<number>();
  for (const row of snapshot.activeRunners) {
    const horseNo = Number(row.horseNo);
    if (!Number.isInteger(horseNo) || horseNo <= 0 || horseNos.has(horseNo) || !validHorseWeight(row.horseWeight)) return false;
    if (row.weightChange != null && (!Number.isInteger(Number(row.weightChange)) || Math.abs(Number(row.weightChange)) > 100)) return false;
    horseNos.add(horseNo);
  }
  return true;
}

export async function loadOfficialBodyWeightSnapshot(db: D1Database, raceId: string): Promise<OfficialBodyWeightSnapshot | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SNAPSHOT_PREFIX}${raceId}`).first<StoredStateRow>();
  if (!row?.value) return null;
  try {
    const parsed = JSON.parse(row.value) as OfficialBodyWeightSnapshot;
    if (!validSnapshotShape(parsed, raceId)) return null;
    const expectedHash = await snapshotHash(parsed.activeRunners);
    return expectedHash === parsed.snapshotSha256 ? parsed : null;
  } catch {
    return null;
  }
}

export function bodyWeightSnapshotMatchesRunners(snapshot: OfficialBodyWeightSnapshot, runners: RunnerRecord[]): boolean {
  if (!validSnapshotShape(snapshot, snapshot.raceId)) return false;
  const active = runners
    .filter((runner) => (runner.runnerStatus || "active") === "active")
    .map((runner) => Number(runner.horseNo))
    .sort((a, b) => a - b);
  const snap = snapshot.activeRunners.map((runner) => Number(runner.horseNo)).sort((a, b) => a - b);
  if (active.length !== snap.length || active.some((horseNo, index) => horseNo !== snap[index])) return false;
  const byHorse = new Map(snapshot.activeRunners.map((row) => [row.horseNo, row]));
  return runners
    .filter((runner) => (runner.runnerStatus || "active") === "active")
    .every((runner) => {
      const official = byHorse.get(Number(runner.horseNo));
      return Boolean(
        official
        && validHorseWeight(runner.horseWeight)
        && Number(runner.horseWeight) === official.horseWeight
        && (runner.weightChange == null ? null : Number(runner.weightChange)) === official.weightChange,
      );
    });
}

async function persistFreshSnapshot(
  db: D1Database,
  race: RaceRecord,
  sourceUrl: string,
  activeRunners: OfficialBodyWeightRunner[],
  parsedStatuses: Array<{ horseNo: number; runnerStatus: string }>,
  fetchedAt: string,
): Promise<OfficialBodyWeightSnapshot> {
  const normalized = normalizedActiveRows(activeRunners);
  const snapshot: OfficialBodyWeightSnapshot = {
    version: SNAPSHOT_VERSION,
    raceId: race.raceId,
    fetchedAt,
    sourceUrl,
    snapshotSha256: await snapshotHash(normalized),
    activeRunners: normalized,
  };
  if (!validSnapshotShape(snapshot, race.raceId)) throw new Error(`BODYWEIGHT_SNAPSHOT_INVALID:${race.raceId}`);
  const activeMap = new Map(normalized.map((row) => [row.horseNo, row]));
  const statements: D1PreparedStatement[] = [];
  for (const status of parsedStatuses) {
    const active = activeMap.get(status.horseNo);
    statements.push(db.prepare(`
      UPDATE rt_runners
      SET horse_weight=?,weight_change=?,runner_status=?
      WHERE race_id=? AND horse_no=?
    `).bind(active?.horseWeight ?? null, active?.weightChange ?? null, status.runnerStatus, race.raceId, status.horseNo));
  }
  statements.push(db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${SNAPSHOT_PREFIX}${race.raceId}`, JSON.stringify(snapshot)));
  await db.batch(statements);

  const reread = activeKnown(await knownRunners(db, race.raceId));
  const rereadByHorse = new Map(reread.map((row) => [Number(row.horseNo), row]));
  if (reread.length !== normalized.length || normalized.some((row) => {
    const saved = rereadByHorse.get(row.horseNo);
    return !saved || Number(saved.horseWeight) !== row.horseWeight || (saved.weightChange == null ? null : Number(saved.weightChange)) !== row.weightChange;
  })) {
    throw new Error(`BODYWEIGHT_D1_VERIFY_FAILED:${race.raceId}`);
  }
  return snapshot;
}

export async function refreshOfficialBodyWeights(db: D1Database, race: RaceRecord, now = new Date()): Promise<OfficialBodyWeightSnapshot> {
  if (!race.entryUrl) throw new Error(`BODYWEIGHT_ENTRY_URL_MISSING:${race.raceId}`);
  const existingRows = await knownRunners(db, race.raceId);
  const knownHorseNos = existingRows.map((row) => Number(row.horseNo)).filter(Number.isInteger).sort((a, b) => a - b);
  if (knownHorseNos.length < 3) throw new Error(`BODYWEIGHT_KNOWN_RUNNERS_TOO_FEW:${race.raceId}:${knownHorseNos.length}`);

  const errors: string[] = [];
  for (const entryUrl of candidateEntryUrls(race.entryUrl)) {
    try {
      const page = await fetchJraPage(entryUrl);
      if (!pageLooksLikeEntry(page.html)) throw new Error("NOT_ENTRY_PAGE");
      const bundle = parseEntryPage(page.html, page.url);
      if (bundle.race.raceId !== race.raceId) throw new Error(`RACE_ID_MISMATCH:${bundle.race.raceId}`);
      const parsedHorseNos = bundle.runners.map((runner) => Number(runner.horseNo)).filter(Number.isInteger).sort((a, b) => a - b);
      if (parsedHorseNos.length !== knownHorseNos.length || parsedHorseNos.some((horseNo, index) => horseNo !== knownHorseNos[index])) {
        throw new Error(`HORSE_SET_INCOMPLETE:${parsedHorseNos.length}/${knownHorseNos.length}`);
      }
      const active = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
      if (active.length < 3) throw new Error(`ACTIVE_RUNNERS_TOO_FEW:${active.length}`);
      const missing = active.filter((runner) => !validHorseWeight(runner.horseWeight)).map((runner) => runner.horseNo);
      if (missing.length) throw new Error(`BODYWEIGHT_NOT_PUBLISHED:${missing.join(",")}`);
      const activeRunners: OfficialBodyWeightRunner[] = active.map((runner) => ({
        horseNo: Number(runner.horseNo),
        horseWeight: Number(runner.horseWeight),
        weightChange: runner.weightChange == null ? null : Number(runner.weightChange),
      }));
      const statuses = bundle.runners.map((runner) => ({ horseNo: Number(runner.horseNo), runnerStatus: runner.runnerStatus || "active" }));
      return await persistFreshSnapshot(db, race, page.url, activeRunners, statuses, now.toISOString());
    } catch (error) {
      errors.push(`${entryUrl}:${errorText(error)}`);
    }
  }
  throw new Error(`BODYWEIGHT_REFRESH_FAILED:${race.raceId}:${errors.join("|")}`);
}

export async function resolveOfficialBodyWeights(
  db: D1Database,
  race: RaceRecord,
  currentRunners: RunnerRecord[],
  now = new Date(),
): Promise<OfficialBodyWeightSnapshot> {
  try {
    return await refreshOfficialBodyWeights(db, race, now);
  } catch (freshError) {
    const stored = await loadOfficialBodyWeightSnapshot(db, race.raceId);
    if (!stored) throw freshError;

    const currentActiveHorseNos = currentRunners
      .filter((runner) => (runner.runnerStatus || "active") === "active")
      .map((runner) => Number(runner.horseNo))
      .sort((a, b) => a - b);
    const storedByHorse = new Map(stored.activeRunners.map((row) => [row.horseNo, row]));
    if (currentActiveHorseNos.length < 3 || currentActiveHorseNos.some((horseNo) => !storedByHorse.has(horseNo))) throw freshError;

    const projectedRows = currentActiveHorseNos.map((horseNo) => storedByHorse.get(horseNo) as OfficialBodyWeightRunner);
    const projected: OfficialBodyWeightSnapshot = {
      ...stored,
      snapshotSha256: await snapshotHash(projectedRows),
      activeRunners: normalizedActiveRows(projectedRows),
    };
    const statements = projected.activeRunners.map((row) => db.prepare(`
      UPDATE rt_runners SET horse_weight=?,weight_change=?
      WHERE race_id=? AND horse_no=? AND COALESCE(runner_status,'active')='active'
    `).bind(row.horseWeight, row.weightChange, race.raceId, row.horseNo));
    if (statements.length) await db.batch(statements);
    return projected;
  }
}
