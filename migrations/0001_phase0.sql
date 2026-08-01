CREATE TABLE IF NOT EXISTS probe_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_url TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual', 'cron')),
  ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
  http_status INTEGER NOT NULL,
  content_type TEXT,
  elapsed_ms INTEGER NOT NULL,
  body_bytes INTEGER NOT NULL,
  body_sha256 TEXT NOT NULL,
  page_kind TEXT NOT NULL,
  confidence REAL NOT NULL,
  markers_found_json TEXT NOT NULL,
  markers_missing_json TEXT NOT NULL,
  title TEXT,
  blocked_reason TEXT,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_probe_runs_fetched_at
  ON probe_runs(fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_probe_runs_source_url
  ON probe_runs(source_url, fetched_at DESC);
