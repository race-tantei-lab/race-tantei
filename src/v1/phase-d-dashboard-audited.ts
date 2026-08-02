import type { CourseMetric } from "./course-db.js";
import { getPhaseDDashboard as getBasePhaseDDashboard } from "./phase-d-dashboard.js";
import { getAuditedRaceArchiveIndex, renderAuditedRaceArchiveIndex } from "./race-archive-audited.js";
import {
  getCorrectedThreeMonthPerformance,
  getLiveCourseMetricsOutsideThreeMonthScope,
  getLiveMonthlyMetricsOutsideThreeMonthScope,
  type ThreeMonthPeriodSummary
} from "./three-month-evaluation.js";
import type { BudgetCourse } from "./types.js";
import type { CourseValidationSummary } from "./validation.js";
import { escapeHtml, formatYen } from "./utils.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

interface DisplayMetric {
  course: BudgetCourse;
  races: number;
  hits: number;
  stake: number;
  returns: number;
}

interface MonthlyMetric extends DisplayMetric {
  month: string;
}

function fromLive(row: CourseMetric): DisplayMetric {
  return {
    course: row.course,
    races: row.settledRaces,
    hits: row.hitRatePct === null ? 0 : Math.round(row.settledRaces * row.hitRatePct / 100),
    stake: row.stakeYen,
    returns: row.returnYen
  };
}

function fromHistorical(row: CourseValidationSummary): DisplayMetric {
  return {
    course: row.course,
    races: row.selectedRaces,
    hits: row.hitRaces,
    stake: row.stakeYen,
    returns: row.returnYen
  };
}

function emptyMetric(course: BudgetCourse): DisplayMetric {
  return { course, races: 0, hits: 0, stake: 0, returns: 0 };
}

function combine(left: DisplayMetric, right: DisplayMetric): DisplayMetric {
  return {
    course: left.course,
    races: left.races + right.races,
    hits: left.hits + right.hits,
    stake: left.stake + right.stake,
    returns: left.returns + right.returns
  };
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function metricCard(metric: DisplayMetric): string {
  const roi = metric.stake > 0 ? metric.returns / metric.stake * 100 : null;
  const profit = metric.returns - metric.stake;
  const average = metric.races > 0 ? Math.round(metric.stake / metric.races) : null;
  return `<a class="metric" href="#monthly-history"><div class="metric-head"><b>${escapeHtml(metric.course)}</b><span>${average === null ? "平均購入 —" : `平均購入 ${formatYen(average)}/R`}</span></div><strong>${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong><small>${metric.hits}/${metric.races}R的中　${formatYen(metric.stake)} → ${formatYen(metric.returns)}</small><em class="${profit >= 0 ? "plus" : "minus"}">${signedYen(profit)}</em></a>`;
}

function correctedMetrics(combined: DisplayMetric[]): string {
  return `<div class="section-label"><h2>検証成績＋監査後の本番成績</h2><span>8月1日・2日の調整期間は除外</span></div><section class="metrics">${combined.map(metricCard).join("")}</section>`;
}

function addMonthly(map: Map<string, MonthlyMetric>, row: MonthlyMetric): void {
  const key = `${row.month}:${row.course}`;
  const current = map.get(key);
  if (!current) {
    map.set(key, row);
    return;
  }
  map.set(key, { month: row.month, ...combine(current, row) });
}

function monthlyRows(
  evaluation: ThreeMonthPeriodSummary,
  liveRows: Array<CourseMetric & { month: string }>
): MonthlyMetric[] {
  const map = new Map<string, MonthlyMetric>();
  for (const block of evaluation.monthly) {
    for (const course of block.courses) {
      addMonthly(map, { month: block.month, ...fromHistorical(course) });
    }
  }
  for (const row of liveRows) addMonthly(map, { month: row.month, ...fromLive(row) });
  const courseOrder = new Map(COURSES.map((course, index) => [course, index]));
  return [...map.values()].sort((a, b) =>
    b.month.localeCompare(a.month) || (courseOrder.get(a.course) ?? 9) - (courseOrder.get(b.course) ?? 9)
  );
}

function monthLabel(month: string): string {
  const match = month.match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[1])}年${Number(match[2])}月` : month;
}

function monthCell(row: MonthlyMetric | undefined): string {
  if (!row || row.stake <= 0) return `<td class="month-empty">—</td>`;
  const roi = row.returns / row.stake * 100;
  const profit = row.returns - row.stake;
  return `<td class="month-cell"><strong class="${roi >= 100 ? "plus" : "minus"}">${roi.toFixed(1)}%</strong><span>${signedYen(profit)}・${row.races}R</span></td>`;
}

function monthlyMatrix(rows: MonthlyMetric[]): string {
  const months = [...new Set(rows.map((row) => row.month))].sort().reverse();
  if (months.length === 0) return `<div class="history-empty">精算済み成績はまだありません。</div>`;
  const years = [...new Set(months.map((month) => month.slice(0, 4)))];
  return years.map((year, index) => {
    const yearMonths = months.filter((month) => month.startsWith(year));
    const body = yearMonths.map((month) => {
      const values = rows.filter((row) => row.month === month);
      return `<tr><th>${escapeHtml(monthLabel(month))}</th>${COURSES.map((course) => monthCell(values.find((row) => row.course === course))).join("")}</tr>`;
    }).join("");
    return `<details class="year-block" ${index === 0 ? "open" : ""}><summary><b>${escapeHtml(year)}年</b><span>${yearMonths.length}ヶ月</span></summary><div class="month-table-wrap"><table class="month-table"><thead><tr><th>期間</th>${COURSES.map((course) => `<th>${escapeHtml(course)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div></details>`;
  }).join("");
}

function correctedHistory(
  evaluation: ThreeMonthPeriodSummary,
  tuning: ThreeMonthPeriodSummary,
  combined: DisplayMetric[],
  monthly: MonthlyMetric[]
): string {
  const selected = combined.map((row) => row.races);
  const selectedText = selected.every((value) => value === selected[0])
    ? `${selected[0] ?? 0}R／コース`
    : COURSES.map((course, index) => `${course}${selected[index] ?? 0}R`).join("・");
  return `<section class="home-history" id="monthly-history"><div class="section-label history-label"><h2>月別成績</h2><span>調整期間を混ぜずに表示</span></div><div class="history-kpis"><div class="history-kpi"><small>主要検証期間</small><b>${escapeHtml(evaluation.startDate)}〜${escapeHtml(evaluation.endDate)}</b></div><div class="history-kpi"><small>検証済み</small><b>${evaluation.processedRaces}/${evaluation.totalRaces}R</b></div><div class="history-kpi"><small>累計選出</small><b>${escapeHtml(selectedText)}</b></div><div class="history-kpi"><small>調整期間</small><b>8月1日・2日を除外</b></div></div><div class="history-progress done"><b>固定購入額の監査に合格</b><span>全レースで1,600円／4,200円／8,800円を適用。調整期間${tuning.totalRaces}Rは主要回収率へ含めません。</span></div><div class="monthly-heading"><div><h3>月別推移</h3><p>表示される購入額・払戻額は個別レースページと同じ買い目です。</p></div><a href="/performance">詳細表示</a></div><div class="year-list">${monthlyMatrix(monthly)}</div></section>`;
}

function injectCorrectedStyles(html: string): string {
  const styles = `<style>.audit-method-note{margin:10px 0;padding:10px 12px;border:1px solid #315f55;border-radius:12px;background:#10231f;color:#bde8dc;font-size:12px;line-height:1.6}</style>`;
  return html.replace("</head>", `${styles}</head>`);
}

export async function getAuditedPhaseDDashboard(
  db: D1Database,
  liveModel: string,
  auditFrozen: boolean
): Promise<string> {
  const [baseHtml, archiveRows] = await Promise.all([
    getBasePhaseDDashboard(db, liveModel),
    getAuditedRaceArchiveIndex(db, liveModel)
  ]);
  const archive = renderAuditedRaceArchiveIndex(archiveRows, auditFrozen);
  const archivePattern = /<section class="archive-home" id="race-archive">[\s\S]*?<\/section>/;
  let html = archivePattern.test(baseHtml)
    ? baseHtml.replace(archivePattern, archive)
    : baseHtml.replace("</main>", `${archive}</main>`);

  if (auditFrozen) return html;

  const [performance, liveRows, liveMonthly] = await Promise.all([
    getCorrectedThreeMonthPerformance(db),
    getLiveCourseMetricsOutsideThreeMonthScope(db, liveModel),
    getLiveMonthlyMetricsOutsideThreeMonthScope(db, liveModel)
  ]);
  const combined = COURSES.map((course) => combine(
    fromLive(liveRows.find((row) => row.course === course) ?? {
      course,
      settledRaces: 0,
      betCount: 0,
      stakeYen: 0,
      returnYen: 0,
      profitYen: 0,
      roiPct: null,
      hitRatePct: null
    }),
    fromHistorical(performance.evaluation.combined.find((row) => row.course === course) ?? {
      course,
      processedRaces: 0,
      selectedRaces: 0,
      skippedRaces: 0,
      hitRaces: 0,
      tickets: 0,
      pendingTickets: 0,
      stakeYen: 0,
      returnYen: 0,
      profitYen: 0,
      expectedReturnYen: 0,
      roiPct: null,
      expectedRoiPct: null,
      hitRatePct: null,
      byTicketType: []
    })
  ));
  const monthly = monthlyRows(performance.evaluation, liveMonthly);
  html = html.replace(
    /<div class="section-label"><h2>全期間の累計成績[\s\S]*?<\/section>/,
    correctedMetrics(combined)
  );
  html = html.replace(
    /<section class="home-history" id="monthly-history">[\s\S]*?<\/section>/,
    correctedHistory(performance.evaluation, performance.tuning, combined, monthly)
  );
  html = html.replace(/<title>レース探偵[^<]*<\/title>/, "<title>レース探偵｜監査済み検証成績と全レース</title>");
  return injectCorrectedStyles(html);
}
