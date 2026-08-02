import { getPhaseBDashboard } from "./phase-b-dashboard.js";
import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";
import { getValidationSnapshot, VALIDATION_CONFIGS } from "./validation.js";

const COURSES: Array<{ name: BudgetCourse; budget: number; key: "light" | "standard" | "premium" }> = [
  { name: "ライト", budget: 2000, key: "light" },
  { name: "スタンダード", budget: 5000, key: "standard" },
  { name: "プレミアム", budget: 10000, key: "premium" }
];

interface LiveMetric {
  course: BudgetCourse;
  stake: number;
  returns: number;
  races: number;
  hits: number;
}

interface ValidationRaceRow {
  raceId: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  predictionId: number | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
  betCount: number;
  lightCount: number;
  lightStake: number;
  lightReturn: number;
  standardCount: number;
  standardStake: number;
  standardReturn: number;
  premiumCount: number;
  premiumStake: number;
  premiumReturn: number;
}

function toNumber(value: unknown): number {
  return Number(value ?? 0);
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function timeLabel(value: string | null): string {
  return value?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定";
}

function metricCard(metric: LiveMetric, budget: number): string {
  const roi = metric.stake > 0 ? metric.returns / metric.stake * 100 : null;
  const profit = metric.returns - metric.stake;
  return `<a class="metric" href="/performance">
    <div class="metric-head"><b>${escapeHtml(metric.course)}</b><span>${formatYen(budget)}</span></div>
    <strong>${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong>
    <small>${metric.hits}/${metric.races}R的中　${formatYen(metric.stake)} → ${formatYen(metric.returns)}</small>
    <em class="${profit >= 0 ? "plus" : "minus"}">${signedYen(profit)}</em>
  </a>`;
}

async function getLiveMetrics(db: D1Database, liveModel: string): Promise<LiveMetric[]> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
      COALESCE(SUM(b.stake_yen),0) AS stake,
      COALESCE(SUM(b.return_yen),0) AS returns,
      COUNT(DISTINCT b.race_id) AS races,
      COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hits
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE p.model_version=? AND p.status='locked' AND b.settlement_status='settled'
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(liveModel).all<LiveMetric>();
  const map = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map(({ name }) => ({
    course: name,
    stake: toNumber(map.get(name)?.stake),
    returns: toNumber(map.get(name)?.returns),
    races: toNumber(map.get(name)?.races),
    hits: toNumber(map.get(name)?.hits)
  }));
}

function replaceMetrics(html: string, metrics: LiveMetric[]): string {
  const start = html.indexOf('<div class="section-label">');
  const metricsStart = html.indexOf('<section class="metrics">', start);
  const end = html.indexOf("</section>", metricsStart);
  if (start < 0 || metricsStart < 0 || end < 0) return html;
  const replacement = `<div class="section-label"><h2>本番公開成績</h2><span>遡及検証を含まない</span></div><section class="metrics">${COURSES.map(({ name, budget }) => metricCard(metrics.find((row) => row.course === name) ?? { course: name, stake: 0, returns: 0, races: 0, hits: 0 }, budget)).join("")}</section>`;
  return `${html.slice(0, start)}${replacement}${html.slice(end + "</section>".length)}`;
}

function replaceRaceCard(html: string, raceId: string, replacement: string): string {
  const href = `href="/races/${encodeURIComponent(raceId)}"`;
  const hrefAt = html.indexOf(href);
  if (hrefAt < 0) return html;
  const start = html.lastIndexOf('<a class="race-card"', hrefAt);
  const endAt = html.indexOf("</a>", hrefAt);
  if (start < 0 || endAt < 0) return html;
  return `${html.slice(0, start)}${replacement}${html.slice(endAt + 4)}`;
}

function courseValue(row: ValidationRaceRow, key: "light" | "standard" | "premium"): { count: number; stake: number; returns: number } {
  if (key === "light") return { count: row.lightCount, stake: row.lightStake, returns: row.lightReturn };
  if (key === "standard") return { count: row.standardCount, stake: row.standardStake, returns: row.standardReturn };
  return { count: row.premiumCount, stake: row.premiumStake, returns: row.premiumReturn };
}

function validationRaceCard(row: ValidationRaceRow): string {
  if (row.predictionId === null) {
    return `<a class="race-card" data-race-category="finished" href="/races/${encodeURIComponent(row.raceId)}">
      <div class="race-top"><div><b>${row.raceNo}R</b><span>${timeLabel(row.startTimeJst)}</span></div><span class="status neutral">検証計算中</span></div>
      <h4>${escapeHtml(row.raceName)}</h4><div class="retro">フェーズC遡及検証</div>
      <div class="winner">1着 <b>${row.winnerHorseNo ?? "—"}</b> ${escapeHtml(row.winnerHorseName ?? "取得中")}</div>
      <div class="card-note">新しい期待値エンジンで再計算しています。</div>
    </a>`;
  }

  const hits = COURSES.filter(({ key }) => courseValue(row, key).returns > 0).length;
  const status = row.betCount === 0
    ? `<span class="status skip">見送り</span>`
    : hits > 0
      ? `<span class="status hit">的中 ${hits}/3</span>`
      : `<span class="status miss">不的中</span>`;
  const courseRows = COURSES.map(({ name, key }) => {
    const value = courseValue(row, key);
    if (value.count === 0) return `<div class="course-result"><b>${name}</b><span>見送り</span><strong>—</strong><em>±0円</em></div>`;
    const profit = value.returns - value.stake;
    return `<div class="course-result ${value.returns > 0 ? "won" : "lost"}"><b>${name}</b><span>${value.returns > 0 ? "的中" : "不的中"}</span><strong>${formatYen(value.returns)}</strong><em>${signedYen(profit)}</em></div>`;
  }).join("");

  return `<a class="race-card" data-race-category="finished" href="/races/${encodeURIComponent(row.raceId)}">
    <div class="race-top"><div><b>${row.raceNo}R</b><span>${timeLabel(row.startTimeJst)}</span></div>${status}</div>
    <h4>${escapeHtml(row.raceName)}</h4><div class="retro">フェーズC遡及検証</div>
    <div class="winner">1着 <b>${row.winnerHorseNo ?? "—"}</b> ${escapeHtml(row.winnerHorseName ?? "取得中")}</div>
    ${row.betCount === 0 ? `<div class="card-note">全コースで期待値基準未達のため見送りました。</div>` : courseRows}
  </a>`;
}

async function getValidationRaces(db: D1Database, liveModel: string): Promise<ValidationRaceRow[]> {
  const all: ValidationRaceRow[] = [];
  for (const config of VALIDATION_CONFIGS) {
    const rows = await db.prepare(`
      SELECT r.race_id AS raceId, r.race_no AS raceNo, r.race_name AS raceName,
        r.start_time_jst AS startTimeJst, p.id AS predictionId,
        (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
        (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
        (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
        (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
          WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName,
        COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id),0) AS betCount,
        COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightCount,
        COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightStake,
        COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightReturn,
        COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardCount,
        COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardStake,
        COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardReturn,
        COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumCount,
        COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumStake,
        COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumReturn
      FROM rt_races r
      LEFT JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
      WHERE r.race_date=? AND r.status='finished'
        AND NOT EXISTS (
          SELECT 1 FROM rt_predictions live
          WHERE live.race_id=r.race_id AND live.model_version=? AND live.status='locked'
        )
      ORDER BY r.venue, r.race_no
    `).bind(config.modelVersion, config.raceDate, liveModel).all<ValidationRaceRow>();
    all.push(...rows.results.map((row) => ({
      ...row,
      raceNo: toNumber(row.raceNo),
      betCount: toNumber(row.betCount),
      lightCount: toNumber(row.lightCount),
      lightStake: toNumber(row.lightStake),
      lightReturn: toNumber(row.lightReturn),
      standardCount: toNumber(row.standardCount),
      standardStake: toNumber(row.standardStake),
      standardReturn: toNumber(row.standardReturn),
      premiumCount: toNumber(row.premiumCount),
      premiumStake: toNumber(row.premiumStake),
      premiumReturn: toNumber(row.premiumReturn)
    })));
  }
  return all;
}

export async function getPhaseCDashboard(db: D1Database, liveModel: string): Promise<string> {
  let html = await getPhaseBDashboard(db, liveModel);
  const [metrics, validation, validationRaces] = await Promise.all([
    getLiveMetrics(db, liveModel),
    getValidationSnapshot(db),
    getValidationRaces(db, liveModel)
  ]);

  html = replaceMetrics(html, metrics);
  for (const row of validationRaces) html = replaceRaceCard(html, row.raceId, validationRaceCard(row));

  const validationNotice = `<div class="notice">フェーズC検証 ${validation.processedRaces}/${validation.totalRaces}R${validation.complete ? " 完了" : `・残り${validation.remainingRaces}R`}　<a href="/validation" style="color:inherit;text-decoration:underline">検証レポートを見る</a></div>`;
  const metricsEnd = html.indexOf("</section>", html.indexOf('<section class="metrics">'));
  if (metricsEnd >= 0) html = `${html.slice(0, metricsEnd + 10)}${validationNotice}${html.slice(metricsEnd + 10)}`;

  return html
    .replace(/<a href="\/backtest\/2026-08-01">検証<\/a>/, '<a href="/validation">検証</a>')
    .replace("期待値基準を満たした買い目だけを表示し、条件未達は見送ります。", "本番成績と遡及検証を分離し、期待値基準未達は見送ります。")
    .replace("<title>レース探偵｜期待値選別</title>", "<title>レース探偵｜フェーズC</title>");
}
