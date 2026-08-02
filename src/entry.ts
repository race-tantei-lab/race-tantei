import app, { runSync } from "./complete.js";
import { getValidationAnalysisData } from "./v1/analysis-data.js";
import { getCourseMetrics, getCourseMonthlyMetrics } from "./v1/course-db.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import {
  getThreeMonthHistoryProgressV2 as getThreeMonthHistoryProgress,
  runThreeMonthHistoryStepV2 as runThreeMonthHistoryStep
} from "./v1/three-month-history-v2.js";
import {
  getThreeMonthValidationSnapshot,
  normalizeThreeMonthVenueQuotas,
  runThreeMonthValidationBatch
} from "./v1/three-month-validation.js";
import { getThreeMonthStakeAuditV2 } from "./v1/three-month-audit-v2.js";
import { runThreeMonthFixedStakeRepair } from "./v1/three-month-repair.js";
import { isThreeMonthDate } from "./v1/three-month-scope.js";
import { fetchJraPage } from "./v1/jra.js";
import { refreshMissingLivePredictions } from "./v1/live-prediction-refresh.js";
import { getAuditedPhaseDDashboard } from "./v1/phase-d-dashboard-audited.js";
import { historyDateFromPath, renderAuditedRaceArchiveDate } from "./v1/race-archive-audited.js";
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

const HISTORICAL_AUDIT_FROZEN = true;
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
  if (threeMonth.processedRaces > 0) {
    return {
      historical: threeMonth.combined,
      monthly: threeMonth.monthly,
      scope: {
        startDate: threeMonth.startDate,
        endDate: threeMonth.endDate,
        complete: threeMonth.complete,
        totalRaces: threeMonth.totalRaces
      },
      threeMonth
    };
  }
  const fallback = await getValidationSnapshot(db);
  return { historical: fallback.combined, monthly: [], scope: undefined, threeMonth };
}

async function coursePerformanceSnapshot(env: Env): Promise<unknown> {
  const live = await getCourseMetrics(env.DB, env.MODEL_VERSION);
  if (HISTORICAL_AUDIT_FROZEN) {
    return {
      live,
      historical: [],
      threeMonth: { auditFrozen: true, message: "Historical performance is hidden until fixed-stake reconciliation passes." },
      auditFrozen: true
    };
  }
  const display = await displayedHistoricalSnapshot(env.DB);
  return { live, historical: display.historical, threeMonth: display.threeMonth, auditFrozen: false };
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

  if (historyProgress.phase === "complete") {
    validation = await runThreeMonthValidationBatch(env.DB, 48);
    quotas = await normalizeThreeMonthVenueQuotas(env.DB, 8);
  }

  const snapshot = await getThreeMonthValidationSnapshot(env.DB);
  const pendingTickets = snapshot.combined.reduce((sum, row) => sum + row.pendingTickets, 0);
  const requiredSelections = snapshot.venueDays * 5;
  const quotasComplete = snapshot.combined.length === 3
    && snapshot.combined.every((row) => row.selectedRaces === requiredSelections);
  return {
    ok: true,
    stage: historyProgress.complete ? "validation" : "history-import",
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

function auditHoldSection(): string {
  return `<section style="margin:20px 0;padding:18px;border:1px solid #c76767;border-radius:16px;background:#2a1619;color:#fff">
    <h2 style="margin:0 0 8px;font-size:20px">過去3ヶ月成績を監査中</h2>
    <p style="margin:0;color:#e8bdc0;line-height:1.7">固定購入額違反と参照予想の不一致が確認されたため、回収率・収支・月別成績・個別買い目を一時的に非表示にしています。全開催日と全レースの一覧は確認できます。</p>
  </section>`;
}

function maskDisputedHomeMetrics(html: string): string {
  let next = html.replace(
    /<div class="section-label"><h2>全期間の累計成績[\s\S]*?<\/section>/,
    auditHoldSection()
  );
  next = next.replace(/<section class="home-history" id="monthly-history">[\s\S]*?<\/section>/, "");
  return next;
}

function auditNoticePage(title: string, detail: string): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>レース探偵｜成績監査中</title><style>body{margin:0;background:#07111b;color:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:760px;margin:auto;padding:28px 18px}.box{margin-top:40px;padding:22px;border:1px solid #c76767;border-radius:18px;background:#2a1619}.box h1{margin:0 0 12px}.box p{color:#e8bdc0;line-height:1.8}.box a{display:inline-block;margin-top:10px;color:#78dfb3;text-decoration:none}</style></head><body><main class="wrap"><div class="box"><h1>${title}</h1><p>${detail}</p><a href="/">ホームへ戻る</a></div></main></body></html>`;
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
      if (pathname === "/api/audit/three-months") {
        if (request.headers.get("x-race-audit") !== "stake-reconciliation-v1") {
          return json({ ok: false, error: "AUDIT_HEADER_REQUIRED" }, 403);
        }
        return json(await getThreeMonthStakeAuditV2(env.DB, env.MODEL_VERSION, url.searchParams.get("full") === "1"));
      }
      if (pathname === "/api/audit/three-months/repair" && request.method === "POST") {
        if (request.headers.get("x-race-audit-repair") !== "fixed-stake-v1") {
          return json({ ok: false, error: "AUDIT_REPAIR_HEADER_REQUIRED" }, 403);
        }
        const maximumVenues = Number(url.searchParams.get("venues") ?? 4);
        return json(await runThreeMonthFixedStakeRepair(env.DB, env.MODEL_VERSION, maximumVenues));
      }
      if (pathname === "/api/validation") {
        const snapshot = await getValidationSnapshot(env.DB);
        scheduleBackground(ctx, env);
        return json(snapshot);
      }
      if (pathname === "/api/history/three-months/status") {
        const progress = await getThreeMonthHistoryProgress(env.DB);
        return json({ progress, auditFrozen: HISTORICAL_AUDIT_FROZEN });
      }
      if (pathname === "/api/history/three-months/step" && request.method === "POST") {
        if (HISTORICAL_AUDIT_FROZEN) {
          return json({ ok: false, error: "HISTORICAL_AUDIT_FROZEN", message: "Three-month writes are disabled except for the controlled fixed-stake repair." }, 423);
        }
        if (request.headers.get("x-race-backfill") !== "three-month-v1") {
          return json({ ok: false, error: "BACKFILL_HEADER_REQUIRED" }, 403);
        }
        return json(await runThreeMonthPipelineStep(env));
      }
      if (pathname === "/api/performance/three-months/read-only") {
        if (HISTORICAL_AUDIT_FROZEN) return json({ auditFrozen: true, message: "Historical figures are hidden during reconciliation." });
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
        const dashboard = await getAuditedPhaseDDashboard(env.DB, env.MODEL_VERSION, HISTORICAL_AUDIT_FROZEN);
        scheduleBackground(ctx, env);
        return page(HISTORICAL_AUDIT_FROZEN ? maskDisputedHomeMetrics(dashboard) : dashboard);
      }
      const historyDate = historyDateFromPath(pathname);
      if (historyDate) {
        const body = await renderAuditedRaceArchiveDate(env.DB, historyDate, env.MODEL_VERSION, HISTORICAL_AUDIT_FROZEN);
        scheduleBackground(ctx, env);
        return body ? page(body) : page("指定された開催日のレースが見つかりません。", 404);
      }
      if (pathname.startsWith("/races/")) {
        const id = decodeURIComponent(pathname.slice("/races/".length));
        const detail = await getDisplayRaceDetail(env.DB, id, env.MODEL_VERSION);
        scheduleBackground(ctx, env);
        if (!detail) return page("レースが見つかりません。", 404);
        if (HISTORICAL_AUDIT_FROZEN && isThreeMonthDate(detail.race.raceDate)) {
          return page(auditNoticePage("個別買い目を監査中", "このレースの表示買い目と累計集計の参照元を統一し、固定購入額で再精算しています。監査完了まで買い目と払戻額は表示しません。"));
        }
        return page(renderPhaseCRaceDetail(detail));
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
        if (HISTORICAL_AUDIT_FROZEN) {
          return page(auditNoticePage("過去3ヶ月成績を監査中", "固定購入額、個別レースの買い目、累計集計に使われた買い目を全件突合しています。検証が完了するまで回収率と収支は表示しません。"));
        }
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
