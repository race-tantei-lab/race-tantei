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
      CREATE TRIGGER IF NOT EXISTS rt_guard_final_bet_insert_deadline
      BEFORE INSERT ON rt_public_bets
      WHEN NEW.source_prediction_id = -2
        AND COALESCE(
          (SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id = NEW.race_id LIMIT 1),
          0
        ) < unixepoch('now') + 900
      BEGIN
        SELECT RAISE(ABORT, 'FINAL_BET_DEADLINE_PASSED');
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
      CREATE TRIGGER IF NOT EXISTS rt_guard_final_state_insert_deadline
      BEFORE INSERT ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_final:%'
        AND json_extract(NEW.state_value, '$.status') = 'locked'
        AND COALESCE(
          (
            SELECT unixepoch(start_time_utc)
            FROM rt_races
            WHERE race_id = json_extract(NEW.state_value, '$.raceId')
            LIMIT 1
          ),
          0
        ) < unixepoch('now') + 900
      BEGIN
        SELECT RAISE(ABORT, 'FINAL_STATE_DEADLINE_PASSED');
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
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_insert
      BEFORE INSERT ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_final:%'
        AND json_extract(NEW.state_value, '$.status') = 'locked'
        AND COALESCE(json_extract(NEW.state_value, '$.oddsSource'), '') NOT IN ('jra-fast-official', 'jra-crawl-official')
      BEGIN
        SELECT RAISE(ABORT, 'OFFICIAL_JRA_ODDS_REQUIRED');
      END
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_update
      BEFORE UPDATE ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_final:%'
        AND json_extract(NEW.state_value, '$.status') = 'locked'
        AND COALESCE(json_extract(NEW.state_value, '$.oddsSource'), '') NOT IN ('jra-fast-official', 'jra-crawl-official')
      BEGIN
        SELECT RAISE(ABORT, 'OFFICIAL_JRA_ODDS_REQUIRED');
      END
    `),
  ]);
}
