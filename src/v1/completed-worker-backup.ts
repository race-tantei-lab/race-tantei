import type { CompletedWorkerEnv } from "./completed-worker-lock";
import { lockCompletedRace } from "./completed-worker-lock";

const MODEL_VERSION = "ten-year-completed-model";
const LOCK_MINUTES_MIN = 15;
const LOCK_MINUTES_MAX = 45;
const MAX_LOCKS_PER_TICK = 6;

type SelectionRow = { raceId: string; venue?: string; raceNo?: number };
type SelectionState = {
  sourceModel?: string;
  resultDataUsedForTargetDay?: boolean;
  selected?: SelectionRow[];
};

type RaceClock = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeUtc: string | null;
  status: string;
  betCount: number;
};

export type CompletedBackupAudit = {
  status: "waiting_selection" | "ok" | "partial" | "deadline_missed";
  modelVersion: string;
  targetDate: string;
  checkedAt: string;
  selectedRaceCount: number;
  dueRaceIds: string[];
  lockedRaceIds: string[];
  alreadyLockedRaceIds: string[];
  deadlineMissedRaceIds: string[];
  errors: Array<{ raceId: string; error: string }>;
};

function jstDate(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

function selectionKey(date: string): string {
  return `final_daily_selection:${date}`;
}

async function loadSelection(db: D1Database, date: string): Promise<SelectionState | null> {
  const result = await db.prepare("SELECT value FROM rt_system_state WHERE key=? LIMIT 1").bind(selectionKey(date)).all<{ value: string }>();
  const raw = result.results?.[0]?.value;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SelectionState;
  } catch {
    throw new Error(`DAILY_SELECTION_JSON_INVALID:${date}`);
  }
}

function validateSelection(date: string, state: SelectionState): SelectionRow[] {
  if (state.sourceModel !== MODEL_VERSION) throw new Error(`DAILY_SELECTION_MODEL_MISMATCH:${date}:${state.sourceModel}`);
  if (state.resultDataUsedForTargetDay !== false) throw new Error(`DAILY_SELECTION_RESULT_LEAKAGE_FLAG:${date}`);
  const selected = Array.isArray(state.selected) ? state.selected : [];
  if (!selected.length) throw new Error(`DAILY_SELECTION_EMPTY:${date}`);
  const ids = selected.map((row) => String(row.raceId || "")).filter(Boolean);
  if (new Set(ids).size !== ids.length || ids.length !== selected.length) throw new Error(`DAILY_SELECTION_DUPLICATE_OR_MISSING_ID:${date}`);
  const venues = new Map<string, number>();
  for (const row of selected) {
    const venue = String(row.venue || "");
    if (!venue) throw new Error(`DAILY_SELECTION_VENUE_MISSING:${row.raceId}`);
    venues.set(venue, (venues.get(venue) ?? 0) + 1);
  }
  if (venues.size < 2 || [...venues.values()].some((count) => count !== 5)) {
    throw new Error(`DAILY_SELECTION_NOT_FIVE_PER_VENUE:${date}:${JSON.stringify(Object.fromEntries(venues))}`);
  }
  return selected.map((row) => ({ ...row, raceId: String(row.raceId) }));
}

async function loadRaceClocks(db: D1Database, raceIds: string[]): Promise<RaceClock[]> {
  const result = await db.prepare(`
    SELECT ra.race_id AS raceId,ra.venue,ra.race_no AS raceNo,ra.start_time_utc AS startTimeUtc,ra.status,
           (SELECT COUNT(*) FROM rt_public_bets b WHERE b.race_id=ra.race_id) AS betCount
    FROM rt_races ra
    WHERE ra.race_id IN (SELECT value FROM json_each(?))
  `).bind(JSON.stringify(raceIds)).all<RaceClock>();
  return (result.results ?? []).map((row) => ({ ...row, raceNo: Number(row.raceNo), betCount: Number(row.betCount) }));
}

async function writeAudit(db: D1Database, audit: CompletedBackupAudit): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(key,value) VALUES(?,?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
  `).bind(`worker_completed_backup:${audit.targetDate}`, JSON.stringify(audit)).run();
  await db.prepare(`
    INSERT INTO rt_system_state(key,value) VALUES(?,?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
  `).bind("worker_completed_backup:last", JSON.stringify(audit)).run();
}

export async function runCompletedWorkerBackup(env: CompletedWorkerEnv, now = new Date()): Promise<CompletedBackupAudit> {
  const targetDate = jstDate(now);
  const checkedAt = now.toISOString();
  const state = await loadSelection(env.DB, targetDate);
  if (!state) {
    const audit: CompletedBackupAudit = {
      status: "waiting_selection", modelVersion: MODEL_VERSION, targetDate, checkedAt, selectedRaceCount: 0,
      dueRaceIds: [], lockedRaceIds: [], alreadyLockedRaceIds: [], deadlineMissedRaceIds: [], errors: [],
    };
    await writeAudit(env.DB, audit);
    return audit;
  }

  const selected = validateSelection(targetDate, state);
  const clocks = await loadRaceClocks(env.DB, selected.map((row) => row.raceId));
  if (clocks.length !== selected.length) throw new Error(`DAILY_SELECTION_RACE_LOOKUP_MISMATCH:${targetDate}:${clocks.length}:${selected.length}`);

  const due: RaceClock[] = [];
  const already: string[] = [];
  const deadlineMissed: string[] = [];
  for (const race of clocks) {
    if (race.betCount > 0) {
      already.push(race.raceId);
      continue;
    }
    if (!race.startTimeUtc) throw new Error(`SELECTED_RACE_START_MISSING:${race.raceId}`);
    if (race.status === "cancelled") continue;
    const startMs = Date.parse(race.startTimeUtc.endsWith("Z") ? race.startTimeUtc : `${race.startTimeUtc}Z`);
    if (!Number.isFinite(startMs)) throw new Error(`SELECTED_RACE_START_INVALID:${race.raceId}:${race.startTimeUtc}`);
    const minutes = (startMs - now.getTime()) / 60_000;
    if (minutes >= LOCK_MINUTES_MIN && minutes <= LOCK_MINUTES_MAX) due.push(race);
    else if (minutes < LOCK_MINUTES_MIN) deadlineMissed.push(race.raceId);
  }
  due.sort((a, b) => Date.parse(String(a.startTimeUtc)) - Date.parse(String(b.startTimeUtc)) || a.raceId.localeCompare(b.raceId));

  const locked: string[] = [];
  const errors: Array<{ raceId: string; error: string }> = [];
  for (const race of due.slice(0, MAX_LOCKS_PER_TICK)) {
    try {
      const result = await lockCompletedRace(env, race.raceId, now);
      if (result.status === "locked") locked.push(race.raceId);
      else already.push(race.raceId);
    } catch (error) {
      errors.push({ raceId: race.raceId, error: error instanceof Error ? error.message : String(error) });
    }
  }

  let status: CompletedBackupAudit["status"] = "ok";
  if (deadlineMissed.length) status = "deadline_missed";
  else if (errors.length || due.length > MAX_LOCKS_PER_TICK) status = "partial";
  const audit: CompletedBackupAudit = {
    status, modelVersion: MODEL_VERSION, targetDate, checkedAt, selectedRaceCount: selected.length,
    dueRaceIds: due.map((row) => row.raceId), lockedRaceIds: locked,
    alreadyLockedRaceIds: [...new Set(already)].sort(), deadlineMissedRaceIds: deadlineMissed.sort(), errors,
  };
  await writeAudit(env.DB, audit);
  return audit;
}
