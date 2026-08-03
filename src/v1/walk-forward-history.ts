import { getState, setState } from "./db.js";
import { getCompleteHistoryRaceIds, saveHistoryBundlePairsBatch, setHistoryStatesBatch } from "./history-batch-db.js";
import { fetchJraPage, pageLooksLikeResult, parseResultPage } from "./jra.js";
import { getArchiveResultUrls } from "./three-month-archive.js";
import { parseDesktopPayouts, parseDesktopResultRunners } from "./three-month-desktop.js";
import {
  WALK_FORWARD_ARCHIVE_MONTHS,
  WALK_FORWARD_CONTEXT_START_DATE,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_SCOPE_VERSION,
  isWalkForwardArchiveDate
} from "./walk-forward-scope.js";
import type { RaceBundle } from "./types.js";

const HISTORY_VERSION = `${WALK_FORWARD_SCOPE_VERSION}:official-search-v1`;
const STATE_PREFIX = `walk_forward_history:${WALK_FORWARD_SCOPE_VERSION}`;
const VERSION_KEY = `${STATE_PREFIX}:version`;
const MONTH_INDEX_KEY = `${STATE_PREFIX}:month_index`;
const URLS_KEY = `${STATE_PREFIX}:urls`;
const URL_INDEX_KEY = `${STATE_PREFIX}:url_index`;
const FAILURES_KEY = `${STATE_PREFIX}:failures`;
const PERMANENT_FAILURES_KEY = `${STATE_PREFIX}:permanent_failures`;
const LAST_BATCH_METRICS_KEY = `${STATE_PREFIX}:last_batch_metrics`;
const BATCH_SIZE = 4;
const FETCH_CONCURRENCY = 4;
const MAX_FAILURE_ATTEMPTS = 3;

interface FailedUrl { url: string; attempts: number; error: string }
interface PreparedImport { url: string; raceId: string; entry: RaceBundle; result: RaceBundle }
interface HistoryBatchMetrics {
  urls: number; prepared: number; imported: number; skipped: number; errors: number;
  dbStatements: number; fetchParseMs: number; completeCheckMs: number;
  dbPersistMs: number; statePersistMs: number; totalMs: number; concurrency: number;
}

export interface WalkForwardHistoryProgress {
  scopeVersion: string;
  phase: "discovery" | "import" | "retry" | "complete";
  discoveredMonths: number;
  totalMonths: number;
  resultUrls: number;
  importedUrls: number;
  failedUrls: number;
  permanentFailures: number;
  storedRaces: number;
  lastBatchMetrics: HistoryBatchMetrics | null;
  complete: boolean;
}

function integerState(value: string | null, fallback = 0): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : fallback;
}
function jsonArray<T>(value: string | null): T[] {
  if (!value) return [];
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed as T[] : []; } catch { return []; }
}
function jsonObject<T>(value: string | null): T | null {
  if (!value) return null;
  try { const parsed = JSON.parse(value); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as T : null; } catch { return null; }
}
function elapsedMs(startedAt: number): number { return Math.max(0, Math.round(performance.now() - startedAt)); }
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function cname(url: string): string {
  try { return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? ""); } catch { return ""; }
}
function archiveRaceDate(url: string): string | null {
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
  await setHistoryStatesBatch(db, [
    { key: VERSION_KEY, value: HISTORY_VERSION }, { key: MONTH_INDEX_KEY, value: "0" },
    { key: URLS_KEY, value: "[]" }, { key: URL_INDEX_KEY, value: "0" },
    { key: FAILURES_KEY, value: "[]" }, { key: PERMANENT_FAILURES_KEY, value: "[]" },
    { key: LAST_BATCH_METRICS_KEY, value: "null" }
  ]);
}

async function storedRaceCount(db: D1Database): Promise<number> {
  const row = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date BETWEEN ? AND ? AND status='finished'`)
    .bind(WALK_FORWARD_CONTEXT_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE).first<{ count: number }>();
  return Number(row?.count ?? 0);
}

export async function getWalkForwardHistoryProgress(db: D1Database): Promise<WalkForwardHistoryProgress> {
  await initialize(db);
  const [monthValue, urlsValue, indexValue, failuresValue, permanentValue, metricsValue, storedRaces] = await Promise.all([
    getState(db, MONTH_INDEX_KEY), getState(db, URLS_KEY), getState(db, URL_INDEX_KEY),
    getState(db, FAILURES_KEY), getState(db, PERMANENT_FAILURES_KEY), getState(db, LAST_BATCH_METRICS_KEY), storedRaceCount(db)
  ]);
  const monthIndex = integerState(monthValue);
  const urls = jsonArray<string>(urlsValue);
  const urlIndex = integerState(indexValue);
  const failures = jsonArray<FailedUrl>(failuresValue);
  const permanent = jsonArray<FailedUrl>(permanentValue);
  const discoveryComplete = monthIndex >= WALK_FORWARD_ARCHIVE_MONTHS.length;
  const importComplete = discoveryComplete && urlIndex >= urls.length;
  const complete = importComplete && failures.length === 0;
  return {
    scopeVersion: WALK_FORWARD_SCOPE_VERSION,
    phase: !discoveryComplete ? "discovery" : !importComplete ? "import" : failures.length ? "retry" : "complete",
    discoveredMonths: Math.min(monthIndex, WALK_FORWARD_ARCHIVE_MONTHS.length), totalMonths: WALK_FORWARD_ARCHIVE_MONTHS.length,
    resultUrls: urls.length, importedUrls: Math.min(urlIndex, urls.length), failedUrls: failures.length,
    permanentFailures: permanent.length, storedRaces, lastBatchMetrics: jsonObject<HistoryBatchMetrics>(metricsValue), complete
  };
}

async function discoverMonth(db: D1Database): Promise<unknown> {
  const monthIndex = integerState(await getState(db, MONTH_INDEX_KEY));
  const yearMonth = WALK_FORWARD_ARCHIVE_MONTHS[monthIndex];
  if (!yearMonth) return { yearMonth: null, discovered: 0, retained: 0 };
  const discovered = await getArchiveResultUrls(yearMonth);
  const retained = discovered.filter((url) => { const date = archiveRaceDate(url); return date !== null && isWalkForwardArchiveDate(date); });
  const merged = sortedUniqueUrls([...jsonArray<string>(await getState(db, URLS_KEY)), ...retained]);
  await setHistoryStatesBatch(db, [
    { key: URLS_KEY, value: JSON.stringify(merged) }, { key: MONTH_INDEX_KEY, value: String(monthIndex + 1) }
  ]);
  return { yearMonth, discovered: discovered.length, retained: retained.length, total: merged.length };
}

async function prepareImport(url: string): Promise<PreparedImport> {
  const page = await fetchJraPage(url);
  if (!pageLooksLikeResult(page.html)) throw new Error("WALK_FORWARD_RESULT_SIGNATURE_MISSING");
  const parsed = parseResultPage(page.html, page.url);
  if (!isWalkForwardArchiveDate(parsed.race.raceDate)) throw new Error(`WALK_FORWARD_OUT_OF_SCOPE:${parsed.race.raceDate}`);
  const runners = parseDesktopResultRunners(page.html);
  const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
  if (runners.filter((row) => row.runnerStatus === "active" && row.winOdds !== null).length < 2) throw new Error(`WALK_FORWARD_RUNNERS_NOT_FOUND:${runners.length}`);
  if (parsed.race.status !== "cancelled" && payouts.length === 0) throw new Error("WALK_FORWARD_PAYOUTS_NOT_FOUND");
  const result: RaceBundle = { ...parsed, payouts };
  const entry: RaceBundle = { race: { ...result.race, status: "scheduled" }, runners, results: [], payouts: [], refundHorseNos: [] };
  return { url, raceId: parsed.race.raceId, entry, result };
}

function replaceFailure(failures: FailedUrl[], failure: FailedUrl): FailedUrl[] {
  return [...failures.filter((row) => row.url !== failure.url), failure];
}

async function importBatch(db: D1Database): Promise<HistoryBatchMetrics> {
  const totalStartedAt = performance.now();
  const [urlsValue, indexValue, failuresValue] = await Promise.all([getState(db, URLS_KEY), getState(db, URL_INDEX_KEY), getState(db, FAILURES_KEY)]);
  const urls = jsonArray<string>(urlsValue);
  const index = integerState(indexValue);
  const batch = urls.slice(index, index + BATCH_SIZE);
  let failures = jsonArray<FailedUrl>(failuresValue);
  const metrics: HistoryBatchMetrics = {
    urls: batch.length, prepared: 0, imported: 0, skipped: 0, errors: 0, dbStatements: 0,
    fetchParseMs: 0, completeCheckMs: 0, dbPersistMs: 0, statePersistMs: 0, totalMs: 0, concurrency: FETCH_CONCURRENCY
  };
  if (batch.length === 0) {
    metrics.totalMs = elapsedMs(totalStartedAt);
    await setState(db, LAST_BATCH_METRICS_KEY, JSON.stringify(metrics));
    return metrics;
  }

  const fetchStartedAt = performance.now();
  const outcomes = await Promise.allSettled(batch.map((url) => prepareImport(url)));
  metrics.fetchParseMs = elapsedMs(fetchStartedAt);
  const prepared: PreparedImport[] = [];
  outcomes.forEach((outcome, position) => {
    const url = batch[position]!;
    if (outcome.status === "fulfilled") { prepared.push(outcome.value); metrics.prepared += 1; }
    else { metrics.errors += 1; failures = replaceFailure(failures, { url, attempts: 0, error: errorMessage(outcome.reason) }); }
  });

  if (prepared.length > 0) {
    const checkStartedAt = performance.now();
    const completeRaceIds = await getCompleteHistoryRaceIds(db, prepared.map((row) => row.raceId));
    metrics.completeCheckMs = elapsedMs(checkStartedAt);
    metrics.skipped = completeRaceIds.size;
    const pending = prepared.filter((row) => !completeRaceIds.has(row.raceId));
    if (pending.length > 0) {
      const persistStartedAt = performance.now();
      try {
        const persisted = await saveHistoryBundlePairsBatch(db, pending.map((row) => ({ entry: row.entry, result: row.result })));
        metrics.imported = persisted.races;
        metrics.dbStatements = persisted.statements;
      } catch (error) {
        metrics.errors += pending.length;
        for (const row of pending) failures = replaceFailure(failures, { url: row.url, attempts: 0, error: errorMessage(error) });
      }
      metrics.dbPersistMs = elapsedMs(persistStartedAt);
    }
  }

  const stateStartedAt = performance.now();
  metrics.totalMs = elapsedMs(totalStartedAt);
  await setHistoryStatesBatch(db, [
    { key: URL_INDEX_KEY, value: String(index + batch.length) },
    { key: FAILURES_KEY, value: JSON.stringify(failures) },
    { key: LAST_BATCH_METRICS_KEY, value: JSON.stringify(metrics) }
  ]);
  metrics.statePersistMs = elapsedMs(stateStartedAt);
  metrics.totalMs = elapsedMs(totalStartedAt);
  return metrics;
}

async function retryFailure(db: D1Database): Promise<unknown> {
  const failures = jsonArray<FailedUrl>(await getState(db, FAILURES_KEY));
  const failure = failures.shift();
  if (!failure) return { retried: false };
  try {
    const prepared = await prepareImport(failure.url);
    const complete = await getCompleteHistoryRaceIds(db, [prepared.raceId]);
    if (!complete.has(prepared.raceId)) await saveHistoryBundlePairsBatch(db, [{ entry: prepared.entry, result: prepared.result }]);
    await setState(db, FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: true, url: failure.url };
  } catch (error) {
    const next = { ...failure, attempts: failure.attempts + 1, error: errorMessage(error) };
    if (next.attempts >= MAX_FAILURE_ATTEMPTS) {
      const permanent = jsonArray<FailedUrl>(await getState(db, PERMANENT_FAILURES_KEY));
      permanent.push(next);
      await setHistoryStatesBatch(db, [
        { key: FAILURES_KEY, value: JSON.stringify(failures) }, { key: PERMANENT_FAILURES_KEY, value: JSON.stringify(permanent) }
      ]);
      return { retried: true, recovered: false, permanent: true, failure: next };
    }
    failures.push(next);
    await setState(db, FAILURES_KEY, JSON.stringify(failures));
    return { retried: true, recovered: false, permanent: false, failure: next };
  }
}

export async function runWalkForwardHistoryStep(db: D1Database): Promise<unknown> {
  await initialize(db);
  const before = await getWalkForwardHistoryProgress(db);
  const action = before.phase === "discovery"
    ? { type: "official-search", ...(await discoverMonth(db) as object) }
    : before.phase === "import"
      ? { type: "official-import", ...(await importBatch(db) as object) }
      : before.phase === "retry"
        ? { type: "official-retry", ...(await retryFailure(db) as object) }
        : { type: "complete" };
  return { action, progress: await getWalkForwardHistoryProgress(db) };
}
