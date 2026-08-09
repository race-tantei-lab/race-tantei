import type { Env, RaceRecord } from "./v1/types.js";
import {
  beginSyncRun,
  ensureSchema,
  finishSyncRun,
  getDueRaceSources,
  getRace,
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

const DISCOVERY_REVISION = "2026-08-09-public-data-only-v2";
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
  return addMinutes(now, 5);
}

function hasResultUrl(url: string): boolean {
  return /\/JRADB\/accessS\.html/i.test(url) && /(?:pw|sw)01sde/i.test(decodeURIComponent(url));
}

function resultUrlCandidates(race: RaceRecord, sourceResultUrl: string, entryUrl: string): string[] {
  const candidates = [race.resultUrl, sourceResultUrl];
  try { candidates.push(toResultUrl(entryUrl)); } catch { /* invalid source URL is handled by the normal retry path */ }
  return [...new Set(candidates.filter((value): value is string => Boolean(value) && hasResultUrl(value)))];
}

function canonicalCombination(betType: string, combination: string): string {
  const numbers = (combination.match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(betType)) numbers.sort((a, b) => a - b);
  return numbers.join("-");
}

async function settlePublicBetsFromResult(env: Env, result: Awaited<ReturnType<typeof parseResultPage>>): Promise<void> {
  try {
    const pending = await env.DB.prepare(`
      SELECT id,bet_type AS betType,combination,stake_yen AS stakeYen
      FROM rt_public_bets
      WHERE race_id=? AND settlement_status='pending'
      ORDER BY id
    `).bind(result.race.raceId).all<{ id: number; betType: string; combination: string; stakeYen: number }>();
    if (!pending.results.length) return;

    const payoutTypes = new Set(result.payouts.map((payout) => payout.betType));
    const payoutMap = new Map(result.payouts.map((payout) => [
      `${payout.betType}:${canonicalCombination(payout.betType, payout.combination)}`,
      Number(payout.payoutYen)
    ]));
    const refunds = new Set(result.refundHorseNos.map(Number));
    const updates = [];

    for (const bet of pending.results) {
      const horses = (bet.combination.match(/\d{1,2}/g) ?? []).map(Number);
      let returnYen: number | null = null;
      if (horses.some((horseNo) => refunds.has(horseNo))) {
        returnYen = Number(bet.stakeYen);
      } else if (payoutTypes.has(bet.betType)) {
        const payout = payoutMap.get(`${bet.betType}:${canonicalCombination(bet.betType, bet.combination)}`) ?? 0;
        returnYen = Math.round((Number(bet.stakeYen) / 100) * payout);
      }
      if (returnYen !== null) {
        updates.push(env.DB.prepare(`
          UPDATE rt_public_bets
          SET settlement_status='settled',return_yen=?
          WHERE id=? AND settlement_status='pending'
        `).bind(returnYen, bet.id));
      }
    }
    if (updates.length) await env.DB.batch(updates);
  } catch {
    // Public history may not be initialized yet. The normal settlement layer will retry later.
  }
}

async function loadRaceForSync(
  env: Env,
  source: Awaited<ReturnType<typeof getDueRaceSources>>[number]
): Promise<{ race: RaceRecord; entryFetched: boolean; entryError: string | null }> {
  try {
    const entryPage = await fetchJraPage(source.entryUrl);
    if (!pageLooksLikeEntry(entryPage.html)) throw new Error("ENTRY_PAGE_SIGNATURE_MISSING");
    const entry = parseEntryPage(entryPage.html, entryPage.url);
    await saveEntryBundle(env.DB, entry);
    return { race: entry.race, entryFetched: true, entryError: null };
  } catch (error) {
    const entryError = error instanceof Error ? error.message : String(error);
    if (!source.raceId) throw error;
    const stored = await getRace(env.DB, source.raceId);
    if (!stored) throw error;
    return { race: stored, entryFetched: false, entryError };
  }
}

async function processSource(
  env: Env,
  source: Awaited<ReturnType<typeof getDueRaceSources>>[number],
  now: Date
): Promise<boolean> {
  try {
    const loaded = await loadRaceForSync(env, source);
    const race = loaded.race;
    const startMs = race.startTimeUtc ? new Date(race.startTimeUtc).getTime() : Number.POSITIVE_INFINITY;
    const resultDue = now.getTime() >= startMs + 4 * 60_000;

    if (!resultDue) {
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: race.raceId,
        status: "active",
        nextFetchAt: loaded.entryError ? addMinutes(now, 5) : nextEntryFetch(race, now),
        entryFetched: loaded.entryFetched,
        error: loaded.entryError
      });
      return !loaded.entryError;
    }

    const candidates = resultUrlCandidates(race, source.resultUrl, source.entryUrl);
    const errors: string[] = [];
    for (const candidate of candidates) {
      try {
        const resultPage = await fetchJraPage(candidate);
        if (!pageLooksLikeResult(resultPage.html)) throw new Error("RESULT_PAGE_SIGNATURE_MISSING");
        const result = parseResultPage(resultPage.html, resultPage.url);
        if (result.race.raceId !== race.raceId) throw new Error(`RACE_ID_MISMATCH:${result.race.raceId}`);
        await saveResultBundle(env.DB, result);
        await settlePublicBetsFromResult(env, result);
        await updateRaceSource(env.DB, source.entryUrl, {
          raceId: race.raceId,
          status: "complete",
          nextFetchAt: addMinutes(now, 7 * 24 * 60),
          entryFetched: loaded.entryFetched,
          resultFetched: true,
          error: null
        });
        return true;
      } catch (error) {
        errors.push(error instanceof Error ? error.message : String(error));
      }
    }

    const resultError = candidates.length
      ? `RESULT_FETCH_FAILED:${[...new Set(errors)].join("|")}`
      : "RESULT_URL_NOT_READY";
    await updateRaceSource(env.DB, source.entryUrl, {
      raceId: race.raceId,
      status: "awaiting_result",
      nextFetchAt: addMinutes(now, 3),
      entryFetched: loaded.entryFetched,
      error: loaded.entryError ? `${loaded.entryError}|${resultError}` : resultError
    });
    return false;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const delay = Math.min(120, 10 * Math.pow(2, Math.min(3, source.failureCount)));
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
