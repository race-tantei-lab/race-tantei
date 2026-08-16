export async function ensureCompletedFinalImmutability(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_locked_public_bet_terms
      BEFORE UPDATE OF course,bet_type,combination,stake_yen,assumed_odds,locked_at,source_prediction_id ON rt_public_bets
      WHEN OLD.source_prediction_id = -2
      BEGIN
        SELECT RAISE(ABORT, 'IMMUTABLE_FINAL_BET_TERMS');
      END
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_locked_worker_final_state
      BEFORE UPDATE ON rt_system_state
      WHEN OLD.state_key LIKE 'worker_live_final:%'
        AND json_extract(OLD.state_value, '$.status') = 'locked'
      BEGIN
        SELECT RAISE(ABORT, 'IMMUTABLE_WORKER_FINAL_STATE');
      END
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_insert
      BEFORE INSERT ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_final:%'
        AND json_extract(NEW.state_value, '$.oddsMode') = 'probability_fallback'
      BEGIN
        SELECT RAISE(ABORT, 'PROBABILITY_FALLBACK_FORBIDDEN');
      END
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_update
      BEFORE UPDATE ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_final:%'
        AND json_extract(NEW.state_value, '$.oddsMode') = 'probability_fallback'
      BEGIN
        SELECT RAISE(ABORT, 'PROBABILITY_FALLBACK_FORBIDDEN');
      END
    `),
  ]);
}
