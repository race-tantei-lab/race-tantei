import type { RaceDetail } from "./db.js";
import { getRace, getRunners } from "./db.js";

const AUG1_DATE = "2026-08-01";
const AUG1_MODEL = "backtest-2026-08-01-budget-courses-v3";
const AUG2_DATE = "2026-08-02";
const AUG2_MODEL = "backfill-2026-08-02-budget-courses-v1";

interface PredictionRow {
  id: number; status: string; modelVersion: string; generatedAt: string; lockedAt: string | null;
}

async function selectDisplayPrediction(db: D1Database, raceId: string, raceDate: string): Promise<PredictionRow | null> {
  if (raceDate === AUG1_DATE) {
    return await db.prepare(`
      SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
      FROM rt_predictions WHERE race_id=? AND model_version=? ORDER BY id DESC LIMIT 1
    `).bind(raceId, AUG1_MODEL).first<PredictionRow>();
  }

  if (raceDate === AUG2_DATE) {
    return await db.prepare(`
      SELECT p.id, p.status, p.model_version AS modelVersion, p.generated_at AS generatedAt, p.locked_at AS lockedAt
      FROM rt_predictions p
      WHERE p.race_id=? AND EXISTS (
        SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      )
      ORDER BY CASE WHEN p.model_version=? THEN 1 ELSE 0 END, p.id DESC
      LIMIT 1
    `).bind(raceId, AUG2_MODEL).first<PredictionRow>();
  }

  return await db.prepare(`
    SELECT p.id, p.status, p.model_version AS modelVersion, p.generated_at AS generatedAt, p.locked_at AS lockedAt
    FROM rt_predictions p
    WHERE p.race_id=? AND EXISTS (
      SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    )
    ORDER BY p.id DESC LIMIT 1
  `).bind(raceId).first<PredictionRow>();
}

export async function getDisplayRaceDetail(db: D1Database, raceId: string): Promise<RaceDetail | null> {
  const race = await getRace(db, raceId);
  if (!race) return null;
  const runners = await getRunners(db, raceId);
  const resultRows = await db.prepare(`SELECT horse_no AS horseNo, finish_position AS finishPosition FROM rt_results WHERE race_id=?`)
    .bind(raceId).all<{ horseNo: number; finishPosition: number | null }>();
  const finishMap = new Map(resultRows.results.map((row) => [Number(row.horseNo), row.finishPosition]));
  const runnersWithResult = runners.map((runner) => ({ ...runner, finishPosition: finishMap.get(runner.horseNo) ?? null }));

  const prediction = await selectDisplayPrediction(db, raceId, race.raceDate);
  if (!prediction) return { race, runners: runnersWithResult, prediction: null, predictedRunners: [], bets: [] };

  const predicted = await db.prepare(`
    SELECT horse_no AS horseNo, horse_name AS horseName, predicted_order AS predictedOrder,
      win_probability AS winProbability, place_probability AS placeProbability, fair_odds AS fairOdds,
      current_odds AS currentOdds, expected_value_pct AS expectedValuePct, explanation
    FROM rt_prediction_runners WHERE prediction_id=? ORDER BY predicted_order
  `).bind(prediction.id).all<RaceDetail["predictedRunners"][number]>();

  const bets = await db.prepare(`
    SELECT bet_type AS betType, combination, stake_yen AS stakeYen, assumed_odds AS assumedOdds,
      expected_value_pct AS expectedValuePct, settlement_status AS settlementStatus, return_yen AS returnYen
    FROM rt_bets WHERE prediction_id=?
      AND (bet_type LIKE 'ライト｜%' OR bet_type LIKE 'スタンダード｜%' OR bet_type LIKE 'プレミアム｜%')
    ORDER BY CASE
      WHEN bet_type LIKE '%｜単勝' THEN 1 WHEN bet_type LIKE '%｜複勝' THEN 2
      WHEN bet_type LIKE '%｜ワイド' THEN 3 WHEN bet_type LIKE '%｜馬連' THEN 4
      WHEN bet_type LIKE '%｜馬単' THEN 5 WHEN bet_type LIKE '%｜3連複' THEN 6
      WHEN bet_type LIKE '%｜3連単' THEN 7 ELSE 99 END, combination
  `).bind(prediction.id).all<RaceDetail["bets"][number]>();

  return { race, runners: runnersWithResult, prediction, predictedRunners: predicted.results, bets: bets.results };
}
