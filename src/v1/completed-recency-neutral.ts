import type { RunnerRecord } from "./types.js";
import type { CompletedRecencyAudit, CompletedRecencyLearning } from "./completed-recency-learning.js";

const COMPLETED_RECENCY_VERSION = "canonical-recency-v1";
const COMPLETED_RECENCY_HISTORY_DAYS = 30;
const COMPLETED_RECENCY_HALF_LIFE_DAYS = 7;
const RUNNER_FACTOR_MIN = 0.5;
const RUNNER_FACTOR_MAX = 2.0;
const BET_FACTOR_MIN = 0.7;
const BET_FACTOR_MAX = 1.35;

function baseAudit(cutoffUtc: string): CompletedRecencyAudit {
  return {
    status: "neutral_fallback", version: COMPLETED_RECENCY_VERSION, cutoffUtc,
    historyDays: COMPLETED_RECENCY_HISTORY_DAYS, halfLifeDays: COMPLETED_RECENCY_HALF_LIFE_DAYS,
    dateMultipliers: { sameDay: 6, previousDay: 4, days2To7: 2, days8To30: 1 },
    futureResultsAllowed: false, sameDayFinishedResultsAllowed: true,
    runnerHistoryRaces: 0, sameDayFinishedRaces: 0, previousDayFinishedRaces: 0, last7DaysFinishedRaces: 0,
    betHistoryRaces: 0, sameDaySettledBetRaces: 0, previousDaySettledBetRaces: 0, last7DaysSettledBetRaces: 0,
    runnerFactorRange: [RUNNER_FACTOR_MIN, RUNNER_FACTOR_MAX], betFactorRange: [BET_FACTOR_MIN, BET_FACTOR_MAX],
  };
}

export function neutralCompletedRecencyLearning(runners: RunnerRecord[], cutoffUtc: string, error?: string): CompletedRecencyLearning {
  const audit = baseAudit(cutoffUtc);
  if (error) audit.error = error;
  return {
    runnerFactors: runners.map(() => 1),
    runnerDetails: runners.map((runner) => ({
      horseNo: Number(runner.horseNo), factor: 1,
      signals: { horse: 0, jockey: 0, trainer: 0, sameVenueSurfaceDraw: 0 },
      samples: { horse: 0, jockey: 0, trainer: 0, sameVenueSurfaceDraw: 0 },
      sameDaySamples: { horse: 0, jockey: 0, trainer: 0, sameVenueSurfaceDraw: 0 },
    })),
    betBuckets: new Map(), audit,
  };
}
