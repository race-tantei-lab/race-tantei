import app from "./learning-entry.js";
import {
  APPROVED_PRODUCTION_MODEL_VERSION,
  APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY
} from "./v1/approved-production-model.js";
import {
  getCourseMetrics,
  getCourseMonthlyMetrics,
  type CourseMetric
} from "./v1/course-db.js";
import { renderWorkerCalibrationPanel } from "./v1/learned-calibration-ui.js";
import { getWalkForwardTrainingProgress } from "./v1/walk-forward-training.js";
import { getWorkerCalibrationState } from "./v1/worker-calibration-v2.js";
import type { BudgetCourse, Env } from "./v1/types.js";
import { escapeHtml, formatYen } from "./v1/utils.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

function htmlResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-race-ui-version": "production-validation-split-v1"
    }
  });
}

function jsonResponse(data: unknown, status = 200): Response {
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

function normalizedMetrics(rows: CourseMetric[]): CourseMetric[] {
  return COURSES.map((course) => rows.find((row) => row.course === course) ?? {
    course,
    settledRaces: 0,
    betCount: 0,
    stakeYen: 0,
    returnYen: 0,
    profitYen: 0,
    roiPct: null,
    hitRatePct: null
  });
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function productionHomeCard(row: CourseMetric): string {
  const average = row.settledRaces > 0 ? Math.round(row.stakeYen / row.settledRaces) : null;
  const roi = row.roiPct === null ? "—" : `${row.roiPct.toFixed(1)}%`;
  const result = row.settledRaces > 0
    ? `<small>${row.settledRaces}R精算　${formatYen(row.stakeYen)} → ${formatYen(row.returnYen)}</small><em class="${row.profitYen >= 0 ? "plus" : "minus"}">${signedYen(row.profitYen)}</em>`
    : `<small>新モデルの本番精算はまだありません</small><em>集計開始待ち</em>`;
  return `<a class="metric" href="/performance"><div class="metric-head"><b>${escapeHtml(row.course)}</b><span>${average === null ? "平均購入 —" : `平均購入 ${formatYen(average)}/R`}</span></div><strong>${roi}</strong>${result}</a>`;
}

function productionHomeMetrics(rows: CourseMetric[]): string {
  return `<div class="section-label"><h2>新モデルの本番公開成績</h2><span>検証結果を含めず、公開後の実績だけ</span></div><section class="metrics">${normalizedMetrics(rows).map(productionHomeCard).join("")}</section>`;
}

function monthLabel(month: string): string {
  const match = month.match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[1])}年${Number(match[2])}月` : month;
}

function productionMonthlyTable(rows: Array<CourseMetric & { month: string }>): string {
  const months = [...new Set(rows.map((row) => row.month))].sort().reverse();
  if (months.length === 0) {
    return `<div class="history-empty">新モデルの本番レースが精算されると、ここへ月別成績を自動表示します。</div>`;
  }
  const body = months.map((month) => {
    const monthRows = rows.filter((row) => row.month === month);
    const cells = COURSES.map((course) => {
      const row = monthRows.find((item) => item.course === course);
      if (!row || row.stakeYen <= 0) return `<td class="month-empty">—</td>`;
      const roi = row.returnYen / row.stakeYen * 100;
      return `<td class="month-cell"><strong class="${roi >= 100 ? "plus" : "minus"}">${roi.toFixed(1)}%</strong><span>${signedYen(row.returnYen - row.stakeYen)}・${row.settledRaces}R</span></td>`;
    }).join("");
    return `<tr><th>${escapeHtml(monthLabel(month))}</th>${cells}</tr>`;
  }).join("");
  return `<div class="month-table-wrap"><table class="month-table"><thead><tr><th>期間</th>${COURSES.map((course) => `<th>${escapeHtml(course)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function productionHomeHistory(
  metrics: CourseMetric[],
  monthly: Array<CourseMetric & { month: string }>
): string {
  const selected = normalizedMetrics(metrics).reduce((sum, row) => sum + row.settledRaces, 0);
  return `<section class="home-history" id="monthly-history"><div class="section-label history-label"><h2>本番成績の月別推移</h2><span>検証期間は別ページへ分離</span></div><div class="history-kpis"><div class="history-kpi"><small>本番モデル</small><b>${escapeHtml(APPROVED_PRODUCTION_MODEL_VERSION)}</b></div><div class="history-kpi"><small>選出ルール</small><b>会場ごと${APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY}R</b></div><div class="history-kpi"><small>精算済み</small><b>${selected}R／3コース合計</b></div><div class="history-kpi"><small>検証結果</small><b><a href="/validation">検証ページで確認</a></b></div></div><div class="history-progress done"><b>本番成績はゼロから集計</b><span>237.0%は採用判断に使った検証値です。ここには新モデルで発走前に公開・固定した買い目だけを積み上げます。</span></div><div class="monthly-heading"><div><h3>月別推移</h3><p>購入額・払戻額は本番公開後の精算済み買い目のみです。</p></div><a href="/performance">詳細表示</a></div><div class="year-list">${productionMonthlyTable(monthly)}</div></section>`;
}

function stripLearningPanel(html: string): string {
  return html.replace(/<section id="learned-model-status"[\s\S]*?<\/section>/, "");
}

function convertHomeToProduction(
  source: string,
  metrics: CourseMetric[],
  monthly: Array<CourseMetric & { month: string }>
): string {
  let html = stripLearningPanel(source);
  const metricsBlock = productionHomeMetrics(metrics);
  const historyBlock = productionHomeHistory(metrics, monthly);
  const metricsPattern = /<div class="section-label"><h2>[\s\S]*?<\/div><section class="metrics">[\s\S]*?<\/section>/;
  const historyPattern = /<section class="home-history" id="monthly-history">[\s\S]*?<\/section>/;
  html = metricsPattern.test(html)
    ? html.replace(metricsPattern, metricsBlock)
    : html.replace("</main>", `${metricsBlock}</main>`);
  html = historyPattern.test(html)
    ? html.replace(historyPattern, historyBlock)
    : html.replace("</main>", `${historyBlock}</main>`);
  return html.replace(/<title>レース探偵[^<]*<\/title>/, "<title>レース探偵｜新モデル本番成績</title>");
}

function performanceCard(row: CourseMetric): string {
  const roi = row.roiPct === null ? "—" : `${row.roiPct.toFixed(1)}%`;
  const average = row.settledRaces > 0 ? Math.round(row.stakeYen / row.settledRaces) : null;
  return `<section class="course"><div class="course-head"><div><small>本番公開後のみ</small><h2>${escapeHtml(row.course)}</h2></div><strong class="${row.roiPct !== null && row.roiPct >= 100 ? "plus" : row.roiPct === null ? "" : "minus"}">${roi}</strong></div><div class="stats"><div><span>精算済み</span><b>${row.settledRaces}R</b></div><div><span>平均購入</span><b>${average === null ? "—" : formatYen(average)}</b></div><div><span>購入</span><b>${formatYen(row.stakeYen)}</b></div><div><span>払戻</span><b>${formatYen(row.returnYen)}</b></div><div><span>収支</span><b class="${row.profitYen >= 0 ? "plus" : "minus"}">${row.settledRaces > 0 ? signedYen(row.profitYen) : "—"}</b></div><div><span>買い目的中率</span><b>${row.hitRatePct === null ? "—" : `${row.hitRatePct.toFixed(1)}%`}</b></div></div></section>`;
}

function performanceMonthlyRows(rows: Array<CourseMetric & { month: string }>): string {
  if (rows.length === 0) return `<div class="empty">本番レースの精算後に自動で追加されます。</div>`;
  const ordered = [...rows].sort((a, b) => b.month.localeCompare(a.month) || COURSES.indexOf(a.course) - COURSES.indexOf(b.course));
  return `<div class="table-wrap"><table><thead><tr><th>月</th><th>コース</th><th>レース</th><th>購入</th><th>払戻</th><th>収支</th><th>回収率</th></tr></thead><tbody>${ordered.map((row) => `<tr><td>${escapeHtml(monthLabel(row.month))}</td><td>${escapeHtml(row.course)}</td><td>${row.settledRaces}R</td><td>${formatYen(row.stakeYen)}</td><td>${formatYen(row.returnYen)}</td><td class="${row.profitYen >= 0 ? "plus" : "minus"}">${signedYen(row.profitYen)}</td><td>${row.roiPct === null ? "—" : `${row.roiPct.toFixed(1)}%`}</td></tr>`).join("")}</tbody></table></div>`;
}

function renderProductionPerformance(
  metrics: CourseMetric[],
  monthly: Array<CourseMetric & { month: string }>
): string {
  const cards = normalizedMetrics(metrics).map(performanceCard).join("");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111b"><title>本番公開成績｜レース探偵</title><style>:root{color-scheme:dark;--bg:#07111b;--panel:#101c29;--line:#2b3d52;--text:#f2f5f8;--muted:#9baec4;--green:#51d0a5;--red:#ff7d77}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:920px;margin:auto;padding:18px 16px 42px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:24px}.brand{font-size:26px;font-weight:900;color:var(--green)}nav{display:flex;gap:8px}nav a{padding:9px 13px;border:1px solid var(--line);border-radius:999px}.hero{padding:20px;border:1px solid #2d6657;border-radius:20px;background:#0d241e;margin-bottom:18px}.hero h1{margin:0 0 8px}.hero p{margin:6px 0;color:var(--muted);line-height:1.7}.hero b{color:var(--green)}.course{padding:19px;border:1px solid var(--line);border-radius:18px;background:var(--panel);margin:12px 0}.course-head{display:flex;justify-content:space-between;align-items:flex-start}.course-head small,.stats span{color:var(--muted)}.course-head h2{margin:4px 0 0}.course-head strong{font-size:34px}.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:16px}.stats div{padding:11px;border-radius:12px;background:#0a1520}.stats span,.stats b{display:block}.stats b{margin-top:4px}.plus{color:var(--green)}.minus{color:var(--red)}h2.section{margin:30px 0 12px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:14px}table{width:100%;min-width:720px;border-collapse:collapse;background:var(--panel)}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted)}.empty{padding:20px;border:1px dashed var(--line);border-radius:14px;color:var(--muted)}@media(min-width:720px){.stats{grid-template-columns:repeat(6,minmax(0,1fr))}.wrap{padding-top:26px}}</style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav><a href="/performance">成績</a><a href="/validation">検証</a></nav></header><section class="hero"><h1>新モデルの本番公開成績</h1><p><b>${escapeHtml(APPROVED_PRODUCTION_MODEL_VERSION)}</b>で、発走前に公開・固定した買い目だけを集計します。</p><p>検証期間の237.0%はここへ合算しません。採用判断の詳細は<a href="/validation"><b>検証ページ</b></a>に分離しました。</p></section>${cards}<h2 class="section">月別成績</h2>${performanceMonthlyRows(monthly)}</main></body></html>`;
}

async function validationPanel(db: D1Database): Promise<string> {
  const [state, training] = await Promise.all([
    getWorkerCalibrationState(db),
    getWalkForwardTrainingProgress(db)
  ]);
  return renderWorkerCalibrationPanel({ ...state, trainingProgress: training } as typeof state)
    .replace("12か月学習モデル", "採用モデルの検証結果")
    .replace("回収率200%基準達成・本番モデル公開中", "検証合格・本番採用中");
}

async function transformHtmlResponse(response: Response, transform: (html: string) => string | Promise<string>): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const transformed = await transform(await response.text());
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(transformed).length));
  headers.set("x-race-ui-version", "production-validation-split-v1");
  return new Response(transformed, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;

    if (pathname === "/performance") {
      const [metrics, monthly] = await Promise.all([
        getCourseMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION),
        getCourseMonthlyMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION)
      ]);
      return htmlResponse(renderProductionPerformance(metrics, monthly));
    }

    if (pathname === "/api/performance/courses" || pathname === "/api/performance/courses/read-only") {
      const metrics = await getCourseMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION);
      return jsonResponse({
        modelVersion: APPROVED_PRODUCTION_MODEL_VERSION,
        scope: "production-only",
        historicalIncluded: false,
        metrics
      });
    }

    if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await app.fetch(request, env, ctx);

    if (pathname === "/") {
      const [metrics, monthly] = await Promise.all([
        getCourseMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION),
        getCourseMonthlyMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION)
      ]);
      return transformHtmlResponse(response, (source) => convertHomeToProduction(source, metrics, monthly));
    }

    if (pathname === "/validation") {
      const panel = await validationPanel(env.DB);
      return transformHtmlResponse(response, (source) => {
        const withoutDuplicate = stripLearningPanel(source);
        return withoutDuplicate.replace(/<main\b[^>]*>/, (match) => `${match}${panel}`);
      });
    }

    return response;
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (app.scheduled) await app.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
