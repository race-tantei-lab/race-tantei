import { generatePrediction } from "./model.js";
import { getRace, getRunners, savePrediction, settleRace } from "./db.js";
import type { BetRecommendation, PredictionOutput, RaceRecord, RunnerRecord } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

export const BACKTEST_DATE = "2026-08-01";
export const BACKTEST_MODEL = "backtest-2026-08-01-multibet-v2";

interface BacktestRaceRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  status: string;
  predictionId: number | null;
  predictionStatus: string | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  stakeYen: number;
  returnYen: number;
  betCount: number;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
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
    const activeWithOdds = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
    if (activeWithOdds.length < 2) continue;

    // Deliberately excludes historical-result features. This retrospective test uses only the
    // stored runners and final captured win odds, so race results are not prediction inputs.
    const prediction = generatePrediction(race, runners, [], BACKTEST_MODEL, 0, 2000);
    if (prediction.runners.length === 0 || prediction.bets.length === 0) continue;
    await savePrediction(db, raceId, prediction, "locked");
    await settleRace(db, raceId);
    processed += 1;
  }
  const remainingRow = await db.prepare(`
    SELECT COUNT(*) AS count
    FROM rt_races ra
    WHERE ra.race_date=? AND ra.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=ra.race_id AND p.model_version=? AND p.status='locked'
      )
  `).bind(BACKTEST_DATE, BACKTEST_MODEL).first<{ count: number }>();
  return { processed, remaining: Number(remainingRow?.count ?? 0) };
}

export async function getBacktestRows(db: D1Database): Promise<BacktestRaceRow[]> {
  const rows = await db.prepare(`
    SELECT ra.race_id AS raceId, ra.race_date AS raceDate, ra.venue, ra.race_no AS raceNo,
      ra.race_name AS raceName, ra.start_time_jst AS startTimeJst, ra.status,
      p.id AS predictionId, p.status AS predictionStatus,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id),0) AS stakeYen,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id),0) AS returnYen,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id),0) AS betCount,
      (SELECT horse_no FROM rt_results WHERE race_id=ra.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no WHERE rs.race_id=ra.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName
    FROM rt_races ra
    LEFT JOIN rt_predictions p ON p.race_id=ra.race_id AND p.model_version=?
    WHERE ra.race_date=?
    ORDER BY ra.venue, ra.race_no
  `).bind(BACKTEST_MODEL, BACKTEST_DATE).all<BacktestRaceRow>();
  return rows.results;
}

export async function renderBacktest(db: D1Database): Promise<string> {
  const rows = await getBacktestRows(db);
  const completed = rows.filter((row) => row.predictionId !== null && row.betCount > 0);
  const stake = completed.reduce((sum, row) => sum + Number(row.stakeYen || 0), 0);
  const returns = completed.reduce((sum, row) => sum + Number(row.returnYen || 0), 0);
  const hits = completed.filter((row) => Number(row.returnYen || 0) > 0).length;
  const roi = stake > 0 ? returns / stake * 100 : 0;
  const byVenue = new Map<string, BacktestRaceRow[]>();
  for (const row of rows) {
    const list = byVenue.get(row.venue) ?? [];
    list.push(row);
    byVenue.set(row.venue, list);
  }
  const venueHtml = [...byVenue.entries()].map(([venue, venueRows]) => `
    <section><h2>${escapeHtml(venue)}競馬場</h2>${venueRows.map((row) => {
      const predicted = row.topHorseNo ? `${row.topHorseNo} ${escapeHtml(row.topHorseName ?? "")}` : "未計算";
      const winner = row.winnerHorseNo ? `${row.winnerHorseNo} ${escapeHtml(row.winnerHorseName ?? "")}` : "結果未取得";
      const hit = row.returnYen > 0;
      return `<a class="race" href="/races/${encodeURIComponent(row.raceId)}"><div><b>${row.raceNo}R ${escapeHtml(row.raceName)}</b><small>${escapeHtml(row.startTimeJst ?? "")}</small></div><div>予想 ◎ ${predicted}<br>1着 ${winner}</div><div class="${hit ? "hit" : "miss"}">${row.betCount ? `${hit ? "的中" : "不的中"}<br>${formatYen(row.returnYen)}` : "計算待ち"}</div></a>`;
    }).join("")}</section>`).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="${completed.length < rows.length ? 12 : 300}"><title>8月1日 遡及検証｜レース探偵</title><style>
  body{margin:0;background:#0b0f14;color:#eef3f8;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:900px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.hero,.metric,.race{background:#121923;border:1px solid #293649;border-radius:14px}.hero{padding:20px}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0}.metric{padding:14px}.metric b{font-size:22px;display:block}.race{display:grid;grid-template-columns:1.4fr 1fr auto;gap:10px;padding:13px;margin:8px 0;align-items:center}.race small{display:block;color:#9fb0c2}.hit{color:#4fd1a1;text-align:right}.miss{color:#ff7b72;text-align:right}.note{color:#9fb0c2;font-size:13px;line-height:1.7}h2{margin-top:26px}@media(max-width:620px){.race{grid-template-columns:1fr}.hit,.miss{text-align:left}.metrics{grid-template-columns:1fr 1fr}}
  </style></head><body><main class="wrap"><p><a href="/">← 予想一覧へ</a></p><section class="hero"><h1>2026年8月1日 全レース遡及検証</h1><p class="note">結果を予想材料には使用せず、保存済みの出走馬情報と最終取得単勝オッズで再計算しています。当時の発走15分前オッズを保存していないため、正式な事前予想成績ではなく遡及シミュレーションです。各レース2,000円以内で、◎○▲から単勝・ワイド・馬連・馬単・3連複を一貫して組み立てます。</p></section><div class="metrics"><div class="metric">計算済み<b>${completed.length}/${rows.length}R</b></div><div class="metric">的中<b>${hits}R</b></div><div class="metric">購入／払戻<b>${formatYen(stake)} / ${formatYen(returns)}</b></div><div class="metric">回収率<b>${roi.toFixed(1)}%</b></div></div>${venueHtml || "<p>8月1日のデータを取得中です。</p>"}</main></body></html>`;
}
