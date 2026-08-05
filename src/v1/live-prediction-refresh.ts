import { isApprovedProductionModelVersion } from "./approved-production-model.js";
import { savePredictionWithCourses } from "./course-db.js";
import { getRace, getRunnerHistoryStats, getRunners } from "./db.js";
import { generatePrediction } from "./model.js";
import type { Env } from "./types.js";
import { positiveInt, positiveNumber } from "./utils.js";
import { ensureVenueDailyQuota, type VenueQuotaVenueResult } from "./venue-quota.js";

export interface LivePredictionRefreshResult {
  candidates: number;
  generated: number;
  withBets: number;
  skipped: number;
  errors: number;
  quotaAddedRaces: number;
  quotaAddedTickets: number;
  venueQuotas: Array<{ raceDate: string; venues: VenueQuotaVenueResult[] }>;
}

function emptyResult(): LivePredictionRefreshResult {
  return {
    candidates: 0,
    generated: 0,
    withBets: 0,
    skipped: 0,
    errors: 0,
    quotaAddedRaces: 0,
    quotaAddedTickets: 0,
    venueQuotas: []
  };
}

export async function refreshMissingLivePredictions(
  env: Env,
  limit = 60
): Promise<LivePredictionRefreshResult> {
  // The approved nonlinear model is trained and published by the dedicated
  // GitHub Actions job. The Worker must not overwrite its probabilities,
  // five-race selection, or fixed 10/10/80 allocation with the legacy model.
  if (isApprovedProductionModelVersion(env.MODEL_VERSION)) return emptyResult();

  const rows = await env.DB.prepare(`
    SELECT r.race_id AS raceId
    FROM rt_races r
    WHERE r.status != 'finished'
      AND r.start_time_utc IS NOT NULL
      AND datetime(r.start_time_utc) > datetime('now')
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id AND p.model_version=?
      )
      AND (
        SELECT COUNT(*) FROM rt_runners rr
        WHERE rr.race_id=r.race_id
          AND rr.runner_status='active'
          AND rr.win_odds IS NOT NULL
      ) >= 2
    ORDER BY datetime(r.start_time_utc), r.venue, r.race_no
    LIMIT ?
  `).bind(env.MODEL_VERSION, limit).all<{ raceId: string }>();

  const result = emptyResult();
  result.candidates = rows.results.length;
  const now = Date.now();

  for (const row of rows.results) {
    try {
      const race = await getRace(env.DB, row.raceId);
      if (!race?.startTimeUtc || race.status === "finished") {
        result.skipped += 1;
        continue;
      }
      const startMs = new Date(race.startTimeUtc).getTime();
      if (!Number.isFinite(startMs) || startMs <= now) {
        result.skipped += 1;
        continue;
      }

      const runners = await getRunners(env.DB, row.raceId);
      const activeWithOdds = runners.filter((runner) =>
        runner.runnerStatus === "active" && runner.winOdds !== null
      );
      if (activeWithOdds.length < 2) {
        result.skipped += 1;
        continue;
      }

      const history = await getRunnerHistoryStats(env.DB, race, runners);
      const generated = generatePrediction(
        race,
        runners,
        history,
        env.MODEL_VERSION,
        positiveNumber(env.MIN_EXPECTED_VALUE, 108),
        positiveInt(env.MAX_RACE_BUDGET_YEN, 10000)
      );
      const prediction = { ...generated, bets: [] };
      const minutesToStart = (startMs - now) / 60_000;
      const status = minutesToStart <= 15 ? "locked" : "draft";
      const saved = await savePredictionWithCourses(env.DB, race.raceId, prediction, status);
      if (!saved.saved) {
        result.skipped += 1;
        continue;
      }
      result.generated += 1;
    } catch (error) {
      result.errors += 1;
      console.error("LIVE_PREDICTION_REFRESH_FAILED", row.raceId, error);
    }
  }

  const dates = await env.DB.prepare(`
    SELECT DISTINCT r.race_date AS raceDate
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=?
    WHERE r.status='scheduled'
      AND r.start_time_utc IS NOT NULL
      AND datetime(r.start_time_utc)>datetime('now')
    ORDER BY r.race_date
  `).bind(env.MODEL_VERSION).all<{ raceDate: string }>();

  for (const { raceDate } of dates.results) {
    const quota = await ensureVenueDailyQuota(env.DB, env.MODEL_VERSION, raceDate, "live");
    result.quotaAddedRaces += quota.addedRaces;
    result.quotaAddedTickets += quota.addedTickets;
    result.withBets += quota.venues.reduce((sum, venue) => sum + venue.selectedAfter, 0);
    result.venueQuotas.push({ raceDate, venues: quota.venues });
  }

  return result;
}
