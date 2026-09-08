const SELECTION_PREFIX = "final_daily_selection:";
const PREVIEW_PREFIX = "worker_live_preview:";
const SLA_PREFIX = "live_deadline_sla:";
const LEASE_KEY = "live-deadline-primary";
const OFFICIAL_ODDS_SOURCES = new Set(["jra-fast-official", "jra-crawl-official"]);
const SLA_HEARTBEAT_INTERVAL_MS = 3 * 60_000;

export type LiveDeadlineSlaAudit = {
  checkedAt: string;
  date: string;
  selectedRaceCount: number;
  previewReadyRaceIds: string[];
  finalReadyRaceIds: string[];
  previewMissingByT40RaceIds: string[];
  previewMissingByT30RaceIds: string[];
  finalMissingByT30RaceIds: string[];
  finalMissingByT25RaceIds: string[];
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

// Kept as a compatibility hook for the live driver. Persistent schema is
// installed by migrate-live-runtime-guards.yml and verified by production
// readiness. Scheduled race-day Workers must not inspect sqlite_master/PRAGMA.
export async function ensureLivePreviewSafetySchema(_db: D1Database): Promise<void> {
  return;
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
    WHERE rt_live_deadline_lease.expires_at_epoch <= ? OR rt_live_deadline_lease.owner=excluded.owner
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

function slaFingerprint(audit: LiveDeadlineSlaAudit): string {
  return JSON.stringify({
    date: audit.date,
    selectedRaceCount: audit.selectedRaceCount,
    previewReadyRaceIds: audit.previewReadyRaceIds,
    finalReadyRaceIds: audit.finalReadyRaceIds,
    previewMissingByT40RaceIds: audit.previewMissingByT40RaceIds,
    previewMissingByT30RaceIds: audit.previewMissingByT30RaceIds,
    finalMissingByT30RaceIds: audit.finalMissingByT30RaceIds,
    finalMissingByT25RaceIds: audit.finalMissingByT25RaceIds,
    finalMissingByT17RaceIds: audit.finalMissingByT17RaceIds,
    finalMissingByT16RaceIds: audit.finalMissingByT16RaceIds,
    deadlineMissedRaceIds: audit.deadlineMissedRaceIds,
  });
}

async function persistSlaAuditIfNeeded(db: D1Database, audit: LiveDeadlineSlaAudit): Promise<void> {
  const key = `${SLA_PREFIX}${audit.date}`;
  const previous = await db.prepare("SELECT state_value AS value,updated_at AS updatedAt FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(key).first<{ value: string; updatedAt: string }>();
  let unchanged = false;
  if (previous?.value) {
    try { unchanged = slaFingerprint(JSON.parse(previous.value) as LiveDeadlineSlaAudit) === slaFingerprint(audit); }
    catch { unchanged = false; }
  }
  const previousMs = Date.parse(String(previous?.updatedAt || ""));
  const heartbeatDue = !Number.isFinite(previousMs) || Date.now() - previousMs >= SLA_HEARTBEAT_INTERVAL_MS;
  if (unchanged && !heartbeatDue) return;
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(key, JSON.stringify(audit)).run();
}

export async function auditLiveDeadlineSla(db: D1Database, date: string, now = new Date()): Promise<LiveDeadlineSlaAudit> {
  const ids = await loadSelectedRaceIds(db, date);
  const audit: LiveDeadlineSlaAudit = {
    checkedAt: iso(now), date, selectedRaceCount: ids.length,
    previewReadyRaceIds: [], finalReadyRaceIds: [],
    previewMissingByT40RaceIds: [], previewMissingByT30RaceIds: [],
    finalMissingByT30RaceIds: [], finalMissingByT25RaceIds: [],
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
    if (remaining > 0 && remaining <= 30 * 60_000 && !finalReady) audit.finalMissingByT30RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 25 * 60_000 && !finalReady) audit.finalMissingByT25RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 17 * 60_000 && !finalReady) audit.finalMissingByT17RaceIds.push(raceId);
    if (remaining > 0 && remaining <= 16 * 60_000 && !finalReady) audit.finalMissingByT16RaceIds.push(raceId);
    if (remaining > 0 && remaining < 10 * 60_000 && !finalReady) audit.deadlineMissedRaceIds.push(raceId);
  }
  await persistSlaAuditIfNeeded(db, audit);
  return audit;
}
