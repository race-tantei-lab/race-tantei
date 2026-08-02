import app, { runSync } from "./complete.js";
import { getValidationAnalysisData } from "./v1/analysis-data.js";
import { getCourseMetrics, getCourseMonthlyMetrics } from "./v1/course-db.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import {
  getThreeMonthHistoryProgress,
  runThreeMonthHistoryStep
} from "./v1/three-month-history.js";
import {
  getThreeMonthValidationSnapshot,
  normalizeThreeMonthVenueQuotas,
  runThreeMonthValidationBatch
} from "./v1/three-month-validation.js";
import { fetchJraPage } from "./v1/jra.js";
import { refreshMissingLivePredictions } from "./v1/live-prediction-refresh.js";
import { getPhaseDDashboard } from "./v1/phase-d-dashboard.js";
import { renderPhaseCRaceDetail } from "./v1/race-detail-phase-c.js";
import type { Env } from "./v1/types.js";
import { stripHtml } from "./v1/utils.js";
import { ensureValidationVenueQuotas } from "./v1/venue-quota.js";
import {
  getValidationSnapshot,
  renderValidation,
  runValidationBatch,
  VALIDATION_CONFIGS
} from "./v1/validation.js";

let startupReady: Promise<void> | null = null;
let maintenanceRunning: Promise<void> | null = null;
let quotaNormalizationRunning: Promise<void> | null = null;

function prepare(db: D1Database): Promise<void> {
  startupReady ??= ensureSchema(db).catch((error) => {
    startupReady = null;
    throw error;
  });
  return startupReady;
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

function failureResponse(request: Request, error: unknown): Response {
  console.error("WORKER_STARTUP_FAILED", error);
  const pathname = new URL(request.url).pathname;
  const detail = error instanceof Error ? error.message : String(error);
  if (pathname === "/health" || pathname.startsWith("/api/")) {
    return json({ ok: false, error: "WORKER_STARTUP_FAILED", detail }, 500);
  }
  return new Response(`レース探偵の起動処理に失敗しました。\nエラーコード: WORKER_STARTUP_FAILED\n詳細: ${detail}`, {
    status: 500,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" }
  });
}

function extractOfficialRaceName(html: string): string | null {
  const match = html.match(/<span\b[^>]*class=["'][^"']*titleRaceName[^"']*["'][^>]*>([\s\S]*?)<\/span>/i);
  if (!match?.[1]) return null;
  const name = stripHtml(match[1]).replace(/\s+/g, " ").trim();
  if (!name || /^(?:検索ウィンドウ|メニュー|出馬表|レース結果|オッズ|払戻金)$/.test(name)) return null;
  return name;
}

async function repairRaceNames(db: D1Database, limit = 8): Promise<number> {
  const rows = await db.prepare(`
    SELECT race_id AS raceId, entry_url AS entryUrl, result_url AS resultUrl
    FROM rt_races
    WHERE race_name IN ('検索ウィンドウ','メニュー','出馬表','レース結果','オッズ','払戻金')
       OR race_name GLOB '[0-9]*レース'
    ORDER BY race_date DESC, venue, race_no LIMIT ?
  `).bind(limit).all<{ raceId: string; entryUrl: string; resultUrl: string }>();
  let repaired = 0;
  for (const row of rows.results) {
    try {
      let name: string | null = null;
      for (const url of [row.resultUrl, row.entryUrl]) {
        if (!url) continue;
        try {
          const page = await fetchJraPage(url);
          name = extractOfficialRaceName(page.html);
          if (name) break;
        } catch {
          // Try the next official page.
        }
      }
      if (!name) continue;
      await db.prepare(`UPDATE rt_races SET race_name=?, updated_at=CURRENT_TIMESTAMP WHERE race_id=?`)
        .bind(name, row.raceId).run();
      repaired += 1;
    } catch (error) {
      console.error("RACE_NAME_REPAIR_FAILED", row.raceId, error);
    }
  }
  return repaired;
}

function logRefresh(result: Awaited<ReturnType<typeof refreshMissingLivePredictions>>): void {
  if (
    result.candidates > 0
    || result.quotaAddedRaces > 0
    || result.quotaAddedTickets > 0
    || result.errors > 0
  ) {
    console.log("LIVE_PREDICTION_REFRESH", JSON.stringify(result));
  }
}

async function applyOneValidationVenue(db: D1Database): Promise<void> {
  const results = await ensureValidationVenueQuotas(db, VALIDATION_CONFIGS, 1);
  if (results.some((row) =>
    row.addedRaces > 0
    || row.replacedRaces > 0
    || row.removedRaces > 0
    || row.normalizedVenues > 0
  )) {
    console.log("VALIDATION_VENUE_QUOTAS", JSON.stringify(results));
  }
}

function runQuotaNormalization(db: D1Database): Promise<void> {
  if (quotaNormalizationRunning) return quotaNormalizationRunning;
  quotaNormalizationRunning = applyOneValidationVenue(db).catch((error) => {
    console.error("QUOTA_NORMALIZATION_FAILED", error);
  }).finally(() => {
    quotaNormalizationRunning = null;
  });
  return quotaNormalizationRunning;
}

function runMaintenance(env: Env): Promise<void> {
  if (maintenanceRunning) return maintenanceRunning;
  maintenanceRunning = (async () => {
    await runSync(env, "deploy");
    logRefresh(await refreshMissingLivePredictions(env, 60));
    await repairRaceNames(env.DB, 8);
    await runValidationBatch(env.DB, 12);
  })().catch((error) => {
    console.error("BACKGROUND_MAINTENANCE_FAILED", error);
  }).finally(() => {
    maintenanceRunning = null;
  });
  return maintenanceRunning;
}

function scheduleBackground(ctx: ExecutionContext, env: Env): void {
  ctx.waitUntil(runQuotaNormalization(env.DB));
  ctx.waitUntil(runMaintenance(env));
}

async function displayedHistoricalSnapshot(db: D1Database): Promise<{
  historical: Awaited<ReturnType<typeof getValidationSnapshot>>["combined"];
  monthly: Awaited<ReturnType<typeof getThreeMonthValidationSnapshot>>["monthly"];
  scope: { startDate: string; endDate: string; complete: boolean; totalRaces: number } | undefined;
  threeMonth: Awaited<ReturnType<typeof getThreeMonthValidationSnapshot>>;
}> {
  const threeMonth = await getThreeMonthValidationSnapshot(db);
  if (threeMonth.complete) {
    return {
      historical: threeMonth.combined,
      monthly: threeMonth.monthly,
      scope: {
        startDate: threeMonth.startDate,
        endDate: threeMonth.endDate,
        complete: true,
        totalRaces: threeMonth.totalRaces
      },
      threeMonth
    };
  }
  const fallback = await getValidationSnapshot(db);
  return { historical: fallback.combined, monthly: [], scope: undefined, threeMonth };
}

async function coursePerformanceSnapshot(env: Env): Promise<unknown> {
  const [live, display] = await Promise.all([
    getCourseMetrics(env.DB, env.MODEL_VERSION),
    displayedHistoricalSnapshot(env.DB)
  ]);
  return { live, historical: display.historical, threeMonth: display.threeMonth };
}

async function runThreeMonthPipelineStep(env: Env): Promise<unknown> {
  const history = await runThreeMonthHistoryStep(env.DB);
  const historyProgress = await getThreeMonthHistoryProgress(env.DB);
  let validation: Awaited<ReturnType<typeof runThreeMonthValidationBatch>> = {
    processed: 0,
    errors: 0,
    remaining: 0
  };
  let quotas: Awaited<ReturnType<typeof normalizeThreeMonthVenueQuotas>> = [];

  if (historyProgress.phase !== "discovery") {
    const validationBatchSize = historyProgress.phase === "import" ? 12 : 48;
    const quotaBatchSize = historyProgress.phase === "import" ? 2 : 8;
    validation = await runThreeMonthValidationBatch(env.DB, validationBatchSize);
    quotas = await normalizeThreeMonthVenueQuotas(env.DB, quotaBatchSize);
  }

  const snapshot = await getThreeMonthValidationSnapshot(env.DB);
  const pendingTickets = snapshot.combined.reduce((sum, row) => sum + row.pendingTickets, 0);
  const requiredSelections = snapshot.venueDays * 5;
  const quotasComplete = snapshot.combined.length === 3
    && snapshot.combined.every((row) => row.selectedRaces === requiredSelections);
  return {
    ok: true,
    history,
    validation,
    normalizedVenues: quotas.reduce((sum, row) => sum + row.normalizedVenues, 0),
    progress: historyProgress,
    snapshot: {
      complete: snapshot.complete,
      totalRaces: snapshot.totalRaces,
      processedRaces: snapshot.processedRaces,
      remainingRaces: snapshot.remainingRaces,
      venueDays: snapshot.venueDays,
      requiredSelections,
      quotasComplete,
      pendingTickets,
      courses: snapshot.combined
    },
    complete: historyProgress.complete
      && snapshot.complete
      && pendingTickets === 0
      && quotasComplete
  };
}

function page(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-race-ui-version": "phase-d"
    }
  });
}

function validationDateFromPath(pathname: string): string | null {
  const prefix = pathname.startsWith("/validation/") ? "/validation/" : pathname.startsWith("/backtest/") ? "/backtest/" : null;
  if (!prefix) return null;
  const value = decodeURIComponent(pathname.slice(prefix.length));
  return VALIDATION_CONFIGS.some((config) => config.raceDate === value) ? value : null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    try {
      await prepare(env.DB);
      const url = new URL(request.url);
      const pathname = url.pathname;

      if (pathname === "/api/validation/analysis-data") {
        return json(await getValidationAnalysisData(env.DB));
      }
      if (pathname === "/api/validation") {
        const snapshot = await getValidationSnapshot(env.DB);
        scheduleBackground(ctx, env);
        return json(snapshot);
      }
      if (pathname === "/api/history/three-months/status") {
        const [progress, validation] = await Promise.all([
          getThreeMonthHistoryProgress(env.DB),
          getThreeMonthValidationSnapshot(env.DB)
        ]);
        return json({ progress, validation });
      }
      if (pathname === "/api/history/three-months/step" && request.method === "POST") {
        if (request.headers.get("x-race-backfill") !== "three-month-v1") {
          return json({ ok: false, error: "BACKFILL_HEADER_REQUIRED" }, 403);
        }
        return json(await runThreeMonthPipelineStep(env));
      }
      if (pathname === "/api/performance/three-months/read-only") {
        return json(await getThreeMonthValidationSnapshot(env.DB));
      }
      if (pathname === "/api/performance/courses/read-only") {
        return json(await coursePerformanceSnapshot(env));
      }
      if (pathname === "/api/performance/courses") {
        const snapshot = await coursePerformanceSnapshot(env);
        scheduleBackground(ctx, env);
        return json(snapshot);
      }
      if (pathname === "/") {
        const dashboard = await getPhaseDDashboard(env.DB, env.MODEL_VERSION);
        scheduleBackground(ctx, env);
        return page(dashboard);
      }
      if (pathname.startsWith("/races/")) {
        const id = decodeURIComponent(pathname.slice("/races/".length));
        const detail = await getDisplayRaceDetail(env.DB, id, env.MODEL_VERSION);
        scheduleBackground(ctx, env);
        return detail ? page(renderPhaseCRaceDetail(detail)) : page("レースが見つかりません。", 404);
      }
      if (pathname === "/validation") {
        const body = await renderValidation(env.DB);
        scheduleBackground(ctx, env);
        return page(body);
      }
      const validationDate = validationDateFromPath(pathname);
      if (validationDate) {
        const body = await renderValidation(env.DB, validationDate);
        scheduleBackground(ctx, env);
        return page(body);
      }
      if (pathname === "/performance") {
        const [cumulative, monthly, display] = await Promise.all([
          getCourseMetrics(env.DB, env.MODEL_VERSION),
          getCourseMonthlyMetrics(env.DB, env.MODEL_VERSION),
          displayedHistoricalSnapshot(env.DB)
        ]);
        scheduleBackground(ctx, env);
        return page(renderCoursePerformance(
          cumulative,
          monthly,
          display.historical,
          display.monthly,
          display.scope
        ));
      }
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      return await app.fetch(request, env, ctx);
    } catch (error) {
      return failureResponse(request, error);
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    try {
      await prepare(env.DB);
      if (app.scheduled) await app.scheduled(controller, env, ctx);
      scheduleBackground(ctx, env);
    } catch (error) {
      console.error("SCHEDULED_STARTUP_FAILED", error);
    }
  }
} satisfies ExportedHandler<Env>;
