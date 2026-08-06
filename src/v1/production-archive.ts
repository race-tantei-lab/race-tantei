import { escapeHtml } from "./utils.js";

export interface ProductionArchiveDateSummary {
  raceDate: string;
  totalRaces: number;
  venueCount: number;
  venues: string[];
  processedRaces: number;
  selectedRaces: number;
  hitRaces: number;
}

interface ArchiveIndexRow {
  raceDate: string;
  totalRaces: number;
  venueCount: number;
  venues: string | null;
  processedRaces: number;
  selectedRaces: number;
  hitRaces: number;
}

function n(value: unknown): number {
  return Number(value ?? 0);
}

function dateLabel(date: string): string {
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return date;
  const weekday = ["日", "月", "火", "水", "木", "金", "土"][
    new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  ];
  return `${Number(match[2])}月${Number(match[3])}日（${weekday}）`;
}

function monthLabel(month: string): string {
  const match = month.match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[1])}年${Number(match[2])}月` : month;
}

export async function getProductionRaceArchiveIndex(
  db: D1Database,
  modelVersion: string,
  startDate: string
): Promise<ProductionArchiveDateSummary[]> {
  const rows = await db.prepare(`
    WITH chosen AS (
      SELECT p.id,p.race_id
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE p.status='locked'
        AND p.model_version=?
        AND r.status='finished'
        AND r.race_date>=?
    ), ticket_state AS (
      SELECT c.race_id,
        MAX(CASE WHEN b.id IS NOT NULL THEN 1 ELSE 0 END) AS selected,
        MAX(CASE WHEN b.return_yen>0 THEN 1 ELSE 0 END) AS hit
      FROM chosen c
      LEFT JOIN rt_bets b ON b.prediction_id=c.id
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      GROUP BY c.race_id
    )
    SELECT r.race_date AS raceDate,
      COUNT(*) AS totalRaces,
      COUNT(DISTINCT r.venue) AS venueCount,
      GROUP_CONCAT(DISTINCT r.venue) AS venues,
      SUM(CASE WHEN c.id IS NULL THEN 0 ELSE 1 END) AS processedRaces,
      SUM(COALESCE(t.selected,0)) AS selectedRaces,
      SUM(COALESCE(t.hit,0)) AS hitRaces
    FROM rt_races r
    LEFT JOIN chosen c ON c.race_id=r.race_id
    LEFT JOIN ticket_state t ON t.race_id=r.race_id
    WHERE r.status='finished' AND r.race_date>=?
    GROUP BY r.race_date
    ORDER BY r.race_date DESC
  `).bind(modelVersion, startDate, startDate).all<ArchiveIndexRow>();

  return rows.results.map((row) => ({
    raceDate: row.raceDate,
    totalRaces: n(row.totalRaces),
    venueCount: n(row.venueCount),
    venues: (row.venues ?? "").split(",").map((value) => value.trim()).filter(Boolean),
    processedRaces: n(row.processedRaces),
    selectedRaces: n(row.selectedRaces),
    hitRaces: n(row.hitRaces)
  }));
}

export function renderProductionRaceArchiveIndex(rows: ProductionArchiveDateSummary[]): string {
  if (rows.length === 0) {
    return `<section class="archive-home" id="race-archive"><div class="section-label"><h2>2026年8月以降の全レース</h2><span>v4モデルのみ</span></div><div class="archive-empty">8月の保存済みレースはまだありません。</div></section>`;
  }

  const months = [...new Set(rows.map((row) => row.raceDate.slice(0, 7)))];
  const blocks = months.map((month, monthIndex) => {
    const dates = rows.filter((row) => row.raceDate.startsWith(month));
    const total = dates.reduce((sum, row) => sum + row.totalRaces, 0);
    const selected = dates.reduce((sum, row) => sum + row.selectedRaces, 0);
    const links = dates.map((row) => {
      const progress = row.processedRaces < row.totalRaces
        ? `・v4計算 ${row.processedRaces}/${row.totalRaces}`
        : "";
      return `<a class="archive-date" href="/history/${encodeURIComponent(row.raceDate)}"><div><b>${escapeHtml(dateLabel(row.raceDate))}</b><span>${escapeHtml(row.venues.join("・") || `${row.venueCount}会場`)}</span></div><div class="archive-date-stats"><strong>${row.totalRaces}R</strong><span>選出 ${row.selectedRaces}R${progress}</span></div></a>`;
    }).join("");
    return `<details class="archive-month" ${monthIndex === 0 ? "open" : ""}><summary><div><b>${escapeHtml(monthLabel(month))}</b><span>${dates.length}開催日</span></div><strong>${selected}/${total}R選出</strong></summary><div class="archive-date-grid">${links}</div></details>`;
  }).join("");

  return `<section class="archive-home" id="race-archive"><div class="section-label archive-title"><div><h2>2026年8月以降の全レース</h2><p>現行v4モデルで再計算・公開したレースだけを表示します。7月以前の旧モデルは検証ページへ分離しています。</p></div><span>${rows.length}開催日</span></div><div class="archive-month-list">${blocks}</div></section>`;
}
