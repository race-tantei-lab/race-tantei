import type { Env, RaceRecord } from "./v1/types.js";
import {
  beginSyncRun,
  ensureSchema,
  finishSyncRun,
  getDueRaceSources,
  getState,
  resetRaceSourcesForDiscoveryRevision,
  saveEntryBundle,
  saveResultBundle,
  setState,
  updateRaceSource,
  upsertRaceSources
} from "./v1/db.js";
import {
  discoverRaceUrls,
  fetchJraPage,
  pageLooksLikeEntry,
  pageLooksLikeResult,
  parseEntryPage,
  parseResultPage,
  toResultUrl
} from "./v1/jra.js";
import { isJstEntryWindow, isJstRaceWindow, nowIso, positiveInt } from "./v1/utils.js";

const DISCOVERY_REVISION = "2026-08-09-public-data-only-v1";
const SYNC_LOCK_KEY = "public_data_sync_lock_until";
let schemaReady: Promise<void> | null = null;
let inMemorySync: Promise<unknown> | null = null;

function ready(db: D1Database): Promise<void> {
  schemaReady ??= ensureSchema(db).catch((error) => {
    schemaReady = null;
    throw error;
  });
  return schemaReady;
}

function addMinutes(date: Date, minutes: number): string {
  return new Date(date.getTime() + minutes * 60_000).toISOString();
}

function seeds(env: Env): string[] {
  return env.JRA_SEED_ENTRY_URLS.split(",").map((value) => value.trim()).filter(Boolean);
}

async function shouldDiscover(env: Env, now: Date): Promise<boolean> {
  const revision = await getState(env.DB, "public_data_last_discovery_revision");
  if (revision !== DISCOVERY_REVISION) return true;
  const last = await getState(env.DB, "public_data_last_discovery_at");
  if (!last) return true;
  const lastMs = new Date(last).getTime();
  if (!Number.isFinite(lastMs)) return true;
  const elapsedMinutes = (now.getTime() - lastMs) / 60_000;
  if (!isJstEntryWindow(now)) return elapsedMinutes >= 24 * 60;
  return elapsedMinutes >= (isJstRaceWindow(now) ? 20 : 90);
}

function nextEntryFetch(race: RaceRecord, now: Date): string {
  if (!race.startTimeUtc) return addMinutes(now, 60);
  const deltaMinutes = (new Date(race.startTimeUtc).getTime() - now.getTime()) / 60_000;
  if (deltaMinutes > 24 * 60) return addMinutes(now, 180);
  if (deltaMinutes > 180) return addMinutes(now, 60);
  if (deltaMinutes > 45) return addMinutes(now, 15);
  if (deltaMinutes > 0) return addMinutes(now, 5);
  return addMinutes(now, 8);
}

function hasResultUrl(url: string): boolean {
  return /\/JRADB\/accessS\.html/i.test(url) && /(?:pw|sw)01sde/i.test(decodeURIComponent(url));
}

async function processSource(
  env: Env,
  source: Awaited<ReturnType<typeof getDueRaceSources>>[number],
  now: Date
): Promise<boolean> {
  try {
    const entryPage = await fetchJraPage(source.entryUrl);
    if (!pageLooksLikeEntry(entryPage.html)) throw new Error("ENTRY_PAGE_SIGNATURE_MISSING");
    const entry = parseEntryPage(entryPage.html, entryPage.url);
    await saveEntryBundle(env.DB, entry);

    const startMs = entry.race.startTimeUtc ? new Date(entry.race.startTimeUtc).getTime() : Number.POSITIVE_INFINITY;
    const resultDue = now.getTime() >= startMs + 4 * 60_000;
    if (!resultDue) {
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "active",
        nextFetchAt: nextEntryFetch(entry.race, now),
        entryFetched: true,
        error: null
      });
      return true;
    }

    try {
      if (!hasResultUrl(entry.race.resultUrl)) throw new Error("RESULT_URL_NOT_READY");
      const resultPage = await fetchJraPage(entry.race.resultUrl);
      if (!pageLooksLikeResult(resultPage.html)) throw new Error("RESULT_NOT_READY");
      const result = parseResultPage(resultPage.html, resultPage.url);
      if (result.race.raceId !== entry.race.raceId) throw new Error("RACE_ID_MISMATCH");
      await saveResultBundle(env.DB, result);
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "complete",
        nextFetchAt: addMinutes(now, 7 * 24 * 60),
        entryFetched: true,
        resultFetched: true,
        error: null
      });
      return true;
    } catch (resultError) {
      const message = resultError instanceof Error ? resultError.message : String(resultError);
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "awaiting_result",
        nextFetchAt: addMinutes(now, message === "RESULT_URL_NOT_READY" ? 5 : 10),
        entryFetched: true,
        error: message
      });
      return message === "RESULT_NOT_READY" || message === "RESULT_URL_NOT_READY";
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const delay = Math.min(240, 15 * Math.pow(2, Math.min(4, source.failureCount)));
    await updateRaceSource(env.DB, source.entryUrl, {
      raceId: source.raceId,
      status: "discovered",
      nextFetchAt: addMinutes(now, delay),
      error: message
    });
    return false;
  }
}

async function acquireSyncLock(env: Env, now: Date): Promise<boolean> {
  const lock = await getState(env.DB, SYNC_LOCK_KEY);
  const lockMs = lock ? new Date(lock).getTime() : 0;
  if (Number.isFinite(lockMs) && lockMs > now.getTime()) return false;
  await setState(env.DB, SYNC_LOCK_KEY, addMinutes(now, 4));
  return true;
}

async function executeSync(env: Env, triggerType: "cron" | "manual"): Promise<unknown> {
  await ready(env.DB);
  const now = new Date();
  if (!(await acquireSyncLock(env, now))) return { ok: true, skipped: "SYNC_ALREADY_RUNNING", now: nowIso() };

  const runId = await beginSyncRun(env.DB, triggerType);
  let discovered = 0;
  let processed = 0;
  let success = 0;
  let errors = 0;
  let discoveryError: string | null = null;
  let fatal: string | undefined;

  try {
    if (await shouldDiscover(env, now)) {
      try {
        const previousRevision = await getState(env.DB, "public_data_last_discovery_revision");
        if (previousRevision !== DISCOVERY_REVISION) await resetRaceSourcesForDiscoveryRevision(env.DB);
        const urls = await discoverRaceUrls(env.JRA_HOME_URL, seeds(env));
        discovered = urls.length;
        await upsertRaceSources(env.DB, urls, toResultUrl);
        await setState(env.DB, "public_data_last_discovery_at", nowIso());
        await setState(env.DB, "public_data_last_discovery_count", String(urls.length));
        await setState(env.DB, "public_data_last_discovery_revision", DISCOVERY_REVISION);
        await setState(env.DB, "public_data_last_discovery_error", "");
      } catch (error) {
        discoveryError = error instanceof Error ? error.message : String(error);
        errors += 1;
        await setState(env.DB, "public_data_last_discovery_error", discoveryError);
      }
    }

    const due = await getDueRaceSources(env.DB, positiveInt(env.SYNC_BATCH_SIZE, 12));
    processed = due.length;
    for (const source of due) {
      const ok = await processSource(env, source, now);
      if (ok) success += 1;
      else errors += 1;
    }
    await setState(env.DB, "public_data_last_successful_cycle_at", nowIso());
    await setState(env.DB, "public_data_last_cycle_error", discoveryError ?? "");
  } catch (error) {
    fatal = error instanceof Error ? error.message : String(error);
    errors += 1;
    await setState(env.DB, "public_data_last_cycle_error", fatal);
  } finally {
    await finishSyncRun(env.DB, runId, fatal
      ? { discovered, processed, success, errors, errorMessage: fatal }
      : { discovered, processed, success, errors, ...(discoveryError ? { errorMessage: discoveryError } : {}) });
    await setState(env.DB, SYNC_LOCK_KEY, new Date(0).toISOString());
  }

  return { ok: !fatal, discovered, processed, success, errors, discoveryError, error: fatal ?? null, now: nowIso() };
}

export function runPublicDataSync(env: Env, triggerType: "cron" | "manual"): Promise<unknown> {
  if (inMemorySync) return inMemorySync;
  inMemorySync = executeSync(env, triggerType).finally(() => { inMemorySync = null; });
  return inMemorySync;
}
