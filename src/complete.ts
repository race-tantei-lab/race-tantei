import type { Env, RaceRecord } from "./v1/types.js";
import {
  beginSyncRun,
  ensureSchema,
  finishSyncRun,
  getDashboardMetrics,
  getDueRaceSources,
  getLatestRaces,
  getPerformanceRows,
  getRace,
  getRaceDetail,
  getRunnerHistoryStats,
  getRunners,
  getState,
  getSystemSnapshot,
  saveEntryBundle,
  savePrediction,
  saveResultBundle,
  setState,
  settleRace,
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
import { generatePrediction } from "./v1/model.js";
import {
  renderHome,
  renderMethodology,
  renderNotFound,
  renderPerformance,
  renderRace,
  renderSystem
} from "./v1/ui.js";
import { isJstEntryWindow, isJstRaceWindow, nowIso, positiveInt, positiveNumber } from "./v1/utils.js";

let schemaReady: Promise<void> | null = null;

function ready(db: D1Database): Promise<void> {
  schemaReady ??= ensureSchema(db).catch((error) => {
    schemaReady = null;
    throw error;
  });
  return schemaReady;
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

function html(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
      "x-frame-options": "DENY",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

function authorized(request: Request, env: Env): boolean {
  return Boolean(env.ADMIN_TOKEN) && request.headers.get("authorization") === `Bearer ${env.ADMIN_TOKEN}`;
}

function addMinutes(date: Date, minutes: number): string {
  return new Date(date.getTime() + minutes * 60_000).toISOString();
}

function nextEntryFetch(race: RaceRecord, now: Date): string {
  if (!race.startTimeUtc) return addMinutes(now, 60);
  const deltaMinutes = (new Date(race.startTimeUtc).getTime() - now.getTime()) / 60_000;
  if (deltaMinutes > 24 * 60) return addMinutes(now, 180);
  if (deltaMinutes > 120) return addMinutes(now, 45);
  if (deltaMinutes > 30) return addMinutes(now, 15);
  if (deltaMinutes > 0) return addMinutes(now, 5);
  return addMinutes(now, 8);
}

function seeds(env: Env): string[] {
  return env.JRA_SEED_ENTRY_URLS.split(",").map((value) => value.trim()).filter(Boolean);
}

async function shouldDiscover(env: Env, now: Date): Promise<boolean> {
  if (!isJstEntryWindow(now)) return false;
  const last = await getState(env.DB, "last_discovery_at");
  if (!last) return true;
  const elapsedMinutes = (now.getTime() - new Date(last).getTime()) / 60_000;
  return elapsedMinutes >= (isJstRaceWindow(now) ? 30 : 120);
}

async function updatePrediction(env: Env, race: RaceRecord, now: Date): Promise<void> {
  if (!race.startTimeUtc || race.status === "finished") return;
  const minutesToStart = (new Date(race.startTimeUtc).getTime() - now.getTime()) / 60_000;
  if (minutesToStart <= 0 || minutesToStart > 180) return;
  const runners = await getRunners(env.DB, race.raceId);
  if (runners.filter((runner) => runner.runnerStatus === "active").length < 2) return;
  const history = await getRunnerHistoryStats(env.DB, race, runners);
  const minEv = positiveNumber(env.MIN_EXPECTED_VALUE, 108);
  const budget = positiveInt(env.MAX_RACE_BUDGET_YEN, 2000);
  const prediction = generatePrediction(race, runners, history, env.MODEL_VERSION, minEv, budget);
  const status = minutesToStart <= 15 ? "locked" : "draft";
  if (status === "draft") prediction.bets = [];
  await savePrediction(env.DB, race.raceId, prediction, status);
}

async function processSource(env: Env, source: Awaited<ReturnType<typeof getDueRaceSources>>[number], now: Date): Promise<boolean> {
  try {
    const entryPage = await fetchJraPage(source.entryUrl);
    if (!pageLooksLikeEntry(entryPage.html)) throw new Error("ENTRY_PAGE_SIGNATURE_MISSING");
    const entry = parseEntryPage(entryPage.html, entryPage.url);
    await saveEntryBundle(env.DB, entry);
    await updatePrediction(env, entry.race, now);

    const startMs = entry.race.startTimeUtc ? new Date(entry.race.startTimeUtc).getTime() : Number.POSITIVE_INFINITY;
    const resultDue = now.getTime() >= startMs + 5 * 60_000;
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
      const resultPage = await fetchJraPage(source.resultUrl || toResultUrl(source.entryUrl));
      if (!pageLooksLikeResult(resultPage.html)) throw new Error("RESULT_NOT_READY");
      const result = parseResultPage(resultPage.html, resultPage.url);
      if (result.race.raceId !== entry.race.raceId) throw new Error("RACE_ID_MISMATCH");
      await saveResultBundle(env.DB, result);
      await settleRace(env.DB, entry.race.raceId);
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "complete",
        nextFetchAt: addMinutes(now, 24 * 60),
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
        nextFetchAt: addMinutes(now, 10),
        entryFetched: true,
        error: message
      });
      return message === "RESULT_NOT_READY";
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const delay = Math.min(240, 20 * Math.pow(2, Math.min(3, source.failureCount)));
    await updateRaceSource(env.DB, source.entryUrl, {
      raceId: source.raceId,
      status: "discovered",
      nextFetchAt: addMinutes(now, delay),
      error: message
    });
    return false;
  }
}

export async function runSync(env: Env, triggerType: "cron" | "manual" | "deploy"): Promise<unknown> {
  await ready(env.DB);
  const now = new Date();
  const runId = await beginSyncRun(env.DB, triggerType);
  let discovered = 0;
  let processed = 0;
  let success = 0;
  let errors = 0;
  let fatal: string | undefined;

  try {
    if (await shouldDiscover(env, now)) {
      const urls = await discoverRaceUrls(env.JRA_HOME_URL, seeds(env));
      discovered = urls.length;
      await upsertRaceSources(env.DB, urls, toResultUrl);
      await setState(env.DB, "last_discovery_at", nowIso());
      await setState(env.DB, "last_discovery_count", String(urls.length));
    }

    const batchSize = positiveInt(env.SYNC_BATCH_SIZE, 8);
    const due = await getDueRaceSources(env.DB, batchSize);
    processed = due.length;
    for (const source of due) {
      const ok = await processSource(env, source, now);
      if (ok) success += 1;
      else errors += 1;
    }
    await setState(env.DB, "last_successful_cycle_at", nowIso());
  } catch (error) {
    fatal = error instanceof Error ? error.message : String(error);
    errors += 1;
    await setState(env.DB, "last_cycle_error", fatal);
  } finally {
    await finishSyncRun(env.DB, runId, fatal ? { discovered, processed, success, errors, errorMessage: fatal } : { discovered, processed, success, errors });
  }

  return { ok: !fatal, discovered, processed, success, errors, error: fatal ?? null, now: nowIso() };
}

async function handleApi(request: Request, env: Env, pathname: string): Promise<Response | null> {
  if (pathname === "/api/health" || pathname === "/health") {
    const snapshot = await getSystemSnapshot(env.DB);
    return json({ ok: true, project: "race-tantei", modelVersion: env.MODEL_VERSION, snapshot });
  }
  if (pathname === "/api/status") return json(await getSystemSnapshot(env.DB));
  if (pathname === "/api/races") return json(await getLatestRaces(env.DB, 100));
  if (pathname.startsWith("/api/races/")) {
    const id = decodeURIComponent(pathname.slice("/api/races/".length));
    const detail = await getRaceDetail(env.DB, id);
    return detail ? json(detail) : json({ ok: false, error: "NOT_FOUND" }, 404);
  }
  if (pathname === "/api/admin/sync" && request.method === "POST") {
    if (!authorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    return json(await runSync(env, "manual"));
  }
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    await ready(env.DB);
    const url = new URL(request.url);
    const api = await handleApi(request, env, url.pathname);
    if (api) return api;

    if (url.pathname === "/") {
      const [metrics, races] = await Promise.all([getDashboardMetrics(env.DB), getLatestRaces(env.DB)]);
      return html(renderHome(metrics, races));
    }
    if (url.pathname.startsWith("/races/")) {
      const id = decodeURIComponent(url.pathname.slice("/races/".length));
      const detail = await getRaceDetail(env.DB, id);
      return detail ? html(renderRace(detail)) : html(renderNotFound(), 404);
    }
    if (url.pathname === "/performance") {
      const [metrics, rows] = await Promise.all([getDashboardMetrics(env.DB), getPerformanceRows(env.DB)]);
      return html(renderPerformance(metrics, rows));
    }
    if (url.pathname === "/methodology") return html(renderMethodology());
    if (url.pathname === "/system") return html(renderSystem(await getSystemSnapshot(env.DB)));
    if (url.pathname === "/robots.txt") return new Response("User-agent: *\nDisallow: /\n", { headers: { "content-type": "text/plain" } });
    if (url.pathname === "/favicon.ico") return new Response(null, { status: 204 });
    return html(renderNotFound(), 404);
  },

  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const now = new Date();
    if (!isJstEntryWindow(now)) return;
    ctx.waitUntil(runSync(env, "cron"));
  }
} satisfies ExportedHandler<Env>;
