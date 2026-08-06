import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

const COURSES: Array<{ name: BudgetCourse; key: "light" | "standard" | "premium" }> = [
  { name: "ライト", key: "light" },
  { name: "スタンダード", key: "standard" },
  { name: "プレミアム", key: "premium" }
];

interface ProductionRaceRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  modelVersion: string | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
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

function n(value: unknown): number {
  return Number(value ?? 0);
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function dateLabel(date: string): string {
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return date;
  const weekday = ["日", "月", "火", "水", "木", "金", "土"][
    new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  ];
  return `${Number(match[2])}月${Number(match[3])}日（${weekday}）`;
}

function timeLabel(value: string | null): string {
  return value?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定";
}

function courseValue(
  race: ProductionRaceRow,
  key: "light" | "standard" | "premium"
): { count: number; stake: number; returns: number } {
  if (key === "light") return { count: race.lightCount, stake: race.lightStake, returns: race.lightReturn };
  if (key === "standard") return { count: race.standardCount, stake: race.standardStake, returns: race.standardReturn };
  return { count: race.premiumCount, stake: race.premiumStake, returns: race.premiumReturn };
}

function isSelected(race: ProductionRaceRow): boolean {
  return COURSES.some(({ key }) => courseValue(race, key).count > 0);
}

function raceCard(race: ProductionRaceRow): string {
  const selected = isSelected(race);
  const hitCourses = COURSES.filter(({ key }) => courseValue(race, key).returns > 0).length;
  const status = !selected
    ? `<span class="status skip">未選出</span>`
    : hitCourses > 0
      ? `<span class="status hit">的中 ${hitCourses}/3</span>`
      : `<span class="status miss">不的中</span>`;
  const courseRows = selected
    ? COURSES.map(({ name, key }) => {
        const value = courseValue(race, key);
        const hit = value.returns > 0;
        return `<div class="course-result ${hit ? "won" : "lost"}"><b>${escapeHtml(name)}</b><span>${hit ? "的中" : "不的中"}</span><strong>${formatYen(value.returns)}</strong><em>${signedYen(value.returns - value.stake)}</em></div>`;
      }).join("")
    : `<div class="card-note">会場内のv4選出上位5Rに入りませんでした。</div>`;
  const backfill = race.raceDate === "2026-08-01" || race.raceDate === "2026-08-02";
  return `<a class="race-card" ${selected ? 'data-race-selected="true" ' : ""}data-race-category="${selected ? "buy finished" : "finished"}" href="/races/${encodeURIComponent(race.raceId)}">
    <div class="race-top"><div><b>${race.raceNo}R</b><span>${timeLabel(race.startTimeJst)}</span></div>${status}</div>
    <h4>${escapeHtml(race.raceName)}</h4>
    ${backfill ? `<div class="retro">8月v4再計算</div>` : `<div class="retro">発走前公開v4</div>`}
    <div class="winner">1着 <b>${race.winnerHorseNo ?? "—"}</b> ${escapeHtml(race.winnerHorseName ?? "取得中")}</div>
    ${race.topHorseNo === null ? "" : `<div class="pick">予想◎ ${race.topHorseNo} ${escapeHtml(race.topHorseName ?? "")}</div>`}
    ${courseRows}
  </a>`;
}

function dailyTotals(races: ProductionRaceRow[]): string {
  return `<div class="production-day-totals">${COURSES.map(({ name, key }) => {
    const values = races.map((race) => courseValue(race, key)).filter((value) => value.count > 0);
    const stake = values.reduce((sum, value) => sum + value.stake, 0);
    const returns = values.reduce((sum, value) => sum + value.returns, 0);
    const roi = stake > 0 ? returns / stake * 100 : null;
    return `<div class="production-day-total"><b>${escapeHtml(name)}</b><strong class="${roi !== null && roi >= 100 ? "plus" : "minus"}">${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong><span>${values.length}R　${formatYen(stake)} → ${formatYen(returns)}</span></div>`;
  }).join("")}</div>`;
}

function dayPanel(date: string, races: ProductionRaceRow[]): string {
  const venues = [...new Set(races.map((race) => race.venue))];
  const selected = races.filter(isSelected).length;
  const venueButtons = venues.map((venue) => {
    const count = races.filter((race) => race.venue === venue && isSelected(race)).length;
    return `<button type="button" data-venue-tab="${escapeHtml(venue)}" data-buy-count="${count}"><b>${escapeHtml(venue)}</b>${count > 0 ? `<span>${count}</span>` : ""}</button>`;
  }).join("");
  const venuePanels = venues.map((venue) => {
    const venueRaces = races.filter((race) => race.venue === venue);
    return `<section class="venue-panel" data-venue-panel="${escapeHtml(venue)}" hidden><div class="race-rail">${venueRaces.map(raceCard).join("")}</div><div class="no-races" hidden>この条件に該当するレースはありません。</div></section>`;
  }).join("");
  return `<section class="day-panel" data-day-panel="${date}" data-default-filter="buy" hidden>
    <div class="day-summary"><div><h2>${escapeHtml(dateLabel(date))}</h2><span>${races.length}R</span></div><p>選出レース ${selected}R　終了 ${races.length}R</p></div>
    ${dailyTotals(races)}
    <div class="filter-tabs" role="group" aria-label="表示するレース">
      <button type="button" data-filter="buy">選出レース <span>${selected}</span></button>
      <button type="button" data-filter="all">全レース <span>${races.length}</span></button>
      <button type="button" data-filter="finished">終了 <span>${races.length}</span></button>
    </div>
    <div class="venue-tabs">${venueButtons}</div>${venuePanels}
  </section>`;
}

async function loadProductionRaces(
  db: D1Database,
  modelVersion: string,
  startDate: string
): Promise<ProductionRaceRow[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
      r.race_name AS raceName, r.start_time_jst AS startTimeJst, p.model_version AS modelVersion,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
        WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName,
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
    WHERE r.race_date>=? AND r.status='finished'
    ORDER BY r.race_date DESC, r.venue, r.race_no
    LIMIT 360
  `).bind(modelVersion, startDate).all<ProductionRaceRow>();
  return rows.results.map((row) => ({
    ...row,
    raceNo: n(row.raceNo),
    lightCount: n(row.lightCount), lightStake: n(row.lightStake), lightReturn: n(row.lightReturn),
    standardCount: n(row.standardCount), standardStake: n(row.standardStake), standardReturn: n(row.standardReturn),
    premiumCount: n(row.premiumCount), premiumStake: n(row.premiumStake), premiumReturn: n(row.premiumReturn)
  }));
}

export async function renderProductionLatestDetail(
  db: D1Database,
  modelVersion: string,
  startDate = "2026-08-01"
): Promise<string> {
  const rows = await loadProductionRaces(db, modelVersion, startDate);
  if (rows.length === 0) return "";
  const dates = [...new Set(rows.map((row) => row.raceDate))];
  const tabs = dates.map((date) => `<button type="button" data-day-tab="${date}">${escapeHtml(dateLabel(date))}</button>`).join("");
  const panels = dates.map((date) => dayPanel(date, rows.filter((row) => row.raceDate === date))).join("");
  return `<div class="section-label latest-label"><h2>最新開催の詳細</h2><span>上の集計と同じv4予想IDのみ</span></div>
    <style>.production-day-totals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:0 0 10px}.production-day-total{border:1px solid var(--line);border-radius:12px;background:#0d1722;padding:9px}.production-day-total b,.production-day-total strong,.production-day-total span{display:block}.production-day-total strong{margin:3px 0;font-size:18px}.production-day-total span{color:var(--muted);font-size:10px}@media(max-width:720px){.production-day-totals{grid-template-columns:1fr}}</style>
    <nav class="day-tabs" aria-label="開催日">${tabs}</nav>${panels}`;
}
