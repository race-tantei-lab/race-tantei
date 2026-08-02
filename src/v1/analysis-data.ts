import { VALIDATION_CONFIGS } from "./validation.js";

interface RaceRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  surface: string | null;
  distanceM: number | null;
  fieldSize: number;
  predictionId: number;
  modelVersion: string;
}

interface PredictionRunnerRow {
  predictionId: number;
  horseNo: number;
  horseName: string;
  predictedOrder: number;
  winProbability: number;
  placeProbability: number;
  fairOdds: number;
  currentOdds: number | null;
  expectedValuePct: number | null;
  popularity: number | null;
}

interface ResultRow {
  raceId: string;
  horseNo: number;
  finishPosition: number | null;
}

interface PayoutRow {
  raceId: string;
  betType: string;
  combination: string;
  payoutYen: number;
}

interface ExistingBetRow {
  raceId: string;
  predictionId: number;
  betType: string;
  combination: string;
  stakeYen: number;
  returnYen: number | null;
  hitProbability: number;
  expectedValuePct: number;
}

function numberValue(value: unknown): number {
  return Number(value ?? 0);
}

export async function getValidationAnalysisData(db: D1Database): Promise<unknown> {
  const modelVersions = VALIDATION_CONFIGS.map((config) => config.modelVersion);
  const dates = VALIDATION_CONFIGS.map((config) => config.raceDate);
  const modelPlaceholders = modelVersions.map(() => "?").join(",");
  const datePlaceholders = dates.map(() => "?").join(",");

  const [raceRows, runnerRows, resultRows, payoutRows, betRows] = await Promise.all([
    db.prepare(`
      SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
        r.race_name AS raceName, r.surface, r.distance_m AS distanceM,
        (SELECT COUNT(*) FROM rt_runners rr WHERE rr.race_id=r.race_id AND rr.runner_status='active') AS fieldSize,
        p.id AS predictionId, p.model_version AS modelVersion
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE p.model_version IN (${modelPlaceholders}) AND p.status='locked'
      ORDER BY r.race_date, r.venue, r.race_no
    `).bind(...modelVersions).all<RaceRow>(),
    db.prepare(`
      SELECT pr.prediction_id AS predictionId, pr.horse_no AS horseNo, pr.horse_name AS horseName,
        pr.predicted_order AS predictedOrder, pr.win_probability AS winProbability,
        pr.place_probability AS placeProbability, pr.fair_odds AS fairOdds,
        pr.current_odds AS currentOdds, pr.expected_value_pct AS expectedValuePct,
        rr.popularity
      FROM rt_prediction_runners pr
      JOIN rt_predictions p ON p.id=pr.prediction_id
      LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
      WHERE p.model_version IN (${modelPlaceholders}) AND p.status='locked'
      ORDER BY pr.prediction_id, pr.predicted_order
    `).bind(...modelVersions).all<PredictionRunnerRow>(),
    db.prepare(`
      SELECT rs.race_id AS raceId, rs.horse_no AS horseNo, rs.finish_position AS finishPosition
      FROM rt_results rs
      JOIN rt_races r ON r.race_id=rs.race_id
      WHERE r.race_date IN (${datePlaceholders}) AND rs.finish_position IS NOT NULL
      ORDER BY rs.race_id, rs.finish_position
    `).bind(...dates).all<ResultRow>(),
    db.prepare(`
      SELECT p.race_id AS raceId, p.bet_type AS betType, p.combination, p.payout_yen AS payoutYen
      FROM rt_payouts p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date IN (${datePlaceholders})
      ORDER BY p.race_id, p.bet_type, p.combination
    `).bind(...dates).all<PayoutRow>(),
    db.prepare(`
      SELECT b.race_id AS raceId, b.prediction_id AS predictionId, b.bet_type AS betType,
        b.combination, b.stake_yen AS stakeYen, b.return_yen AS returnYen,
        b.hit_probability AS hitProbability, b.expected_value_pct AS expectedValuePct
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      WHERE p.model_version IN (${modelPlaceholders})
      ORDER BY b.prediction_id, b.id
    `).bind(...modelVersions).all<ExistingBetRow>()
  ]);

  const runnersByPrediction = new Map<number, PredictionRunnerRow[]>();
  for (const row of runnerRows.results) {
    const predictionId = numberValue(row.predictionId);
    const values = runnersByPrediction.get(predictionId) ?? [];
    values.push({
      ...row,
      predictionId,
      horseNo: numberValue(row.horseNo),
      predictedOrder: numberValue(row.predictedOrder),
      winProbability: Number(row.winProbability),
      placeProbability: Number(row.placeProbability),
      fairOdds: Number(row.fairOdds),
      currentOdds: row.currentOdds === null ? null : Number(row.currentOdds),
      expectedValuePct: row.expectedValuePct === null ? null : Number(row.expectedValuePct),
      popularity: row.popularity === null ? null : numberValue(row.popularity)
    });
    runnersByPrediction.set(predictionId, values);
  }

  const resultsByRace = new Map<string, ResultRow[]>();
  for (const row of resultRows.results) {
    const values = resultsByRace.get(row.raceId) ?? [];
    values.push({
      ...row,
      horseNo: numberValue(row.horseNo),
      finishPosition: row.finishPosition === null ? null : numberValue(row.finishPosition)
    });
    resultsByRace.set(row.raceId, values);
  }

  const payoutsByRace = new Map<string, PayoutRow[]>();
  for (const row of payoutRows.results) {
    const values = payoutsByRace.get(row.raceId) ?? [];
    values.push({ ...row, payoutYen: numberValue(row.payoutYen) });
    payoutsByRace.set(row.raceId, values);
  }

  const betsByPrediction = new Map<number, ExistingBetRow[]>();
  for (const row of betRows.results) {
    const predictionId = numberValue(row.predictionId);
    const values = betsByPrediction.get(predictionId) ?? [];
    values.push({
      ...row,
      predictionId,
      stakeYen: numberValue(row.stakeYen),
      returnYen: row.returnYen === null ? null : numberValue(row.returnYen),
      hitProbability: Number(row.hitProbability),
      expectedValuePct: Number(row.expectedValuePct)
    });
    betsByPrediction.set(predictionId, values);
  }

  return {
    generatedAt: new Date().toISOString(),
    scope: "analysis-in-sample",
    dates,
    races: raceRows.results.map((row) => {
      const predictionId = numberValue(row.predictionId);
      return {
        ...row,
        raceNo: numberValue(row.raceNo),
        distanceM: row.distanceM === null ? null : numberValue(row.distanceM),
        fieldSize: numberValue(row.fieldSize),
        predictionId,
        runners: runnersByPrediction.get(predictionId) ?? [],
        results: resultsByRace.get(row.raceId) ?? [],
        payouts: payoutsByRace.get(row.raceId) ?? [],
        existingBets: betsByPrediction.get(predictionId) ?? []
      };
    })
  };
}
