// Regression contract for the production importer.
// The importer must process only one five-URL checkpoint per Cron and isolate
// a failing race instead of aborting the whole checkpoint. Runtime behavior is
// covered by the existing walk-forward integration suite; this file documents
// the invariant next to the implementation so future batching changes do not
// silently restore the D1 query-budget failure.

export const WALK_FORWARD_HISTORY_RESILIENCE_CONTRACT = {
  maxUrlsPerCron: 5,
  checkpointSize: 5,
  isolatesFailedRaceWrites: true,
  advancesCursorAfterFailureIsolation: true
} as const;
