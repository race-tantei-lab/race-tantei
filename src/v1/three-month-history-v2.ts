import { getState, saveEntryBundle, saveResultBundle, setState } from "./db.js";
import { fetchJraPage, pageLooksLikeResult, parseResultPage } from "./jra.js";
import { getArchiveResultUrls } from "./three-month-archive.js";
import { parseDesktopPayouts, parseDesktopResultRunners } from "./three-month-desktop.js";
import {
  THREE_MONTH_END_DATE,
  THREE_MONTH_RACE_DATES,
  THREE_MONTH_SCOPE_VERSION,
  THREE_MONTH_START_DATE
} from "./three-month-scope.js";
import type { RaceBundle } from "./types.js";

const HISTORY_VERSION = `${THREE_MONTH_SCOPE_VERSION}:official-search-v2`;
const STATE_PREFIX = `three_month_history:${THREE_MONTH_SCOPE_VERSION}:official_search_v2`;
const VERSION_KEY = `${STATE_PREFIX}:version`;
const MONTH_INDEX_KEY = `${STATE_PREFIX}:month_index`;
const URLS_KEY = `${STATE_PREFIX}:urls`;
const URL_INDEX_KEY = `${STATE_PREFIX}:url_index`;
const FAILURES_KEY = `${STATE_PREFIX}:failures`;
const MONTHS = ["202605", "202606", "202607", "202608"] as const;
const TARGET_DATES = new Set<string>(THREE_MONTH_RACE_DATES);
const BATCH_SIZE = 4;

interface FailedUrl {
  url: string;
  attempts: number;
  error: string;
}

export interface ThreeMonthHistoryProgressV2 {
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

function jsonArray<T>(value: string | null): T[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed as T[] : [];
  } catch {
    return [];
  }
}

function cname(url: string): string {
  try {
    return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "");
  } catch {
    return "";
  }
}

export function archiveRaceDate(url: string): string | null {
  const match = cname(url).match(/(20\d{6})\/[0-9A-F]{2}$/i);
  if (!match?.[1]) return null;
  const raw = match[1];
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

function sortedUniqueUrls(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) => {
    const dateOrder = (archiveRaceDate(a) ?? "").localeCompare(archiveRaceDate(b) ?? "");
    return dateOrder !== 0 ? dateOrder : cname(a).localeCompare(cname(b));
  });
}

async function initialize(db: D1Database): Promise<void> {
  if (await getState(db, VERSION_KEY) === HISTORY_VERSION) return;
  await Promise.all([
    setState(db, VERSION_KEY, HISTORY_VERSION),
    setState(db, MONTH_INDEX_KEY, "0"),
    setState(db, URLS_KEY, "[]"),
    setState(db, URL_INDEX_KEY, "0"),
    setState(db, FAILURES_KEY, "[]")
  ]);
}

async function storedRaceCount(db: D1Database): Promise<number> {
  const row = await db.prepare(`
    SELECT COUNT(*) AS count FROM rt_races
    WHERE race_date BETWEEN ? AND ? AND status='finished'
  `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).first<{ count: number }>();
  return Number(row?.count ?? 0);
}

export async function getThreeMonthHistoryProgressV2(db: D1Database): Promise<ThreeMonthHistoryProgressV2> {
  await initialize(db);
  const [monthValue, urlsValue, indexValue, failuresValue, storedRaces] = await Promise.all([
    getState(db, MONTH_INDEX_KEY),
    getState(db, URLS_KEY),
    getState(db, URL_INDEX_KEY),
    getState(db, FAILURES_KEY),
    storedRaceCount(db)
  ]);
  const monthIndex = integerState(monthValue);
  const urls = jsonArray<string>(urlsValue);
  const urlIndex = integerState(indexValue);
  const failures = jsonArray<FailedUrl>(failuresValue);
  const discoveryComplete = monthIndex >= MONTHS.length;
  const importComplete = discoveryComplete && urlIndex >= urls.length;
  const complete = importComplete && failures.length === 0;
  return {
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    phase: !discoveryComplete ? "discovery" : !importComplete ? "import" : failures.length ? "retry" : "complete",
    discoveryDates: Math.min(monthIndex, MONTHS.length),
    totalDiscoveryDates: MONTHS.length,
    meetingTasks: urls.length,
    completedMeetingTasks: Math.min(urlIndex, urls.length),
    nextRaceNo: 1,
    failedRaces: failures.length,
    storedRaces,
    complete
  };
}

async function discoverMonth(db: D1Database): Promise<unknown> {
  const monthIndex = integerState(await getState(db, MONTH_INDEX_KEY));
  const yearMonth = MONTHS[monthIndex];
  if (!yearMonth) return { yearMonth: null, discovered: 0, retained: 0 };
  const discovered = await getArchiveResultUrls(yearMonth);
  const retained = discovered.filter((url) => {
    const date = archiveRaceDate(url);
    return date !== null && TARGET_DATES.has(date);
  });
  const current = jsonArray<string>(await getState(db, URLS_KEY));
  const merged = sortedUniqueUrls([...current, ...retained]);
  await Promise.all([
    setState(db, URLS_KEY, JSON.stringify(merged)),
    setState(db, MONTH_INDEX_KEY, String(monthIndex + 1))
  ]);
  return { yearMonth, discovered: discovered.length, retained: retained.length, total: merged.length };
}

async function alreadyComplete(db: D1Database, raceId: string): Promise<boolean> {
  const row = await db.prepare(`
    SELECT r.status,
      (SELECT COUNT(*) FROM rt_runners x WHERE x.race_id=r.race_id AND x.runner_status='active' AND x.win_odds IS NOT NULL) AS runners,
      (SELECT COUNT(*) FROM rt_results x WHERE x.race_id=r.race_id) AS results,
      (SELECT COUNT(*) FROM rt_payouts x WHERE x.race_id=r.race_id) AS payouts
    FROM rt_races r WHERE r.race_id=?
  `).bind(raceId).first<{ status: string; runners: number; results: number; payouts: number }>();
  return row?.status === "finished"
    && Number(row.runners ?? 0) >= 2
    && Number(row.results ?? 0) >= 2
    && Number(row.payouts ?? 0) >= 1;
}

async function importUrl(db: D1Database, url: string): Promise<{ imported: boolean; skipped: boolean }> {
  const page = await fetchJraPage(url);
  if (!pageLooksLikeResult(page.html)) throw new Error("HISTORY_RESULT_SIGNATURE_MISSING");

  const parsed = parseResultPage(page.html, page.url);
  if (!TARGET_DATES.has(parsed.race.raceDate)) throw new Error(`OUT_OF_SCOPE_RESULT:${parsed.race.raceDate}`);
  if (await alreadyComplete(db, parsed.race.raceId)) return { imported: false, skipped: true };

  const runners = parseDesktopResultRunners(page.html);
  const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
  if (runners.filter((row) => row.runnerStatus === "active" && row.winOdds !== null).length < 2) {
    throw new Error(`HISTORY_RUNNERS_NOT_FOUND:${runners.length}`);
  }
  if (parsed.race.status !== "cancelled" && payouts.length === 0) {
    throw new Error("HISTORY_PAYOUTS_NOT_FOUND");
  }

  const result: RaceBundle = { ...parsed, payouts };
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

function replaceFailure(failures: FailedUrl[], failure: FailedUrl): FailedUrl[] {
  return [...failures.filter((row) => row.url !== failure.url), failure];
}

async function importBatch(db: D1Database): Promise<unknown> {
  const urls = jsonArray<string>(await getState(db, URLS_KEY));
  let index = integerState(await getState(db, URL_INDEX_KEY));
  const batch = urls.slice(index, index + BATCH_SIZE);
  if (!batch.length) return { urls: [], imported: 0, skipped: 0, errors: 0 };
  let imported = 0;
  let skipped = 0;
  let errors = 0;
  let failures = jsonArray<FailedUrl>(await getState(db, FAILURES_KEY));
  const results = await Promise.allSettled(batch.map((url) => importUrl(db, url)));
  results.forEach((result, position) => {
    const url = batch[position]!;
    if (result.status === "fulfilled") {
      imported += result.value.imported ? 1 : 0;
      skipped += result.value.skipped ? 1 : 0;
    } else {
      errors += 1;
      failures = replaceFailure(failures, {
        url,
        attempts: 0,
        error: result.reason instanceof Error ? result.reason.message : String(result.reason)
      });
    }
  });
  index += batch.length;
  await Promise.all([
    setState(db, URL_INDEX_KEY, String(index)),
    setState(db, FAILURES_KEY, JSON.stringify(failures))
  ]);
  return { urls: batch, imported, skipped, errors };
}

async function retryFailure(db: D1Database): Promise<unknown> {
  const failures = jsonArray<FailedUrl>(await getState(db, FAILURES_KEY));
  const failure = failures.shift();
  if (!failure) return { retried: false };
  try {
    await importUrl(db, failure.url);
    await setState(db, FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: true, url: failure.url };
  } catch (error) {
    const next = {
      ...failure,
      attempts: failure.attempts + 1,
      error: error instanceof Error ? error.message : String(error)
    };
    failures.push(next);
    await setState(db, FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: false, failure: next };
  }
}

export async function runThreeMonthHistoryStepV2(db: D1Database): Promise<unknown> {
  await initialize(db);
  const before = await getThreeMonthHistoryProgressV2(db);
  const action = before.phase === "discovery"
    ? { type: "official-search", ...(await discoverMonth(db) as object) }
    : before.phase === "import"
      ? { type: "official-import", ...(await importBatch(db) as object) }
      : before.phase === "retry"
        ? { type: "official-retry", ...(await retryFailure(db) as object) }
        : { type: "complete" };
  return { action, progress: await getThreeMonthHistoryProgressV2(db) };
}
