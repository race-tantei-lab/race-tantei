import base from "./entry.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import { getHistoricalAuditState, type HistoricalAuditState } from "./v1/historical-audit-state.js";
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
import { escapeHtml } from "./v1/utils.js";

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
      "x-race-ui-version": "phase-d-audited-light"
    }
  });
}

function finding(state: HistoricalAuditState, key: string): number {
  return Number(state.findings[key] ?? 0);
}

function maintenancePage(state: HistoricalAuditState): string {
  const items: Array<[string, number]> = [
    ["固定購入額違反", finding(state, "stakeViolationRaceCourses")],
    ["未精算", finding(state, "pendingRaceCourses")],
    ["会場5R違反", finding(state, "venueQuotaViolations")],
    ["個別表示不一致", finding(state, "individualDetailMismatchRaces")],
    ["コース選出不一致", finding(state, "courseSelectionMismatchRaces")],
    ["予想未生成", finding(state, "missingModelRaces")]
  ];
  const checkedAt = state.checkedAt ? new Date(state.checkedAt).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) : "—";
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111b"><meta http-equiv="refresh" content="30"><title>監査修復中｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#07111b;--panel:#101a27;--line:#2b3a4e;--text:#edf3f8;--muted:#9eafc2;--green:#57d6aa;--gold:#e6c875}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:720px;margin:auto;padding:28px 20px 48px}.top{display:flex;align-items:center;justify-content:space-between;margin:24px 0 56px}.brand{font-size:28px;font-weight:900;color:var(--green)}.badge{border:1px solid var(--line);border-radius:999px;padding:8px 12px;color:var(--muted);font-size:13px}.card{border:1px solid #765f2b;background:#241f13;border-radius:22px;padding:24px}.card h1{font-size:27px;margin:0 0 12px}.card p{margin:0;color:#dacda8;line-height:1.8}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:22px}.item{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px}.item small{display:block;color:var(--muted);margin-bottom:4px}.item b{font-size:21px}.note{margin-top:20px;padding:14px;border-radius:14px;background:#0d1723;color:var(--muted);line-height:1.7}.time{margin-top:14px;color:var(--muted);font-size:12px}@media(max-width:480px){.wrap{padding:22px 16px}.top{margin-bottom:38px}.grid{grid-template-columns:1fr 1fr}.card{padding:20px}.card h1{font-size:24px}}
  </style></head><body><main class="wrap"><div class="top"><div class="brand">レース探偵</div><div class="badge">軽量表示</div></div><section class="card"><h1>過去成績を修復中</h1><p>誤った回収率や買い目は表示していません。修復処理は画面表示とは切り離し、1分ごとの定期処理で進めています。この画面は30秒ごとに自動更新されます。</p><div class="grid">${items.map(([label, value]) => `<div class="item"><small>${escapeHtml(label)}</small><b>${value}</b></div>`).join("")}</div><div class="note">全項目が0になり、固定購入額・会場5R・個別ページ・累計の一致を確認できた時点で、正しい成績画面へ自動的に戻ります。</div><div class="time">最終監査：${escapeHtml(checkedAt)}</div></section></main></body></html>`;
}

function runRepair(env: Env): Promise<void> {
  if (repairRunning) return repairRunning;
  repairRunning = (async () => {
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    if (state.valid) return;
    const result = await runThreeMonthFixedStakeRepair(env.DB, env.MODEL_VERSION, 1);
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
  const corrected = html
    .replace("過去3ヶ月と本番公開分の合算", "主要検証期間と本番公開分の合算")
    .replace("過去3ヶ月分はJRA結果ページに残る最終人気から市場確率を固定式で復元しています。", "過去検証分はJRA結果ページに残る最終人気から市場確率を固定式で復元しています。");
  return corrected.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
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

async function handledAfterAudit(request: Request, env: Env): Promise<Response | null> {
  const pathname = new URL(request.url).pathname;
  if (pathname === "/api/audit/three-months/public-status") {
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    return json({ auditFrozen: !state.valid, state });
  }
  if (pathname === "/api/history/three-months/status") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({ auditFrozen: false, evaluation: performance.evaluation, tuningReference: performance.tuning, fullScope: performance.full });
  }
  if (pathname === "/api/performance/three-months/read-only") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({ auditFrozen: false, evaluation: performance.evaluation, tuningReference: performance.tuning, fullScope: performance.full });
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
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    await ensureSchema(env.DB);
    const pathname = new URL(request.url).pathname;
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);

    if (!state.valid) {
      if (pathname === "/api/audit/three-months/public-status") {
        return json({ auditFrozen: true, state });
      }
      if (pathname === "/health" || pathname === "/api/health") {
        if (!base.fetch) return json({ ok: true, auditFrozen: true });
        return base.fetch(request, env, ctx);
      }
      return page(maintenancePage(state));
    }

    const handled = await handledAfterAudit(request, env);
    if (handled) return handled;
    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
    return base.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await ensureSchema(env.DB);
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    if (!state.valid) {
      ctx.waitUntil(runRepair(env));
      return;
    }
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
