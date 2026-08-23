const SELECTION_PREFIX = "final_daily_selection:";
const PREVIEW_PREFIX = "worker_live_preview:";
const SLA_PREFIX = "live_deadline_sla:";
const LEASE_KEY = "live-deadline-primary";
const OFFICIAL_ODDS_SOURCES = new Set(["jra-fast-official", "jra-crawl-official"]);

export type LiveDeadlineSlaAudit = {
  checkedAt: string;
  date: string;
  selectedRaceCount: number;
  previewReadyRaceIds: string[];
  finalReadyRaceIds: string[];
  previewMissingByT40RaceIds: string[];
  previewMissingByT30RaceIds: string[];
  finalMissingByT17RaceIds: string[];
  finalMissingByT16RaceIds: string[];
  deadlineMissedRaceIds: string[];
};

type SelectionPayload = { selected?: Array<{ raceId?: string }> };
type RaceSlaRow = { raceId: string; startTimeUtc: string | null; finalBetCount: number; previewJson: string | null };

function iso(now = new Date()): string { return now.toISOString(); }

function parseOfficialPreviewGeneratedAt(value: string | null): number {
  if (!value) return Number.NaN;
  try {
    const parsed = JSON.parse(value) as { version?: number; raceId?: string; snapshots?: Array<Record<string, unknown>> };
    if (parsed.version !== 1 || !Array.isArray(parsed.snapshots)) return Number.NaN;
    let newest = Number.NaN;
    for (const snapshot of parsed.snapshots) {
      const source = String(snapshot.oddsSource || "");
      if (!OFFICIAL_ODDS_SOURCES.has(source)) continue;
      const generatedAt = Date.parse(String(snapshot.generatedAt || ""));
      const oddsFetchedAt = Date.parse(String(snapshot.oddsFetchedAt || ""));
      if (!Number.isFinite(generatedAt) || !Number.isFinite(oddsFetchedAt)) continue;
      newest = Number.isFinite(newest) ? Math.max(newest, generatedAt) : generatedAt;
    }
    return newest;
  } catch {
    return Number.NaN;
  }
}

async function loadSelectedRaceIds(db: D1Database, date: string): Promise<string[]> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`).first<{ value: string }>();
  if (!row?.value) return [];
  try {
    const parsed = JSON.parse(row.value) as SelectionPayload;
    if (!Array.isArray(parsed.selected)) return [];
    return [...new Set(parsed.selected.map((item) => String(item.raceId || "")).filter(Boolean))];
  } catch {
    return [];
  }
}

export async function ensureLivePreviewSafetySchema(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      CREATE TABLE IF NOT EXISTS rt_live_preview_archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        race_id TEXT NOT NULL,
        envelope_json TEXT NOT NULL,
        newest_generated_at TEXT,
        archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_live_preview_archive_race_id ON rt_live_preview_archive(race_id,id DESC)"),
    db.prepare(`
      CREATE TABLE IF NOT EXISTS rt_live_deadline_lease (
        lease_key TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        expires_at_epoch INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_archive_live_preview_insert
      AFTER INSERT ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_preview:%' AND json_valid(NEW.state_value)=1
      BEGIN
        INSERT INTO rt_live_preview_archive(race_id,envelope_json,newest_generated_at)
        VALUES(
          COALESCE(json_extract(NEW.state_value,'$.raceId'), substr(NEW.state_key,21)),
          NEW.state_value,
          json_extract(NEW.state_value,'$.snapshots[0].generatedAt')
        );
      END
    `),
    db.prepare(`
      CREATE TRIGGER IF NOT EXISTS rt_archive_live_preview_update
      AFTER UPDATE OF state_value ON rt_system_state
      WHEN NEW.state_key LIKE 'worker_live_preview:%' AND json_valid(NEW.state_value)=1
      BEGIN
        INSERT INTO rt_live_preview_archive(race_id,envelope_json,newest_generated_at)
        VALUES(
          COALESCE(json_extract(NEW.state_value,'$.raceId'), substr(NEW.state_key,21)),
          NEW.state_value,
          json_extract(NEW.state_value,'$.snapshots[0].generatedAt')
        );
      END
    `),
  ]);
}

export async function acquireLiveDeadlineLease(db: D1Database, owner: string, ttlSeconds = 55): Promise<boolean> {
  const nowEpoch = Math.floor(Date.now() / 1000);
  const expiresAt = nowEpoch + Math.max(15, Math.trunc(ttlSeconds));
  await db.prepare(`
    INSERT INTO rt_live_deadline_lease(lease_key,owner,expires_at_epoch,updated_at)
    VALUES(?,?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(lease_key) DO UPDATE SET
      owner=excluded.owner,
      expires_at_epoch=excluded.expires_at_epoch,
      updated_at=CURRENT_TIMESTAMP
    WHERE rt_live_deadline_lease.expires_at_epoch <= ?
  `).bind(LEASE_KEY, owner, expiresAt, nowEpoch).run();
  const row = await db.prepare("SELECT owner,expires_at_epoch AS expiresAtEpoch FROM rt_live_deadline_lease WHERE lease_key=? LIMIT 1")
    .bind(LEASE_KEY).first<{ owner: string; expiresAtEpoch: number }>();
  return row?.owner === owner && Number(row.expiresAtEpoch) > nowEpoch;
}

export async function releaseLiveDeadlineLease(db: D1Database, owner: string): Promise<void> {
  await db.prepare("DELETE FROM rt_live_deadline_lease WHERE lease_key=? AND owner=?").bind(LEASE_KEY, owner).run();
}

export async function restoreNewestOfficialPreviewArchives(db: D1Database, date: string): Promise<string[]> {
  const ids = await loadSelectedRaceIds(db, date);
  const restored: string[] = [];
  for (const raceId of ids) {
    const current = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
      .bind(`${PREVIEW_PREFIX}${raceId}`).first<{ value: string }>();
    const archived = await db.prepare(`
      SELECT envelope_json AS value
      FROM rt_live_preview_archive
      WHERE race_id=?
      ORDER BY id DESC
      LIMIT 12
    `).bind(raceId).all<{ value: string }>();
    let bestValue = current?.value ?? null;
    let bestMs = parseOfficialPreviewGeneratedAt(bestValue);
    for (const row of archived.results ?? []) {
      const candidateMs = parseOfficialPreviewGeneratedAt(row.value);
      if (!Number.isFinite(candidateMs)) continue;
      if (!Number.isFinite(bestMs) || candidateMs > bestMs) {
        bestMs = candidateMs;
        bestValue = row.value;
      }
    }
    const currentMs = parseOfficialPreviewGeneratedAt(current?.value ?? null);
    if (bestValue && Number.isFinite(bestMs) && (!Number.isFinite(currentMs) || bestMs > currentMs)) {
      await db.prepare(`
        INSERT INTO rt_system_state(state_key,state_value,updated_at)
        VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
      `).bind(`${PREVIEW_PREFIX}${raceId}`, bestValue).run();
      restored.push(raceId);
    }
  }
  return restored;
}

export async function auditLiveDeadlineSla(db: D1Database, date: string, now = new Date()): Promise<LiveDeadlineSlaAudit> {
  const ids = await loadSelectedRaceIds(db, date);
  const audit: LiveDeadlineSlaAudit = {
    checkedAt: iso(now), date, selectedRaceCount: ids.length,
    previewReadyRaceIds: [], finalReadyRaceIds: [],
    previewMissingByT40RaceIds: [], previewMissingByT30RaceIds: [],
    finalMissingByT17RaceIds: [], finalMissingByT16RaceIds: [], deadlineMissedRaceIds: [],
  };
  if (!ids.length) return audit;
  const placeholders = ids.map(() => "?").join(",");
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId,r.start_time_utc AS startTimeUtc,
      (SELECT COUNT(*) FROM rt_public_bets b WHERE b.race_id=r.race_id AND b.source_prediction_id=-2) AS finalBetCount,
      (SELECT s.state_value FROM rt_system_state s WHERE s.state_key='worker_live_preview:'||r.race_id LIMIT 1) AS previewJson
    FROM rt_races r WHERE r.race_id IN (${placeholders})
  `).bind(...ids).all<RaceSlaRow>();
  for (const row of rows.results ?? []) {
    const raceId = String(row.raceId);
    const startMs = Date.parse(String(row.startTimeUtc || ""));
    if (!Number.isFinite(startMs)) continue;
    const remaining = startMs - now.getTime();
    const previewReady = Number.isFinite(parseOfficialPreviewGeneratedAt(row.previewJson));
    const finalReady = Number(row.finalBetCount) === 6;
    if (previewReady) audit.previewReadyRaceIds.push(raceId);
    if (finalReady) audit.finalReadyRaceIds.push(raceId);
    if (remaining > 0 && remaining <= 40 * 60_000 && !previewReady) audit.previewMissingByT40RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 30 * 60_000 && !previewReady) audit.previewMissingByT30RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 17 * 60_000 && !finalReady) audit.finalMissingByT17RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 16 * 60_000 && !finalReady) audit.finalMissingByT16RaceIds.push(raceId);
    if (remaining > 0 && remaining < 15 * 60_000 && !finalReady) audit.deadlineMissedRaceIds.push(raceId);
  }
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${SLA_PREFIX}${date}`, JSON.stringify(audit)).run();
  return audit;
}
