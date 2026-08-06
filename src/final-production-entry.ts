import app from "./learning-entry.js";
import {
  APPROVED_PRODUCTION_COURSE_METRICS,
  APPROVED_PRODUCTION_MODEL_VERSION,
  APPROVED_PRODUCTION_PROMOTION_ELIGIBLE,
  APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT,
  APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY,
  APPROVED_PRODUCTION_TARGET_ROI_PCT,
  APPROVED_PRODUCTION_VALIDATION
} from "./v1/approved-production-model.js";
import {
  getCourseMetrics,
  getCourseMonthlyMetrics,
  type CourseMetric
} from "./v1/course-db.js";
import {
  getProductionRaceArchiveIndex,
  renderProductionRaceArchiveIndex
} from "./v1/production-archive.js";
import { renderProductionLatestDetail } from "./v1/production-latest-detail.js";
import type { BudgetCourse, Env } from "./v1/types.js";
import { escapeHtml, formatYen } from "./v1/utils.js";

const START_DATE = "2026-08-01";
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

const STYLE = `:root{color-scheme:dark;--bg:#07111b;--panel:#101c29;--line:#2b3d52;--text:#f2f5f8;--muted:#9baec4;--green:#51d0a5;--red:#ff7d77;--warn:#f2d48d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:960px;margin:auto;padding:22px 16px 48px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:22px}.brand{font-size:28px;font-weight:900;color:var(--green)}nav{display:flex;gap:8px}nav a{padding:9px 13px;border:1px solid var(--line);border-radius:999px}.hero,.notice,.metric,.validation-card,.history-empty{border:1px solid var(--line);border-radius:18px;background:var(--panel)}.hero{padding:20px;margin-bottom:18px}.hero h1{margin:0 0 8px}.hero p{margin:6px 0;color:var(--muted);line-height:1.7}.hero b{color:var(--green)}.notice{padding:14px;margin:14px 0;color:var(--warn);border-color:#765f32;background:#251f12;line-height:1.7}.section-label{display:flex;justify-content:space-between;align-items:end;gap:10px;margin:28px 0 12px}.section-label h2{margin:0}.section-label span,.muted{color:var(--muted)}.metrics,.validation-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.metric,.validation-card{padding:18px}.metric-head{display:flex;justify-content:space-between;gap:8px}.metric strong,.validation-card strong{display:block;font-size:34px;margin:8px 0}.metric small,.metric em,.validation-card span,.validation-card small{display:block;color:var(--muted);font-style:normal;margin-top:5px}.plus{color:var(--green)!important}.minus{color:var(--red)!important}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:15px;background:var(--panel)}table{width:100%;min-width:720px;border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left}.archive-home{margin-top:30px}.production-day-totals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.production-day-total{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:11px}.race-rail{display:flex;overflow:auto;gap:12px}.race-card{min-width:310px;border:1px solid var(--line);border-radius:18px;background:var(--panel);padding:16px}.course-result{display:grid;grid-template-columns:1fr auto auto auto;gap:8px;padding:8px 0;border-top:1px solid var(--line)}button{color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:10px 14px}.day-tabs,.filter-tabs,.venue-tabs{display:flex;gap:8px;overflow:auto;margin:10px 0}.day-summary{display:flex;justify-content:space-between;align-items:center}.winner{color:var(--warn);margin:10px 0}.pick{color:var(--green);font-weight:800;margin:8px 0}.status{padding:4px 8px;border-radius:999px}.hit{background:#144d3b}.miss{background:#542827}.retro{color:var(--muted);font-size:12px;margin-top:6px}.history-empty{padding:18px;color:var(--muted)}@media(max-width:720px){.metrics,.validation-grid,.production-day-totals{grid-template-columns:1fr}.wrap{padding:16px 14px 42px}.metric strong,.validation-card strong{font-size:31px}}`;

function response(body: string, status = 200): Response {
  return new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": "final-v5-single-source" } });
}

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data, null, 2), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store, max-age=0" } });
}

function shell(title: string, body: string): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111b"><title>${escapeHtml(title)}｜レース探偵</title><style>${STYLE}</style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav><a href="/performance">成績</a><a href="/validation">検証</a></nav></header>${body}</main></body></html>`;
}

function normalized(rows: CourseMetric[]): CourseMetric[] {
  return COURSES.map((course) => rows.find((row) => row.course === course) ?? { course, settledRaces: 0, betCount: 0, stakeYen: 0, returnYen: 0, profitYen: 0, roiPct: null, hitRatePct: null });
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function metricCards(rows: CourseMetric[]): string {
  return `<section class="metrics">${normalized(rows).map((row) => {
    const average = row.settledRaces > 0 ? Math.round(row.stakeYen / row.settledRaces) : null;
    return `<a class="metric" href="/performance"><div class="metric-head"><b>${row.course}</b><span class="muted">${average === null ? "—" : `${formatYen(average)}/R`}</span></div><strong class="${row.roiPct !== null && row.roiPct >= 100 ? "plus" : "minus"}">${row.roiPct === null ? "—" : `${row.roiPct.toFixed(1)}%`}</strong><small>${row.settledRaces}R　${formatYen(row.stakeYen)} → ${formatYen(row.returnYen)}</small><em class="${row.profitYen >= 0 ? "plus" : "minus"}">${row.settledRaces > 0 ? signedYen(row.profitYen) : "集計待ち"}</em></a>`;
  }).join("")}</section>`;
}

function monthlyTable(rows: Array<CourseMetric & { month: string }>): string {
  const filtered = rows.filter((row) => row.month >= "2026-08");
  if (filtered.length === 0) return `<div class="history-empty">最終v5の8月精算結果を反映中です。</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>月</th><th>コース</th><th>R</th><th>購入</th><th>払戻</th><th>収支</th><th>回収率</th></tr></thead><tbody>${filtered.map((row) => `<tr><td>${row.month}</td><td>${row.course}</td><td>${row.settledRaces}</td><td>${formatYen(row.stakeYen)}</td><td>${formatYen(row.returnYen)}</td><td class="${row.profitYen >= 0 ? "plus" : "minus"}">${signedYen(row.profitYen)}</td><td>${row.roiPct === null ? "—" : `${row.roiPct.toFixed(1)}%`}</td></tr>`).join("")}</tbody></table></div>`;
}

async function home(db: D1Database): Promise<string> {
  const [metrics, monthly, archiveRows, latest] = await Promise.all([
    getCourseMetrics(db, APPROVED_PRODUCTION_MODEL_VERSION),
    getCourseMonthlyMetrics(db, APPROVED_PRODUCTION_MODEL_VERSION),
    getProductionRaceArchiveIndex(db, APPROVED_PRODUCTION_MODEL_VERSION, START_DATE),
    renderProductionLatestDetail(db, APPROVED_PRODUCTION_MODEL_VERSION, START_DATE)
  ]);
  const archive = renderProductionRaceArchiveIndex(archiveRows);
  return shell("最終v5", `<section class="hero"><h1>最終v5コース別モデル</h1><p><b>${APPROVED_PRODUCTION_MODEL_VERSION}</b></p><p>馬順位と会場ごと5R選別は共通ですが、ライト・スタンダード・プレミアムは券種・点数・購入額が異なります。</p></section><div class="section-label"><h2>2026年8月の成績</h2><span>検証値を含めない</span></div>${metricCards(metrics)}<div class="section-label"><h2>月別成績</h2><span>最終v5のみ</span></div>${monthlyTable(monthly)}${latest}${archive}`);
}

async function performance(db: D1Database): Promise<string> {
  const [metrics, monthly] = await Promise.all([
    getCourseMetrics(db, APPROVED_PRODUCTION_MODEL_VERSION),
    getCourseMonthlyMetrics(db, APPROVED_PRODUCTION_MODEL_VERSION)
  ]);
  return shell("成績", `<section class="hero"><h1>最終v5の本番・8月再計算成績</h1><p>対象は<b>${APPROVED_PRODUCTION_MODEL_VERSION}</b>だけです。旧モデルや検証期間の回収率は合算しません。</p></section>${metricCards(metrics)}<div class="section-label"><h2>月別成績</h2><span>2026年8月以降</span></div>${monthlyTable(monthly)}`);
}

function validation(): string {
  const cards = APPROVED_PRODUCTION_COURSE_METRICS.map((row) => {
    const gap = row.roiPct - APPROVED_PRODUCTION_TARGET_ROI_PCT;
    return `<article class="validation-card"><b>${row.course}</b><strong class="${gap >= 0 ? "plus" : "minus"}">${row.roiPct.toFixed(1)}%</strong><span>7月固定確認 ${row.selectedRaces}R</span><span>的中率 ${row.hitRatePct.toFixed(1)}%</span><span>5–6月 ${row.validationRoiPct.toFixed(1)}%</span><span>月別最低 ${row.minimumValidationMonthRoiPct.toFixed(1)}%</span><span>購入 ${formatYen(row.targetStakeYen)}/R</span><small class="${gap >= 0 ? "plus" : "minus"}">${gap >= 0 ? `目標超過 ${gap.toFixed(1)}pt` : `目標まで ${Math.abs(gap).toFixed(1)}pt`}</small></article>`;
  }).join("");
  return shell("検証", `<section class="hero"><h1>最終v5の検証結果</h1><p><b>${APPROVED_PRODUCTION_MODEL_VERSION}</b>／会場ごと${APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY}R</p><p>${APPROVED_PRODUCTION_VALIDATION.method}</p></section><div class="notice">判定：${APPROVED_PRODUCTION_PROMOTION_ELIGIBLE ? "全コース合格" : "ライトのみ200%未達"}。目標${APPROVED_PRODUCTION_TARGET_ROI_PCT}%、的中率基準${APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT}%です。${APPROVED_PRODUCTION_VALIDATION.note}</div><section class="validation-grid">${cards}</section><div class="section-label"><h2>期間</h2><span>成績ページとは分離</span></div><div class="table-wrap"><table><tbody><tr><th>学習・選定</th><td>${APPROVED_PRODUCTION_VALIDATION.validationStartDate}〜${APPROVED_PRODUCTION_VALIDATION.validationEndDate}</td></tr><tr><th>固定確認</th><td>${APPROVED_PRODUCTION_VALIDATION.holdoutStartDate}〜${APPROVED_PRODUCTION_VALIDATION.holdoutEndDate}</td></tr><tr><th>8月実績</th><td><a class="plus" href="/performance">成績ページで確認</a></td></tr></tbody></table></div>`);
}

async function delegate(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
  const original = await app.fetch(request, env, ctx);
  const contentType = original.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return original;
  let body = await original.text();
  body = body
    .replaceAll("v4.1.0-nonlinear-hgb-5r", APPROVED_PRODUCTION_MODEL_VERSION)
    .replaceAll("8月v4再計算", "8月最終v5再計算")
    .replaceAll("発走前公開v4", "発走前公開v5")
    .replaceAll("237.0%", "最終v5検証ページ参照");
  const headers = new Headers(original.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(body).length));
  headers.set("x-race-ui-version", "final-v5-single-source");
  return new Response(body, { status: original.status, statusText: original.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/") return response(await home(env.DB));
    if (pathname === "/performance") return response(await performance(env.DB));
    if (pathname === "/validation") return response(validation());
    if (pathname === "/api/performance/courses" || pathname === "/api/performance/courses/read-only") {
      return jsonResponse({ modelVersion: APPROVED_PRODUCTION_MODEL_VERSION, startDate: START_DATE, scope: "final-v5-only", metrics: await getCourseMetrics(env.DB, APPROVED_PRODUCTION_MODEL_VERSION) });
    }
    return delegate(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (app.scheduled) await app.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
