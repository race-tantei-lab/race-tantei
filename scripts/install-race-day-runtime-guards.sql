-- Persistent production D1 guards for race-day runtime.
-- This file is executed only during deployment. Race-day Workers must never
-- create/drop tables, indexes, or triggers in their scheduled hot paths.

CREATE TABLE IF NOT EXISTS rt_live_preview_archive (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  race_id TEXT NOT NULL,
  envelope_json TEXT NOT NULL,
  newest_generated_at TEXT,
  archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_live_preview_archive_race_id
  ON rt_live_preview_archive(race_id,id DESC);
CREATE TABLE IF NOT EXISTS rt_live_deadline_lease (
  lease_key TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  expires_at_epoch INTEGER NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The preview envelope itself keeps the recent official snapshots. Automatic
-- archive triggers doubled every preview write and grew without a bound.
DROP TRIGGER IF EXISTS rt_archive_live_preview_insert;
DROP TRIGGER IF EXISTS rt_archive_live_preview_update;

-- Keep a verified race name from being overwritten by JRA page chrome.
-- This protects the storage boundary even if any parser/updater regresses.
DROP TRIGGER IF EXISTS rt_guard_race_name_update_chrome;
CREATE TRIGGER rt_guard_race_name_update_chrome
AFTER UPDATE OF race_name ON rt_races
WHEN
  (
    trim(COALESCE(NEW.race_name, '')) = ''
    OR instr(NEW.race_name, '検索ウィンドウ') > 0
    OR NEW.race_name IN (
      '検索','検索窓','検索メニュー','サイト内検索','メニューを開く','JRAホーム',
      'レース情報トップ','出馬表','レース','レース結果','払戻金','関連メニュー',
      '開催お知らせ','緊急情報','コースレコード','勝馬の紹介',
      '開催選択へ戻る','レース選択へ戻る'
    )
  )
  AND NOT (
    trim(COALESCE(OLD.race_name, '')) = ''
    OR instr(OLD.race_name, '検索ウィンドウ') > 0
    OR OLD.race_name IN (
      '検索','検索窓','検索メニュー','サイト内検索','メニューを開く','JRAホーム',
      'レース情報トップ','出馬表','レース','レース結果','払戻金','関連メニュー',
      '開催お知らせ','緊急情報','コースレコード','勝馬の紹介',
      '開催選択へ戻る','レース選択へ戻る'
    )
  )
BEGIN
  UPDATE rt_races SET race_name=OLD.race_name WHERE race_id=NEW.race_id;
END;

-- Final-bet deadline and immutability guards. These are provisioned here once,
-- then runtime only verifies that they remain present.
DROP TRIGGER IF EXISTS rt_guard_final_bet_insert_deadline;
DROP TRIGGER IF EXISTS rt_guard_final_state_insert_deadline;
CREATE TRIGGER rt_guard_final_state_insert_deadline BEFORE INSERT ON rt_system_state
WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value, '$.status')='locked' AND (
  COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0) < unixepoch('now')+600
  OR (COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0) < unixepoch('now')+900
    AND NOT (json_extract(NEW.state_value,'$.finalizedFrom')='fresh' AND unixepoch(json_extract(NEW.state_value,'$.generationStartedAt')) IS NOT NULL
      AND unixepoch(json_extract(NEW.state_value,'$.generationStartedAt')) <= COALESCE((SELECT unixepoch(start_time_utc)-900 FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0))))
BEGIN SELECT RAISE(ABORT,'FINAL_STATE_REFLECTION_WINDOW_PASSED'); END;
CREATE TRIGGER rt_guard_final_bet_insert_deadline BEFORE INSERT ON rt_public_bets
WHEN NEW.source_prediction_id=-2 AND (
  COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0) < unixepoch('now')+600
  OR (COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0) < unixepoch('now')+900
    AND NOT EXISTS (SELECT 1 FROM rt_system_state s WHERE s.state_key='worker_live_final:'||NEW.race_id
      AND json_extract(s.state_value,'$.status')='locked' AND json_extract(s.state_value,'$.finalizedFrom')='fresh'
      AND unixepoch(json_extract(s.state_value,'$.generationStartedAt')) IS NOT NULL
      AND unixepoch(json_extract(s.state_value,'$.generationStartedAt')) <= COALESCE((SELECT unixepoch(start_time_utc)-900 FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0))))
BEGIN SELECT RAISE(ABORT,'FINAL_BET_REFLECTION_WINDOW_PASSED'); END;

CREATE TRIGGER IF NOT EXISTS rt_guard_locked_public_bet_terms
BEFORE UPDATE OF course,bet_type,combination,stake_yen,assumed_odds,locked_at,source_prediction_id ON rt_public_bets
WHEN OLD.source_prediction_id=-2
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FINAL_BET_TERMS'); END;
CREATE TRIGGER IF NOT EXISTS rt_guard_locked_worker_final_state
BEFORE UPDATE ON rt_system_state
WHEN OLD.state_key LIKE 'worker_live_final:%' AND json_extract(OLD.state_value,'$.status')='locked'
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_WORKER_FINAL_STATE'); END;
CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_insert
BEFORE INSERT ON rt_system_state
WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.oddsMode')='probability_fallback'
BEGIN SELECT RAISE(ABORT,'PROBABILITY_FALLBACK_FORBIDDEN'); END;
CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_update
BEFORE UPDATE ON rt_system_state
WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.oddsMode')='probability_fallback'
BEGIN SELECT RAISE(ABORT,'PROBABILITY_FALLBACK_FORBIDDEN'); END;
CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_insert
BEFORE INSERT ON rt_system_state
WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.status')='locked'
 AND COALESCE(json_extract(NEW.state_value,'$.oddsSource'),'') NOT IN ('jra-fast-official','jra-crawl-official')
BEGIN SELECT RAISE(ABORT,'OFFICIAL_JRA_ODDS_REQUIRED'); END;
CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_update
BEFORE UPDATE ON rt_system_state
WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.status')='locked'
 AND COALESCE(json_extract(NEW.state_value,'$.oddsSource'),'') NOT IN ('jra-fast-official','jra-crawl-official')
BEGIN SELECT RAISE(ABORT,'OFFICIAL_JRA_ODDS_REQUIRED'); END;

-- Exact no-op updates must never spend rows_written merely to refresh timestamps.
DROP TRIGGER IF EXISTS rt_ignore_unchanged_system_state;
CREATE TRIGGER rt_ignore_unchanged_system_state BEFORE UPDATE OF state_value ON rt_system_state
WHEN OLD.state_value IS NEW.state_value
BEGIN SELECT RAISE(IGNORE); END;

DROP TRIGGER IF EXISTS rt_ignore_unchanged_runner;
CREATE TRIGGER rt_ignore_unchanged_runner BEFORE UPDATE ON rt_runners
WHEN OLD.frame_no IS NEW.frame_no
 AND OLD.horse_name IS NEW.horse_name
 AND OLD.sex_age IS NEW.sex_age
 AND OLD.coat_color IS NEW.coat_color
 AND OLD.horse_weight IS NEW.horse_weight
 AND OLD.weight_change IS NEW.weight_change
 AND OLD.jockey IS NEW.jockey
 AND OLD.assigned_weight IS NEW.assigned_weight
 AND OLD.trainer IS NEW.trainer
 AND OLD.stable IS NEW.stable
 AND OLD.win_odds IS NEW.win_odds
 AND OLD.popularity IS NEW.popularity
 AND OLD.runner_status IS NEW.runner_status
BEGIN SELECT RAISE(IGNORE); END;

DROP TRIGGER IF EXISTS rt_ignore_unchanged_race;
CREATE TRIGGER rt_ignore_unchanged_race BEFORE UPDATE ON rt_races
WHEN OLD.race_date IS NEW.race_date
 AND OLD.venue IS NEW.venue
 AND OLD.meeting_no IS NEW.meeting_no
 AND OLD.meeting_day IS NEW.meeting_day
 AND OLD.race_no IS NEW.race_no
 AND OLD.race_name IS NEW.race_name
 AND OLD.conditions IS NEW.conditions
 AND OLD.surface IS NEW.surface
 AND OLD.distance_m IS NEW.distance_m
 AND OLD.direction IS NEW.direction
 AND OLD.start_time_jst IS NEW.start_time_jst
 AND OLD.start_time_utc IS NEW.start_time_utc
 AND OLD.weather IS NEW.weather
 AND OLD.track_condition IS NEW.track_condition
 AND OLD.entry_url IS NEW.entry_url
 AND OLD.result_url IS NEW.result_url
 AND OLD.status IS NEW.status
 AND OLD.refund_horse_nos_json IS NEW.refund_horse_nos_json
 AND OLD.entry_updated_at IS NEW.entry_updated_at
 AND OLD.result_updated_at IS NEW.result_updated_at
BEGIN SELECT RAISE(IGNORE); END;

DROP TRIGGER IF EXISTS rt_ignore_unchanged_race_source;
CREATE TRIGGER rt_ignore_unchanged_race_source BEFORE UPDATE ON rt_race_sources
WHEN OLD.result_url IS NEW.result_url
 AND OLD.race_id IS NEW.race_id
 AND OLD.status IS NEW.status
 AND OLD.next_fetch_at IS NEW.next_fetch_at
 AND OLD.last_entry_fetch_at IS NEW.last_entry_fetch_at
 AND OLD.last_result_fetch_at IS NEW.last_result_fetch_at
 AND OLD.failure_count IS NEW.failure_count
 AND OLD.last_error IS NEW.last_error
BEGIN SELECT RAISE(IGNORE); END;

DROP TRIGGER IF EXISTS rt_ignore_unchanged_result;
CREATE TRIGGER rt_ignore_unchanged_result BEFORE UPDATE ON rt_results
WHEN OLD.finish_position IS NEW.finish_position
 AND OLD.result_status IS NEW.result_status
 AND OLD.time_text IS NEW.time_text
 AND OLD.margin_text IS NEW.margin_text
 AND OLD.final3f IS NEW.final3f
BEGIN SELECT RAISE(IGNORE); END;

DROP TRIGGER IF EXISTS rt_ignore_unchanged_payout;
CREATE TRIGGER rt_ignore_unchanged_payout BEFORE UPDATE ON rt_payouts
WHEN OLD.payout_yen IS NEW.payout_yen
 AND OLD.popularity IS NEW.popularity
BEGIN SELECT RAISE(IGNORE); END;
