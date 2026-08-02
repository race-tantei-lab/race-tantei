import { getPhaseADashboard } from "./phase-a-dashboard.js";
import { escapeHtml } from "./utils.js";

interface NoBetPredictionRow {
  raceId: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  raceStatus: string;
  predictionStatus: string;
  topHorseNo: number | null;
  topHorseName: string | null;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
}

function timeLabel(value: string | null): string {
  return value?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定";
}

function noBetCard(row: NoBetPredictionRow): string {
  const finished = row.raceStatus === "finished";
  const locked = row.predictionStatus === "locked";
  const status = locked
    ? `<span class="status skip">見送り</span>`
    : `<span class="status neutral">買い目調整中</span>`;
  const body = finished
    ? `<div class="winner">1着 <b>${row.winnerHorseNo ?? "—"}</b> ${escapeHtml(row.winnerHorseName ?? "取得中")}</div><div class="card-note">期待値基準を満たす買い目がなく、購入していません。</div>`
    : `<div class="pick">◎ ${row.topHorseNo ?? "—"} ${escapeHtml(row.topHorseName ?? "予想生成中")}</div><div class="card-note">${locked ? "期待値基準を満たす買い目がないため見送りです。" : "発走15分前までオッズを再判定します。"}</div>`;
  return `<a class="race-card" data-race-category="${finished ? "finished" : "other"}" href="/races/${encodeURIComponent(row.raceId)}">
    <div class="race-top"><div><b>${Number(row.raceNo)}R</b><span>${timeLabel(row.startTimeJst)}</span></div>${status}</div>
    <h4>${escapeHtml(row.raceName)}</h4>
    ${body}
  </a>`;
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

export async function getPhaseBDashboard(db: D1Database, liveModel: string): Promise<string> {
  let html = await getPhaseADashboard(db, liveModel);
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_no AS raceNo, r.race_name AS raceName,
      r.start_time_jst AS startTimeJst, r.status AS raceStatus, p.status AS predictionStatus,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs
       JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
       WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName
    FROM rt_predictions p
    JOIN rt_races r ON r.race_id=p.race_id
    WHERE p.model_version=?
      AND NOT EXISTS (
        SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      )
    ORDER BY p.id DESC
  `).bind(liveModel).all<NoBetPredictionRow>();

  for (const row of rows.results) html = replaceRaceCard(html, row.raceId, noBetCard(row));
  return html.replace("買い目・結果・収支を同じ基準で表示しています。", "期待値基準を満たした買い目だけを表示し、条件未達は見送ります。")
    .replace("<title>レース探偵</title>", "<title>レース探偵｜期待値選別</title>");
}
