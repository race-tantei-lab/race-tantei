import { generatePrediction } from "./model.js";
import { getRace, getRunners } from "./db.js";
import { savePredictionWithCourses, settleRaceWithCourses } from "./course-db.js";

export const AUG2_DATE = "2026-08-02";
export const AUG2_BACKFILL_MODEL = "backfill-2026-08-02-budget-courses-v1";

async function pendingRaceIds(db: D1Database, liveModel: string, limit: number): Promise<string[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId
    FROM rt_races r
    WHERE r.race_date=? AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id
          AND p.status='locked'
          AND p.model_version IN (?, ?)
          AND EXISTS (
            SELECT 1 FROM rt_bets b
            WHERE b.prediction_id=p.id
              AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
          )
      )
    ORDER BY r.venue, r.race_no
    LIMIT ?
  `).bind(AUG2_DATE, liveModel, AUG2_BACKFILL_MODEL, limit).all<{ raceId: string }>();
  return rows.results.map((row) => row.raceId);
}

export async function runAug2BackfillBatch(
  db: D1Database,
  liveModel: string,
  limit = 6
): Promise<{ processed: number; remaining: number }> {
  const raceIds = await pendingRaceIds(db, liveModel, limit);
  let processed = 0;

  for (const raceId of raceIds) {
    const race = await getRace(db, raceId);
    if (!race || race.status !== "finished") continue;
    const runners = await getRunners(db, raceId);
    const usable = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
    if (usable.length < 3) continue;

    // Retrospective simulation: use only the stored entry/odds fields. Results are not passed to the model.
    const prediction = generatePrediction(race, runners, [], AUG2_BACKFILL_MODEL, 0, 10000);
    if (prediction.runners.length < 3 || prediction.bets.length === 0) continue;

    await savePredictionWithCourses(db, raceId, prediction, "locked");
    await settleRaceWithCourses(db, raceId);
    processed += 1;
  }

  const remaining = await pendingRaceIds(db, liveModel, 1000);
  return { processed, remaining: remaining.length };
}
