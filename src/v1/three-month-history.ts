import {
  getState,
  saveEntryBundle,
  saveResultBundle,
  setState
} from "./db.js";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "./jra.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE
} from "./three-month-scope.js";
import type { RaceBundle, RunnerRecord } from "./types.js";
import { clamp, stripHtml } from "./utils.js";

const VENUE_CODES: Record<string, string> = {
  札幌: "01",
  函館: "02",
  福島: "03",
  新潟: "04",
  東京: "05",
  中山: "06",
  中京: "07",
  京都: "08",
  阪神: "09",
  小倉: "10"
};
const VENUE_PATTERN = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";
const STATE_PREFIX = `three_month_history:${THREE_MONTH_SCOPE_VERSION}`;
const STATE_VERSION_KEY = `${STATE_PREFIX}:version`;
const STATE_DISCOVERY_INDEX_KEY = `${STATE_PREFIX}:discovery_index`;
const STATE_TASKS_KEY = `${STATE_PREFIX}:tasks`;
const STATE_TASK_INDEX_KEY = `${STATE_PREFIX}:task_index`;
const STATE_RACE_NO_KEY = `${STATE_PREFIX}:race_no`;
const STATE_FAILURES_KEY = `${STATE_PREFIX}:failures`;
const RACES_PER_BATCH = 4;
const MARKET_TAKEOUT_FACTOR = 0.8;
const POPULARITY_POWER = 1.07;
const HISTORICAL_TRANSITION_SUFFIX = "34";

export interface HistoricalMeetingTask {
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
}

interface FailedRace extends HistoricalMeetingTask {
  raceNo: number;
  attempts: number;
  error: string;
}

interface ParsedHistoricalRunner {
  horseNo: number;
  frameNo: number | null;
  horseName: string;
  sexAge: string | null;
  horseWeight: number | null;
  weightChange: number | null;
  jockey: string | null;
  assignedWeight: number | null;
  trainer: string | null;
  stable: string | null;
  popularity: number | null;
  runnerStatus: RunnerRecord["runnerStatus"];
}

export interface ThreeMonthHistoryProgress {
  scopeVersion: string;
  phase: "discovery" | "import" | "retry" | "complete";
  discoveryDates: number;
  totalDiscoveryDates: number;
  meetingTasks: number;
  completedMeetingTasks: number;
  nextRaceNo: number;
  failedRaces: number;
  storedRaces: number;
  complete: boolean;
}

function integerState(value: string | null, fallback = 0): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : fallback;
}

function parseJsonArray<T>(value: string | null): T[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed as T[] : [];
  } catch {
    return [];
  }
}

function calendarUrl(raceDate: string): string {
  const [year, month, day] = raceDate.split("-");
  return `https://www.jra.go.jp/keiba/calendar${year}/${year}/${Number(month)}/${month}${day}.html`;
}

function compactText(html: string): string {
  return stripHtml(
    html
      .replace(/<\s*br\s*\/?>/gi, "\n")
      .replace(/<\/(?:h[1-6]|div|section|article|li|p|td|th|tr)>/gi, "\n")
  ).replace(/\s+/g, " ");
}

export function parseHistoricalMeetings(html: string, raceDate: string): HistoricalMeetingTask[] {
  const text = compactText(html);
  const found = new Map<string, HistoricalMeetingTask>();
  const pattern = new RegExp(`(\\d+)回(${VENUE_PATTERN})(\\d+)日`, "g");
  for (const match of text.matchAll(pattern)) {
    const venue = match[2] ?? "";
    if (!VENUE_CODES[venue]) continue;
    const task: HistoricalMeetingTask = {
      raceDate,
      venue,
      meetingNo: Number(match[1]),
      meetingDay: Number(match[3])
    };
    found.set(`${raceDate}:${venue}`, task);
  }
  return [...found.values()].sort((a, b) => a.venue.localeCompare(b.venue, "ja"));
}

function resultTableRows(html: string): string[][] {
  const rows: string[][] = [];
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...(match[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)]
      .map((cell) => stripHtml(cell[1] ?? "").replace(/\s+/g, " ").trim());
    if (cells.some((cell) => /(?:\d+:\d{2}\.\d|除外|中止|失格|取消)/.test(cell))) rows.push(cells);
  }
  return rows;
}

function parseDetailedRunner(cells: string[]): ParsedHistoricalRunner | null {
  const frameNo = /^\d{1,2}$/.test(cells[1] ?? "") ? Number(cells[1]) : null;
  const horseNo = /^\d{1,2}$/.test(cells[2] ?? "") ? Number(cells[2]) : null;
  if (!horseNo || horseNo < 1 || horseNo > 18) return null;
  const detail = cells.slice(3).join(" ").replace(/\s+/g, " ").trim();
  const status: RunnerRecord["runnerStatus"] = /除外/.test(detail)
    ? "excluded"
    : /取消/.test(detail)
      ? "scratched"
      : "active";
  const popularityMatch = detail.match(/(\d+)番人気/);
  const popularity = popularityMatch?.[1] ? Number(popularityMatch[1]) : null;
  const horseName = (popularityMatch?.index !== undefined
    ? detail.slice(0, popularityMatch.index)
    : detail.split(/\s+(?:[牡牝騸セ]\d+|除外|取消)/)[0] ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!horseName) return null;

  const sexAgeMatch = detail.match(/([牡牝騸セ])(\d+)/);
  const bodyMatch = detail.match(/(\d{3})kg\(([+-]?\d+)\)/);
  const peopleMatch = bodyMatch
    ? detail.slice((bodyMatch.index ?? 0) + bodyMatch[0].length)
      .match(/^\s*(.+?)\s+\((\d+(?:\.\d+)?)\)\s+(.+?)\s+\((美浦|栗東|本会外)\)/)
    : null;

  return {
    horseNo,
    frameNo,
    horseName,
    sexAge: sexAgeMatch ? `${sexAgeMatch[1]}${sexAgeMatch[2]}` : null,
    horseWeight: bodyMatch?.[1] ? Number(bodyMatch[1]) : null,
    weightChange: bodyMatch?.[2] ? Number(bodyMatch[2]) : null,
    jockey: peopleMatch?.[1]?.trim() || null,
    assignedWeight: peopleMatch?.[2] ? Number(peopleMatch[2]) : null,
    trainer: peopleMatch?.[3]?.trim() || null,
    stable: peopleMatch?.[4] ?? null,
    popularity,
    runnerStatus: status
  };
}

function popularityProxyOdds(runners: ParsedHistoricalRunner[]): Map<number, number> {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const fallbackStart = Math.max(
    active.length,
    ...active.map((runner) => runner.popularity ?? 0),
    1
  );
  const ranks = new Map<number, number>();
  let fallbackOffset = 0;
  for (const runner of active) {
    ranks.set(runner.horseNo, runner.popularity ?? fallbackStart + (++fallbackOffset));
  }
  const weights = new Map<number, number>();
  for (const runner of active) {
    const rank = ranks.get(runner.horseNo) ?? fallbackStart + 1;
    weights.set(runner.horseNo, Math.pow(Math.max(1, rank), -POPULARITY_POWER));
  }
  const total = [...weights.values()].reduce((sum, value) => sum + value, 0);
  const odds = new Map<number, number>();
  for (const runner of active) {
    const probability = total > 0
      ? (weights.get(runner.horseNo) ?? 0) / total
      : 1 / Math.max(1, active.length);
    const decimalOdds = clamp(MARKET_TAKEOUT_FACTOR / Math.max(0.0001, probability), 1.1, 999.9);
    odds.set(runner.horseNo, Math.floor(decimalOdds * 10) / 10);
  }
  return odds;
}

export function parseHistoricalResultRunners(html: string): RunnerRecord[] {
  const parsed = resultTableRows(html)
    .map(parseDetailedRunner)
    .filter((runner): runner is ParsedHistoricalRunner => runner !== null);
  const unique = new Map<number, ParsedHistoricalRunner>();
  for (const runner of parsed) unique.set(runner.horseNo, runner);
  const values = [...unique.values()].sort((a, b) => a.horseNo - b.horseNo);
  const odds = popularityProxyOdds(values);
  return values.map((runner) => ({
    horseNo: runner.horseNo,
    frameNo: runner.frameNo,
    horseName: runner.horseName,
    sexAge: runner.sexAge,
    coatColor: null,
    horseWeight: runner.horseWeight,
    weightChange: runner.weightChange,
    jockey: runner.jockey,
    assignedWeight: runner.assignedWeight,
    trainer: runner.trainer,
    stable: runner.stable,
    winOdds: runner.runnerStatus === "active" ? odds.get(runner.horseNo) ?? null : null,
    popularity: runner.popularity,
    runnerStatus: runner.runnerStatus
  }));
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

export function historicalResultUrl(task: HistoricalMeetingTask, raceNo: number): string {
  const venueCode = VENUE_CODES[task.venue];
  if (!venueCode) throw new Error(`UNKNOWN_VENUE:${task.venue}`);
  const ymd = task.raceDate.replace(/-/g, "");
  const year = task.raceDate.slice(0, 4);
  const cname = `sw01sde01${venueCode}${year}${pad2(task.meetingNo)}${pad2(task.meetingDay)}${pad2(raceNo)}${ymd}/${HISTORICAL_TRANSITION_SUFFIX}`;
  return `https://sp.jra.jp/JRADB/accessS.html?CNAME=${encodeURIComponent(cname)}`;
}

async function alreadyComplete(db: D1Database, task: HistoricalMeetingTask, raceNo: number): Promise<boolean> {
  const row = await db.prepare(`
    SELECT r.status,
      (SELECT COUNT(*) FROM rt_runners rr WHERE rr.race_id=r.race_id AND rr.runner_status='active' AND rr.win_odds IS NOT NULL) AS runners,
      (SELECT COUNT(*) FROM rt_results rs WHERE rs.race_id=r.race_id) AS results,
      (SELECT COUNT(*) FROM rt_payouts p WHERE p.race_id=r.race_id) AS payouts
    FROM rt_races r
    WHERE r.race_date=? AND r.venue=? AND r.race_no=?
  `).bind(task.raceDate, task.venue, raceNo)
    .first<{ status: string; runners: number; results: number; payouts: number }>();
  return row?.status === "finished"
    && Number(row.runners ?? 0) >= 2
    && Number(row.results ?? 0) >= 2
    && Number(row.payouts ?? 0) >= 1;
}

async function importHistoricalRace(
  db: D1Database,
  task: HistoricalMeetingTask,
  raceNo: number
): Promise<{ imported: boolean; skipped: boolean }> {
  if (await alreadyComplete(db, task, raceNo)) return { imported: false, skipped: true };

  const resultUrl = historicalResultUrl(task, raceNo);
  const resultPage = await fetchJraPage(resultUrl);
  if (!pageLooksLikeResult(resultPage.html)) throw new Error("HISTORY_RESULT_SIGNATURE_MISSING");
  const result = parseResultPage(resultPage.html, resultPage.url);
  if (result.race.raceDate !== task.raceDate || result.race.venue !== task.venue || result.race.raceNo !== raceNo) {
    throw new Error(`RESULT_RACE_MISMATCH:${result.race.raceDate}:${result.race.venue}:${result.race.raceNo}`);
  }
  const runners = parseHistoricalResultRunners(resultPage.html);
  if (runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null).length < 2) {
    throw new Error(`HISTORY_RUNNERS_NOT_FOUND:${runners.length}`);
  }
  const entry: RaceBundle = {
    race: { ...result.race, status: "scheduled" },
    runners,
    results: [],
    payouts: [],
    refundHorseNos: []
  };
  await saveEntryBundle(db, entry);
  await saveResultBundle(db, result);
  return { imported: true, skipped: false };
}

async function initializeState(db: D1Database): Promise<void> {
  const version = await getState(db, STATE_VERSION_KEY);
  if (version === THREE_MONTH_SCOPE_VERSION) return;
  await Promise.all([
    setState(db, STATE_VERSION_KEY, THREE_MONTH_SCOPE_VERSION),
    setState(db, STATE_DISCOVERY_INDEX_KEY, "0"),
    setState(db, STATE_TASKS_KEY, "[]"),
    setState(db, STATE_TASK_INDEX_KEY, "0"),
    setState(db, STATE_RACE_NO_KEY, "1"),
    setState(db, STATE_FAILURES_KEY, "[]")
  ]);
}

async function storedRaceCount(db: D1Database): Promise<number> {
  const row = await db.prepare(`
    SELECT COUNT(*) AS count
    FROM rt_races
    WHERE race_date BETWEEN ? AND ? AND status='finished'
  `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).first<{ count: number }>();
  return Number(row?.count ?? 0);
}

export async function getThreeMonthHistoryProgress(db: D1Database): Promise<ThreeMonthHistoryProgress> {
  await initializeState(db);
  const [discoveryValue, tasksValue, taskValue, raceValue, failuresValue, storedRaces] = await Promise.all([
    getState(db, STATE_DISCOVERY_INDEX_KEY),
    getState(db, STATE_TASKS_KEY),
    getState(db, STATE_TASK_INDEX_KEY),
    getState(db, STATE_RACE_NO_KEY),
    getState(db, STATE_FAILURES_KEY),
    storedRaceCount(db)
  ]);
  const discoveryDates = integerState(discoveryValue);
  const tasks = parseJsonArray<HistoricalMeetingTask>(tasksValue);
  const taskIndex = integerState(taskValue);
  const raceNo = Math.max(1, integerState(raceValue, 1));
  const failures = parseJsonArray<FailedRace>(failuresValue);
  const discoveryComplete = discoveryDates >= THREE_MONTH_RACE_DATES.length;
  const importComplete = discoveryComplete && taskIndex >= tasks.length;
  const complete = importComplete && failures.length === 0;
  return {
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    phase: !discoveryComplete ? "discovery" : !importComplete ? "import" : failures.length > 0 ? "retry" : "complete",
    discoveryDates,
    totalDiscoveryDates: THREE_MONTH_RACE_DATES.length,
    meetingTasks: tasks.length,
    completedMeetingTasks: Math.min(taskIndex, tasks.length),
    nextRaceNo: raceNo,
    failedRaces: failures.length,
    storedRaces,
    complete
  };
}

async function discoverNextDate(db: D1Database): Promise<{ raceDate: string; meetings: HistoricalMeetingTask[] }> {
  const index = integerState(await getState(db, STATE_DISCOVERY_INDEX_KEY));
  const raceDate = THREE_MONTH_RACE_DATES[index];
  if (!raceDate) return { raceDate: THREE_MONTH_END_DATE, meetings: [] };
  const page = await fetchJraPage(calendarUrl(raceDate));
  const meetings = parseHistoricalMeetings(page.html, raceDate);
  if (meetings.length === 0) throw new Error(`HISTORY_MEETINGS_NOT_FOUND:${raceDate}`);
  const tasks = parseJsonArray<HistoricalMeetingTask>(await getState(db, STATE_TASKS_KEY));
  const byKey = new Map(tasks.map((task) => [`${task.raceDate}:${task.venue}`, task]));
  for (const meeting of meetings) byKey.set(`${meeting.raceDate}:${meeting.venue}`, meeting);
  await Promise.all([
    setState(db, STATE_TASKS_KEY, JSON.stringify([...byKey.values()])),
    setState(db, STATE_DISCOVERY_INDEX_KEY, String(index + 1))
  ]);
  return { raceDate, meetings };
}

function appendFailure(failures: FailedRace[], failure: FailedRace): FailedRace[] {
  const key = `${failure.raceDate}:${failure.venue}:${failure.raceNo}`;
  const next = failures.filter((item) => `${item.raceDate}:${item.venue}:${item.raceNo}` !== key);
  next.push(failure);
  return next;
}

async function importNextRaceBatch(db: D1Database): Promise<{
  task: HistoricalMeetingTask | null;
  raceNos: number[];
  imported: number;
  skipped: number;
  errors: number;
}> {
  const tasks = parseJsonArray<HistoricalMeetingTask>(await getState(db, STATE_TASKS_KEY));
  let taskIndex = integerState(await getState(db, STATE_TASK_INDEX_KEY));
  let raceNo = Math.max(1, integerState(await getState(db, STATE_RACE_NO_KEY), 1));
  const task = tasks[taskIndex] ?? null;
  if (!task) return { task: null, raceNos: [], imported: 0, skipped: 0, errors: 0 };

  const raceNos = Array.from(
    { length: Math.min(RACES_PER_BATCH, 13 - raceNo) },
    (_, index) => raceNo + index
  );
  let imported = 0;
  let skipped = 0;
  let errors = 0;
  let failures = parseJsonArray<FailedRace>(await getState(db, STATE_FAILURES_KEY));

  const results = await Promise.allSettled(raceNos.map((currentRaceNo) =>
    importHistoricalRace(db, task, currentRaceNo)
  ));
  results.forEach((result, index) => {
    const currentRaceNo = raceNos[index] ?? raceNo;
    if (result.status === "fulfilled") {
      imported += result.value.imported ? 1 : 0;
      skipped += result.value.skipped ? 1 : 0;
      return;
    }
    errors += 1;
    const message = result.reason instanceof Error ? result.reason.message : String(result.reason);
    failures = appendFailure(failures, { ...task, raceNo: currentRaceNo, attempts: 0, error: message });
  });

  raceNo += raceNos.length;
  if (raceNo > 12) {
    taskIndex += 1;
    raceNo = 1;
  }
  await Promise.all([
    setState(db, STATE_TASK_INDEX_KEY, String(taskIndex)),
    setState(db, STATE_RACE_NO_KEY, String(raceNo)),
    setState(db, STATE_FAILURES_KEY, JSON.stringify(failures))
  ]);
  return { task, raceNos, imported, skipped, errors };
}

async function retryOneFailure(db: D1Database): Promise<{
  retried: boolean;
  recovered: boolean;
  failure: FailedRace | null;
}> {
  const failures = parseJsonArray<FailedRace>(await getState(db, STATE_FAILURES_KEY));
  const failure = failures.shift() ?? null;
  if (!failure) return { retried: false, recovered: false, failure: null };
  try {
    await importHistoricalRace(db, failure, failure.raceNo);
    await setState(db, STATE_FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: true, failure };
  } catch (error) {
    const attempts = failure.attempts + 1;
    const message = error instanceof Error ? error.message : String(error);
    failures.push({ ...failure, attempts, error: message });
    await setState(db, STATE_FAILURES_KEY, JSON.stringify(failures));
    console.error("THREE_MONTH_HISTORY_RETRY_FAILED", failure, message);
    return { retried: true, recovered: false, failure: { ...failure, attempts, error: message } };
  }
}

export async function runThreeMonthHistoryStep(db: D1Database): Promise<unknown> {
  await initializeState(db);
  const before = await getThreeMonthHistoryProgress(db);
  let action: unknown;
  if (before.phase === "discovery") {
    action = { type: "discovery", ...(await discoverNextDate(db)) };
  } else if (before.phase === "import") {
    action = { type: "import", ...(await importNextRaceBatch(db)) };
  } else if (before.phase === "retry") {
    action = { type: "retry", ...(await retryOneFailure(db)) };
  } else {
    action = { type: "complete" };
  }
  return { action, progress: await getThreeMonthHistoryProgress(db) };
}
