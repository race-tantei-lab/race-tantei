import {
  getRace,
  getRunnerHistoryStats,
  getRunners,
  savePrediction
} from "./db.js";
import { generatePrediction } from "./model.js";
import {
  getWalkForwardHistoryProgress,
  runWalkForwardHistoryStep,
  type WalkForwardHistoryProgress
} from "./walk-forward-history.js";
import {
  WALK_FORWARD_BASE_MODEL_VERSION,
  WALK_FORWARD_HOLDOUT_END_DATE,
  WALK_FORWARD_HOLDOUT_START_DATE,
  WALK_FORWARD_TRAIN_END_DATE,
  WALK_FORWARD_TRAIN_START_DATE,
  WALK_FORWARD_VALIDATION_END_DATE,
  WALK_FORWARD_VALIDATION_START_DATE,
  walkForwardSplitForDate
} from "./walk-forward-scope.js";
import type { PredictionOutput } from "./types.js";
import { nowIso } from "./utils.js";

export interface WalkForwardTrainingProgress {
  phase: "history" | "features" | "complete";
  history: WalkForwardHistoryProgress;
  targetRaces: number;
  generatedRaces: number;
  remainingRaces: number;
  splitCounts: Record<"train" | "validation" | "holdout", number>;
  complete: boolean;
}

function emptyPrediction(): PredictionOutput {
  return {
    modelVersion: WALK_FORWARD_BASE_MODEL_VERSION,
    runners: [],
    bets: [],
    generatedAt: nowIso()
  };
}

const SPLIT_SQL = `(
  r.race_date BETWEEN ? AND ?
  OR r.race_date BETWEEN ? AND ?
  OR r.race_date BETWEEN ? AND ?
)`;

function splitBindings(): string[] {
  return [
    WALK_FORWARD_TRAIN_START_DATE,
    WALK_FORWARD_TRAIN_END_DATE,
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE
  ];
}

async function pendingRaces(
  db: D1Database,
  limit: number
): Promise<Array<{ raceId: string; raceDate: string }>> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate
    FROM rt_races r
    WHERE ${SPLIT_SQL}
      AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id
          AND p.model_version=?
          AND p.status='locked'
      )
    ORDER BY r.race_date, r.venue, r.race_no
    LIMIT ?
  `).bind(
    ...splitBindings(),
    WALK_FORWARD_BASE_MODEL_VERSION,
    limit
  ).all<{ raceId: string; raceDate: string }>();
  return rows.results;
}

async function generateBatch(
  db: D1Database,
  limit: number
): Promise<{ processed: number; errors: number }> {
  const rows = await pendingRaces(db, limit);
  let processed = 0;
  let errors = 0;
  for (const row of rows) {
    try {
      const race = await getRace(db, row.raceId);
      if (!race || race.status !== "finished" || !walkForwardSplitForDate(race.raceDate)) continue;
      const runners = await getRunners(db, race.raceId);
      const usable = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
      if (usable.length < 2) {
        await savePrediction(db, race.raceId, emptyPrediction(), "locked");
        processed += 1;
        continue;
      }
      const history = await getRunnerHistoryStats(db, race, runners);
      const base = generatePrediction(
        race,
        runners,
        history,
        WALK_FORWARD_BASE_MODEL_VERSION,
        108,
        10000
      );
      await savePrediction(db, race.raceId, { ...base, bets: [] }, "locked");
      processed += 1;
    } catch (error) {
      errors += 1;
      console.error("WALK_FORWARD_BASE_PREDICTION_FAILED", row.raceId, error);
    }
  }
  return { processed, errors };
}

export async function getWalkForwardTrainingProgress(db: D1Database): Promise<WalkForwardTrainingProgress> {
  const history = await getWalkForwardHistoryProgress(db);
  const rows = await db.prepare(`
    SELECT
      COUNT(DISTINCT r.race_id) AS targetRaces,
      COUNT(DISTINCT CASE WHEN p.id IS NOT NULL AND p.status='locked' THEN r.race_id END) AS generatedRaces,
      COUNT(DISTINCT CASE WHEN r.race_date BETWEEN ? AND ? THEN r.race_id END) AS trainRaces,
      COUNT(DISTINCT CASE WHEN r.race_date BETWEEN ? AND ? THEN r.race_id END) AS validationRaces,
      COUNT(DISTINCT CASE WHEN r.race_date BETWEEN ? AND ? THEN r.race_id END) AS holdoutRaces
    FROM rt_races r
    LEFT JOIN rt_predictions p
      ON p.race_id=r.race_id AND p.model_version=?
    WHERE r.status='finished'
      AND ${SPLIT_SQL}
  `).bind(
    WALK_FORWARD_TRAIN_START_DATE,
    WALK_FORWARD_TRAIN_END_DATE,
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE,
    WALK_FORWARD_BASE_MODEL_VERSION,
    ...splitBindings()
  ).first<{
    targetRaces: number;
    generatedRaces: number;
    trainRaces: number;
    validationRaces: number;
    holdoutRaces: number;
  }>();
  const targetRaces = Number(rows?.targetRaces ?? 0);
  const generatedRaces = Number(rows?.generatedRaces ?? 0);
  const remainingRaces = Math.max(0, targetRaces - generatedRaces);
  const complete = history.complete && targetRaces > 0 && remainingRaces === 0;
  return {
    phase: !history.complete ? "history" : complete ? "complete" : "features",
    history,
    targetRaces,
    generatedRaces,
    remainingRaces,
    splitCounts: {
      train: Number(rows?.trainRaces ?? 0),
      validation: Number(rows?.validationRaces ?? 0),
      holdout: Number(rows?.holdoutRaces ?? 0)
    },
    complete
  };
}

export async function runWalkForwardTrainingStep(
  db: D1Database,
  predictionBatchSize = 8
): Promise<unknown> {
  const before = await getWalkForwardTrainingProgress(db);
  if (before.phase === "history") {
    return {
      stage: "history",
      action: await runWalkForwardHistoryStep(db),
      progress: await getWalkForwardTrainingProgress(db)
    };
  }
  if (before.phase === "features") {
    return {
      stage: "features",
      action: await generateBatch(db, Math.max(1, Math.min(16, predictionBatchSize))),
      progress: await getWalkForwardTrainingProgress(db)
    };
  }
  return { stage: "complete", action: { type: "complete" }, progress: before };
}
