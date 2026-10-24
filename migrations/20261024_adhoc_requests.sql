-- ADHOC requests live in a separate table. No change to canonical selections, bets, results or model tables.
CREATE TABLE IF NOT EXISTS rt_adhoc_requests (
  race_id TEXT PRIMARY KEY NOT NULL,
  race_date TEXT NOT NULL,
  venue TEXT NOT NULL,
  race_no INTEGER NOT NULL,
  start_time_utc TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed','expired')),
  requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  completed_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  result_json TEXT,
  message TEXT
);
CREATE INDEX IF NOT EXISTS idx_rt_adhoc_date_status ON rt_adhoc_requests(race_date,status);
-- Atomic global hard ceiling: duplicate requests cannot add load and concurrent
-- visitors cannot create more than 3 jobs for any JRA race date.
CREATE TRIGGER IF NOT EXISTS trg_rt_adhoc_daily_cap
BEFORE INSERT ON rt_adhoc_requests
WHEN (SELECT COUNT(*) FROM rt_adhoc_requests WHERE race_date=NEW.race_date)>=3
BEGIN SELECT RAISE(IGNORE); END;
