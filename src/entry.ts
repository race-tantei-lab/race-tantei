import app, { runSync } from "./complete.js";
import { getCourseMetrics, getCourseMonthlyMetrics } from "./v1/course-db.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import { fetchJraPage } from "./v1/jra.js";
import { getPhaseCDashboard } from "./v1/phase-c-dashboard.js";
import { renderPhaseCRaceDetail } from "./v1/race-detail-phase-c.js";
import type { Env } from "./v1/types.js";
import { stripHtml } from "./v1/utils.js";
import {
  getValidationSnapshot,
  renderValidation,
  runValidationBatch,
  VALIDATION_CONFIGS
} from "./v1/validation.js";

let startupReady: Promise<void> | null = null;
let maintenanceRunning: Promise<void> | null = null;

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

function runMaintenance(env: Env): Promise<void> {
  if (maintenanceRunning) return maintenanceRunning;
  maintenanceRunning = (async () => {
    await runSync(env, "deploy");
    await repairRaceNames(env.DB, 8);
    await runValidationBatch(env.DB, 6);
  })().finally(() => {
    maintenanceRunning = null;
  });
  return maintenanceRunning;
}

function page(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-race-ui-version": "phase-c"
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
      const pathname = new URL(request.url).pathname;

      if (pathname === "/api/validation") {
        ctx.waitUntil(runMaintenance(env));
        return json(await getValidationSnapshot(env.DB));
      }
      if (pathname === "/api/performance/courses") {
        return json(await getCourseMetrics(env.DB, env.MODEL_VERSION));
      }
      if (pathname === "/") {
        const dashboard = await getPhaseCDashboard(env.DB, env.MODEL_VERSION);
        ctx.waitUntil(runMaintenance(env));
        return page(dashboard);
      }
      if (pathname.startsWith("/races/")) {
        const id = decodeURIComponent(pathname.slice("/races/".length));
        const detail = await getDisplayRaceDetail(env.DB, id, env.MODEL_VERSION);
        ctx.waitUntil(runMaintenance(env));
        return detail ? page(renderPhaseCRaceDetail(detail)) : page("レースが見つかりません。", 404);
      }
      if (pathname === "/validation") {
        ctx.waitUntil(runMaintenance(env));
        return page(await renderValidation(env.DB));
      }
      const validationDate = validationDateFromPath(pathname);
      if (validationDate) {
        ctx.waitUntil(runMaintenance(env));
        return page(await renderValidation(env.DB, validationDate));
      }
      if (pathname === "/performance") {
        const [cumulative, monthly] = await Promise.all([
          getCourseMetrics(env.DB, env.MODEL_VERSION),
          getCourseMonthlyMetrics(env.DB, env.MODEL_VERSION)
        ]);
        return page(renderCoursePerformance(cumulative, monthly));
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
      ctx.waitUntil(runMaintenance(env));
    } catch (error) {
      console.error("SCHEDULED_STARTUP_FAILED", error);
    }
  }
} satisfies ExportedHandler<Env>;
