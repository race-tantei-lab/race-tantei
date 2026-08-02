import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

const AUG1_DATE = "2026-08-01";
const AUG1_MODEL = "backtest-2026-08-01-budget-courses-v3";
const AUG2_DATE = "2026-08-02";
const AUG2_MODEL = "backfill-2026-08-02-budget-courses-v1";

const COURSES: Array<{ name: BudgetCourse; budget: number; key: "light" | "standard" | "premium" }> = [
  { name: "ライト", budget: 2000, key: "light" },
  { name: "スタンダード", budget: 5000, key: "standard" },
  { name: "プレミアム", budget: 10000, key: "premium" }
];

interface DashboardRace {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  status: string;
  predictionStatus: string | null;
  modelVersion: string | null;
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

interface CourseMetric {
  course: BudgetCourse;
  stake: number;
  returns: number;
  races: number;
  hits: number;
}

function chosenCte(): string {
  return `
    candidate AS (
      SELECT p.*, r.race_date,
        CASE
          WHEN r.race_date='${AUG1_DATE}' AND p.model_version='${AUG1_MODEL}' THEN 1
          WHEN r.race_date='${AUG2_DATE}' AND p.model_version=? THEN 1
          WHEN r.race_date='${AUG2_DATE}' AND p.model_version='${AUG2_MODEL}' THEN 2
          WHEN r.race_date NOT IN ('${AUG1_DATE}','${AUG2_DATE}') AND p.model_version=? THEN 1
          ELSE 99
        END AS priority
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE EXISTS (
        SELECT 1 FROM rt_bets b
        WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      )
    ),
    ranked AS (
      SELECT candidate.*, ROW_NUMBER() OVER (PARTITION BY race_id ORDER BY priority, id DESC) AS rn
      FROM candidate WHERE priority<99
    ),
    chosen_prediction AS (SELECT * FROM ranked WHERE rn=1)
  `;
}

function toNumber(value: unknown): number {
  return Number(value ?? 0);
}

async function loadDashboard(db: D1Database, liveModel: string): Promise<{ races: DashboardRace[]; metrics: CourseMetric[]; progress: { completed: number; total: number } }> {
  const racesResult = await db.prepare(`
    WITH ${chosenCte()}
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
      r.race_name AS raceName, r.start_time_jst AS startTimeJst, r.status,
      p.status AS predictionStatus, p.model_version AS modelVersion,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name
       FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
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
    LEFT JOIN chosen_prediction p ON p.race_id=r.race_id
    WHERE r.race_date >= '${AUG1_DATE}'
    ORDER BY r.race_date DESC, r.venue, r.race_no
    LIMIT 180
  `).bind(liveModel, liveModel).all<DashboardRace>();

  const metricsResult = await db.prepare(`
    WITH ${chosenCte()},
    aug1_done AS (
      SELECT COUNT(DISTINCT race_id) AS count
      FROM chosen_prediction
      WHERE race_date='${AUG1_DATE}' AND model_version='${AUG1_MODEL}'
    )
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
    JOIN chosen_prediction p ON p.id=b.prediction_id
    WHERE b.settlement_status='settled'
      AND (p.race_date<>'${AUG1_DATE}' OR (SELECT count FROM aug1_done)>=36)
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(liveModel, liveModel).all<CourseMetric>();

  const [totalRow, completedRow] = await Promise.all([
    db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date=? AND status='finished'`)
      .bind(AUG1_DATE).first<{ count: number }>(),
    db.prepare(`
      SELECT COUNT(DISTINCT p.race_id) AS count
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date=? AND p.model_version=? AND p.status='locked'
        AND EXISTS (SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id AND b.settlement_status='settled')
    `).bind(AUG1_DATE, AUG1_MODEL).first<{ count: number }>()
  ]);

  const races = racesResult.results.map((race) => ({
    ...race,
    raceNo: toNumber(race.raceNo),
    betCount: toNumber(race.betCount),
    lightCount: toNumber(race.lightCount),
    lightStake: toNumber(race.lightStake),
    lightReturn: toNumber(race.lightReturn),
    standardCount: toNumber(race.standardCount),
    standardStake: toNumber(race.standardStake),
    standardReturn: toNumber(race.standardReturn),
    premiumCount: toNumber(race.premiumCount),
    premiumStake: toNumber(race.premiumStake),
    premiumReturn: toNumber(race.premiumReturn)
  }));

  const metricMap = new Map(metricsResult.results.map((metric) => [metric.course, metric]));
  const metrics = COURSES.map(({ name }) => {
    const metric = metricMap.get(name);
    return {
      course: name,
      stake: toNumber(metric?.stake),
      returns: toNumber(metric?.returns),
      races: toNumber(metric?.races),
      hits: toNumber(metric?.hits)
    };
  });

  return {
    races,
    metrics,
    progress: { completed: toNumber(completedRow?.count), total: toNumber(totalRow?.count) }
  };
}

function dateLabel(date: string): string {
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return date;
  const weekday = ["日", "月", "火", "水", "木", "金", "土"][new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()];
  return `${Number(match[2])}月${Number(match[3])}日（${weekday}）`;
}

function timeLabel(value: string | null): string {
  return value?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定";
}

function publishTime(value: string | null): string {
  const match = value?.match(/(\d{1,2}):(\d{2})/);
  if (!match) return "オッズ取得後に公開";
  const total = Number(match[1]) * 60 + Number(match[2]) - 60;
  const normalized = (total + 24 * 60) % (24 * 60);
  return `${String(Math.floor(normalized / 60)).padStart(2, "0")}:${String(normalized % 60).padStart(2, "0")}ごろ公開`;
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function courseValues(race: DashboardRace, key: "light" | "standard" | "premium"): { count: number; stake: number; returns: number } {
  if (key === "light") return { count: race.lightCount, stake: race.lightStake, returns: race.lightReturn };
  if (key === "standard") return { count: race.standardCount, stake: race.standardStake, returns: race.standardReturn };
  return { count: race.premiumCount, stake: race.premiumStake, returns: race.premiumReturn };
}

function category(race: DashboardRace): "buy" | "finished" | "other" {
  if (race.status === "finished") return "finished";
  if (race.betCount > 0) return "buy";
  return "other";
}

function statusBadge(race: DashboardRace): string {
  if (race.status === "finished") {
    if (race.betCount === 0) return `<span class="status neutral">結果反映中</span>`;
    const hits = COURSES.filter(({ key }) => courseValues(race, key).returns > 0).length;
    return hits > 0
      ? `<span class="status hit">的中 ${hits}/3</span>`
      : `<span class="status miss">不的中</span>`;
  }
  if (race.betCount > 0) {
    return race.predictionStatus === "locked"
      ? `<span class="status open">買い目確定</span>`
      : `<span class="status open">買い目あり</span>`;
  }
  if (race.predictionStatus === "locked") return `<span class="status skip">見送り</span>`;
  if (race.predictionStatus) return `<span class="status neutral">買い目調整中</span>`;
  return `<span class="status neutral">公開待ち</span>`;
}

function openCourseRows(race: DashboardRace): string {
  const rows = COURSES.map(({ name, key }) => {
    const value = courseValues(race, key);
    if (value.count === 0) return "";
    return `<div class="course-mini"><b>${name}</b><span>${value.count}点</span><strong>${formatYen(value.stake)}</strong></div>`;
  }).join("");
  return rows || `<div class="card-note">${race.predictionStatus ? "発走15分前まで買い目を調整します。" : publishTime(race.startTimeJst)}</div>`;
}

function finishedCourseRows(race: DashboardRace): string {
  if (race.betCount === 0) return `<div class="card-note">公式結果と買い目を照合しています。</div>`;
  return COURSES.map(({ name, key }) => {
    const value = courseValues(race, key);
    const profit = value.returns - value.stake;
    const hit = value.returns > 0;
    return `<div class="course-result ${hit ? "won" : "lost"}"><b>${name}</b><span>${hit ? "的中" : "不的中"}</span><strong>${formatYen(value.returns)}</strong><em>${signedYen(profit)}</em></div>`;
  }).join("");
}

function raceCard(race: DashboardRace): string {
  const retrospective = race.modelVersion === AUG1_MODEL || race.modelVersion === AUG2_MODEL;
  const body = race.status === "finished"
    ? `<div class="winner">1着 <b>${race.winnerHorseNo ?? "—"}</b> ${escapeHtml(race.winnerHorseName ?? "取得中")}</div>${finishedCourseRows(race)}`
    : `<div class="pick">◎ ${race.topHorseNo ?? "—"} ${escapeHtml(race.topHorseName ?? "予想生成前")}</div>${openCourseRows(race)}`;

  return `<a class="race-card" data-race-category="${category(race)}" href="/races/${encodeURIComponent(race.raceId)}">
    <div class="race-top"><div><b>${race.raceNo}R</b><span>${timeLabel(race.startTimeJst)}</span></div>${statusBadge(race)}</div>
    <h4>${escapeHtml(race.raceName)}</h4>
    ${retrospective ? `<div class="retro">遡及検証</div>` : ""}
    ${body}
  </a>`;
}

function metricCard(metric: CourseMetric, budget: number): string {
  const roi = metric.stake > 0 ? metric.returns / metric.stake * 100 : null;
  const profit = metric.returns - metric.stake;
  return `<a class="metric" href="/performance">
    <div class="metric-head"><b>${metric.course}</b><span>${formatYen(budget)}</span></div>
    <strong>${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong>
    <small>${metric.hits}/${metric.races}R的中　${formatYen(metric.stake)} → ${formatYen(metric.returns)}</small>
    <em class="${profit >= 0 ? "plus" : "minus"}">${signedYen(profit)}</em>
  </a>`;
}

function daySection(date: string, races: DashboardRace[]): string {
  const venues = [...new Set(races.map((race) => race.venue))];
  const buyCount = races.filter((race) => category(race) === "buy").length;
  const finishedCount = races.filter((race) => category(race) === "finished").length;
  const defaultFilter = buyCount > 0 ? "buy" : "all";

  const venueButtons = venues.map((venue) => {
    const venueRaces = races.filter((race) => race.venue === venue);
    const venueBuyCount = venueRaces.filter((race) => category(race) === "buy").length;
    return `<button type="button" data-venue-tab="${escapeHtml(venue)}" data-buy-count="${venueBuyCount}"><b>${escapeHtml(venue)}</b>${venueBuyCount > 0 ? `<span>${venueBuyCount}</span>` : ""}</button>`;
  }).join("");

  const venuePanels = venues.map((venue) => {
    const venueRaces = races.filter((race) => race.venue === venue);
    return `<section class="venue-panel" data-venue-panel="${escapeHtml(venue)}" hidden>
      <div class="race-rail">${venueRaces.map(raceCard).join("")}</div>
      <div class="no-races" hidden>この条件に該当するレースはありません。</div>
    </section>`;
  }).join("");

  return `<section class="day-panel" data-day-panel="${date}" data-default-filter="${defaultFilter}" hidden>
    <div class="day-summary"><div><h2>${dateLabel(date)}</h2><span>${races.length}R</span></div><p>買い目あり ${buyCount}R　終了 ${finishedCount}R</p></div>
    <div class="filter-tabs" role="group" aria-label="表示するレース">
      <button type="button" data-filter="buy">買い目あり <span>${buyCount}</span></button>
      <button type="button" data-filter="all">全レース <span>${races.length}</span></button>
      <button type="button" data-filter="finished">終了 <span>${finishedCount}</span></button>
    </div>
    <div class="venue-tabs">${venueButtons}</div>
    ${venuePanels}
  </section>`;
}

export async function getPhaseADashboard(db: D1Database, liveModel: string): Promise<string> {
  const { races, metrics, progress } = await loadDashboard(db, liveModel);
  const dates = [...new Set(races.map((race) => race.raceDate))];
  const metricHtml = COURSES.map(({ name, budget }) => metricCard(metrics.find((metric) => metric.course === name) ?? { course: name, stake: 0, returns: 0, races: 0, hits: 0 }, budget)).join("");
  const progressComplete = progress.total > 0 && progress.completed >= progress.total;
  const progressHtml = progressComplete ? "" : `<div class="notice">8月1日検証を集計中 ${progress.completed}/${progress.total || 36}R。完了するまで累計成績には含めません。</div>`;
  const dayTabs = dates.map((date) => `<button type="button" data-day-tab="${date}">${dateLabel(date)}</button>`).join("");
  const dayPanels = dates.map((date) => daySection(date, races.filter((race) => race.raceDate === date))).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>レース探偵</title><style>
  :root{color-scheme:dark;--bg:#071019;--panel:#101a25;--panel2:#0b141e;--line:#293b4e;--text:#f4f7fa;--muted:#93a6b9;--green:#52d5a5;--red:#ff7b72;--amber:#f0c36d}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}a{color:inherit;text-decoration:none}button{font:inherit}.wrap{max-width:1120px;margin:auto;padding:14px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0 15px}.brand{font-size:25px;font-weight:900;color:var(--green)}.links{display:flex;gap:7px;overflow:auto}.links a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;font-size:13px}.section-label{display:flex;justify-content:space-between;align-items:end;margin:5px 0 9px}.section-label h2{margin:0;font-size:17px}.section-label span{color:var(--muted);font-size:12px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.metric{position:relative;display:block;min-width:0;padding:13px;border:1px solid var(--line);border-radius:15px;background:var(--panel)}.metric-head{display:flex;justify-content:space-between;gap:8px}.metric-head span,.metric small{color:var(--muted);font-size:11px}.metric strong{display:block;font-size:23px;margin:5px 0 2px}.metric small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric em{display:block;margin-top:5px;font-style:normal;font-weight:900;font-size:13px}.plus{color:var(--green)}.minus{color:var(--red)}.notice{margin:11px 0 0;padding:10px 12px;border:1px solid #65552f;border-radius:12px;background:#241f13;color:#f2d28a;font-size:12px}.day-tabs{display:flex;gap:7px;overflow:auto;margin:17px 0 10px}.day-tabs button,.filter-tabs button,.venue-tabs button{appearance:none;border:1px solid var(--line);background:#0d1722;color:var(--text);border-radius:999px;white-space:nowrap}.day-tabs button{padding:9px 13px}.day-tabs button.active,.filter-tabs button.active,.venue-tabs button.active{border-color:var(--green);color:var(--green);background:#10231f}.day-panel[hidden],.venue-panel[hidden],.race-card[hidden]{display:none}.day-summary{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:2px 0 9px}.day-summary>div{display:flex;align-items:baseline;gap:8px}.day-summary h2{margin:0;font-size:21px}.day-summary span,.day-summary p{color:var(--muted);font-size:12px}.day-summary p{margin:0}.filter-tabs,.venue-tabs{display:flex;gap:7px;overflow:auto}.filter-tabs{margin-bottom:9px}.filter-tabs button{padding:8px 11px}.filter-tabs span{font-size:11px;opacity:.8}.venue-tabs{margin-bottom:10px}.venue-tabs button{display:flex;align-items:center;gap:6px;padding:8px 12px}.venue-tabs button span{display:inline-flex;align-items:center;justify-content:center;min-width:19px;height:19px;border-radius:999px;background:#174235;color:#8af0c9;font-size:11px;font-weight:900}.race-rail{display:grid;grid-auto-flow:column;grid-template-rows:repeat(2,minmax(0,1fr));grid-auto-columns:minmax(270px,320px);gap:9px;overflow-x:auto;padding:1px 0 12px;scroll-snap-type:x mandatory}.race-card{scroll-snap-align:start;display:block;padding:13px;border:1px solid var(--line);border-radius:16px;background:var(--panel);min-height:210px}.race-top{display:flex;justify-content:space-between;align-items:center;gap:10px}.race-top>div{display:flex;align-items:baseline;gap:8px}.race-top b{font-size:22px}.race-top div span{color:var(--muted);font-size:12px}.race-card h4{margin:9px 0 8px;min-height:38px;font-size:15px}.status{display:inline-block;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:900}.status.open,.status.hit{background:#153b31;color:#84eac6}.status.miss{background:#3a2023;color:#ff9b94}.status.skip{background:#3b2b1b;color:#f2c47b}.status.neutral{background:#1a2a3b;color:#b3c8dc}.retro{display:inline-block;margin-bottom:7px;color:#b8c9d9;font-size:10px}.pick{color:#8ee8cb;font-weight:900;margin-bottom:9px}.winner{margin:6px 0 8px;color:#ffd895;font-size:13px}.course-mini,.course-result{display:grid;align-items:center;gap:6px;border-top:1px solid var(--line);padding:7px 0;font-size:12px}.course-mini{grid-template-columns:86px 1fr auto}.course-mini span{color:var(--muted)}.course-result{grid-template-columns:76px 48px 1fr auto}.course-result span,.course-result em{font-size:11px}.course-result strong{text-align:right}.course-result em{font-style:normal;font-weight:900}.course-result.won span,.course-result.won em{color:var(--green)}.course-result.lost span,.course-result.lost em{color:var(--red)}.card-note{border-top:1px solid var(--line);padding-top:9px;color:var(--muted);font-size:12px}.no-races{padding:24px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);text-align:center}.footer{padding:25px 0 45px;color:var(--muted);font-size:11px;text-align:center}
  @media(max-width:720px){.metrics{display:flex;overflow:auto}.metric{flex:0 0 225px}.day-summary{align-items:flex-end}.day-summary p{max-width:150px;text-align:right}.race-rail{grid-auto-columns:minmax(260px,84vw)}.links a{padding:7px 9px}.brand{font-size:22px}}
  @media(max-width:380px){.race-rail{grid-template-rows:1fr}.day-summary p{display:none}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav class="links"><a href="/performance">成績</a><a href="/backtest/${AUG1_DATE}">検証</a></nav></header><div class="section-label"><h2>公開済み成績</h2><span>コース別</span></div><section class="metrics">${metricHtml}</section>${progressHtml}<nav class="day-tabs" aria-label="開催日">${dayTabs}</nav>${dayPanels}<footer class="footer">買い目・結果・収支を同じ基準で表示しています。</footer></main><script>(()=>{
    const dayTabs=[...document.querySelectorAll('[data-day-tab]')];
    const dayPanels=[...document.querySelectorAll('[data-day-panel]')];
    const setVenue=(panel,venue)=>{const tabs=[...panel.querySelectorAll('[data-venue-tab]')];const panels=[...panel.querySelectorAll('[data-venue-panel]')];tabs.forEach(tab=>tab.classList.toggle('active',tab.dataset.venueTab===venue));panels.forEach(item=>item.hidden=item.dataset.venuePanel!==venue);};
    const applyFilter=(panel,filter)=>{panel.dataset.filter=filter;panel.querySelectorAll('[data-filter]').forEach(button=>button.classList.toggle('active',button.dataset.filter===filter));panel.querySelectorAll('[data-race-category]').forEach(card=>{card.hidden=filter!=='all'&&card.dataset.raceCategory!==filter});panel.querySelectorAll('[data-venue-panel]').forEach(venuePanel=>{const visible=[...venuePanel.querySelectorAll('[data-race-category]')].some(card=>!card.hidden);const empty=venuePanel.querySelector('.no-races');if(empty)empty.hidden=visible});const activeVenue=panel.querySelector('[data-venue-tab].active');if(filter==='buy'&&activeVenue&&Number(activeVenue.dataset.buyCount||0)===0){const first=[...panel.querySelectorAll('[data-venue-tab]')].find(tab=>Number(tab.dataset.buyCount||0)>0);if(first)setVenue(panel,first.dataset.venueTab||'')}};
    const activateDay=(date)=>{dayTabs.forEach(tab=>tab.classList.toggle('active',tab.dataset.dayTab===date));dayPanels.forEach(panel=>panel.hidden=panel.dataset.dayPanel!==date);const panel=dayPanels.find(item=>item.dataset.dayPanel===date);if(!panel)return;const filter=panel.dataset.defaultFilter||'all';const venueTabs=[...panel.querySelectorAll('[data-venue-tab]')];const preferred=filter==='buy'?venueTabs.find(tab=>Number(tab.dataset.buyCount||0)>0):venueTabs[0];if(preferred)setVenue(panel,preferred.dataset.venueTab||'');applyFilter(panel,filter)};
    dayTabs.forEach(tab=>tab.addEventListener('click',()=>activateDay(tab.dataset.dayTab||'')));
    dayPanels.forEach(panel=>{panel.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>applyFilter(panel,button.dataset.filter||'all')));panel.querySelectorAll('[data-venue-tab]').forEach(button=>button.addEventListener('click',()=>setVenue(panel,button.dataset.venueTab||'')))});
    if(dayTabs[0])activateDay(dayTabs[0].dataset.dayTab||'');
  })();</script></body></html>`;
}
