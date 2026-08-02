import app, { runSync } from "./complete.js";
import { BACKTEST_DATE, renderBacktest, runBacktestBatch } from "./v1/backtest.js";
import { runAug2BackfillBatch } from "./v1/backfill-aug2.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import { fetchJraPage } from "./v1/jra.js";
import { getPhaseBDashboard } from "./v1/phase-b-dashboard.js";
import { renderPhaseARaceDetail } from "./v1/race-detail-phase-a.js";
import type { Env } from "./v1/types.js";
import { stripHtml } from "./v1/utils.js";

let startupReady: Promise<void> | null = null;
let maintenanceRunning: Promise<void> | null = null;

function prepare(db: D1Database): Promise<void> {
  startupReady ??= ensureSchema(db).catch((error) => {
    startupReady = null;
    throw error;
  });
  return startupReady;
}

function failureResponse(request: Request, error: unknown): Response {
  console.error("WORKER_STARTUP_FAILED", error);
  const pathname = new URL(request.url).pathname;
  const detail = error instanceof Error ? error.message : String(error);
  if (pathname === "/health" || pathname.startsWith("/api/")) {
    return new Response(JSON.stringify({ ok: false, error: "WORKER_STARTUP_FAILED", detail }), {
      status: 500,
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" }
    });
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
      await db.prepare(`UPDATE rt_races SET race_name=?, updated_at=CURRENT_TIMESTAMP WHERE race_id=?`).bind(name, row.raceId).run();
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
    await Promise.all([
      repairRaceNames(env.DB, 8),
      runBacktestBatch(env.DB, 12),
      runAug2BackfillBatch(env.DB, env.MODEL_VERSION, 12)
    ]);
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
      "x-race-ui-version": "phase-b"
    }
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    try {
      await prepare(env.DB);
      const pathname = new URL(request.url).pathname;
      if (pathname === "/") {
        const dashboard = await getPhaseBDashboard(env.DB, env.MODEL_VERSION);
        ctx.waitUntil(runMaintenance(env));
        return page(dashboard);
      }
      if (pathname.startsWith("/races/")) {
        const id = decodeURIComponent(pathname.slice("/races/".length));
        const detail = await getDisplayRaceDetail(env.DB, id, env.MODEL_VERSION);
        ctx.waitUntil(runMaintenance(env));
        return detail ? page(renderPhaseARaceDetail(detail)) : page("レースが見つかりません。", 404);
      }
      if (pathname === `/backtest/${BACKTEST_DATE}`) {
        await runMaintenance(env);
        return page(await renderBacktest(env.DB));
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
