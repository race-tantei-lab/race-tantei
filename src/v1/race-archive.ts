import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

export interface RaceArchiveDateSummary {
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

interface ArchiveRaceRow {
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
  lightPending: number;
  lightStake: number;
  lightReturn: number;
  standardCount: number;
  standardPending: number;
  standardStake: number;
  standardReturn: number;
  premiumCount: number;
  premiumPending: number;
  premiumStake: number;
  premiumReturn: number;
}

function numberValue(value: unknown): number {
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

function monthLabel(month: string): string {
  const match = month.match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[1])}年${Number(match[2])}月` : month;
}

function timeLabel(value: string | null): string {
  return value?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定";
}

export function historyDateFromPath(pathname: string): string | null {
  const prefix = "/history/";
  if (!pathname.startsWith(prefix)) return null;
  const value = decodeURIComponent(pathname.slice(prefix.length));
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

export async function getRaceArchiveIndex(db: D1Database): Promise<RaceArchiveDateSummary[]> {
  const rows = await db.prepare(`
    SELECT r.race_date AS raceDate,
      COUNT(DISTINCT r.race_id) AS totalRaces,
      COUNT(DISTINCT r.venue) AS venueCount,
      GROUP_CONCAT(DISTINCT r.venue) AS venues,
      COUNT(DISTINCT CASE WHEN EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id AND p.status='locked'
      ) THEN r.race_id END) AS processedRaces,
      COUNT(DISTINCT CASE WHEN EXISTS (
        SELECT 1 FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        WHERE b.race_id=r.race_id AND p.status='locked'
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ) THEN r.race_id END) AS selectedRaces,
      COUNT(DISTINCT CASE WHEN EXISTS (
        SELECT 1 FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        WHERE b.race_id=r.race_id AND p.status='locked' AND b.return_yen>0
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ) THEN r.race_id END) AS hitRaces
    FROM rt_races r
    WHERE r.status='finished'
    GROUP BY r.race_date
    ORDER BY r.race_date DESC
  `).all<ArchiveIndexRow>();

  return rows.results.map((row) => ({
    raceDate: row.raceDate,
    totalRaces: numberValue(row.totalRaces),
    venueCount: numberValue(row.venueCount),
    venues: (row.venues ?? "").split(",").map((value) => value.trim()).filter(Boolean),
    processedRaces: numberValue(row.processedRaces),
    selectedRaces: numberValue(row.selectedRaces),
    hitRaces: numberValue(row.hitRaces)
  }));
}

export function renderRaceArchiveIndex(rows: RaceArchiveDateSummary[]): string {
  if (rows.length === 0) {
    return `<section class="archive-home" id="race-archive"><div class="section-label"><h2>全レース</h2><span>開催日別</span></div><div class="archive-empty">保存済みレースはまだありません。</div></section>`;
  }

  const months = [...new Set(rows.map((row) => row.raceDate.slice(0, 7)))];
  const latestMonth = months[0];
  const blocks = months.map((month) => {
    const dates = rows.filter((row) => row.raceDate.startsWith(month));
    const total = dates.reduce((sum, row) => sum + row.totalRaces, 0);
    const selected = dates.reduce((sum, row) => sum + row.selectedRaces, 0);
    const links = dates.map((row) => `<a class="archive-date" href="/history/${encodeURIComponent(row.raceDate)}">
      <div><b>${escapeHtml(dateLabel(row.raceDate))}</b><span>${escapeHtml(row.venues.join("・") || `${row.venueCount}会場`)}</span></div>
      <div class="archive-date-stats"><strong>${row.totalRaces}R</strong><span>選出 ${row.selectedRaces}R${row.processedRaces < row.totalRaces ? `・集計 ${row.processedRaces}/${row.totalRaces}` : ""}</span></div>
    </a>`).join("");
    return `<details class="archive-month" ${month === latestMonth ? "open" : ""}>
      <summary><div><b>${escapeHtml(monthLabel(month))}</b><span>${dates.length}開催日</span></div><strong>${selected}/${total}R選出</strong></summary>
      <div class="archive-date-grid">${links}</div>
    </details>`;
  }).join("");

  return `<section class="archive-home" id="race-archive">
    <div class="section-label archive-title"><div><h2>全レース</h2><p>月から開催日を選ぶと、その日の全会場・全レースを表示します。</p></div><span>${rows.length}開催日</span></div>
    <div class="archive-month-list">${blocks}</div>
  </section>`;
}

function courseValues(row: ArchiveRaceRow, course: BudgetCourse): { count: number; pending: number; stake: number; returns: number } {
  if (course === "ライト") return { count: row.lightCount, pending: row.lightPending, stake: row.lightStake, returns: row.lightReturn };
  if (course === "スタンダード") return { count: row.standardCount, pending: row.standardPending, stake: row.standardStake, returns: row.standardReturn };
  return { count: row.premiumCount, pending: row.premiumPending, stake: row.premiumStake, returns: row.premiumReturn };
}

function raceCategory(row: ArchiveRaceRow): string {
  const values = COURSES.map((course) => courseValues(row, course));
  if (values.some((value) => value.returns > 0)) return "selected hit";
  if (values.some((value) => value.count > 0)) return "selected miss";
  return "unselected";
}

function courseLine(row: ArchiveRaceRow, course: BudgetCourse): string {
  const value = courseValues(row, course);
  if (value.count === 0) {
    return `<div class="archive-course muted"><b>${escapeHtml(course)}</b><span>未選出</span><strong>—</strong><em>—</em></div>`;
  }
  if (value.pending > 0) {
    return `<div class="archive-course pending"><b>${escapeHtml(course)}</b><span>${value.count}点・精算中</span><strong>${formatYen(value.stake)}</strong><em>—</em></div>`;
  }
  const profit = value.returns - value.stake;
  const hit = value.returns > 0;
  return `<div class="archive-course ${hit ? "won" : "lost"}"><b>${escapeHtml(course)}</b><span>${hit ? "的中" : "不的中"}・${value.count}点</span><strong>${formatYen(value.returns)}</strong><em>${signedYen(profit)}</em></div>`;
}

function raceCard(row: ArchiveRaceRow, liveModel: string): string {
  const selected = COURSES.some((course) => courseValues(row, course).count > 0);
  const hitCourses = COURSES.filter((course) => courseValues(row, course).returns > 0).length;
  const retrospective = Boolean(row.modelVersion && row.modelVersion !== liveModel);
  const status = !row.modelVersion
    ? `<span class="archive-status neutral">集計待ち</span>`
    : selected
      ? hitCourses > 0
        ? `<span class="archive-status hit">的中 ${hitCourses}/3</span>`
        : `<span class="archive-status miss">不的中</span>`
      : `<span class="archive-status skip">未選出</span>`;

  return `<a class="archive-race" data-race-category="${raceCategory(row)}" href="/races/${encodeURIComponent(row.raceId)}">
    <div class="archive-race-top"><div><b>${row.raceNo}R</b><span>${timeLabel(row.startTimeJst)}</span></div>${status}</div>
    <h3>${escapeHtml(row.raceName)}</h3>
    ${retrospective ? `<div class="archive-retro">過去検証</div>` : ""}
    <div class="archive-winner">1着 <b>${row.winnerHorseNo ?? "—"}</b> ${escapeHtml(row.winnerHorseName ?? "取得中")}</div>
    ${row.topHorseNo === null ? "" : `<div class="archive-pick">予想◎ ${row.topHorseNo} ${escapeHtml(row.topHorseName ?? "")}</div>`}
    ${COURSES.map((course) => courseLine(row, course)).join("")}
  </a>`;
}

async function loadArchiveDate(db: D1Database, raceDate: string, liveModel: string): Promise<ArchiveRaceRow[]> {
  const rows = await db.prepare(`
    WITH candidates AS (
      SELECT p.id, p.race_id, p.model_version,
        ROW_NUMBER() OVER (
          PARTITION BY p.race_id
          ORDER BY CASE
            WHEN p.model_version=? THEN 1
            WHEN p.model_version=('validation-' || r.race_date || '-roi-policy-v1-3m') THEN 2
            ELSE 9
          END, p.id DESC
        ) AS rn
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date=? AND p.status='locked'
    ), chosen AS (
      SELECT id, race_id, model_version FROM candidates WHERE rn=1
    )
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
      r.race_name AS raceName, r.start_time_jst AS startTimeJst,
      p.model_version AS modelVersion,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
        WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightCount,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%' AND settlement_status<>'settled'),0) AS lightPending,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightReturn,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardCount,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%' AND settlement_status<>'settled'),0) AS standardPending,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardReturn,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumCount,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%' AND settlement_status<>'settled'),0) AS premiumPending,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumReturn
    FROM rt_races r
    LEFT JOIN chosen p ON p.race_id=r.race_id
    WHERE r.race_date=? AND r.status='finished'
    ORDER BY r.venue, r.race_no
  `).bind(liveModel, raceDate, raceDate).all<ArchiveRaceRow>();

  return rows.results.map((row) => ({
    ...row,
    raceNo: numberValue(row.raceNo),
    lightCount: numberValue(row.lightCount),
    lightPending: numberValue(row.lightPending),
    lightStake: numberValue(row.lightStake),
    lightReturn: numberValue(row.lightReturn),
    standardCount: numberValue(row.standardCount),
    standardPending: numberValue(row.standardPending),
    standardStake: numberValue(row.standardStake),
    standardReturn: numberValue(row.standardReturn),
    premiumCount: numberValue(row.premiumCount),
    premiumPending: numberValue(row.premiumPending),
    premiumStake: numberValue(row.premiumStake),
    premiumReturn: numberValue(row.premiumReturn)
  }));
}

export async function renderRaceArchiveDate(db: D1Database, raceDate: string, liveModel: string): Promise<string | null> {
  const rows = await loadArchiveDate(db, raceDate, liveModel);
  if (rows.length === 0) return null;
  const venues = [...new Set(rows.map((row) => row.venue))];
  const selected = rows.filter((row) => COURSES.some((course) => courseValues(row, course).count > 0)).length;
  const hits = rows.filter((row) => COURSES.some((course) => courseValues(row, course).returns > 0)).length;
  const venueLinks = venues.map((venue) => `<a href="#venue-${encodeURIComponent(venue)}">${escapeHtml(venue)} <span>${rows.filter((row) => row.venue === venue).length}</span></a>`).join("");
  const venueSections = venues.map((venue) => `<section class="archive-venue" id="venue-${encodeURIComponent(venue)}">
    <div class="archive-venue-head"><h2>${escapeHtml(venue)}</h2><span>${rows.filter((row) => row.venue === venue).length}R</span></div>
    <div class="archive-race-grid">${rows.filter((row) => row.venue === venue).map((row) => raceCard(row, liveModel)).join("")}</div>
  </section>`).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#08111b"><title>${escapeHtml(dateLabel(raceDate))} 全レース｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#08111b;--panel:#101b28;--panel2:#0c1622;--line:#2a3b4f;--text:#f2f6fa;--muted:#9eafc2;--green:#53dfb0;--red:#ff827a;--gold:#ffd287}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}a{color:inherit;text-decoration:none}.wrap{max-width:1180px;margin:auto;padding:15px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0 18px}.brand{font-size:24px;font-weight:900;color:var(--green)}.top nav{display:flex;gap:8px}.top nav a{border:1px solid var(--line);border-radius:999px;padding:8px 11px;font-size:12px}.hero{border:1px solid var(--line);border-radius:20px;padding:18px;background:linear-gradient(135deg,#122335,#0c1d19)}.hero h1{margin:0 0 8px}.hero p{margin:0;color:var(--muted)}.archive-filter{display:flex;gap:8px;overflow:auto;margin:14px 0 8px}.archive-filter button{appearance:none;border:1px solid var(--line);border-radius:999px;padding:9px 13px;background:var(--panel2);color:var(--text);white-space:nowrap}.archive-filter button.active{border-color:var(--green);color:var(--green)}.archive-venue-nav{display:flex;gap:8px;overflow:auto;position:sticky;top:0;z-index:3;padding:9px 0;background:rgba(8,17,27,.94);backdrop-filter:blur(8px)}.archive-venue-nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 12px}.archive-venue-nav span{color:var(--green)}.archive-venue{scroll-margin-top:60px;margin-top:22px}.archive-venue-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:9px}.archive-venue-head h2{margin:0}.archive-venue-head span{color:var(--muted)}.archive-race-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.archive-race{display:block;border:1px solid var(--line);border-radius:17px;padding:14px;background:var(--panel);min-width:0}.archive-race[hidden]{display:none}.archive-race-top{display:flex;justify-content:space-between;align-items:center}.archive-race-top>div{display:flex;align-items:baseline;gap:8px}.archive-race-top b{font-size:24px}.archive-race-top div span{color:var(--muted);font-size:12px}.archive-status{border-radius:999px;padding:5px 8px;font-size:11px;font-weight:900}.archive-status.hit{background:#153c31;color:#8df0ce}.archive-status.miss{background:#3b2226;color:#ff9d96}.archive-status.skip{background:#30291b;color:#e8c683}.archive-status.neutral{background:#1a2a3b;color:#b7c9dc}.archive-race h3{margin:10px 0 8px;font-size:15px;min-height:38px}.archive-retro{color:var(--muted);font-size:10px}.archive-winner{margin:7px 0;color:var(--gold);font-size:13px}.archive-pick{margin:7px 0;color:var(--green);font-size:12px}.archive-course{display:grid;grid-template-columns:82px 1fr auto auto;gap:7px;align-items:center;border-top:1px solid var(--line);padding:8px 0;font-size:11px}.archive-course strong{text-align:right}.archive-course em{font-style:normal;font-weight:900}.archive-course.won span,.archive-course.won em{color:var(--green)}.archive-course.lost span,.archive-course.lost em{color:var(--red)}.archive-course.muted{color:var(--muted)}.archive-course.pending span{color:var(--gold)}@media(max-width:900px){.archive-race-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.archive-race-grid{grid-template-columns:1fr}.archive-course{grid-template-columns:78px 1fr auto auto}.wrap{padding:12px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav><a href="/#race-archive">開催日一覧</a><a href="/performance">成績</a></nav></header><section class="hero"><h1>${escapeHtml(dateLabel(raceDate))} 全レース</h1><p>${rows.length}R・${venues.length}会場　選出${selected}R　的中レース${hits}R</p></section><div class="archive-filter"><button type="button" data-filter="all" class="active">全レース ${rows.length}</button><button type="button" data-filter="selected">選出 ${selected}</button><button type="button" data-filter="hit">的中 ${hits}</button></div><nav class="archive-venue-nav">${venueLinks}</nav>${venueSections}</main><script>(()=>{const buttons=[...document.querySelectorAll('[data-filter]')];const cards=[...document.querySelectorAll('[data-race-category]')];const apply=(filter)=>{buttons.forEach(button=>button.classList.toggle('active',button.dataset.filter===filter));cards.forEach(card=>{const values=(card.dataset.raceCategory||'').split(' ');card.hidden=filter!=='all'&&!values.includes(filter)})};buttons.forEach(button=>button.addEventListener('click',()=>apply(button.dataset.filter||'all')));})();</script></body></html>`;
}
