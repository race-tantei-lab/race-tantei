// Persistent finalization triggers are installed by the dedicated D1 migration
// workflow and verified by production readiness outside the scheduled hot path.
//
// This compatibility hook intentionally performs no D1 work. It remains exported
// because the completed live-lock/deadline-guard call sites share it, but running
// sqlite_master/PRAGMA checks every race-day tick is forbidden: those checks are
// control-plane concerns and previously amplified D1 rows_read consumption.
export async function ensureCompletedFinalImmutability(_db: D1Database): Promise<void> {
  return;
}
