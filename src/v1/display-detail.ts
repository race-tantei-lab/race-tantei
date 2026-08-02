import type { RaceDetail } from "./db.js";
import { getRace, getRunners } from "./db.js";
import { isThreeMonthDate } from "./three-month-scope.js";
import { validationModelForDate } from "./validation.js";

interface PredictionRow {
  id: number;
  status: string;
  modelVersion: string;
  generatedAt: string;
  lockedAt: string | null;
}

function threeMonthModelForDate(raceDate: string): string | null {
  return isThreeMonthDate(raceDate)
    ? `validation-${raceDate}-roi-policy-v1-3m`
    : null;
}

async function selectDisplayPrediction(
  db: D1Database,
  raceId: string,
  raceDate: string,
  liveModel: string
): Promise<PredictionRow | null> {
  const threeMonthModel = threeMonthModelForDate(raceDate);
  if (threeMonthModel) {
    return await db.prepare(`
      SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
      FROM rt_predictions
      WHERE race_id=? AND model_version IN (?, ?)
      ORDER BY CASE WHEN model_version=? THEN 1 ELSE 2 END,
        CASE WHEN status='locked' THEN 1 ELSE 2 END,
        id DESC
      LIMIT 1
    `).bind(raceId, threeMonthModel, liveModel, threeMonthModel).first<PredictionRow>();
  }

  const validationModel = validationModelForDate(raceDate);
  if (validationModel) {
    return await db.prepare(`
      SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
      FROM rt_predictions
      WHERE race_id=? AND model_version IN (?, ?)
      ORDER BY CASE WHEN model_version=? THEN 1 ELSE 2 END,
        CASE WHEN status='locked' THEN 1 ELSE 2 END,
        id DESC
      LIMIT 1
    `).bind(raceId, liveModel, validationModel, liveModel).first<PredictionRow>();
  }

  return await db.prepare(`
    SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
    FROM rt_predictions
    WHERE race_id=? AND model_version=?
    ORDER BY CASE WHEN status='locked' THEN 1 ELSE 2 END, id DESC
    LIMIT 1
  `).bind(raceId, liveModel).first<PredictionRow>();
}

export async function getDisplayRaceDetail(
  db: D1Database,
  raceId: string,
  liveModel: string
): Promise<RaceDetail | null> {
  const race = await getRace(db, raceId);
  if (!race) return null;
  const runners = await getRunners(db, raceId);
  const resultRows = await db.prepare(`
    SELECT horse_no AS horseNo, finish_position AS finishPosition
    FROM rt_results WHERE race_id=?
  `).bind(raceId).all<{ horseNo: number; finishPosition: number | null }>();
  const finishMap = new Map(resultRows.results.map((row) => [Number(row.horseNo), row.finishPosition]));
  const runnersWithResult = runners.map((runner) => ({
    ...runner,
    finishPosition: finishMap.get(runner.horseNo) ?? null
  }));

  const prediction = await selectDisplayPrediction(db, raceId, race.raceDate, liveModel);
  if (!prediction) {
    return { race, runners: runnersWithResult, prediction: null, predictedRunners: [], bets: [] };
  }

  const predicted = await db.prepare(`
    SELECT horse_no AS horseNo, horse_name AS horseName, predicted_order AS predictedOrder,
      win_probability AS winProbability, place_probability AS placeProbability, fair_odds AS fairOdds,
      current_odds AS currentOdds, expected_value_pct AS expectedValuePct, explanation
    FROM rt_prediction_runners
    WHERE prediction_id=?
    ORDER BY predicted_order
  `).bind(prediction.id).all<RaceDetail["predictedRunners"][number]>();

  const bets = await db.prepare(`
    SELECT bet_type AS betType, combination, stake_yen AS stakeYen, assumed_odds AS assumedOdds,
      expected_value_pct AS expectedValuePct, settlement_status AS settlementStatus,
      return_yen AS returnYen
    FROM rt_bets
    WHERE prediction_id=?
      AND (bet_type LIKE 'ライト｜%' OR bet_type LIKE 'スタンダード｜%' OR bet_type LIKE 'プレミアム｜%')
    ORDER BY CASE
      WHEN bet_type LIKE '%｜単勝' THEN 1 WHEN bet_type LIKE '%｜複勝' THEN 2
      WHEN bet_type LIKE '%｜ワイド' THEN 3 WHEN bet_type LIKE '%｜馬連' THEN 4
      WHEN bet_type LIKE '%｜馬単' THEN 5 WHEN bet_type LIKE '%｜3連複' THEN 6
      WHEN bet_type LIKE '%｜3連単' THEN 7 ELSE 99 END,
      combination
  `).bind(prediction.id).all<RaceDetail["bets"][number]>();

  return {
    race,
    runners: runnersWithResult,
    prediction,
    predictedRunners: predicted.results,
    bets: bets.results
  };
}
