import { generatePrediction } from "./model.js";
import { getRace, getRunners } from "./db.js";
import { savePredictionWithCourses, settleRaceWithCourses } from "./course-db.js";
import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

export const BACKTEST_DATE = "2026-08-01";
export const BACKTEST_MODEL = "backtest-2026-08-01-budget-courses-v3";
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

interface BacktestRaceRow {
  raceId: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  predictionId: number | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
}

interface CourseSummary {
  course: BudgetCourse;
  races: number;
  stake: number;
  returns: number;
  hits: number;
}

async function pendingRaceIds(db: D1Database, limit: number): Promise<string[]> {
  const rows = await db.prepare(`
    SELECT ra.race_id AS raceId
    FROM rt_races ra
    WHERE ra.race_date=? AND ra.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=ra.race_id AND p.model_version=? AND p.status='locked'
      )
    ORDER BY ra.venue, ra.race_no
    LIMIT ?
  `).bind(BACKTEST_DATE, BACKTEST_MODEL, limit).all<{ raceId: string }>();
  return rows.results.map((row) => row.raceId);
}

export async function runBacktestBatch(db: D1Database, limit = 4): Promise<{ processed: number; remaining: number }> {
  const raceIds = await pendingRaceIds(db, limit);
  let processed = 0;
  for (const raceId of raceIds) {
    const race = await getRace(db, raceId);
    if (!race) continue;
    const runners = await getRunners(db, raceId);
    if (runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null).length < 3) continue;
    const prediction = generatePrediction(race, runners, [], BACKTEST_MODEL, 0, 10000);
    if (prediction.runners.length < 3 || prediction.bets.length === 0) continue;
    await savePredictionWithCourses(db, raceId, prediction, "locked");
    await settleRaceWithCourses(db, raceId);
    processed += 1;
  }
  const row = await db.prepare(`
    SELECT COUNT(*) AS count FROM rt_races ra
    WHERE ra.race_date=? AND ra.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=ra.race_id AND p.model_version=? AND p.status='locked'
      )
  `).bind(BACKTEST_DATE, BACKTEST_MODEL).first<{ count: number }>();
  return { processed, remaining: Number(row?.count ?? 0) };
}

async function getRows(db: D1Database): Promise<BacktestRaceRow[]> {
  const rows = await db.prepare(`
    SELECT ra.race_id AS raceId, ra.venue, ra.race_no AS raceNo, ra.race_name AS raceName,
      ra.start_time_jst AS startTimeJst, p.id AS predictionId,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=ra.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
       WHERE rs.race_id=ra.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName
    FROM rt_races ra
    LEFT JOIN rt_predictions p ON p.race_id=ra.race_id AND p.model_version=?
    WHERE ra.race_date=?
    ORDER BY ra.venue, ra.race_no
  `).bind(BACKTEST_MODEL, BACKTEST_DATE).all<BacktestRaceRow>();
  return rows.results;
}

async function getCourseSummaries(db: D1Database): Promise<CourseSummary[]> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
    COUNT(DISTINCT b.race_id) AS races,
    COALESCE(SUM(b.stake_yen),0) AS stake,
    COALESCE(SUM(b.return_yen),0) AS returns,
    COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hits
    FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE p.model_version=? AND b.settlement_status='settled'
    GROUP BY course
  `).bind(BACKTEST_MODEL).all<CourseSummary>();
  const map = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map((course) => ({
    course,
    races: Number(map.get(course)?.races ?? 0),
    stake: Number(map.get(course)?.stake ?? 0),
    returns: Number(map.get(course)?.returns ?? 0),
    hits: Number(map.get(course)?.hits ?? 0)
  }));
}

async function raceCourseResults(db: D1Database, predictionId: number): Promise<Map<BudgetCourse, { stake: number; returns: number }>> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
    COALESCE(SUM(stake_yen),0) AS stake, COALESCE(SUM(return_yen),0) AS returns
    FROM rt_bets WHERE prediction_id=? GROUP BY course
  `).bind(predictionId).all<{ course: BudgetCourse; stake: number; returns: number }>();
  return new Map(rows.results.map((row) => [row.course, { stake: Number(row.stake), returns: Number(row.returns) }]));
}

export async function renderBacktest(db: D1Database): Promise<string> {
  const rows = await getRows(db);
  const summaries = await getCourseSummaries(db);
  const completed = rows.filter((row) => row.predictionId !== null).length;
  const summaryHtml = summaries.map((row) => {
    const profit = row.returns - row.stake;
    const roi = row.stake > 0 ? row.returns / row.stake * 100 : 0;
    return `<section class="course"><div class="head"><div><small>${escapeHtml(row.course)}コース</small><h2>${row.course === "ライト" ? "2,000円" : row.course === "スタンダード" ? "5,000円" : "10,000円"}</h2></div><strong class="${roi >= 100 ? "plus" : "minus"}">${roi.toFixed(1)}%</strong></div><div class="stats"><div>購入<b>${formatYen(row.stake)}</b></div><div>払戻<b>${formatYen(row.returns)}</b></div><div>収支<b class="${profit >= 0 ? "plus" : "minus"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</b></div><div>的中レース<b>${row.hits}/${row.races}R</b></div></div></section>`;
  }).join("");

  const byVenue = new Map<string, BacktestRaceRow[]>();
  for (const row of rows) {
    const list = byVenue.get(row.venue) ?? [];
    list.push(row);
    byVenue.set(row.venue, list);
  }
  const venues: string[] = [];
  for (const [venue, venueRows] of byVenue) {
    const raceHtml: string[] = [];
    for (const row of venueRows) {
      const results = row.predictionId ? await raceCourseResults(db, row.predictionId) : new Map();
      const courseLines = COURSES.map((course) => {
        const value = results.get(course);
        if (!value) return `${course}：計算待ち`;
        const profit = value.returns - value.stake;
        return `${course}：${formatYen(value.stake)} → ${formatYen(value.returns)}（${profit >= 0 ? "+" : ""}${formatYen(profit)}）`;
      }).join("<br>");
      raceHtml.push(`<a class="race" href="/races/${encodeURIComponent(row.raceId)}"><div><b>${row.raceNo}R ${escapeHtml(row.raceName)}</b><small>${escapeHtml(row.startTimeJst ?? "")}</small></div><div>◎ ${row.topHorseNo ?? "—"} ${escapeHtml(row.topHorseName ?? "")}<br>1着 ${row.winnerHorseNo ?? "—"} ${escapeHtml(row.winnerHorseName ?? "")}</div><div class="courses">${courseLines}</div></a>`);
    }
    venues.push(`<section><h2>${escapeHtml(venue)}競馬場</h2>${raceHtml.join("")}</section>`);
  }

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="${completed < rows.length ? 10 : 300}"><title>8月1日 3コース検証｜レース探偵</title><style>:root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--green:#4fd1a1;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;background:#0b0f14;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:980px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.hero,.course,.race{background:var(--panel);border:1px solid var(--line);border-radius:16px}.hero{padding:20px}.note,small{color:var(--muted)}.course{padding:16px;margin:12px 0}.head{display:flex;justify-content:space-between;align-items:center}.head h2{margin:4px 0}.head strong{font-size:28px}.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.stats div{background:#0d141d;padding:10px;border-radius:10px}.stats b{display:block;margin-top:4px}.plus{color:var(--green)}.minus{color:var(--red)}.race{display:grid;grid-template-columns:1fr 1fr 1.5fr;gap:10px;padding:13px;margin:8px 0}.courses{font-size:13px;line-height:1.7}@media(max-width:700px){.race{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}}</style></head><body><main class="wrap"><p><a href="/">← 予想一覧へ</a></p><section class="hero"><h1>2026年8月1日 全36R・3コース遡及検証</h1><p class="note">結果は予想材料に使用せず、保存済み出走馬情報と最終取得単勝オッズで再計算しています。ライト2,000円、スタンダード5,000円、プレミアム10,000円を別々に公式払戻と照合します。</p><b>計算済み ${completed}/${rows.length}R</b></section>${summaryHtml}${venues.join("")}</main></body></html>`;
}
