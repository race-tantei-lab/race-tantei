import { getWalkForwardTrainingProgress } from "./walk-forward-training.js";
import {
  WALK_FORWARD_BASE_MODEL_VERSION,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_SCOPE_VERSION,
  WALK_FORWARD_TRAIN_START_DATE,
  WALK_FORWARD_VALIDATION_START_DATE,
  walkForwardSplitForDate
} from "./walk-forward-scope.js";

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

interface BaselineBetRow {
  raceId: string;
  betType: string;
  combination: string;
  stakeYen: number;
  returnYen: number;
}

function numberValue(value: unknown): number {
  return Number(value ?? 0);
}

export async function getWalkForwardAnalysisData(db: D1Database): Promise<unknown> {
  const progress = await getWalkForwardTrainingProgress(db);
  if (!progress.complete) {
    return {
      scope: WALK_FORWARD_SCOPE_VERSION,
      complete: false,
      progress,
      races: []
    };
  }

  const [raceRows, runnerRows, resultRows, payoutRows, baselineRows] = await Promise.all([
    db.prepare(`
      SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
        r.race_name AS raceName, r.surface, r.distance_m AS distanceM,
        (SELECT COUNT(*) FROM rt_runners rr WHERE rr.race_id=r.race_id AND rr.runner_status='active') AS fieldSize,
        p.id AS predictionId
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE p.model_version=? AND p.status='locked'
        AND r.race_date BETWEEN ? AND ?
      ORDER BY r.race_date, r.venue, r.race_no
    `).bind(
      WALK_FORWARD_BASE_MODEL_VERSION,
      WALK_FORWARD_TRAIN_START_DATE,
      WALK_FORWARD_HOLDOUT_END_DATE
    ).all<RaceRow>(),
    db.prepare(`
      SELECT pr.prediction_id AS predictionId, pr.horse_no AS horseNo, pr.horse_name AS horseName,
        pr.predicted_order AS predictedOrder, pr.win_probability AS winProbability,
        pr.place_probability AS placeProbability, pr.fair_odds AS fairOdds,
        pr.current_odds AS currentOdds, pr.expected_value_pct AS expectedValuePct,
        rr.popularity
      FROM rt_prediction_runners pr
      JOIN rt_predictions p ON p.id=pr.prediction_id
      JOIN rt_races r ON r.race_id=p.race_id
      LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
      WHERE p.model_version=? AND p.status='locked'
        AND r.race_date BETWEEN ? AND ?
      ORDER BY pr.prediction_id, pr.predicted_order
    `).bind(
      WALK_FORWARD_BASE_MODEL_VERSION,
      WALK_FORWARD_TRAIN_START_DATE,
      WALK_FORWARD_HOLDOUT_END_DATE
    ).all<PredictionRunnerRow>(),
    db.prepare(`
      SELECT rs.race_id AS raceId, rs.horse_no AS horseNo, rs.finish_position AS finishPosition
      FROM rt_results rs
      JOIN rt_races r ON r.race_id=rs.race_id
      WHERE r.race_date BETWEEN ? AND ? AND rs.finish_position IS NOT NULL
      ORDER BY rs.race_id, rs.finish_position
    `).bind(WALK_FORWARD_TRAIN_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE).all<ResultRow>(),
    db.prepare(`
      SELECT p.race_id AS raceId, p.bet_type AS betType, p.combination, p.payout_yen AS payoutYen
      FROM rt_payouts p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date BETWEEN ? AND ?
      ORDER BY p.race_id, p.bet_type, p.combination
    `).bind(WALK_FORWARD_TRAIN_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE).all<PayoutRow>(),
    db.prepare(`
      SELECT b.race_id AS raceId, b.bet_type AS betType, b.combination,
        b.stake_yen AS stakeYen, COALESCE(b.return_yen,0) AS returnYen
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE p.model_version=('validation-' || r.race_date || '-roi-policy-v1-3m')
        AND p.status='locked'
        AND b.settlement_status='settled'
        AND r.race_date BETWEEN ? AND ?
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ORDER BY b.race_id, b.id
    `).bind(WALK_FORWARD_VALIDATION_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE).all<BaselineBetRow>()
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

  const baselineByRace = new Map<string, BaselineBetRow[]>();
  for (const row of baselineRows.results) {
    const values = baselineByRace.get(row.raceId) ?? [];
    values.push({
      ...row,
      stakeYen: numberValue(row.stakeYen),
      returnYen: numberValue(row.returnYen)
    });
    baselineByRace.set(row.raceId, values);
  }

  const races = raceRows.results.flatMap((row) => {
    const split = walkForwardSplitForDate(row.raceDate);
    if (!split) return [];
    const predictionId = numberValue(row.predictionId);
    return [{
      ...row,
      split,
      raceNo: numberValue(row.raceNo),
      distanceM: row.distanceM === null ? null : numberValue(row.distanceM),
      fieldSize: numberValue(row.fieldSize),
      predictionId,
      runners: runnersByPrediction.get(predictionId) ?? [],
      results: resultsByRace.get(row.raceId) ?? [],
      payouts: payoutsByRace.get(row.raceId) ?? [],
      baselineBets: baselineByRace.get(row.raceId) ?? []
    }];
  });

  const splitCounts = { train: 0, validation: 0, holdout: 0 };
  for (const race of races) splitCounts[race.split] += 1;

  return {
    generatedAt: new Date().toISOString(),
    scope: WALK_FORWARD_SCOPE_VERSION,
    complete: true,
    preRaceFeaturesOnly: true,
    baseModelVersion: WALK_FORWARD_BASE_MODEL_VERSION,
    baselinePolicyVersion: "roi-policy-v1",
    splitCounts,
    progress,
    races
  };
}
