import base from "./entry.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import { getHistoricalAuditState } from "./v1/historical-audit-state.js";
import { getAuditedPhaseDDashboard } from "./v1/phase-d-dashboard-audited.js";
import { historyDateFromPath, renderAuditedRaceArchiveDate } from "./v1/race-archive-audited.js";
import { renderPhaseCRaceDetail } from "./v1/race-detail-phase-c.js";
import {
  getCorrectedThreeMonthPerformance,
  getLiveCourseMetricsOutsideThreeMonthScope,
  getLiveMonthlyMetricsOutsideThreeMonthScope
} from "./v1/three-month-evaluation.js";
import { runThreeMonthFixedStakeRepair } from "./v1/three-month-repair.js";
import { isThreeMonthTuningDate } from "./v1/three-month-scope.js";
import type { Env } from "./v1/types.js";

let repairRunning: Promise<void> | null = null;

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

function page(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-race-ui-version": "phase-d-audited"
    }
  });
}

function runRepair(env: Env): Promise<void> {
  if (repairRunning) return repairRunning;
  repairRunning = (async () => {
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    if (state.valid) return;
    const result = await runThreeMonthFixedStakeRepair(env.DB, env.MODEL_VERSION, 12);
    console.log("AUDITED_THREE_MONTH_REPAIR", JSON.stringify({
      complete: result.complete,
      repairedVenues: result.repairedVenues,
      addedRaces: result.addedRaces,
      replacedRaces: result.replacedRaces,
      removedRaces: result.removedRaces,
      findings: result.audit.findings
    }));
  })().catch((error) => {
    console.error("AUDITED_THREE_MONTH_REPAIR_FAILED", error);
  }).finally(() => {
    repairRunning = null;
  });
  return repairRunning;
}

function addMethodologyNotice(html: string): string {
  const notice = `<section style="margin:0 0 16px;padding:14px;border:1px solid #315f55;border-radius:14px;background:#10231f;color:#d9f3ec;line-height:1.7"><b>監査済み成績</b><br>主要回収率は2026年5月2日〜7月26日の固定購入額検証です。モデル調整に使った8月1日・2日は累計から除外しています。個別レースと累計は同じ予想ID・同じ買い目を参照します。</section>`;
  return html.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
}

function addTuningNotice(html: string): string {
  const notice = `<div style="margin:12px 0;padding:11px;border:1px solid #80652d;border-radius:12px;background:#2a2414;color:#f2d48d;line-height:1.6"><b>調整期間</b>　このレースはモデル調整に使用した8月1日・2日のデータです。買い目は表示しますが、主要な累計回収率には含めません。</div>`;
  return html.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
}

async function correctedPerformancePayload(env: Env): Promise<Record<string, unknown>> {
  const [performance, live] = await Promise.all([
    getCorrectedThreeMonthPerformance(env.DB),
    getLiveCourseMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION)
  ]);
  return {
    auditFrozen: false,
    live,
    historical: performance.evaluation.combined,
    threeMonth: {
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: {
        startDate: performance.full.startDate,
        endDate: performance.full.endDate,
        totalRaces: performance.full.totalRaces,
        processedRaces: performance.full.processedRaces,
        complete: performance.full.complete
      }
    }
  };
}

async function handledAfterAudit(
  request: Request,
  env: Env,
  ctx: ExecutionContext
): Promise<Response | null> {
  const url = new URL(request.url);
  const pathname = url.pathname;

  if (pathname === "/api/audit/three-months/public-status") {
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    return json({ auditFrozen: !state.valid, state });
  }
  if (pathname === "/api/history/three-months/status") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({
      auditFrozen: false,
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: {
        startDate: performance.full.startDate,
        endDate: performance.full.endDate,
        totalRaces: performance.full.totalRaces,
        processedRaces: performance.full.processedRaces,
        complete: performance.full.complete
      }
    });
  }
  if (pathname === "/api/performance/three-months/read-only") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({
      auditFrozen: false,
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: performance.full
    });
  }
  if (pathname === "/api/performance/courses" || pathname === "/api/performance/courses/read-only") {
    return json(await correctedPerformancePayload(env));
  }
  if (pathname === "/") {
    return page(await getAuditedPhaseDDashboard(env.DB, env.MODEL_VERSION, false));
  }
  const historyDate = historyDateFromPath(pathname);
  if (historyDate) {
    const body = await renderAuditedRaceArchiveDate(env.DB, historyDate, env.MODEL_VERSION, false);
    if (!body) return page("指定された開催日のレースが見つかりません。", 404);
    return page(isThreeMonthTuningDate(historyDate) ? addTuningNotice(body) : body);
  }
  if (pathname.startsWith("/races/")) {
    const raceId = decodeURIComponent(pathname.slice("/races/".length));
    const detail = await getDisplayRaceDetail(env.DB, raceId, env.MODEL_VERSION);
    if (!detail) return page("レースが見つかりません。", 404);
    const body = renderPhaseCRaceDetail(detail);
    return page(isThreeMonthTuningDate(detail.race.raceDate) ? addTuningNotice(body) : body);
  }
  if (pathname === "/performance") {
    const [performance, live, liveMonthly] = await Promise.all([
      getCorrectedThreeMonthPerformance(env.DB),
      getLiveCourseMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION),
      getLiveMonthlyMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION)
    ]);
    return page(addMethodologyNotice(renderCoursePerformance(
      live,
      liveMonthly,
      performance.evaluation.combined,
      performance.evaluation.monthly,
      {
        startDate: performance.evaluation.startDate,
        endDate: performance.evaluation.endDate,
        complete: performance.evaluation.complete,
        totalRaces: performance.evaluation.totalRaces
      }
    )));
  }

  void ctx;
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    await ensureSchema(env.DB);
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    if (!state.valid) {
      ctx.waitUntil(runRepair(env));
      if (new URL(request.url).pathname === "/api/audit/three-months/public-status") {
        return json({ auditFrozen: true, state });
      }
      if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
      return base.fetch(request, env, ctx);
    }

    const handled = await handledAfterAudit(request, env, ctx);
    if (handled) return handled;
    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
    return base.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await ensureSchema(env.DB);
    ctx.waitUntil(runRepair(env));
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
