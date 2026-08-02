import {
  getState,
  saveEntryBundle,
  saveResultBundle,
  setState
} from "./db.js";
import {
  fetchJraPage,
  pageLooksLikeEntry,
  pageLooksLikeResult,
  parseEntryPage,
  parseResultPage
} from "./jra.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE
} from "./three-month-scope.js";
import { stripHtml } from "./utils.js";

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

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function jraDbUrl(task: HistoricalMeetingTask, raceNo: number, kind: "entry" | "result"): string {
  const venueCode = VENUE_CODES[task.venue];
  if (!venueCode) throw new Error(`UNKNOWN_VENUE:${task.venue}`);
  const ymd = task.raceDate.replace(/-/g, "");
  const year = task.raceDate.slice(0, 4);
  const pageKind = kind === "entry" ? "dde" : "sde";
  const cname = `sw01${pageKind}01${venueCode}${year}${pad2(task.meetingNo)}${pad2(task.meetingDay)}${pad2(raceNo)}${ymd}/00`;
  const path = kind === "entry" ? "accessD.html" : "accessS.html";
  return `https://sp.jra.jp/JRADB/${path}?CNAME=${encodeURIComponent(cname)}`;
}

async function alreadyComplete(db: D1Database, task: HistoricalMeetingTask, raceNo: number): Promise<boolean> {
  const row = await db.prepare(`
    SELECT r.status,
      (SELECT COUNT(*) FROM rt_runners rr WHERE rr.race_id=r.race_id AND rr.runner_status='active') AS runners,
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

  const entryUrl = jraDbUrl(task, raceNo, "entry");
  const resultUrl = jraDbUrl(task, raceNo, "result");
  const [entryPage, resultPage] = await Promise.all([
    fetchJraPage(entryUrl),
    fetchJraPage(resultUrl)
  ]);
  if (!pageLooksLikeEntry(entryPage.html)) throw new Error("HISTORY_ENTRY_SIGNATURE_MISSING");
  if (!pageLooksLikeResult(resultPage.html)) throw new Error("HISTORY_RESULT_SIGNATURE_MISSING");

  const entry = parseEntryPage(entryPage.html, entryPage.url);
  const result = parseResultPage(resultPage.html, resultPage.url);
  if (entry.race.raceDate !== task.raceDate || entry.race.venue !== task.venue || entry.race.raceNo !== raceNo) {
    throw new Error(`ENTRY_RACE_MISMATCH:${entry.race.raceDate}:${entry.race.venue}:${entry.race.raceNo}`);
  }
  if (result.race.raceId !== entry.race.raceId) throw new Error("HISTORY_RACE_ID_MISMATCH");

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
  abandoned: boolean;
  failure: FailedRace | null;
}> {
  const failures = parseJsonArray<FailedRace>(await getState(db, STATE_FAILURES_KEY));
  const failure = failures.shift() ?? null;
  if (!failure) return { retried: false, recovered: false, abandoned: false, failure: null };
  try {
    await importHistoricalRace(db, failure, failure.raceNo);
    await setState(db, STATE_FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: true, abandoned: false, failure };
  } catch (error) {
    const attempts = failure.attempts + 1;
    const message = error instanceof Error ? error.message : String(error);
    const abandoned = attempts >= 3;
    if (!abandoned) failures.push({ ...failure, attempts, error: message });
    await setState(db, STATE_FAILURES_KEY, JSON.stringify(failures));
    console.error("THREE_MONTH_HISTORY_RETRY_FAILED", failure, message);
    return { retried: true, recovered: false, abandoned, failure: { ...failure, attempts, error: message } };
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
