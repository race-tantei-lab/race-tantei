import type { CourseMetric } from "./course-db.js";
import { getPhaseCDashboard } from "./phase-c-dashboard.js";
import { getRaceArchiveIndex, renderRaceArchiveIndex } from "./race-archive.js";
import { getThreeMonthValidationSnapshot } from "./three-month-validation.js";
import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";
import {
  getValidationSnapshot,
  type CourseValidationSummary,
  type ValidationDateSnapshot
} from "./validation.js";

const COURSES: Array<{ name: BudgetCourse }> = [
  { name: "ライト" },
  { name: "スタンダード" },
  { name: "プレミアム" }
];

const MAX_SELECTED_RACES_PER_VENUE = 5;

interface DisplayMetric {
  course: BudgetCourse;
  races: number;
  hits: number;
  stake: number;
  returns: number;
}

interface MonthlyDisplayMetric extends DisplayMetric {
  month: string;
}

interface RaceCardMatch {
  card: string;
  index: number;
  category: string;
  historical: boolean;
}

function numberValue(value: unknown): number {
  return Number(value ?? 0);
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function pct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
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

function fromValidation(row: CourseValidationSummary): DisplayMetric {
  return {
    course: row.course,
    races: row.selectedRaces,
    hits: row.hitRaces,
    stake: row.stakeYen,
    returns: row.returnYen
  };
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

function emptyHistorical(course: BudgetCourse): CourseValidationSummary {
  return {
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
  };
}

async function getLiveMetricsOutsideScope(
  db: D1Database,
  liveModel: string,
  startDate: string,
  endDate: string
): Promise<CourseMetric[]> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
      COUNT(DISTINCT b.race_id) AS settledRaces,
      COUNT(*) AS betCount,
      COALESCE(SUM(b.stake_yen),0) AS stakeYen,
      COALESCE(SUM(b.return_yen),0) AS returnYen,
      COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE p.model_version=? AND p.status='locked' AND b.settlement_status='settled'
      AND (r.race_date<? OR r.race_date>?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(liveModel, startDate, endDate).all<{
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hitRaces: number;
  }>();
  const map = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map(({ name }) => {
    const row = map.get(name);
    const races = numberValue(row?.settledRaces);
    const hits = numberValue(row?.hitRaces);
    const stake = numberValue(row?.stakeYen);
    const returns = numberValue(row?.returnYen);
    return {
      course: name,
      settledRaces: races,
      betCount: numberValue(row?.betCount),
      stakeYen: stake,
      returnYen: returns,
      profitYen: returns - stake,
      roiPct: stake > 0 ? returns / stake * 100 : null,
      hitRatePct: races > 0 ? hits / races * 100 : null
    };
  });
}

async function getLiveMonthlyOutsideScope(
  db: D1Database,
  liveModel: string,
  startDate: string,
  endDate: string
): Promise<Array<CourseMetric & { month: string }>> {
  const rows = await db.prepare(`
    SELECT substr(r.race_date,1,7) AS month,
      CASE
        WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
        WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
        WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
      END AS course,
      COUNT(DISTINCT b.race_id) AS settledRaces,
      COUNT(*) AS betCount,
      COALESCE(SUM(b.stake_yen),0) AS stakeYen,
      COALESCE(SUM(b.return_yen),0) AS returnYen,
      COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hitRaces
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE p.model_version=? AND p.status='locked' AND b.settlement_status='settled'
      AND (r.race_date<? OR r.race_date>?)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY month, course
    ORDER BY month DESC, course
  `).bind(liveModel, startDate, endDate).all<{
    month: string;
    course: BudgetCourse;
    settledRaces: number;
    betCount: number;
    stakeYen: number;
    returnYen: number;
    hitRaces: number;
  }>();
  return rows.results.map((row) => {
    const races = numberValue(row.settledRaces);
    const hits = numberValue(row.hitRaces);
    const stake = numberValue(row.stakeYen);
    const returns = numberValue(row.returnYen);
    return {
      month: row.month,
      course: row.course,
      settledRaces: races,
      betCount: numberValue(row.betCount),
      stakeYen: stake,
      returnYen: returns,
      profitYen: returns - stake,
      roiPct: stake > 0 ? returns / stake * 100 : null,
      hitRatePct: races > 0 ? hits / races * 100 : null
    };
  });
}

function metricCard(metric: DisplayMetric): string {
  const roi = metric.stake > 0 ? metric.returns / metric.stake * 100 : null;
  const profit = metric.returns - metric.stake;
  const averageStake = metric.races > 0 ? Math.round(metric.stake / metric.races) : null;
  return `<a class="metric" href="#monthly-history">
    <div class="metric-head"><b>${escapeHtml(metric.course)}</b><span>${averageStake === null ? "平均購入 —" : `平均購入 ${formatYen(averageStake)}/R`}</span></div>
    <strong>${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong>
    <small>${metric.hits}/${metric.races}R的中　${formatYen(metric.stake)} → ${formatYen(metric.returns)}</small>
    <em class="${profit >= 0 ? "plus" : "minus"}">${signedYen(profit)}</em>
  </a>`;
}

function replaceMetricArea(html: string, combined: DisplayMetric[], complete: boolean): string {
  const start = html.indexOf('<div class="section-label">');
  const metricsStart = html.indexOf('<section class="metrics">', start);
  const end = html.indexOf("</section>", metricsStart);
  if (start < 0 || metricsStart < 0 || end < 0) return html;
  const cards = COURSES.map(({ name }) => metricCard(
    combined.find((row) => row.course === name) ?? { course: name, races: 0, hits: 0, stake: 0, returns: 0 }
  )).join("");
  const label = complete ? "過去検証＋本番・重複なし" : "集計済み分を随時反映・暫定値";
  return `${html.slice(0, start)}<div class="section-label"><h2>全期間の累計成績</h2><span>${label}</span></div><section class="metrics">${cards}</section>${html.slice(end + "</section>".length)}`;
}

function addMonthlyMetric(map: Map<string, MonthlyDisplayMetric>, metric: MonthlyDisplayMetric): void {
  const key = `${metric.month}:${metric.course}`;
  const current = map.get(key);
  if (!current) {
    map.set(key, { ...metric });
    return;
  }
  const merged = combine(current, metric);
  map.set(key, { month: metric.month, ...merged });
}

function monthlyFromHistorical(
  blocks: Awaited<ReturnType<typeof getThreeMonthValidationSnapshot>>["monthly"]
): MonthlyDisplayMetric[] {
  const map = new Map<string, MonthlyDisplayMetric>();
  for (const block of blocks) {
    for (const course of block.courses) addMonthlyMetric(map, { month: block.month, ...fromValidation(course) });
  }
  return [...map.values()];
}

function monthlyFromValidationDates(dates: ValidationDateSnapshot[]): MonthlyDisplayMetric[] {
  const map = new Map<string, MonthlyDisplayMetric>();
  for (const date of dates) {
    for (const course of date.courses) {
      addMonthlyMetric(map, { month: date.raceDate.slice(0, 7), ...fromValidation(course) });
    }
  }
  return [...map.values()];
}

function mergeMonthly(
  liveRows: Array<CourseMetric & { month: string }>,
  historicalRows: MonthlyDisplayMetric[]
): MonthlyDisplayMetric[] {
  const map = new Map<string, MonthlyDisplayMetric>();
  for (const row of liveRows) addMonthlyMetric(map, { month: row.month, ...fromLive(row) });
  for (const row of historicalRows) addMonthlyMetric(map, row);
  const order = new Map(COURSES.map((row, index) => [row.name, index]));
  return [...map.values()].sort((a, b) => b.month.localeCompare(a.month) || (order.get(a.course) ?? 9) - (order.get(b.course) ?? 9));
}

function monthLabel(month: string): string {
  const match = month.match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[1])}年${Number(match[2])}月` : month;
}

function monthCell(metric: MonthlyDisplayMetric | undefined): string {
  if (!metric || metric.stake <= 0) return `<td class="month-empty">—</td>`;
  const roi = metric.returns / metric.stake * 100;
  const profit = metric.returns - metric.stake;
  return `<td class="month-cell"><strong class="${roi >= 100 ? "plus" : "minus"}">${pct(roi)}</strong><span>${signedYen(profit)}・${metric.races}R</span></td>`;
}

function monthlyMatrix(rows: MonthlyDisplayMetric[]): string {
  const months = [...new Set(rows.map((row) => row.month))];
  if (months.length === 0) return `<div class="history-empty">精算済みの月別成績はまだありません。</div>`;
  const years = [...new Set(months.map((month) => month.slice(0, 4)))];
  return years.map((year, index) => {
    const yearMonths = months.filter((month) => month.startsWith(year));
    const body = yearMonths.map((month) => {
      const monthRows = rows.filter((row) => row.month === month);
      return `<tr><th>${escapeHtml(monthLabel(month))}</th>${COURSES.map(({ name }) => monthCell(monthRows.find((row) => row.course === name))).join("")}</tr>`;
    }).join("");
    return `<details class="year-block" ${index === 0 ? "open" : ""}><summary><b>${escapeHtml(year)}年</b><span>${yearMonths.length}ヶ月</span></summary><div class="month-table-wrap"><table class="month-table"><thead><tr><th>期間</th>${COURSES.map(({ name }) => `<th>${escapeHtml(name)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div></details>`;
  }).join("");
}

function historyOverview(
  monthly: MonthlyDisplayMetric[],
  combined: DisplayMetric[],
  snapshot: Awaited<ReturnType<typeof getThreeMonthValidationSnapshot>>
): string {
  const months = [...new Set(monthly.map((row) => row.month))].sort();
  const period = months.length > 0 ? `${monthLabel(months[0]!)}〜${monthLabel(months.at(-1)!)}` : "集計準備中";
  const selected = combined.map((row) => row.races);
  const selectedText = selected.every((value) => value === selected[0])
    ? `${selected[0] ?? 0}R／コース`
    : COURSES.map(({ name }, index) => `${name}${selected[index] ?? 0}R`).join("・");
  const progress = snapshot.complete
    ? `<div class="history-progress done"><b>全期間の集計完了</b><span>${escapeHtml(snapshot.startDate)}〜${escapeHtml(snapshot.endDate)}・${snapshot.venueDays}会場日・${snapshot.totalRaces}R</span></div>`
    : `<div class="history-progress working"><b>集計途中の暫定値</b><span>${snapshot.processedRaces}/${snapshot.totalRaces || 960}Rを反映済み。処理が進むたび累計・月別も更新します。</span></div>`;
  return `<section class="home-history" id="monthly-history"><div class="section-label history-label"><h2>成績の積み上がり</h2><span>全期間を月単位で確認</span></div><div class="history-kpis"><div class="history-kpi"><small>表示期間</small><b>${escapeHtml(period)}</b></div><div class="history-kpi"><small>表示月数</small><b>${months.length}ヶ月</b></div><div class="history-kpi"><small>集計済み</small><b>${snapshot.processedRaces}/${snapshot.totalRaces || 0}R</b></div><div class="history-kpi"><small>累計選出</small><b>${escapeHtml(selectedText)}</b></div></div>${progress}<div class="monthly-heading"><div><h3>月別推移</h3><p>回収率・収支・選出レース数を月ごとに表示します。</p></div><a href="/performance">詳細表示</a></div><div class="year-list">${monthlyMatrix(monthly)}</div></section>`;
}

function removeLegacyValidationNotice(html: string): string {
  return html.replace(/<div class="notice">フェーズC検証[\s\S]*?<\/div>/, "");
}

function injectAfterMetrics(html: string, content: string): string {
  const start = html.indexOf('<section class="metrics">');
  const end = html.indexOf("</section>", start);
  if (start < 0 || end < 0) return html;
  const at = end + "</section>".length;
  return `${html.slice(0, at)}${content}${html.slice(at)}`;
}

function injectBeforeDayTabs(html: string, content: string): string {
  const at = html.indexOf('<nav class="day-tabs"');
  if (at < 0) return `${html}${content}`;
  return `${html.slice(0, at)}${content}<div class="section-label latest-label"><h2>最新開催の詳細</h2><span>全開催日は上の一覧から表示</span></div>${html.slice(at)}`;
}

function injectHomeStyles(html: string): string {
  const styles = `<style>
  .home-history,.archive-home{margin:22px 0 4px}.history-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.history-kpi{min-width:0;border:1px solid var(--line);border-radius:14px;background:#0d1722;padding:12px}.history-kpi small{display:block;color:var(--muted);font-size:11px}.history-kpi b{display:block;margin-top:5px;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.history-progress{display:flex;justify-content:space-between;gap:12px;margin:10px 0 15px;padding:11px 13px;border-radius:13px;font-size:12px}.history-progress span{color:var(--muted);text-align:right}.history-progress.done{border:1px solid #285f50;background:#10231f}.history-progress.done b{color:var(--green)}.history-progress.working{border:1px solid #65552f;background:#241f13}.history-progress.working b{color:#f2d28a}.monthly-heading{display:flex;align-items:end;justify-content:space-between;gap:12px;margin:18px 0 8px}.monthly-heading h3{margin:0;font-size:17px}.monthly-heading p,.archive-title p{margin:4px 0 0;color:var(--muted);font-size:11px}.monthly-heading a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 10px;color:var(--muted);font-size:11px}.year-list,.archive-month-list{display:grid;gap:9px}.year-block,.archive-month{border:1px solid var(--line);border-radius:15px;background:var(--panel);overflow:hidden}.year-block summary,.archive-month summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:12px 14px}.year-block summary span,.archive-month summary span{color:var(--muted);font-size:12px}.month-table-wrap{overflow:auto;border-top:1px solid var(--line)}.month-table{width:100%;min-width:700px;border-collapse:collapse}.month-table th,.month-table td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left}.month-table thead th{color:var(--muted);font-size:11px}.month-table tbody th{font-size:12px;white-space:nowrap}.month-cell strong{display:block;font-size:15px}.month-cell span{display:block;margin-top:3px;color:var(--muted);font-size:10px;white-space:nowrap}.month-empty{color:var(--muted)}.archive-title>div{min-width:0}.archive-date-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:10px;border-top:1px solid var(--line)}.archive-date{display:flex;justify-content:space-between;gap:12px;border:1px solid var(--line);border-radius:13px;padding:11px;background:#0d1722}.archive-date>div:first-child{min-width:0}.archive-date b,.archive-date span{display:block}.archive-date>div:first-child span{margin-top:3px;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.archive-date-stats{text-align:right;white-space:nowrap}.archive-date-stats strong{display:block;color:var(--green)}.archive-date-stats span{margin-top:3px;color:var(--muted);font-size:10px}.archive-month summary>div span{margin-left:8px}.archive-month summary>strong{font-size:12px}.latest-label{margin-top:26px}
  @media(max-width:720px){.metrics{display:grid!important;grid-template-columns:1fr!important;overflow:visible!important}.metric{width:auto!important;min-width:0!important;flex:none!important}.history-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.history-progress{display:block}.history-progress span{display:block;margin-top:4px;text-align:left}.archive-date-grid{grid-template-columns:1fr}.monthly-heading{align-items:flex-start}}
  </style>`;
  return html.replace("</head>", `${styles}</head>`);
}

function categoryTokens(category: string): string[] {
  return category.split(/\s+/).filter(Boolean);
}

function isHistoricalCard(card: string): boolean {
  return card.includes('class="retro"') || card.includes("遡及検証");
}

function hasSettledCourseResult(card: string): boolean {
  return card.includes('class="course-result') && !card.includes("status skip") && !card.includes("検証計算中") && !card.includes("結果反映中");
}

function markCardSelected(card: string): string {
  let next = card.replace(/\sdata-race-selected="true"/g, "");
  const category = next.match(/data-race-category="([^"]+)"/)?.[1] ?? "other";
  const tokens = categoryTokens(category);
  if (!tokens.includes("buy")) tokens.unshift("buy");
  next = next.replace(/data-race-category="[^"]+"/, `data-race-category="${tokens.join(" ")}"`);
  return next.replace('<a class="race-card"', '<a class="race-card" data-race-selected="true"');
}

function cleanUnselectedCard(card: string, historical: boolean): string {
  let next = card.replace(/\sdata-race-selected="true"/g, "");
  if (!historical) return next;
  const category = next.match(/data-race-category="([^"]+)"/)?.[1];
  if (!category) return next;
  const tokens = categoryTokens(category).filter((token) => token !== "buy");
  return next.replace(/data-race-category="[^"]+"/, `data-race-category="${tokens.length > 0 ? tokens.join(" ") : "finished"}"`);
}

function selectVenueCards(panel: string): string {
  const pattern = /<a class="race-card"[^>]*data-race-category="([^"]+)"[^>]*>[\s\S]*?<\/a>/g;
  const cards: RaceCardMatch[] = [...panel.matchAll(pattern)].map((match) => ({
    card: match[0],
    index: match.index ?? 0,
    category: match[1] ?? "other",
    historical: isHistoricalCard(match[0])
  }));
  if (cards.length === 0) return panel;
  const selected = new Set<number>();
  const liveCandidates = cards.filter((item) => {
    if (item.historical) return false;
    const tokens = categoryTokens(item.category);
    return tokens.includes("buy") || (tokens.includes("finished") && hasSettledCourseResult(item.card));
  });
  const historicalCandidates = cards.filter((item) => item.historical && hasSettledCourseResult(item.card));
  for (const candidate of [...liveCandidates, ...historicalCandidates]) {
    if (selected.size >= MAX_SELECTED_RACES_PER_VENUE) break;
    selected.add(candidate.index);
  }
  let result = "";
  let cursor = 0;
  for (const item of cards) {
    result += panel.slice(cursor, item.index);
    result += selected.has(item.index) ? markCardSelected(item.card) : cleanUnselectedCard(item.card, item.historical);
    cursor = item.index + item.card.length;
  }
  return result + panel.slice(cursor);
}

export function markSelectedCards(html: string): string {
  const venuePattern = /<section class="venue-panel"[^>]*data-venue-panel="[^"]+"[^>]*>[\s\S]*?<\/section>/g;
  const next = html.replace(venuePattern, (panel) => selectVenueCards(panel));
  return next.replace("card.dataset.raceCategory!==filter", "!card.dataset.raceCategory.split(' ').includes(filter)");
}

function injectSelectionCountScript(html: string): string {
  const script = `<script>(()=>{const update=()=>{document.querySelectorAll('[data-day-panel]').forEach(panel=>{const cards=[...panel.querySelectorAll('.race-card')];const selected=cards.filter(card=>card.dataset.raceSelected==='true');const finished=cards.filter(card=>(card.dataset.raceCategory||'').split(' ').includes('finished'));panel.dataset.defaultFilter=selected.length>0?'buy':'all';const summary=panel.querySelector('.day-summary p');if(summary)summary.textContent='選出レース '+selected.length+'R　終了 '+finished.length+'R';const buyButton=panel.querySelector('[data-filter="buy"]');if(buyButton){const span=buyButton.querySelector('span');if(span)span.textContent=String(selected.length);const first=buyButton.firstChild;if(first)first.textContent='選出レース '}panel.querySelectorAll('[data-venue-tab]').forEach(tab=>{const venue=tab.dataset.venueTab||'';const venuePanel=[...panel.querySelectorAll('[data-venue-panel]')].find(item=>item.dataset.venuePanel===venue);const count=venuePanel?[...venuePanel.querySelectorAll('[data-race-selected="true"]')].length:0;tab.dataset.buyCount=String(count);let badge=tab.querySelector('span');if(count>0){if(!badge){badge=document.createElement('span');tab.appendChild(badge)}badge.textContent=String(count)}else if(badge)badge.remove()})});const active=document.querySelector('[data-day-tab].active');if(active instanceof HTMLElement)active.click()};update()})();</script>`;
  return html.replace("</body>", `${script}</body>`);
}

export async function getPhaseDDashboard(db: D1Database, liveModel: string): Promise<string> {
  let html = await getPhaseCDashboard(db, liveModel);
  const threeMonthSnapshot = await getThreeMonthValidationSnapshot(db);
  const hasThreeMonthData = threeMonthSnapshot.processedRaces > 0;
  const [liveRows, liveMonthlyRows, fallbackSnapshot, archiveRows] = await Promise.all([
    getLiveMetricsOutsideScope(db, liveModel, threeMonthSnapshot.startDate, threeMonthSnapshot.endDate),
    getLiveMonthlyOutsideScope(db, liveModel, threeMonthSnapshot.startDate, threeMonthSnapshot.endDate),
    getValidationSnapshot(db),
    getRaceArchiveIndex(db)
  ]);
  const historicalRows = hasThreeMonthData ? threeMonthSnapshot.combined : fallbackSnapshot.combined;
  const historicalMonthly = hasThreeMonthData
    ? monthlyFromHistorical(threeMonthSnapshot.monthly)
    : monthlyFromValidationDates(fallbackSnapshot.dates);
  const live = COURSES.map(({ name }) => fromLive(liveRows.find((row) => row.course === name) ?? {
    course: name, settledRaces: 0, betCount: 0, stakeYen: 0, returnYen: 0, profitYen: 0, roiPct: null, hitRatePct: null
  }));
  const historical = COURSES.map(({ name }) => fromValidation(historicalRows.find((row) => row.course === name) ?? emptyHistorical(name)));
  const combined = COURSES.map(({ name }) => combine(live.find((row) => row.course === name)!, historical.find((row) => row.course === name)!));
  const monthly = mergeMonthly(liveMonthlyRows, historicalMonthly);

  html = replaceMetricArea(html, combined, threeMonthSnapshot.complete);
  html = removeLegacyValidationNotice(html);
  html = injectAfterMetrics(html, historyOverview(monthly, combined, threeMonthSnapshot));
  html = injectBeforeDayTabs(html, renderRaceArchiveIndex(archiveRows));
  html = markSelectedCards(html)
    .replace(/買い目あり/g, "選出レース")
    .replace("本番成績と遡及検証を分離し、期待値基準未達は見送ります。", "過去検証と本番を重複させず、集計済みの全期間へ積み上げます。")
    .replace("各会場から原則5Rを選出し、期待値厳選と会場上位補完を分けて集計します。", "各会場から原則5Rを選出し、全開催日へ月別一覧から移動できます。")
    .replace("各会場から原則5Rを選出し、過去レースと本番を同じ総合成績に合算します。", "各会場から原則5Rを選出し、全開催日へ月別一覧から移動できます。")
    .replace("各会場から原則5Rを選出し、過去3ヶ月と本番を同じ総合成績に合算します。", "各会場から原則5Rを選出し、全開催日へ月別一覧から移動できます。")
    .replace(/<title>レース探偵[^<]*<\/title>/, "<title>レース探偵｜全期間成績と全レース</title>");
  html = injectHomeStyles(html);
  return injectSelectionCountScript(html);
}
