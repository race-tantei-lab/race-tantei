var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// src/v1/utils.ts
function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
__name(escapeHtml, "escapeHtml");
function decodeEntities(value) {
  const named = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: " "
  };
  return value.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (_match, entity) => {
    if (/^#x/i.test(entity)) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    if (entity.startsWith("#")) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    return named[entity.toLowerCase()] ?? "";
  });
}
__name(decodeEntities, "decodeEntities");
function stripHtml(value) {
  return decodeEntities(
    value.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "").replace(/<!--[\s\S]*?-->/g, "").replace(/<\s*br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ")
  ).replace(/[\u00a0\t ]+/g, " ").replace(/\r/g, "").replace(/\n\s+/g, "\n").trim();
}
__name(stripHtml, "stripHtml");
function htmlToLines(html2) {
  return stripHtml(
    html2.replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n")
  ).split("\n").map((line) => line.trim()).filter(Boolean);
}
__name(htmlToLines, "htmlToLines");
function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
__name(positiveInt, "positiveInt");
function positiveNumber(value, fallback) {
  const parsed = Number.parseFloat(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
__name(positiveNumber, "positiveNumber");
function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
__name(clamp, "clamp");
function nowIso() {
  return (/* @__PURE__ */ new Date()).toISOString();
}
__name(nowIso, "nowIso");
function formatYen(value) {
  return `${Math.round(value).toLocaleString("ja-JP")}\u5186`;
}
__name(formatYen, "formatYen");
function parseJapaneseDateTime(year, month, day, time) {
  if (!time) return null;
  const match = time.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return new Date(Date.UTC(year, month - 1, day, hour - 9, minute)).toISOString();
}
__name(parseJapaneseDateTime, "parseJapaneseDateTime");
function isJstRaceWindow(date = /* @__PURE__ */ new Date()) {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1e3);
  const day = jst.getUTCDay();
  const hour = jst.getUTCHours();
  return (day === 0 || day === 6) && hour >= 8 && hour <= 20;
}
__name(isJstRaceWindow, "isJstRaceWindow");
function isJstEntryWindow(date = /* @__PURE__ */ new Date()) {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1e3);
  const day = jst.getUTCDay();
  return day >= 4 || day === 0;
}
__name(isJstEntryWindow, "isJstEntryWindow");

// src/v1/db.ts
var SCHEMA = [
  `CREATE TABLE IF NOT EXISTS rt_system_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE TABLE IF NOT EXISTS rt_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger_type TEXT NOT NULL,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
  )`,
  `CREATE TABLE IF NOT EXISTS rt_race_sources (
    entry_url TEXT PRIMARY KEY,
    result_url TEXT NOT NULL,
    race_id TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    next_fetch_at TEXT NOT NULL,
    last_entry_fetch_at TEXT,
    last_result_fetch_at TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE INDEX IF NOT EXISTS rt_idx_race_sources_due ON rt_race_sources(status, next_fetch_at)`,
  `CREATE TABLE IF NOT EXISTS rt_races (
    race_id TEXT PRIMARY KEY,
    race_date TEXT NOT NULL,
    venue TEXT NOT NULL,
    meeting_no INTEGER NOT NULL,
    meeting_day INTEGER NOT NULL,
    race_no INTEGER NOT NULL,
    race_name TEXT NOT NULL,
    conditions TEXT,
    surface TEXT,
    distance_m INTEGER,
    direction TEXT,
    start_time_jst TEXT,
    start_time_utc TEXT,
    weather TEXT,
    track_condition TEXT,
    entry_url TEXT NOT NULL,
    result_url TEXT NOT NULL,
    status TEXT NOT NULL,
    refund_horse_nos_json TEXT NOT NULL DEFAULT '[]',
    entry_updated_at TEXT,
    result_updated_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE INDEX IF NOT EXISTS rt_idx_races_date ON rt_races(race_date DESC, venue, race_no)`,
  `CREATE TABLE IF NOT EXISTS rt_runners (
    race_id TEXT NOT NULL,
    horse_no INTEGER NOT NULL,
    frame_no INTEGER,
    horse_name TEXT NOT NULL,
    sex_age TEXT,
    coat_color TEXT,
    horse_weight INTEGER,
    weight_change INTEGER,
    jockey TEXT,
    assigned_weight REAL,
    trainer TEXT,
    stable TEXT,
    win_odds REAL,
    popularity INTEGER,
    runner_status TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (race_id, horse_no)
  )`,
  `CREATE INDEX IF NOT EXISTS rt_idx_runners_horse ON rt_runners(horse_name)`,
  `CREATE INDEX IF NOT EXISTS rt_idx_runners_jockey ON rt_runners(jockey)`,
  `CREATE INDEX IF NOT EXISTS rt_idx_runners_trainer ON rt_runners(trainer)`,
  `CREATE TABLE IF NOT EXISTS rt_results (
    race_id TEXT NOT NULL,
    horse_no INTEGER NOT NULL,
    finish_position INTEGER,
    result_status TEXT NOT NULL,
    time_text TEXT,
    margin_text TEXT,
    final3f REAL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (race_id, horse_no)
  )`,
  `CREATE TABLE IF NOT EXISTS rt_payouts (
    race_id TEXT NOT NULL,
    bet_type TEXT NOT NULL,
    combination TEXT NOT NULL,
    payout_yen INTEGER NOT NULL,
    popularity INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (race_id, bet_type, combination)
  )`,
  `CREATE TABLE IF NOT EXISTS rt_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    locked_at TEXT,
    source_odds_at TEXT,
    payload_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (race_id, model_version)
  )`,
  `CREATE INDEX IF NOT EXISTS rt_idx_predictions_race ON rt_predictions(race_id, status)`,
  `CREATE TABLE IF NOT EXISTS rt_prediction_runners (
    prediction_id INTEGER NOT NULL,
    horse_no INTEGER NOT NULL,
    horse_name TEXT NOT NULL,
    predicted_order INTEGER NOT NULL,
    win_probability REAL NOT NULL,
    place_probability REAL NOT NULL,
    fair_odds REAL NOT NULL,
    current_odds REAL,
    expected_value_pct REAL,
    explanation TEXT NOT NULL,
    PRIMARY KEY (prediction_id, horse_no)
  )`,
  `CREATE TABLE IF NOT EXISTS rt_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL,
    race_id TEXT NOT NULL,
    bet_type TEXT NOT NULL,
    combination TEXT NOT NULL,
    stake_yen INTEGER NOT NULL,
    assumed_odds REAL NOT NULL,
    hit_probability REAL NOT NULL,
    expected_value_pct REAL NOT NULL,
    settlement_status TEXT NOT NULL DEFAULT 'pending',
    return_yen INTEGER,
    settled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (prediction_id, bet_type, combination)
  )`,
  `CREATE INDEX IF NOT EXISTS rt_idx_bets_settlement ON rt_bets(settlement_status, race_id)`,
  `CREATE TABLE IF NOT EXISTS rt_model_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    race_id TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`
];
async function ensureSchema(db) {
  for (const statement of SCHEMA) await db.prepare(statement).run();
}
__name(ensureSchema, "ensureSchema");
async function getState(db, key) {
  const row = await db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key = ?`).bind(key).first();
  return row?.value ?? null;
}
__name(getState, "getState");
async function setState(db, key, value) {
  await db.prepare(`
    INSERT INTO rt_system_state (state_key, state_value, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value, updated_at = CURRENT_TIMESTAMP
  `).bind(key, value).run();
}
__name(setState, "setState");
async function beginSyncRun(db, triggerType) {
  await db.prepare(`INSERT INTO rt_sync_runs (started_at, trigger_type) VALUES (?, ?)`).bind(nowIso(), triggerType).run();
  const row = await db.prepare(`SELECT last_insert_rowid() AS id`).first();
  return row?.id ?? 0;
}
__name(beginSyncRun, "beginSyncRun");
async function finishSyncRun(db, id, counts) {
  await db.prepare(`
    UPDATE rt_sync_runs SET finished_at = ?, discovered_count = ?, processed_count = ?, success_count = ?, error_count = ?, error_message = ?
    WHERE id = ?
  `).bind(nowIso(), counts.discovered, counts.processed, counts.success, counts.errors, counts.errorMessage ?? null, id).run();
}
__name(finishSyncRun, "finishSyncRun");
async function upsertRaceSources(db, entryUrls, resultUrlFor) {
  if (entryUrls.length === 0) return;
  const now = nowIso();
  const statements = entryUrls.map((entryUrl) => db.prepare(`
    INSERT INTO rt_race_sources (entry_url, result_url, next_fetch_at, updated_at)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(entry_url) DO UPDATE SET result_url = excluded.result_url, updated_at = CURRENT_TIMESTAMP
  `).bind(entryUrl, resultUrlFor(entryUrl), now));
  await db.batch(statements);
}
__name(upsertRaceSources, "upsertRaceSources");
async function resetRaceSourcesForDiscoveryRevision(db) {
  await db.prepare(`
    UPDATE rt_race_sources
    SET status = 'discovered', next_fetch_at = ?, failure_count = 0,
        last_error = NULL, updated_at = CURRENT_TIMESTAMP
  `).bind(nowIso()).run();
}
__name(resetRaceSourcesForDiscoveryRevision, "resetRaceSourcesForDiscoveryRevision");
async function getDueRaceSources(db, limit) {
  const result = await db.prepare(`
    SELECT entry_url AS entryUrl, result_url AS resultUrl, race_id AS raceId, status,
           next_fetch_at AS nextFetchAt, failure_count AS failureCount
    FROM rt_race_sources
    WHERE status != 'complete' AND next_fetch_at <= ?
    ORDER BY CASE status WHEN 'awaiting_result' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, next_fetch_at
    LIMIT ?
  `).bind(nowIso(), limit).all();
  return result.results;
}
__name(getDueRaceSources, "getDueRaceSources");
async function updateRaceSource(db, entryUrl, values) {
  const failureDelta = values.error ? 1 : 0;
  await db.prepare(`
    UPDATE rt_race_sources SET
      race_id = COALESCE(?, race_id),
      status = ?,
      next_fetch_at = ?,
      last_entry_fetch_at = CASE WHEN ? THEN ? ELSE last_entry_fetch_at END,
      last_result_fetch_at = CASE WHEN ? THEN ? ELSE last_result_fetch_at END,
      failure_count = CASE WHEN ? = 1 THEN failure_count + 1 ELSE 0 END,
      last_error = ?,
      updated_at = CURRENT_TIMESTAMP
    WHERE entry_url = ?
  `).bind(
    values.raceId ?? null,
    values.status,
    values.nextFetchAt,
    values.entryFetched ? 1 : 0,
    nowIso(),
    values.resultFetched ? 1 : 0,
    nowIso(),
    failureDelta,
    values.error ?? null,
    entryUrl
  ).run();
}
__name(updateRaceSource, "updateRaceSource");
function raceValues(race) {
  return [
    race.raceId,
    race.raceDate,
    race.venue,
    race.meetingNo,
    race.meetingDay,
    race.raceNo,
    race.raceName,
    race.conditions,
    race.surface,
    race.distanceM,
    race.direction,
    race.startTimeJst,
    race.startTimeUtc,
    race.weather,
    race.trackCondition,
    race.entryUrl,
    race.resultUrl,
    race.status
  ];
}
__name(raceValues, "raceValues");
async function saveEntryBundle(db, bundle) {
  const race = bundle.race;
  await db.prepare(`
    INSERT INTO rt_races (
      race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name, conditions,
      surface, distance_m, direction, start_time_jst, start_time_utc, weather, track_condition,
      entry_url, result_url, status, entry_updated_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id) DO UPDATE SET
      race_date=excluded.race_date, venue=excluded.venue, meeting_no=excluded.meeting_no,
      meeting_day=excluded.meeting_day, race_no=excluded.race_no, race_name=excluded.race_name,
      conditions=excluded.conditions, surface=excluded.surface, distance_m=excluded.distance_m,
      direction=excluded.direction, start_time_jst=excluded.start_time_jst,
      start_time_utc=excluded.start_time_utc, weather=COALESCE(excluded.weather, rt_races.weather),
      track_condition=COALESCE(excluded.track_condition, rt_races.track_condition), entry_url=excluded.entry_url,
      result_url=excluded.result_url, status=CASE WHEN rt_races.status='finished' THEN rt_races.status ELSE excluded.status END,
      entry_updated_at=excluded.entry_updated_at, updated_at=CURRENT_TIMESTAMP
  `).bind(...raceValues(race), nowIso()).run();
  const statements = bundle.runners.map((runner) => db.prepare(`
    INSERT INTO rt_runners (
      race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight, weight_change,
      jockey, assigned_weight, trainer, stable, win_odds, popularity, runner_status, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, horse_no) DO UPDATE SET
      frame_no=excluded.frame_no, horse_name=excluded.horse_name, sex_age=excluded.sex_age,
      coat_color=excluded.coat_color, horse_weight=excluded.horse_weight, weight_change=excluded.weight_change,
      jockey=excluded.jockey, assigned_weight=excluded.assigned_weight, trainer=excluded.trainer,
      stable=excluded.stable, win_odds=excluded.win_odds, popularity=excluded.popularity,
      runner_status=excluded.runner_status, updated_at=CURRENT_TIMESTAMP
  `).bind(
    race.raceId,
    runner.horseNo,
    runner.frameNo,
    runner.horseName,
    runner.sexAge,
    runner.coatColor,
    runner.horseWeight,
    runner.weightChange,
    runner.jockey,
    runner.assignedWeight,
    runner.trainer,
    runner.stable,
    runner.winOdds,
    runner.popularity,
    runner.runnerStatus
  ));
  if (statements.length > 0) await db.batch(statements);
}
__name(saveEntryBundle, "saveEntryBundle");
async function saveResultBundle(db, bundle) {
  const race = bundle.race;
  await db.prepare(`
    UPDATE rt_races SET status='finished', weather=?, track_condition=?, refund_horse_nos_json=?,
      result_updated_at=?, updated_at=CURRENT_TIMESTAMP
    WHERE race_id=?
  `).bind(race.weather, race.trackCondition, JSON.stringify(bundle.refundHorseNos), nowIso(), race.raceId).run();
  const resultStatements = bundle.results.map((result) => db.prepare(`
    INSERT INTO rt_results (race_id, horse_no, finish_position, result_status, time_text, margin_text, final3f, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, horse_no) DO UPDATE SET finish_position=excluded.finish_position,
      result_status=excluded.result_status, time_text=excluded.time_text, margin_text=excluded.margin_text,
      final3f=excluded.final3f, updated_at=CURRENT_TIMESTAMP
  `).bind(race.raceId, result.horseNo, result.finishPosition, result.resultStatus, result.timeText, result.marginText, result.final3f));
  if (resultStatements.length > 0) await db.batch(resultStatements);
  const payoutStatements = bundle.payouts.map((payout) => db.prepare(`
    INSERT INTO rt_payouts (race_id, bet_type, combination, payout_yen, popularity, updated_at)
    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET payout_yen=excluded.payout_yen,
      popularity=excluded.popularity, updated_at=CURRENT_TIMESTAMP
  `).bind(race.raceId, payout.betType, payout.combination, payout.payoutYen, payout.popularity));
  if (payoutStatements.length > 0) await db.batch(payoutStatements);
}
__name(saveResultBundle, "saveResultBundle");
async function getRace(db, raceId) {
  return await db.prepare(`
    SELECT race_id AS raceId, race_date AS raceDate, venue, meeting_no AS meetingNo,
      meeting_day AS meetingDay, race_no AS raceNo, race_name AS raceName, conditions,
      surface, distance_m AS distanceM, direction, start_time_jst AS startTimeJst,
      start_time_utc AS startTimeUtc, weather, track_condition AS trackCondition,
      entry_url AS entryUrl, result_url AS resultUrl, status
    FROM rt_races WHERE race_id=?
  `).bind(raceId).first();
}
__name(getRace, "getRace");
async function getRunners(db, raceId) {
  const result = await db.prepare(`
    SELECT horse_no AS horseNo, frame_no AS frameNo, horse_name AS horseName, sex_age AS sexAge,
      coat_color AS coatColor, horse_weight AS horseWeight, weight_change AS weightChange,
      jockey, assigned_weight AS assignedWeight, trainer, stable, win_odds AS winOdds,
      popularity, runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all();
  return result.results;
}
__name(getRunners, "getRunners");
async function getRunnerHistoryStats(db, race, _runners) {
  const result = await db.prepare(`
    SELECT cur.horse_no AS horseNo,
      (SELECT COUNT(*) FROM rt_runners h JOIN rt_results hr ON hr.race_id=h.race_id AND hr.horse_no=h.horse_no JOIN rt_races hra ON hra.race_id=h.race_id WHERE h.horse_name=cur.horse_name AND hra.race_date < current_race.race_date) AS horseStarts,
      (SELECT COALESCE(SUM(CASE WHEN hr.finish_position=1 THEN 1 ELSE 0 END),0) FROM rt_runners h JOIN rt_results hr ON hr.race_id=h.race_id AND hr.horse_no=h.horse_no JOIN rt_races hra ON hra.race_id=h.race_id WHERE h.horse_name=cur.horse_name AND hra.race_date < current_race.race_date) AS horseWins,
      (SELECT COALESCE(SUM(CASE WHEN hr.finish_position BETWEEN 1 AND 3 THEN 1 ELSE 0 END),0) FROM rt_runners h JOIN rt_results hr ON hr.race_id=h.race_id AND hr.horse_no=h.horse_no JOIN rt_races hra ON hra.race_id=h.race_id WHERE h.horse_name=cur.horse_name AND hra.race_date < current_race.race_date) AS horsePlaces,
      (SELECT COUNT(*) FROM rt_runners j JOIN rt_results jr ON jr.race_id=j.race_id AND jr.horse_no=j.horse_no JOIN rt_races jra ON jra.race_id=j.race_id WHERE j.jockey=cur.jockey AND cur.jockey IS NOT NULL AND jra.race_date < current_race.race_date) AS jockeyStarts,
      (SELECT COALESCE(SUM(CASE WHEN jr.finish_position=1 THEN 1 ELSE 0 END),0) FROM rt_runners j JOIN rt_results jr ON jr.race_id=j.race_id AND jr.horse_no=j.horse_no JOIN rt_races jra ON jra.race_id=j.race_id WHERE j.jockey=cur.jockey AND cur.jockey IS NOT NULL AND jra.race_date < current_race.race_date) AS jockeyWins,
      (SELECT COUNT(*) FROM rt_runners t JOIN rt_results tr ON tr.race_id=t.race_id AND tr.horse_no=t.horse_no JOIN rt_races tra ON tra.race_id=t.race_id WHERE t.trainer=cur.trainer AND cur.trainer IS NOT NULL AND tra.race_date < current_race.race_date) AS trainerStarts,
      (SELECT COALESCE(SUM(CASE WHEN tr.finish_position=1 THEN 1 ELSE 0 END),0) FROM rt_runners t JOIN rt_results tr ON tr.race_id=t.race_id AND tr.horse_no=t.horse_no JOIN rt_races tra ON tra.race_id=t.race_id WHERE t.trainer=cur.trainer AND cur.trainer IS NOT NULL AND tra.race_date < current_race.race_date) AS trainerWins,
      (SELECT COUNT(*) FROM rt_runners c JOIN rt_results cr ON cr.race_id=c.race_id AND cr.horse_no=c.horse_no JOIN rt_races cra ON cra.race_id=c.race_id WHERE c.horse_name=cur.horse_name AND cra.venue=current_race.venue AND cra.surface=current_race.surface AND cra.distance_m=current_race.distance_m AND cra.race_date < current_race.race_date) AS courseStarts,
      (SELECT COALESCE(SUM(CASE WHEN cr.finish_position=1 THEN 1 ELSE 0 END),0) FROM rt_runners c JOIN rt_results cr ON cr.race_id=c.race_id AND cr.horse_no=c.horse_no JOIN rt_races cra ON cra.race_id=c.race_id WHERE c.horse_name=cur.horse_name AND cra.venue=current_race.venue AND cra.surface=current_race.surface AND cra.distance_m=current_race.distance_m AND cra.race_date < current_race.race_date) AS courseWins
    FROM rt_runners cur JOIN rt_races current_race ON current_race.race_id=cur.race_id
    WHERE cur.race_id=? ORDER BY cur.horse_no
  `).bind(race.raceId).all();
  return result.results;
}
__name(getRunnerHistoryStats, "getRunnerHistoryStats");
async function savePrediction(db, raceId, prediction, status) {
  const existing = await db.prepare(`
    SELECT id, status FROM rt_predictions WHERE race_id=? AND model_version=?
  `).bind(raceId, prediction.modelVersion).first();
  if (existing?.status === "locked") return { saved: false, predictionId: existing.id };
  await db.prepare(`
    INSERT INTO rt_predictions (race_id, model_version, status, generated_at, locked_at, source_odds_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, model_version) DO UPDATE SET
      status=excluded.status, generated_at=excluded.generated_at,
      locked_at=CASE WHEN excluded.status='locked' THEN excluded.locked_at ELSE rt_predictions.locked_at END,
      source_odds_at=excluded.source_odds_at, updated_at=CURRENT_TIMESTAMP
    WHERE rt_predictions.status != 'locked'
  `).bind(
    raceId,
    prediction.modelVersion,
    status,
    prediction.generatedAt,
    status === "locked" ? prediction.generatedAt : null,
    prediction.generatedAt
  ).run();
  const row = await db.prepare(`SELECT id, status FROM rt_predictions WHERE race_id=? AND model_version=?`).bind(raceId, prediction.modelVersion).first();
  if (!row) return { saved: false, predictionId: null };
  await db.prepare(`DELETE FROM rt_prediction_runners WHERE prediction_id=?`).bind(row.id).run();
  await db.prepare(`DELETE FROM rt_bets WHERE prediction_id=? AND settlement_status='pending'`).bind(row.id).run();
  const runnerStatements = prediction.runners.map((runner) => db.prepare(`
    INSERT INTO rt_prediction_runners (
      prediction_id, horse_no, horse_name, predicted_order, win_probability, place_probability,
      fair_odds, current_odds, expected_value_pct, explanation
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    row.id,
    runner.horseNo,
    runner.horseName,
    runner.predictedOrder,
    runner.winProbability,
    runner.placeProbability,
    runner.fairOdds,
    runner.currentOdds,
    runner.expectedValuePct,
    runner.explanation
  ));
  if (runnerStatements.length > 0) await db.batch(runnerStatements);
  const betStatements = prediction.bets.map((bet) => db.prepare(`
    INSERT INTO rt_bets (
      prediction_id, race_id, bet_type, combination, stake_yen, assumed_odds,
      hit_probability, expected_value_pct, settlement_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
  `).bind(
    row.id,
    raceId,
    bet.betType,
    bet.combination,
    bet.stakeYen,
    bet.assumedOdds,
    bet.hitProbability,
    bet.expectedValuePct
  ));
  if (betStatements.length > 0) await db.batch(betStatements);
  return { saved: true, predictionId: row.id };
}
__name(savePrediction, "savePrediction");
function canonicalCombination(betType, combination) {
  const numbers = (combination.match(/\d{1,2}/g) ?? []).map(Number);
  if (["\u30EF\u30A4\u30C9", "\u99AC\u9023", "3\u9023\u8907"].includes(betType)) numbers.sort((a, b) => a - b);
  return numbers.join("-");
}
__name(canonicalCombination, "canonicalCombination");
async function settleRace(db, raceId) {
  const race = await db.prepare(`SELECT refund_horse_nos_json AS refunds FROM rt_races WHERE race_id=? AND status='finished'`).bind(raceId).first();
  if (!race) return 0;
  const refunds = new Set(JSON.parse(race.refunds || "[]"));
  const payoutRows = await db.prepare(`SELECT bet_type AS betType, combination, payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?`).bind(raceId).all();
  const payoutMap = new Map(payoutRows.results.map((row) => [
    `${row.betType}:${canonicalCombination(row.betType, row.combination)}`,
    row.payoutYen
  ]));
  const pending = await db.prepare(`
    SELECT b.id, b.bet_type AS betType, b.combination, b.stake_yen AS stakeYen
    FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE b.race_id=? AND b.settlement_status='pending' AND p.status='locked'
  `).bind(raceId).all();
  for (const bet of pending.results) {
    const horses = (bet.combination.match(/\d{1,2}/g) ?? []).map(Number);
    let returnYen = 0;
    if (horses.some((horseNo) => refunds.has(horseNo))) {
      returnYen = bet.stakeYen;
    } else {
      const key = `${bet.betType}:${canonicalCombination(bet.betType, bet.combination)}`;
      const payout = payoutMap.get(key) ?? 0;
      returnYen = Math.round(bet.stakeYen / 100 * payout);
    }
    await db.prepare(`
      UPDATE rt_bets SET settlement_status='settled', return_yen=?, settled_at=? WHERE id=?
    `).bind(returnYen, nowIso(), bet.id).run();
  }
  return pending.results.length;
}
__name(settleRace, "settleRace");
async function getDashboardMetrics(db) {
  const raceCount = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races`).first();
  const predictionCount = await db.prepare(`SELECT COUNT(*) AS count FROM rt_predictions WHERE status='locked'`).first();
  const bets = await db.prepare(`
    SELECT COUNT(*) AS count, COALESCE(SUM(stake_yen),0) AS stake,
      COALESCE(SUM(return_yen),0) AS returns,
      COALESCE(SUM(CASE WHEN return_yen > 0 THEN 1 ELSE 0 END),0) AS hits
    FROM rt_bets WHERE settlement_status='settled'
  `).first();
  const stake = bets?.stake ?? 0;
  const returns = bets?.returns ?? 0;
  const count = bets?.count ?? 0;
  return {
    raceCount: raceCount?.count ?? 0,
    predictionCount: predictionCount?.count ?? 0,
    settledBetCount: count,
    totalStakeYen: stake,
    totalReturnYen: returns,
    profitYen: returns - stake,
    roiPct: stake > 0 ? returns / stake * 100 : null,
    hitRatePct: count > 0 ? (bets?.hits ?? 0) / count * 100 : null
  };
}
__name(getDashboardMetrics, "getDashboardMetrics");
async function getLatestRaces(db, limit = 80) {
  const result = await db.prepare(`
    SELECT ra.race_id AS raceId, ra.race_date AS raceDate, ra.venue, ra.race_no AS raceNo,
      ra.race_name AS raceName, ra.start_time_jst AS startTimeJst, ra.status,
      pr.status AS predictionStatus,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=pr.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=pr.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT COUNT(*) FROM rt_bets WHERE prediction_id=pr.id) AS betCount
    FROM rt_races ra
    LEFT JOIN rt_predictions pr ON pr.race_id=ra.race_id AND pr.model_version=(SELECT model_version FROM rt_predictions p2 WHERE p2.race_id=ra.race_id ORDER BY id DESC LIMIT 1)
    ORDER BY ra.race_date DESC, ra.venue, ra.race_no
    LIMIT ?
  `).bind(limit).all();
  return result.results;
}
__name(getLatestRaces, "getLatestRaces");
async function getRaceDetail(db, raceId) {
  const race = await getRace(db, raceId);
  if (!race) return null;
  const runnersResult = await db.prepare(`
    SELECT rr.horse_no AS horseNo, rr.frame_no AS frameNo, rr.horse_name AS horseName,
      rr.sex_age AS sexAge, rr.coat_color AS coatColor, rr.horse_weight AS horseWeight,
      rr.weight_change AS weightChange, rr.jockey, rr.assigned_weight AS assignedWeight,
      rr.trainer, rr.stable, rr.win_odds AS winOdds, rr.popularity, rr.runner_status AS runnerStatus,
      res.finish_position AS finishPosition
    FROM rt_runners rr LEFT JOIN rt_results res ON res.race_id=rr.race_id AND res.horse_no=rr.horse_no
    WHERE rr.race_id=? ORDER BY rr.horse_no
  `).bind(raceId).all();
  const prediction = await db.prepare(`
    SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
    FROM rt_predictions WHERE race_id=? ORDER BY id DESC LIMIT 1
  `).bind(raceId).first();
  if (!prediction) return { race, runners: runnersResult.results, prediction: null, predictedRunners: [], bets: [] };
  const predicted = await db.prepare(`
    SELECT horse_no AS horseNo, horse_name AS horseName, predicted_order AS predictedOrder,
      win_probability AS winProbability, place_probability AS placeProbability, fair_odds AS fairOdds,
      current_odds AS currentOdds, expected_value_pct AS expectedValuePct, explanation
    FROM rt_prediction_runners WHERE prediction_id=? ORDER BY predicted_order
  `).bind(prediction.id).all();
  const bets = await db.prepare(`
    SELECT bet_type AS betType, combination, stake_yen AS stakeYen, assumed_odds AS assumedOdds,
      expected_value_pct AS expectedValuePct, settlement_status AS settlementStatus, return_yen AS returnYen
    FROM rt_bets WHERE prediction_id=? ORDER BY expected_value_pct DESC
  `).bind(prediction.id).all();
  return { race, runners: runnersResult.results, prediction, predictedRunners: predicted.results, bets: bets.results };
}
__name(getRaceDetail, "getRaceDetail");
async function getPerformanceRows(db) {
  const result = await db.prepare(`
    SELECT substr(ra.race_date,1,7) AS label, COUNT(b.id) AS rt_bets,
      COALESCE(SUM(b.stake_yen),0) AS stake, COALESCE(SUM(b.return_yen),0) AS returns
    FROM rt_bets b JOIN rt_races ra ON ra.race_id=b.race_id
    WHERE b.settlement_status='settled'
    GROUP BY substr(ra.race_date,1,7) ORDER BY label DESC
  `).all();
  return result.results.map((row) => ({ ...row, roi: row.stake > 0 ? row.returns / row.stake * 100 : null }));
}
__name(getPerformanceRows, "getPerformanceRows");
async function getSystemSnapshot(db) {
  const lastSync = await db.prepare(`SELECT * FROM rt_sync_runs ORDER BY id DESC LIMIT 1`).first();
  const sourceCounts = await db.prepare(`SELECT status, COUNT(*) AS count FROM rt_race_sources GROUP BY status`).all();
  const lastRace = await db.prepare(`SELECT race_id, updated_at FROM rt_races ORDER BY updated_at DESC LIMIT 1`).first();
  return { lastSync, sourceCounts: sourceCounts.results, lastRace, now: nowIso() };
}
__name(getSystemSnapshot, "getSystemSnapshot");

// src/v1/jra.ts
var ALLOWED_HOSTS = /* @__PURE__ */ new Set(["www.jra.go.jp", "jra.jp", "sp.jra.jp"]);
var MAX_BODY_BYTES = 3e6;
var FETCH_TIMEOUT_MS = 2e4;
var VENUES = "\u672D\u5E4C|\u51FD\u9928|\u798F\u5CF6|\u65B0\u6F5F|\u6771\u4EAC|\u4E2D\u5C71|\u4E2D\u4EAC|\u4EAC\u90FD|\u962A\u795E|\u5C0F\u5009";
function validateUrl(rawUrl) {
  const normalized = rawUrl.replace(/\\u0026/gi, "&").replace(/\\\//g, "/").replace(/&amp;/gi, "&");
  const url = new URL(normalized);
  if (url.protocol !== "https:") throw new Error("HTTPS_REQUIRED");
  if (!ALLOWED_HOSTS.has(url.hostname)) throw new Error("HOST_NOT_ALLOWED");
  return url;
}
__name(validateUrl, "validateUrl");
function decodePage(buffer, contentType) {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1] ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1] ?? null;
  const candidates = [declared, meta, "shift_jis", "utf-8"].filter((value) => Boolean(value));
  for (const charset of candidates) {
    try {
      return new TextDecoder(charset).decode(buffer);
    } catch {
    }
  }
  return new TextDecoder("utf-8").decode(buffer);
}
__name(decodePage, "decodePage");
async function fetchJraPage(rawUrl, fetchImpl = fetch) {
  const initial = validateUrl(rawUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(initial.toString(), {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.5",
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        Referer: "https://www.jra.go.jp/",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
      }
    });
    const finalUrl = validateUrl(response.url || initial.toString());
    const declaredLength = Number(response.headers.get("content-length") ?? "0");
    if (declaredLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const contentType = response.headers.get("content-type");
    const html2 = decodePage(buffer, contentType);
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable/i.test(html2)) throw new Error("BLOCKED_PAGE");
    return { url: finalUrl.toString(), html: html2, status: response.status, contentType };
  } finally {
    clearTimeout(timer);
  }
}
__name(fetchJraPage, "fetchJraPage");
function parsedRows(html2) {
  const rows = [];
  for (const rowMatch of html2.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const rowHtml = rowMatch[0] ?? "";
    const cells = [];
    for (const cellMatch of (rowMatch[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)) cells.push(stripHtml(cellMatch[1] ?? "").replace(/\n+/g, " ").trim());
    if (cells.length > 0) rows.push({ html: rowHtml, cells });
  }
  return rows;
}
__name(parsedRows, "parsedRows");
function allUrlCandidates(html2) {
  const candidates = [];
  for (const match of html2.matchAll(/(?:href|data-url|data-href)\s*=\s*["']([^"']+)["']/gi)) candidates.push(match[1] ?? "");
  for (const match of html2.matchAll(/(?:https?:\\?\/\\?\/[^"'\s<>]+|\/JRADB\/(?:accessD|accessS)\.html\?CNAME=[^"'\s<>]+)/gi)) candidates.push(match[0] ?? "");
  return candidates.map((value) => decodeEntities(value).replace(/\\u0026/gi, "&").replace(/\\\//g, "/"));
}
__name(allUrlCandidates, "allUrlCandidates");
function extractJraDbLinks(html2, baseUrl, kind) {
  const found = /* @__PURE__ */ new Map();
  const pathPattern = kind === "entry" ? /\/JRADB\/accessD\.html$/i : /\/JRADB\/accessS\.html$/i;
  const cnamePattern = kind === "entry" ? /(?:pw|sw)01dde/i : /(?:pw|sw)01sde/i;
  for (const candidate of allUrlCandidates(html2)) {
    try {
      const url = new URL(candidate, baseUrl);
      if (!ALLOWED_HOSTS.has(url.hostname) || !pathPattern.test(url.pathname)) continue;
      const cname = decodeURIComponent(url.searchParams.get("CNAME") ?? "");
      if (!cnamePattern.test(cname)) continue;
      found.set(cname, url.toString());
    } catch {
    }
  }
  return [...found.values()];
}
__name(extractJraDbLinks, "extractJraDbLinks");
function extractEntryLinks(html2, baseUrl) {
  return extractJraDbLinks(html2, baseUrl, "entry");
}
__name(extractEntryLinks, "extractEntryLinks");
function extractResultLinks(html2, baseUrl) {
  return extractJraDbLinks(html2, baseUrl, "result");
}
__name(extractResultLinks, "extractResultLinks");
function extractResultUrl(html2, baseUrl) {
  return extractResultLinks(html2, baseUrl)[0] ?? null;
}
__name(extractResultUrl, "extractResultUrl");
function extractEntryUrl(html2, baseUrl) {
  return extractEntryLinks(html2, baseUrl)[0] ?? null;
}
__name(extractEntryUrl, "extractEntryUrl");
function toResultUrl(entryUrl) {
  const url = validateUrl(entryUrl);
  url.pathname = url.pathname.replace(/accessD\.html$/i, "accessS.html");
  const cname = url.searchParams.get("CNAME");
  if (cname) url.searchParams.set("CNAME", cname.replace(/((?:pw|sw)01)dde/i, "$1sde"));
  return url.toString();
}
__name(toResultUrl, "toResultUrl");
function venueSlug(venue) {
  const map = { \u672D\u5E4C: "sapporo", \u51FD\u9928: "hakodate", \u798F\u5CF6: "fukushima", \u65B0\u6F5F: "niigata", \u6771\u4EAC: "tokyo", \u4E2D\u5C71: "nakayama", \u4E2D\u4EAC: "chukyo", \u4EAC\u90FD: "kyoto", \u962A\u795E: "hanshin", \u5C0F\u5009: "kokura" };
  return map[venue] ?? encodeURIComponent(venue);
}
__name(venueSlug, "venueSlug");
function normalizeText(html2) {
  return stripHtml(html2.replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n").replace(/<\s*br\s*\/?>/gi, "\n"));
}
__name(normalizeText, "normalizeText");
function headingTexts(html2) {
  const headings = [];
  for (const match of html2.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/gi)) {
    const text = stripHtml(match[1] ?? "").replace(/\s+/g, " ").trim();
    if (text) headings.push(text);
  }
  return headings;
}
__name(headingTexts, "headingTexts");
function parseRaceName(html2, raceNo) {
  const explicitHtml = html2.match(/<span\b[^>]*class=["'][^"']*\btitleRaceName\b[^"']*["'][^>]*>([\s\S]*?)<\/span>/i)?.[1];
  if (explicitHtml) {
    const explicitName = stripHtml(explicitHtml).replace(/\s+/g, " ").trim();
    if (explicitName) return explicitName;
  }
  for (const raw of headingTexts(html2)) {
    const text = raw.replace(new RegExp(`^${raceNo}(?:R|\u30EC\u30FC\u30B9)\\s*`), "").trim();
    if (!text || /^(?:出馬表|レース結果|払戻金|関連メニュー|コースレコード|勝馬の紹介)$/.test(text)) continue;
    if (/20\d{2}年|\d+回(?:札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\d+日/.test(text)) continue;
    if (/^(?:\d+歳|障害|サラ系)/.test(text) && /(?:クラス|未勝利|新馬|オープン)/.test(text)) continue;
    return text;
  }
  const match = normalizeText(html2).match(new RegExp(`${raceNo}(?:R|\u30EC\u30FC\u30B9)\\s*([^\\n]+)`));
  return match?.[1]?.trim() || `${raceNo}\u30EC\u30FC\u30B9`;
}
__name(parseRaceName, "parseRaceName");
function parseHeader(html2, pageUrl, isResult) {
  const text = normalizeText(html2);
  const dateVenue = text.match(new RegExp(`(20\\d{2})\u5E74(\\d{1,2})\u6708(\\d{1,2})\u65E5[^\\n]*?(\\d+)\u56DE(${VENUES})(\\d+)\u65E5`));
  if (!dateVenue) throw new Error("RACE_DATE_VENUE_NOT_FOUND");
  const year = Number(dateVenue[1]);
  const month = Number(dateVenue[2]);
  const day = Number(dateVenue[3]);
  const meetingNo = Number(dateVenue[4]);
  const venue = dateVenue[5] ?? "";
  const meetingDay = Number(dateVenue[6]);
  const timeJapanese = text.match(/発走時刻\s*[：:]?\s*(\d{1,2})時(\d{2})分/);
  const timeColon = text.match(/発走\s*[：:]?\s*(\d{1,2}):(\d{2})/);
  const timeH = timeJapanese?.[1] ?? timeColon?.[1] ?? null;
  const timeM = timeJapanese?.[2] ?? timeColon?.[2] ?? null;
  const startTimeJst = timeH && timeM ? `${timeH.padStart(2, "0")}:${timeM}` : null;
  const raceMatches = [...text.matchAll(/(?:^|\s)(\d{1,2})(?:R|レース)(?:\s|$)/gm)].map((m) => Number(m[1])).filter((v) => v >= 1 && v <= 12);
  const decodedCname = decodeURIComponent(new URL(pageUrl).searchParams.get("CNAME") ?? "");
  const cnameRaceNo = Number(decodedCname.match(/(\d{2})20\d{6}\//i)?.[1] ?? 0);
  const raceNo = cnameRaceNo >= 1 && cnameRaceNo <= 12 ? cnameRaceNo : raceMatches[0] ?? 0;
  if (!raceNo) throw new Error("RACE_NUMBER_NOT_FOUND");
  const raceName = parseRaceName(html2, raceNo);
  const course = text.match(/コース\s*[：:]?\s*([0-9,]+)(?:メートル|m)\s*[（(]?\s*(芝|ダート|障害)(?:[・\s]*(右|左|直線|外|内|外内|内外))?/);
  const distanceM = course?.[1] ? Number(course[1].replace(/,/g, "")) : null;
  const surface = course?.[2] ?? null;
  const direction = course?.[3] ?? null;
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const raceNameIndex = lines.findIndex((line) => line === raceName || line.endsWith(` ${raceName}`));
  const conditionLine = raceNameIndex >= 0 ? lines.slice(raceNameIndex + 1, raceNameIndex + 6).find((line) => /コース/.test(line)) ?? null : lines.find((line) => /コース\s*[：:]?\s*[0-9,]+/.test(line)) ?? null;
  const conditions = conditionLine?.replace(/\s*コース[\s\S]*$/, "").trim() || null;
  const weather = text.match(/天候\s*[：:]?\s*([^\s\n]+)/)?.[1] ?? null;
  const trackCondition = text.match(/(?:芝|ダート)\s*[：:]?\s*(良|稍重|重|不良)/)?.[1] ?? null;
  const raceDate = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const explicitEntry = isResult ? extractEntryUrl(html2, pageUrl) : pageUrl;
  const entryUrl = explicitEntry ?? (isResult ? pageUrl.replace(/accessS\.html/i, "accessD.html").replace(/((?:pw|sw)01)sde/i, "$1dde") : pageUrl);
  const resultUrl = (isResult ? pageUrl : extractResultUrl(html2, pageUrl)) ?? toResultUrl(entryUrl);
  return { raceId: `${raceDate}-${venueSlug(venue)}-${String(raceNo).padStart(2, "0")}`, raceDate, venue, meetingNo, meetingDay, raceNo, raceName, conditions, surface, distanceM, direction, startTimeJst, startTimeUtc: parseJapaneseDateTime(year, month, day, startTimeJst), weather, trackCondition, entryUrl, resultUrl, status: isResult ? "finished" : "scheduled" };
}
__name(parseHeader, "parseHeader");
function lastStableMatch(text) {
  const matches = [...text.matchAll(/([A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((美浦|栗東|本会外)\)/gu)];
  const match = matches.at(-1);
  return match?.[1] && match?.[2] ? { trainer: match[1].trim(), stable: match[2] } : null;
}
__name(lastStableMatch, "lastStableMatch");
function parseHorseName(detail) {
  const compact = detail.replace(/\s+/g, " ").trim();
  const oddsIndex = compact.search(/\d+(?:\.\d+)?\s*\(\d+番人気\)/);
  if (oddsIndex > 0) return compact.slice(0, oddsIndex).trim();
  const statusIndex = compact.search(/(?:取消|除外)/);
  if (statusIndex > 0) return compact.slice(0, statusIndex).trim();
  const pedigreeIndex = compact.search(/(?:父[:：]|母[:：])/);
  const beforePedigree = pedigreeIndex > 0 ? compact.slice(0, pedigreeIndex).trim() : compact;
  const stable = [...beforePedigree.matchAll(/([A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((?:美浦|栗東|本会外)\)/gu)].at(-1);
  if (stable?.index !== void 0 && stable.index > 0) {
    const prefix = beforePedigree.slice(0, stable.index).trim();
    const token2 = prefix.split(/\s+/)[0];
    return token2 && token2.length >= 2 ? token2 : prefix || null;
  }
  const token = beforePedigree.split(/\s+/)[0];
  return token && token.length >= 2 ? token : null;
}
__name(parseHorseName, "parseHorseName");
function numbersBefore(cells, end) {
  return cells.slice(0, end).map((cell) => cell.match(/^\s*(\d{1,2})\s*$/)?.[1]).filter((v) => Boolean(v)).map(Number);
}
__name(numbersBefore, "numbersBefore");
function parseEntryRows(html2) {
  const runners = /* @__PURE__ */ new Map();
  for (const row of parsedRows(html2)) {
    const joined = row.cells.join(" ").replace(/\s+/g, " ").trim();
    if (!/(?:番人気|初出走|kg|父[:：]|取消|除外|美浦|栗東)/.test(joined)) continue;
    const detailIndex = row.cells.findIndex((cell) => /(?:番人気|初出走|\d{3}kg|父[:：]|取消|除外|\((?:美浦|栗東|本会外)\))/.test(cell));
    if (detailIndex < 0) continue;
    const nums = numbersBefore(row.cells, detailIndex).filter((v) => v >= 1 && v <= 18);
    const horseNo = nums.at(-1) ?? null;
    if (!horseNo) continue;
    const detail = row.cells[detailIndex] ?? "";
    const horseName = parseHorseName(detail);
    if (!horseName) continue;
    const frameAlt = row.html.match(/alt=["'][^"']*枠(\d)[^"']*["']/i)?.[1];
    const firstFrame = nums[0] ?? null;
    const frameNo = frameAlt ? Number(frameAlt) : nums.length >= 2 && firstFrame !== null && firstFrame <= 8 ? firstFrame : null;
    const status = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : "active";
    const odds = detail.match(/(\d+(?:\.\d+)?)\s*\((\d+)番人気\)/);
    const bodyWeight = detail.match(/(\d{3})\s*kg\s*\(([^)]*)\)/i);
    const weightChangeText = bodyWeight?.[2]?.replace(/初出走/g, "").trim() ?? "";
    const weightChange = /^[+＋-－]?\d+$/.test(weightChangeText) ? Number(weightChangeText.replace("\uFF0B", "+").replace("\uFF0D", "-")) : null;
    const trainerInfo = lastStableMatch(detail) ?? lastStableMatch(joined);
    const infoCell = row.cells.slice(detailIndex + 1).find((cell) => /(?:牡|牝|せん|騸)\s*\d+|\d{2}(?:\.\d)?\s*kg/.test(cell)) ?? detail;
    const sex = infoCell.match(/(牡|牝|せん|騸)\s*(\d+)\s*(?:[/／]\s*([^\s]+))?/u);
    const assigned = infoCell.match(/(\d{2}(?:\.\d)?)\s*kg/i);
    let jockey = assigned?.index !== void 0 ? infoCell.slice(assigned.index + assigned[0].length).replace(/^[\s▲△☆◇]+/u, "").trim() || null : null;
    if (!jockey) jockey = joined.match(/([▲△☆◇]?[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((\d{2}(?:\.\d)?)\)/u)?.[1]?.replace(/^[▲△☆◇]/u, "") ?? null;
    runners.set(horseNo, { horseNo, frameNo, horseName, sexAge: sex ? `${sex[1]}${sex[2]}` : null, coatColor: sex?.[3] ?? null, horseWeight: bodyWeight ? Number(bodyWeight[1]) : null, weightChange, jockey, assignedWeight: assigned ? Number(assigned[1]) : null, trainer: trainerInfo?.trainer ?? null, stable: trainerInfo?.stable ?? null, winOdds: odds ? Number(odds[1]) : null, popularity: odds ? Number(odds[2]) : null, runnerStatus: status });
  }
  return [...runners.values()].sort((a, b) => a.horseNo - b.horseNo);
}
__name(parseEntryRows, "parseEntryRows");
function parseResultRows(html2) {
  const results = /* @__PURE__ */ new Map();
  for (const row of parsedRows(html2)) {
    const joined = row.cells.join(" ").replace(/\s+/g, " ").trim();
    if (!/(?:\d+:\d{2}\.\d|除外|中止|失格|取消)/.test(joined)) continue;
    const finishCell = row.cells[0]?.trim() ?? "";
    const finishPosition = /^\d{1,2}$/.test(finishCell) ? Number(finishCell) : null;
    const status = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : /中止/.test(joined) ? "dnf" : /失格/.test(joined) ? "disqualified" : "finished";
    const horseNo = row.cells.slice(1, 5).map((c) => c.match(/^\s*(\d{1,2})\s*$/)?.[1]).filter((v) => Boolean(v)).map(Number).filter((v) => v >= 1 && v <= 18).at(-1) ?? null;
    if (!horseNo) continue;
    const timeIndex = row.cells.findIndex((c) => /\d+:\d{2}\.\d/.test(c));
    const timeText = timeIndex >= 0 ? row.cells[timeIndex]?.match(/\d+:\d{2}\.\d/)?.[0] ?? null : null;
    const marginCandidate = timeIndex >= 0 ? (row.cells[timeIndex + 1] ?? "").trim() : "";
    const marginText = marginCandidate && !/^\d+(?:\.\d+)?$/.test(marginCandidate) ? marginCandidate : null;
    const final3f = row.cells.slice(Math.max(0, timeIndex + 1)).flatMap((c) => [...c.matchAll(/(?:^|\s)(\d{2}\.\d)(?:\s|$)/g)].map((m) => Number(m[1]))).at(-1) ?? null;
    results.set(horseNo, { horseNo, finishPosition, resultStatus: status, timeText, marginText, final3f });
  }
  return [...results.values()].sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));
}
__name(parseResultRows, "parseResultRows");
function normalizeBetType(value) {
  const compact = value.replace(/\s+/g, "").replace(/３/g, "3");
  return ["\u5358\u52DD", "\u8907\u52DD", "\u67A0\u9023", "\u99AC\u9023", "\u99AC\u5358", "\u30EF\u30A4\u30C9", "3\u9023\u8907", "3\u9023\u5358"].find((type) => compact === type) ?? null;
}
__name(normalizeBetType, "normalizeBetType");
function normalizeCombination(value) {
  const normalized = value.replace(/[‐‑–—−ー]/g, "-").replace(/[→、,]/g, "-").replace(/\s+/g, "").replace(/[^0-9-]/g, "").replace(/-+/g, "-").replace(/^-|-$/g, "");
  return /^\d{1,2}(?:-\d{1,2}){0,2}$/.test(normalized) ? normalized : null;
}
__name(normalizeCombination, "normalizeCombination");
function parsePayoutRows(html2) {
  const payouts = [];
  let currentType = null;
  for (const row of parsedRows(html2)) {
    const explicit = row.cells.map(normalizeBetType).find((v) => Boolean(v));
    if (explicit) currentType = explicit;
    if (!currentType) continue;
    const amounts = row.cells.map((cell, index) => ({ index, match: cell.match(/([0-9,]+)\s*円/) })).filter((x) => Boolean(x.match));
    for (const amount of amounts) {
      let combination = null;
      for (let i = amount.index - 1; i >= 0; i -= 1) {
        combination = normalizeCombination(row.cells[i] ?? "");
        if (combination || normalizeBetType(row.cells[i] ?? "")) break;
      }
      if (!combination) continue;
      const popularity = row.cells.slice(amount.index + 1).join(" ").match(/(\d+)番人気/)?.[1];
      payouts.push({ betType: currentType, combination, payoutYen: Number((amount.match[1] ?? "0").replace(/,/g, "")), popularity: popularity ? Number(popularity) : null });
    }
  }
  const unique = /* @__PURE__ */ new Map();
  for (const payout of payouts) unique.set(`${payout.betType}:${payout.combination}`, payout);
  return [...unique.values()];
}
__name(parsePayoutRows, "parsePayoutRows");
function parseRefunds(html2) {
  const match = normalizeText(html2).match(/返還(?:馬番)?\s*[：:]?\s*([0-9、,\s]+)/);
  return match ? [...new Set(((match[1] ?? "").match(/\d{1,2}/g) ?? []).map(Number).filter((v) => v >= 1 && v <= 18))] : [];
}
__name(parseRefunds, "parseRefunds");
function parseEntryPage(html2, entryUrl) {
  const race = parseHeader(html2, entryUrl, false);
  const runners = parseEntryRows(html2);
  if (runners.length < 2) throw new Error(`RUNNERS_NOT_FOUND:${runners.length}`);
  return { race, runners, results: [], payouts: [], refundHorseNos: [] };
}
__name(parseEntryPage, "parseEntryPage");
function parseResultPage(html2, resultUrl) {
  const race = parseHeader(html2, resultUrl, true);
  const results = parseResultRows(html2);
  const payouts = parsePayoutRows(html2);
  if (results.length < 2) throw new Error(`RESULTS_NOT_FOUND:${results.length}`);
  return { race, runners: [], results, payouts, refundHorseNos: parseRefunds(html2) };
}
__name(parseResultPage, "parseResultPage");
function raceDateFromUrl(rawUrl) {
  try {
    const cname = decodeURIComponent(new URL(rawUrl).searchParams.get("CNAME") ?? "");
    const value = [...cname.matchAll(/(20\d{6})/g)].map((m) => m[1] ?? "").at(-1);
    return value ? new Date(Date.UTC(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))) : null;
  } catch {
    return null;
  }
}
__name(raceDateFromUrl, "raceDateFromUrl");
function isNearCurrentWeekend(rawUrl, now = /* @__PURE__ */ new Date()) {
  const date = raceDateFromUrl(rawUrl);
  if (!date) return true;
  const jst = new Date(now.getTime() + 9 * 36e5);
  const today = Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate());
  const delta = (date.getTime() - today) / 864e5;
  return delta >= -2 && delta <= 9;
}
__name(isNearCurrentWeekend, "isNearCurrentWeekend");
function meetingExpansionKey(rawUrl) {
  try {
    const cname = decodeURIComponent(new URL(rawUrl).searchParams.get("CNAME") ?? "");
    const match = cname.match(/^(.*?)(\d{2})(20\d{6})\//i);
    return match ? `${match[1]}:${match[3]}` : cname || rawUrl;
  } catch {
    return rawUrl;
  }
}
__name(meetingExpansionKey, "meetingExpansionKey");
async function discoverRaceUrls(homeUrl, seeds2, fetchImpl = fetch) {
  const found = /* @__PURE__ */ new Map();
  const add = /* @__PURE__ */ __name((link) => {
    try {
      const cname = decodeURIComponent(new URL(link).searchParams.get("CNAME") ?? "");
      found.set(cname || link, link);
    } catch {
      found.set(link, link);
    }
  }, "add");
  for (const source of [homeUrl, "https://www.jra.go.jp/JRADB/accessD.html"]) {
    try {
      const page = await fetchJraPage(source, fetchImpl);
      for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link);
    } catch {
    }
  }
  for (const seed of seeds2) {
    try {
      const normalized = validateUrl(seed).toString();
      if (isNearCurrentWeekend(normalized)) add(normalized);
    } catch {
    }
  }
  const initial = [...found.values()];
  for (const seed of initial.slice(0, 6)) {
    try {
      const page = await fetchJraPage(seed, fetchImpl);
      for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link);
    } catch {
    }
  }
  const representatives = /* @__PURE__ */ new Map();
  for (const link of found.values()) if (!representatives.has(meetingExpansionKey(link))) representatives.set(meetingExpansionKey(link), link);
  for (const seed of [...representatives.values()].slice(0, 12)) {
    try {
      const page = await fetchJraPage(seed, fetchImpl);
      for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link);
    } catch {
    }
  }
  return [...found.values()];
}
__name(discoverRaceUrls, "discoverRaceUrls");
function pageLooksLikeEntry(html2) {
  const text = htmlToLines(html2).join(" ");
  return /出馬表/.test(text) && (/<table\b/i.test(html2) || /<tr\b/i.test(html2));
}
__name(pageLooksLikeEntry, "pageLooksLikeEntry");
function pageLooksLikeResult(html2) {
  const text = htmlToLines(html2).join(" ");
  return /レース結果/.test(text) && (/<table\b/i.test(html2) || /<tr\b/i.test(html2));
}
__name(pageLooksLikeResult, "pageLooksLikeResult");

// src/v1/model.ts
function safeRate(wins, starts, priorWins, priorStarts) {
  return (wins + priorWins) / (starts + priorStarts);
}
__name(safeRate, "safeRate");
function softmax(scores) {
  if (scores.length === 0) return [];
  const max = Math.max(...scores);
  const exp = scores.map((score) => Math.exp(score - max));
  const total = exp.reduce((sum, value) => sum + value, 0);
  return exp.map((value) => value / total);
}
__name(softmax, "softmax");
function marketProbabilities(runners) {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const inverse = active.map((runner) => ({
    horseNo: runner.horseNo,
    value: runner.winOdds && runner.winOdds > 1 ? 1 / runner.winOdds : 0
  }));
  const total = inverse.reduce((sum, item) => sum + item.value, 0);
  const result = /* @__PURE__ */ new Map();
  for (const item of inverse) result.set(item.horseNo, total > 0 ? item.value / total : 1 / Math.max(1, active.length));
  return result;
}
__name(marketProbabilities, "marketProbabilities");
function historyAdjustment(stats) {
  if (!stats) return { score: 0, reasons: [] };
  const horseWin = safeRate(stats.horseWins, stats.horseStarts, 1, 12);
  const horsePlace = safeRate(stats.horsePlaces, stats.horseStarts, 3, 12);
  const jockeyWin = safeRate(stats.jockeyWins, stats.jockeyStarts, 1, 14);
  const trainerWin = safeRate(stats.trainerWins, stats.trainerStarts, 1, 14);
  const courseWin = safeRate(stats.courseWins, stats.courseStarts, 1, 16);
  const score = 0.9 * Math.log(horseWin / (1 / 12)) + 0.45 * Math.log(horsePlace / (3 / 12)) + 0.35 * Math.log(jockeyWin / (1 / 14)) + 0.25 * Math.log(trainerWin / (1 / 14)) + 0.25 * Math.log(courseWin / (1 / 16));
  const reasons = [];
  if (stats.horseStarts >= 2) reasons.push(`\u99AC\u306E\u84C4\u7A4D\u6210\u7E3E${stats.horseStarts}\u8D70`);
  if (stats.jockeyStarts >= 10) reasons.push(`\u9A0E\u624B\u6210\u7E3E${stats.jockeyStarts}\u8D70`);
  if (stats.trainerStarts >= 10) reasons.push(`\u53A9\u820E\u6210\u7E3E${stats.trainerStarts}\u8D70`);
  if (stats.courseStarts >= 3) reasons.push(`\u540C\u6761\u4EF6${stats.courseStarts}\u8D70`);
  return { score: clamp(score, -0.7, 0.7), reasons };
}
__name(historyAdjustment, "historyAdjustment");
function physicalAdjustment(runner) {
  let score = 0;
  const reasons = [];
  if (runner.weightChange !== null) {
    if (runner.weightChange >= -8 && runner.weightChange <= 10) {
      score += 0.03;
      reasons.push("\u99AC\u4F53\u91CD\u306E\u5897\u6E1B\u304C\u8A31\u5BB9\u7BC4\u56F2");
    } else if (Math.abs(runner.weightChange) >= 18) {
      score -= 0.08;
      reasons.push("\u99AC\u4F53\u91CD\u306E\u5927\u5E45\u5909\u52D5");
    }
  }
  if (runner.assignedWeight !== null && runner.assignedWeight <= 53) {
    score += 0.035;
    reasons.push("\u65A4\u91CF\u9762\u306E\u6069\u6075");
  }
  return { score, reasons };
}
__name(physicalAdjustment, "physicalAdjustment");
function estimatedOdds(type, picks) {
  const odds = picks.map((pick) => Math.max(1.1, pick.currentOdds ?? pick.fairOdds));
  if (type === "\u5358\u52DD") return odds[0] ?? 1;
  if (type === "\u30EF\u30A4\u30C9") return Math.max(1.5, Math.sqrt((odds[0] ?? 1) * (odds[1] ?? 1)) * 0.42);
  if (type === "\u99AC\u9023") return Math.max(2, Math.sqrt((odds[0] ?? 1) * (odds[1] ?? 1)) * 1.15);
  if (type === "\u99AC\u5358") return Math.max(3, (odds[0] ?? 1) * Math.sqrt(odds[1] ?? 1) * 0.95);
  if (type === "3\u9023\u8907") return Math.max(5, Math.cbrt((odds[0] ?? 1) * (odds[1] ?? 1) * (odds[2] ?? 1)) * 2.8);
  return Math.max(8, (odds[0] ?? 1) * Math.sqrt((odds[1] ?? 1) * (odds[2] ?? 1)) * 1.5);
}
__name(estimatedOdds, "estimatedOdds");
function makeBet(betType, picks, stakeYen, probability) {
  const ordered = betType === "\u99AC\u5358" || betType === "3\u9023\u5358";
  const horseNos = picks.map((pick) => pick.horseNo);
  const combination = (ordered ? horseNos : [...horseNos].sort((a, b) => a - b)).join("-");
  const assumedOdds = estimatedOdds(betType, picks);
  return {
    betType,
    combination,
    stakeYen,
    assumedOdds,
    hitProbability: clamp(probability, 1e-3, 0.95),
    expectedValuePct: clamp(probability * assumedOdds * 100, 1, 999)
  };
}
__name(makeBet, "makeBet");
function buildTicket(predictions, maxBudget) {
  const [top, second, third] = predictions;
  if (!top) return [];
  const budget = Math.max(0, Math.floor(maxBudget / 100) * 100);
  if (budget < 100) return [];
  if (!second || !third || budget < 600) {
    return [makeBet("\u5358\u52DD", [top], budget, top.winProbability)];
  }
  const confidenceGap = top.winProbability - second.winProbability;
  const strong = top.winProbability >= 0.34 || confidenceGap >= 0.12;
  const units = strong ? [6, 5, 3, 3, 2, 1] : [2, 5, 4, 4, 2, 3];
  const totalUnits = units.reduce((sum, value) => sum + value, 0);
  const unitYen = Math.max(100, Math.floor(budget / totalUnits / 100) * 100);
  const stakes = units.map((unit) => unit * unitYen);
  const used = stakes.reduce((sum, value) => sum + value, 0);
  stakes[0] = (stakes[0] ?? 0) + Math.max(0, budget - used);
  const p1 = top.winProbability;
  const p2 = second.winProbability;
  const p3 = third.winProbability;
  const place12 = clamp(top.placeProbability * second.placeProbability * 0.72, 0.01, 0.8);
  const place13 = clamp(top.placeProbability * third.placeProbability * 0.65, 0.01, 0.75);
  const quinella12 = clamp(2 * p1 * p2 * 1.45, 5e-3, 0.6);
  const exacta12 = clamp(p1 * p2 * 1.2, 3e-3, 0.45);
  const trio123 = clamp(6 * p1 * p2 * p3 * 1.8, 2e-3, 0.45);
  return [
    makeBet("\u5358\u52DD", [top], stakes[0] ?? 0, p1),
    makeBet("\u30EF\u30A4\u30C9", [top, second], stakes[1] ?? 0, place12),
    makeBet("\u30EF\u30A4\u30C9", [top, third], stakes[2] ?? 0, place13),
    makeBet("\u99AC\u9023", [top, second], stakes[3] ?? 0, quinella12),
    makeBet("\u99AC\u5358", [top, second], stakes[4] ?? 0, exacta12),
    makeBet("3\u9023\u8907", [top, second, third], stakes[5] ?? 0, trio123)
  ].filter((bet) => bet.stakeYen >= 100);
}
__name(buildTicket, "buildTicket");
function generatePrediction(race, runners, stats, modelVersion, _minExpectedValuePct, maxRaceBudgetYen) {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const market = marketProbabilities(runners);
  const statsMap = new Map(stats.map((item) => [item.horseNo, item]));
  const rawScores = active.map((runner) => {
    const base = Math.log(Math.max(0.01, market.get(runner.horseNo) ?? 1 / Math.max(1, active.length)));
    const history = historyAdjustment(statsMap.get(runner.horseNo));
    const physical = physicalAdjustment(runner);
    return { runner, score: 0.84 * base + history.score + physical.score, reasons: [...history.reasons, ...physical.reasons] };
  });
  const probabilities = softmax(rawScores.map((item) => item.score));
  const predictions = rawScores.map((item, index) => {
    const winProbability = probabilities[index] ?? 0;
    const currentOdds = item.runner.winOdds;
    const expectedValuePct = currentOdds ? winProbability * currentOdds * 100 : null;
    const placeProbability = clamp(1 - Math.pow(1 - winProbability, 3), winProbability, 0.96);
    const reasons = item.reasons.length > 0 ? item.reasons.join("\u30FB") : "\u5E02\u5834\u30AA\u30C3\u30BA\u3092\u4E2D\u5FC3\u306B\u63A8\u5B9A";
    return {
      horseNo: item.runner.horseNo,
      horseName: item.runner.horseName,
      winProbability,
      placeProbability,
      fairOdds: winProbability > 0 ? 1 / winProbability : 999,
      currentOdds,
      expectedValuePct,
      predictedOrder: 0,
      explanation: `${race.surface ?? "\u6761\u4EF6"}${race.distanceM ?? ""}m\u3092\u524D\u63D0\u306B\u3001${reasons}`
    };
  });
  predictions.sort((a, b) => b.winProbability - a.winProbability);
  predictions.forEach((prediction, index) => {
    prediction.predictedOrder = index + 1;
  });
  return { modelVersion, runners: predictions, bets: buildTicket(predictions, maxRaceBudgetYen), generatedAt: nowIso() };
}
__name(generatePrediction, "generatePrediction");

// src/v1/ui.ts
var CSS = `
:root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--panel2:#182231;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--accent:#4fd1a1;--danger:#ff7b72;--gold:#ffd166}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14 45%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif;line-height:1.55}
a{color:inherit;text-decoration:none}.wrap{max-width:980px;margin:auto;padding:16px}.top{display:flex;align-items:center;justify-content:space-between;padding:12px 0 18px}.brand{font-weight:900;font-size:22px;letter-spacing:.03em}.brand span{color:var(--accent)}nav{display:flex;gap:8px;overflow:auto;padding-bottom:4px}nav a{white-space:nowrap;padding:8px 11px;background:#111925;border:1px solid var(--line);border-radius:999px;font-size:13px}.hero{padding:20px;background:linear-gradient(135deg,#172638,#10241e);border:1px solid #2b5448;border-radius:20px;margin-bottom:14px}.hero h1{font-size:27px;margin:0 0 7px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.metric,.card{background:rgba(18,25,35,.94);border:1px solid var(--line);border-radius:16px;padding:15px}.metric b{display:block;font-size:22px;margin-top:4px}.section{margin:22px 0 10px;font-size:18px}.race{display:grid;grid-template-columns:72px 1fr auto;gap:12px;align-items:center;margin-bottom:9px}.race .no{font-weight:900;font-size:18px}.pill{display:inline-block;border-radius:999px;padding:3px 8px;font-size:12px;border:1px solid var(--line);color:var(--muted)}.pill.locked{color:#8df0cc;border-color:#347a65}.pill.finished{color:#ffd89a;border-color:#76613a}.right{text-align:right}.positive{color:var(--accent)}.negative{color:var(--danger)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}.horse-no{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:7px;background:#e8edf2;color:#101820;font-weight:900;margin-right:7px}.buy{border-color:#516d42;background:#162416}.warning{border-color:#6e5730;background:#251e12}.error{border-color:#74403d;background:#271817}.tabs{display:flex;gap:8px;margin:12px 0}.bar{height:7px;border-radius:9px;background:#263242;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:var(--accent)}.footer{font-size:12px;color:var(--muted);padding:32px 4px 50px}.empty{text-align:center;padding:34px 15px;color:var(--muted)}code{word-break:break-all;background:#0b111a;padding:2px 5px;border-radius:5px}.status-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--accent);margin-right:6px}@media(min-width:700px){.grid{grid-template-columns:repeat(4,1fr)}.wrap{padding:24px}.hero{padding:28px}.race{grid-template-columns:100px 1fr 180px}}
.date-block{margin:20px 0 30px}.date-head{position:sticky;top:0;z-index:3;background:rgba(9,16,24,.94);backdrop-filter:blur(10px);padding:11px 2px 9px;border-bottom:1px solid var(--line)}.date-title{font-size:23px;font-weight:900}.venue-block{margin:15px 0 22px}.venue-head{display:flex;justify-content:space-between;align-items:center;margin:0 3px 9px}.venue-name{font-size:19px;font-weight:900}.race-list{display:grid;gap:8px}.day-nav{display:flex;gap:7px;overflow:auto;padding:2px 0 8px}.day-nav a{white-space:nowrap;border:1px solid var(--line);background:#101925;padding:8px 11px;border-radius:10px;font-size:13px}.result-box{border-color:#76613a;background:#251e12}.detail-status{margin:10px 0}.race-date{font-weight:800;color:var(--accent)}@media(min-width:700px){.race-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;
function layout(title, body) {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>${escapeHtml(title)}\uFF5C\u30EC\u30FC\u30B9\u63A2\u5075</title><style>${CSS}</style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>\u30EC\u30FC\u30B9</span>\u63A2\u5075</a><nav><a href="/">\u4E88\u60F3</a><a href="/performance">\u6210\u7E3E</a><a href="/methodology">\u4E88\u60F3\u65B9\u6CD5</a><a href="/system">\u7A3C\u50CD\u72B6\u6CC1</a></nav></div>${body}<footer class="footer">\u672C\u30B5\u30A4\u30C8\u306F\u72EC\u81EA\u306E\u7D71\u8A08\u30E2\u30C7\u30EB\u306B\u3088\u308B\u975E\u516C\u5F0F\u306E\u4E88\u60F3\u8A18\u9332\u30B5\u30A4\u30C8\u3067\u3001JRA\u304A\u3088\u3073\u95A2\u4FC2\u56E3\u4F53\u3068\u306F\u95A2\u4FC2\u3042\u308A\u307E\u305B\u3093\u3002\u7684\u4E2D\u3084\u5229\u76CA\u3092\u4FDD\u8A3C\u3057\u307E\u305B\u3093\u3002\u8868\u793A\u3059\u308B\u53CE\u652F\u306F\u767A\u8D70\u524D\u306B\u30ED\u30C3\u30AF\u3055\u308C\u305F\u30E2\u30C7\u30EB\u8CB7\u3044\u76EE\u3092\u8CFC\u5165\u3057\u305F\u3068\u4EEE\u5B9A\u3057\u305F\u6210\u7E3E\u3067\u3059\u3002\u99AC\u5238\u306F20\u6B73\u306B\u306A\u3063\u3066\u304B\u3089\u3001\u7121\u7406\u306E\u306A\u3044\u7BC4\u56F2\u3067\u304A\u697D\u3057\u307F\u304F\u3060\u3055\u3044\u3002</footer></main></body></html>`;
}
__name(layout, "layout");
function pct(value, digits = 1) {
  return value === null ? "\u2014" : `${value.toFixed(digits)}%`;
}
__name(pct, "pct");
function renderHome(metrics, races) {
  const dateLabel = /* @__PURE__ */ __name((date) => {
    const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return date;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const dayOfMonth = Number(match[3]);
    const weekday = new Date(Date.UTC(year, month - 1, dayOfMonth)).getUTCDay();
    const day = ["\u65E5", "\u6708", "\u706B", "\u6C34", "\u6728", "\u91D1", "\u571F"][weekday] ?? "";
    return `${month}\u6708${dayOfMonth}\u65E5\uFF08${day}\uFF09`;
  }, "dateLabel");
  const grouped = /* @__PURE__ */ new Map();
  for (const race of [...races].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja") || a.raceNo - b.raceNo)) {
    const venues = grouped.get(race.raceDate) ?? /* @__PURE__ */ new Map();
    const rows = venues.get(race.venue) ?? [];
    rows.push(race);
    venues.set(race.venue, rows);
    grouped.set(race.raceDate, venues);
  }
  const dates = [...grouped.keys()];
  const nav = dates.map((date) => `<a href="#date-${date}">${escapeHtml(dateLabel(date))}</a>`).join("");
  const sections = dates.map((date) => {
    const venues = grouped.get(date);
    const venueHtml = [...venues.entries()].map(([venue, rows]) => {
      const cards = rows.map((race) => {
        const finished = race.status === "finished";
        const state = finished ? "\u7D50\u679C\u78BA\u5B9A" : race.predictionStatus === "locked" ? "\u4E88\u60F3\u516C\u958B" : race.predictionStatus === "draft" ? "\u66AB\u5B9A\u4E88\u60F3" : "\u4E88\u60F3\u5F85\u3061";
        const cls = finished ? "finished" : race.predictionStatus === "locked" ? "locked" : "";
        const summary = finished ? "\u7740\u9806\u30FB\u6255\u623B\u3092\u78BA\u8A8D" : race.topHorseNo ? `\u25CE ${race.topHorseNo} ${escapeHtml(race.topHorseName)}` : "\u4E88\u60F3\u30C7\u30FC\u30BF\u6E96\u5099\u4E2D";
        return `<a class="card race" href="/races/${encodeURIComponent(race.raceId)}"><div><div class="race-date">${race.raceNo}R</div><div class="muted">${escapeHtml(race.startTimeJst ?? "\u6642\u523B\u672A\u5B9A")}</div></div><div><b>${escapeHtml(race.raceName)}</b><div class="muted">${summary}</div></div><div class="right"><span class="pill ${cls}">${state}</span><div class="muted">\u8CB7\u3044\u76EE ${race.betCount}</div></div></a>`;
      }).join("");
      return `<section class="venue-block"><div class="venue-head"><div class="venue-name">${escapeHtml(venue)}\u7AF6\u99AC\u5834</div><div class="muted">${rows.length}\u30EC\u30FC\u30B9</div></div><div class="race-list">${cards}</div></section>`;
    }).join("");
    return `<section class="date-block" id="date-${date}"><div class="date-head"><div class="date-title">${escapeHtml(dateLabel(date))}</div><div class="muted">${escapeHtml(date)} \uFF0F ${[...venues.values()].reduce((n, v) => n + v.length, 0)}\u30EC\u30FC\u30B9</div></div>${venueHtml}</section>`;
  }).join("");
  return layout("\u4E88\u60F3\u4E00\u89A7", `<section class="hero"><div class="muted"><span class="status-dot"></span>\u5168\u81EA\u52D5\u30FB\u516C\u958B\u4E88\u60F3\u8A18\u9332</div><h1>\u65E5\u4ED8\u3068\u7AF6\u99AC\u5834\u304B\u3089\u30EC\u30FC\u30B9\u3092\u9078\u3076\u3002</h1><div class="muted">\u4E88\u60F3\u3001\u8CB7\u3044\u76EE\u3001\u7D50\u679C\u3001\u6255\u623B\u3092\u5404\u30EC\u30FC\u30B9\u306E\u8A73\u7D30\u753B\u9762\u3067\u78BA\u8A8D\u3067\u304D\u307E\u3059\u3002</div></section><section class="grid"><div class="metric"><span class="muted">\u7D2F\u8A08\u56DE\u53CE\u7387</span><b class="${(metrics.roiPct ?? 0) >= 100 ? "positive" : ""}">${pct(metrics.roiPct)}</b></div><div class="metric"><span class="muted">\u30E2\u30C7\u30EB\u53CE\u652F</span><b class="${metrics.profitYen >= 0 ? "positive" : "negative"}">${metrics.profitYen >= 0 ? "+" : ""}${formatYen(metrics.profitYen)}</b></div><div class="metric"><span class="muted">\u8CFC\u5165\uFF0F\u6255\u623B</span><b>${formatYen(metrics.totalStakeYen)}</b><small class="muted">\u6255\u623B ${formatYen(metrics.totalReturnYen)}</small></div><div class="metric"><span class="muted">\u56FA\u5B9A\u4E88\u60F3</span><b>${metrics.predictionCount}R</b><small class="muted">\u7684\u4E2D\u7387 ${pct(metrics.hitRatePct)}</small></div></section>${nav ? `<h2 class="section">\u958B\u50AC\u65E5</h2><div class="day-nav">${nav}</div>` : ""}${sections || '<div class="card empty">\u30EC\u30FC\u30B9\u30C7\u30FC\u30BF\u3092\u53D6\u5F97\u4E2D\u3067\u3059\u3002</div>'}`);
}
__name(renderHome, "renderHome");
function renderRace(detail) {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const predMap = new Map(predictedRunners.map((r) => [r.horseNo, r]));
  const finished = race.status === "finished";
  const finishers = [...runners].filter((r) => r.finishPosition !== null).sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));
  const stake = bets.reduce((n, b) => n + b.stakeYen, 0), returns = bets.reduce((n, b) => n + (b.returnYen ?? 0), 0), profit = returns - stake;
  const marks = ["\u25CE", "\u25CB", "\u25B2"];
  const predictionBox = prediction ? `<div class="card detail-status"><b>${prediction.status === "locked" ? "\u767A\u8D70\u524D\u56FA\u5B9A\u4E88\u60F3" : "\u66AB\u5B9A\u4E88\u60F3"}</b><div class="tabs">${predictedRunners.slice(0, 3).map((p, i) => `<span class="pill ${i === 0 ? "locked" : ""}">${marks[i]} ${p.horseNo} ${escapeHtml(p.horseName)}</span>`).join("")}</div><div class="muted">\u751F\u6210 ${escapeHtml(prediction.generatedAt)}${prediction.lockedAt ? ` \uFF0F \u56FA\u5B9A ${escapeHtml(prediction.lockedAt)}` : ""}</div></div>` : '<div class="card warning"><b>\u4E88\u60F3\u306F\u307E\u3060\u516C\u958B\u3055\u308C\u3066\u3044\u307E\u305B\u3093</b><div class="muted">\u51FA\u8D70\u99AC\u3068\u30AA\u30C3\u30BA\u53D6\u5F97\u5F8C\u306B\u81EA\u52D5\u751F\u6210\u3057\u307E\u3059\u3002</div></div>';
  const resultBox = finished ? `<div class="card result-box"><b>\u30EC\u30FC\u30B9\u7D50\u679C</b><div class="tabs">${finishers.slice(0, 3).map((r) => `<span class="pill finished">${r.finishPosition}\u7740 ${r.horseNo} ${escapeHtml(r.horseName)}</span>`).join("") || '<span class="muted">\u7740\u9806\u53D6\u5F97\u4E2D</span>'}</div>${bets.length ? `<div>\u8CFC\u5165 ${formatYen(stake)} \uFF0F \u6255\u623B ${formatYen(returns)} \uFF0F <strong class="${profit >= 0 ? "positive" : "negative"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</strong></div>` : '<div class="muted">\u56FA\u5B9A\u8CB7\u3044\u76EE\u306A\u3057</div>'}</div>` : '<div class="card"><b>\u7D50\u679C\u5F85\u3061</b><div class="muted">\u7D42\u4E86\u5F8C\u306B\u7740\u9806\u3001\u6255\u623B\u3001\u53CE\u652F\u3092\u81EA\u52D5\u53CD\u6620\u3057\u307E\u3059\u3002</div></div>';
  const rows = runners.map((r) => {
    const p = predMap.get(r.horseNo);
    return `<tr><td><span class="horse-no">${r.horseNo}</span>${escapeHtml(r.horseName)}<div class="muted">${escapeHtml(r.jockey ?? "")}</div></td><td>${p ? `${p.predictedOrder}\u4F4D<br>${(p.winProbability * 100).toFixed(1)}%` : "\u2014"}</td><td>${r.winOdds ?? "\u2014"}</td><td>${p?.fairOdds.toFixed(2) ?? "\u2014"}</td><td>${p?.expectedValuePct != null ? p.expectedValuePct.toFixed(1) + "%" : "\u2014"}</td><td>${r.finishPosition ?? "\u2014"}</td></tr>`;
  }).join("");
  const betCards = bets.map((b) => `<div class="card buy"><b>${escapeHtml(b.betType)} ${escapeHtml(b.combination)}</b><div>\u8CFC\u5165\u60F3\u5B9A ${formatYen(b.stakeYen)} \uFF0F \u4F7F\u7528\u30AA\u30C3\u30BA ${b.assumedOdds.toFixed(1)}</div><div class="muted">\u671F\u5F85\u5024 ${b.expectedValuePct.toFixed(1)}% \uFF0F ${b.settlementStatus === "settled" ? `\u6255\u623B ${formatYen(b.returnYen ?? 0)}` : "\u767A\u8D70\u524D\u56FA\u5B9A\u6E08\u307F"}</div></div>`).join("");
  const reasons = predictedRunners.slice(0, 5).map((p) => `<div class="card"><b>${p.predictedOrder}\u4F4D ${p.horseNo} ${escapeHtml(p.horseName)}</b><div class="muted">${escapeHtml(p.explanation)}</div></div>`).join("");
  return layout(`${race.raceDate} ${race.venue}${race.raceNo}R`, `<section class="hero"><div class="muted">${escapeHtml(race.raceDate)} \uFF0F ${escapeHtml(race.venue)}\u7AF6\u99AC\u5834</div><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div><b>${escapeHtml(race.startTimeJst ?? "\u6642\u523B\u672A\u5B9A")} \u767A\u8D70</b>\u3000${escapeHtml(race.conditions ?? "")} ${escapeHtml(race.surface ?? "")}${race.distanceM ?? ""}m</div><div class="tabs"><span class="pill ${finished ? "finished" : prediction?.status === "locked" ? "locked" : ""}">${finished ? "\u7D50\u679C\u78BA\u5B9A" : prediction?.status === "locked" ? "\u4E88\u60F3\u516C\u958B\u4E2D" : prediction ? "\u66AB\u5B9A\u4E88\u60F3" : "\u4E88\u60F3\u5F85\u3061"}</span></div></section>${predictionBox}${resultBox}<h2 class="section">\u8CB7\u3044\u76EE</h2>${betCards || '<div class="card empty">\u56FA\u5B9A\u3055\u308C\u305F\u8CB7\u3044\u76EE\u306F\u3042\u308A\u307E\u305B\u3093\u3002</div>'}<h2 class="section">\u51FA\u8D70\u99AC\u30FB\u4E88\u60F3\u30FB\u7D50\u679C</h2><div class="card" style="overflow:auto"><table><thead><tr><th>\u99AC</th><th>\u4E88\u60F3</th><th>\u5358\u52DD</th><th>\u9069\u6B63</th><th>\u671F\u5F85\u5024</th><th>\u7740\u9806</th></tr></thead><tbody>${rows || '<tr><td colspan="6">\u53D6\u5F97\u4E2D</td></tr>'}</tbody></table></div><h2 class="section">\u4E88\u60F3\u6839\u62E0</h2>${reasons || '<div class="card empty">\u4E88\u60F3\u751F\u6210\u5F8C\u306B\u8868\u793A\u3055\u308C\u307E\u3059\u3002</div>'}`);
}
__name(renderRace, "renderRace");
function renderPerformance(metrics, rows) {
  const bodyRows = rows.map((row) => `<tr><td>${escapeHtml(row.label)}</td><td>${row.bets}</td><td>${formatYen(row.stake)}</td><td>${formatYen(row.returns)}</td><td class="${(row.roi ?? 0) >= 100 ? "positive" : ""}">${pct(row.roi)}</td></tr>`).join("");
  return layout("\u6210\u7E3E", `<section class="hero"><h1>\u516C\u958B\u4E88\u60F3\u6210\u7E3E</h1><div class="muted">\u5916\u308C\u3092\u542B\u3080\u3001\u767A\u8D70\u524D\u306B\u56FA\u5B9A\u3057\u305F\u5168\u8CB7\u3044\u76EE\u3092\u96C6\u8A08\u3057\u307E\u3059\u3002</div></section><section class="grid"><div class="metric"><span class="muted">\u7D2F\u8A08\u56DE\u53CE\u7387</span><b>${pct(metrics.roiPct)}</b></div><div class="metric"><span class="muted">\u7D2F\u8A08\u53CE\u652F</span><b>${formatYen(metrics.profitYen)}</b></div><div class="metric"><span class="muted">\u8CB7\u3044\u76EE\u6570</span><b>${metrics.settledBetCount}</b></div><div class="metric"><span class="muted">\u7684\u4E2D\u7387</span><b>${pct(metrics.hitRatePct)}</b></div></section><h2 class="section">\u6708\u5225</h2><div class="card" style="overflow:auto"><table><thead><tr><th>\u6708</th><th>\u8CB7\u3044\u76EE</th><th>\u8CFC\u5165</th><th>\u6255\u623B</th><th>\u56DE\u53CE\u7387</th></tr></thead><tbody>${bodyRows || '<tr><td colspan="5">\u78BA\u5B9A\u30C7\u30FC\u30BF\u5F85\u3061</td></tr>'}</tbody></table></div>`);
}
__name(renderPerformance, "renderPerformance");
function renderMethodology() {
  return layout("\u4E88\u60F3\u65B9\u6CD5", `<section class="hero"><h1>\u4E88\u60F3\u65B9\u6CD5</h1><div class="muted">\u4E3B\u89B3\u7684\u306AS\u30FBA\u30FBB\u30E9\u30F3\u30AF\u306F\u4F7F\u308F\u305A\u3001\u78BA\u7387\u30FB\u9069\u6B63\u30AA\u30C3\u30BA\u30FB\u671F\u5F85\u5024\u3067\u516C\u958B\u3057\u307E\u3059\u3002</div></section><div class="card"><h2>1\uFF0E\u63A8\u5B9A\u52DD\u7387</h2><p>\u5358\u52DD\u30AA\u30C3\u30BA\u3092\u5E02\u5834\u306E\u57FA\u6E96\u78BA\u7387\u3068\u3057\u3066\u6B63\u898F\u5316\u3057\u3001\u30B5\u30A4\u30C8\u5185\u306B\u84C4\u7A4D\u3057\u305F\u99AC\u30FB\u9A0E\u624B\u30FB\u8ABF\u6559\u5E2B\u30FB\u540C\u6761\u4EF6\u6210\u7E3E\u3092\u7E2E\u5C0F\u63A8\u5B9A\u3067\u88DC\u6B63\u3057\u307E\u3059\u3002\u30C7\u30FC\u30BF\u304C\u5C11\u306A\u3044\u6BB5\u968E\u3067\u306F\u5E02\u5834\u6BD4\u7387\u3092\u5F37\u304F\u6B8B\u3057\u3001\u904E\u5B66\u7FD2\u3092\u6291\u3048\u307E\u3059\u3002</p><h2>2\uFF0E\u767A\u8D70\u524D\u56FA\u5B9A</h2><p>\u767A\u8D7015\u5206\u524D\u3092\u76EE\u5B89\u306B\u4E88\u60F3\u9806\u4F4D\u3001\u63A8\u5B9A\u78BA\u7387\u3001\u4F7F\u7528\u30AA\u30C3\u30BA\u3001\u8CB7\u3044\u76EE\u3001\u30E2\u30C7\u30EB\u91D1\u984D\u3092\u56FA\u5B9A\u3057\u307E\u3059\u3002\u767A\u8D70\u5F8C\u306F\u4E0A\u66F8\u304D\u3057\u307E\u305B\u3093\u3002</p><h2>3\uFF0E\u8CB7\u3044\u76EE</h2><p>\u521D\u671F\u30E2\u30C7\u30EB\u306F\u3001\u4E8B\u524D\u30AA\u30C3\u30BA\u3092\u7121\u6599\u3067\u5B89\u5B9A\u53D6\u5F97\u3067\u304D\u308B\u5358\u52DD\u3060\u3051\u3092\u5BFE\u8C61\u306B\u3057\u307E\u3059\u3002\u63A8\u5B9A\u671F\u5F85\u5024\u304C\u8A2D\u5B9A\u57FA\u6E96\u3092\u8D85\u3048\u305F\u5834\u5408\u306E\u307F\u3001\u6291\u5236\u3057\u305F\u5206\u6570Kelly\u65B9\u5F0F\u3067100\u5186\u5358\u4F4D\u306E\u91D1\u984D\u3092\u8A08\u7B97\u3057\u307E\u3059\u3002\u7D44\u5408\u305B\u99AC\u5238\u306F\u4E8B\u524D\u30AA\u30C3\u30BA\u306E\u5B89\u5B9A\u53D6\u5F97\u304C\u78BA\u8A8D\u3067\u304D\u308B\u307E\u3067\u7121\u7406\u306B\u63A8\u5968\u3057\u307E\u305B\u3093\u3002</p><h2>4\uFF0E\u6210\u7E3E</h2><p>\u8868\u793A\u3059\u308B\u56DE\u53CE\u7387\u306F\u3001\u56FA\u5B9A\u6E08\u307F\u30E2\u30C7\u30EB\u8CB7\u3044\u76EE\u3092\u3059\u3079\u3066\u8CFC\u5165\u3057\u305F\u3068\u4EEE\u5B9A\u3057\u305F\u6210\u7E3E\u3067\u3059\u3002\u5916\u308C\u305F\u30EC\u30FC\u30B9\u3082\u524A\u9664\u305B\u305A\u3001\u8FD4\u9084\u30FB\u9664\u5916\u3082\u6A5F\u68B0\u7684\u306B\u51E6\u7406\u3057\u307E\u3059\u3002</p></div>`);
}
__name(renderMethodology, "renderMethodology");
function renderSystem(snapshot) {
  return layout("\u7A3C\u50CD\u72B6\u6CC1", `<section class="hero"><h1>\u30B7\u30B9\u30C6\u30E0\u7A3C\u50CD\u72B6\u6CC1</h1><div class="muted"><span class="status-dot"></span>Cloudflare Workers + D1\uFF0F\u7AF6\u99AC\u5C02\u7528\u74B0\u5883</div></section><div class="card"><pre style="white-space:pre-wrap;word-break:break-word;margin:0">${escapeHtml(JSON.stringify(snapshot, null, 2))}</pre></div>`);
}
__name(renderSystem, "renderSystem");
function renderNotFound() {
  return layout("\u898B\u3064\u304B\u308A\u307E\u305B\u3093", `<div class="card empty">\u30DA\u30FC\u30B8\u304C\u898B\u3064\u304B\u308A\u307E\u305B\u3093\u3002</div>`);
}
__name(renderNotFound, "renderNotFound");

// src/complete.ts
var schemaReady = null;
var inMemorySync = null;
var DISCOVERY_REVISION = "2026-08-02-jst-bets-v3";
function ready(db) {
  schemaReady ??= ensureSchema(db).catch((error) => {
    schemaReady = null;
    throw error;
  });
  return schemaReady;
}
__name(ready, "ready");
function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}
__name(json, "json");
function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
      "x-frame-options": "DENY",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}
__name(html, "html");
function authorized(request, env) {
  return Boolean(env.ADMIN_TOKEN) && request.headers.get("authorization") === `Bearer ${env.ADMIN_TOKEN}`;
}
__name(authorized, "authorized");
function addMinutes(date, minutes) {
  return new Date(date.getTime() + minutes * 6e4).toISOString();
}
__name(addMinutes, "addMinutes");
function nextEntryFetch(race, now) {
  if (!race.startTimeUtc) return addMinutes(now, 60);
  const deltaMinutes = (new Date(race.startTimeUtc).getTime() - now.getTime()) / 6e4;
  if (deltaMinutes > 24 * 60) return addMinutes(now, 180);
  if (deltaMinutes > 180) return addMinutes(now, 60);
  if (deltaMinutes > 45) return addMinutes(now, 15);
  if (deltaMinutes > 0) return addMinutes(now, 5);
  return addMinutes(now, 8);
}
__name(nextEntryFetch, "nextEntryFetch");
function seeds(env) {
  return env.JRA_SEED_ENTRY_URLS.split(",").map((value) => value.trim()).filter(Boolean);
}
__name(seeds, "seeds");
async function shouldDiscover(env, now) {
  const discoveryVersion = await getState(env.DB, "last_discovery_revision");
  if (discoveryVersion !== DISCOVERY_REVISION) return true;
  const last = await getState(env.DB, "last_discovery_at");
  if (!last) return true;
  const lastMs = new Date(last).getTime();
  if (!Number.isFinite(lastMs)) return true;
  const elapsedMinutes = (now.getTime() - lastMs) / 6e4;
  if (!isJstEntryWindow(now)) return elapsedMinutes >= 24 * 60;
  return elapsedMinutes >= (isJstRaceWindow(now) ? 20 : 90);
}
__name(shouldDiscover, "shouldDiscover");
async function updatePrediction(env, race, now) {
  if (!race.startTimeUtc || race.status === "finished") return;
  const minutesToStart = (new Date(race.startTimeUtc).getTime() - now.getTime()) / 6e4;
  if (minutesToStart <= 0) return;
  const runners = await getRunners(env.DB, race.raceId);
  if (runners.filter((runner) => runner.runnerStatus === "active").length < 2) return;
  if (runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null).length < 2) return;
  const history = await getRunnerHistoryStats(env.DB, race, runners);
  const prediction = generatePrediction(
    race,
    runners,
    history,
    env.MODEL_VERSION,
    positiveNumber(env.MIN_EXPECTED_VALUE, 108),
    positiveInt(env.MAX_RACE_BUDGET_YEN, 2e3)
  );
  const status = minutesToStart <= 15 ? "locked" : "draft";
  await savePrediction(env.DB, race.raceId, prediction, status);
}
__name(updatePrediction, "updatePrediction");
function hasResultUrl(url) {
  return /\/JRADB\/accessS\.html/i.test(url) && /(?:pw|sw)01sde/i.test(decodeURIComponent(url));
}
__name(hasResultUrl, "hasResultUrl");
async function processSource(env, source, now) {
  try {
    const entryPage = await fetchJraPage(source.entryUrl);
    if (!pageLooksLikeEntry(entryPage.html)) throw new Error("ENTRY_PAGE_SIGNATURE_MISSING");
    const entry = parseEntryPage(entryPage.html, entryPage.url);
    await saveEntryBundle(env.DB, entry);
    await updatePrediction(env, entry.race, now);
    const startMs = entry.race.startTimeUtc ? new Date(entry.race.startTimeUtc).getTime() : Number.POSITIVE_INFINITY;
    const resultDue = now.getTime() >= startMs + 4 * 6e4;
    if (!resultDue) {
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "active",
        nextFetchAt: nextEntryFetch(entry.race, now),
        entryFetched: true,
        error: null
      });
      return true;
    }
    try {
      if (!hasResultUrl(entry.race.resultUrl)) throw new Error("RESULT_URL_NOT_READY");
      const resultPage = await fetchJraPage(entry.race.resultUrl);
      if (!pageLooksLikeResult(resultPage.html)) throw new Error("RESULT_NOT_READY");
      const result = parseResultPage(resultPage.html, resultPage.url);
      if (result.race.raceId !== entry.race.raceId) throw new Error("RACE_ID_MISMATCH");
      await saveResultBundle(env.DB, result);
      await settleRace(env.DB, entry.race.raceId);
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "complete",
        nextFetchAt: addMinutes(now, 7 * 24 * 60),
        entryFetched: true,
        resultFetched: true,
        error: null
      });
      return true;
    } catch (resultError) {
      const message = resultError instanceof Error ? resultError.message : String(resultError);
      await updateRaceSource(env.DB, source.entryUrl, {
        raceId: entry.race.raceId,
        status: "awaiting_result",
        nextFetchAt: addMinutes(now, message === "RESULT_URL_NOT_READY" ? 5 : 10),
        entryFetched: true,
        error: message
      });
      return message === "RESULT_NOT_READY" || message === "RESULT_URL_NOT_READY";
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const delay = Math.min(240, 15 * Math.pow(2, Math.min(4, source.failureCount)));
    await updateRaceSource(env.DB, source.entryUrl, {
      raceId: source.raceId,
      status: "discovered",
      nextFetchAt: addMinutes(now, delay),
      error: message
    });
    return false;
  }
}
__name(processSource, "processSource");
async function acquireSyncLock(env, now) {
  const lock = await getState(env.DB, "sync_lock_until");
  const lockMs = lock ? new Date(lock).getTime() : 0;
  if (Number.isFinite(lockMs) && lockMs > now.getTime()) return false;
  await setState(env.DB, "sync_lock_until", addMinutes(now, 4));
  return true;
}
__name(acquireSyncLock, "acquireSyncLock");
async function executeSync(env, triggerType) {
  await ready(env.DB);
  const now = /* @__PURE__ */ new Date();
  if (!await acquireSyncLock(env, now)) {
    return { ok: true, skipped: "SYNC_ALREADY_RUNNING", now: nowIso() };
  }
  const runId = await beginSyncRun(env.DB, triggerType);
  let discovered = 0;
  let processed = 0;
  let success = 0;
  let errors = 0;
  let discoveryError = null;
  let fatal;
  try {
    if (await shouldDiscover(env, now)) {
      try {
        const previousRevision = await getState(env.DB, "last_discovery_revision");
        if (previousRevision !== DISCOVERY_REVISION) {
          await resetRaceSourcesForDiscoveryRevision(env.DB);
        }
        const urls = await discoverRaceUrls(env.JRA_HOME_URL, seeds(env));
        discovered = urls.length;
        await upsertRaceSources(env.DB, urls, toResultUrl);
        await setState(env.DB, "last_discovery_at", nowIso());
        await setState(env.DB, "last_discovery_count", String(urls.length));
        await setState(env.DB, "last_discovery_revision", DISCOVERY_REVISION);
        await setState(env.DB, "last_discovery_error", "");
      } catch (error) {
        discoveryError = error instanceof Error ? error.message : String(error);
        errors += 1;
        await setState(env.DB, "last_discovery_error", discoveryError);
      }
    }
    const due = await getDueRaceSources(env.DB, positiveInt(env.SYNC_BATCH_SIZE, 12));
    processed = due.length;
    for (const source of due) {
      const ok = await processSource(env, source, now);
      if (ok) success += 1;
      else errors += 1;
    }
    await setState(env.DB, "last_successful_cycle_at", nowIso());
    await setState(env.DB, "last_cycle_error", discoveryError ?? "");
  } catch (error) {
    fatal = error instanceof Error ? error.message : String(error);
    errors += 1;
    await setState(env.DB, "last_cycle_error", fatal);
  } finally {
    await finishSyncRun(env.DB, runId, fatal ? { discovered, processed, success, errors, errorMessage: fatal } : { discovered, processed, success, errors, ...discoveryError ? { errorMessage: discoveryError } : {} });
    await setState(env.DB, "sync_lock_until", (/* @__PURE__ */ new Date(0)).toISOString());
  }
  return { ok: !fatal, discovered, processed, success, errors, discoveryError, error: fatal ?? null, now: nowIso() };
}
__name(executeSync, "executeSync");
function runSync(env, triggerType) {
  if (inMemorySync) return inMemorySync;
  inMemorySync = executeSync(env, triggerType).finally(() => {
    inMemorySync = null;
  });
  return inMemorySync;
}
__name(runSync, "runSync");
async function handleApi(request, env, pathname) {
  if (pathname === "/api/health" || pathname === "/health") {
    const snapshot = await getSystemSnapshot(env.DB);
    return json({ ok: true, project: "race-tantei", modelVersion: env.MODEL_VERSION, snapshot });
  }
  if (pathname === "/api/status") return json(await getSystemSnapshot(env.DB));
  if (pathname === "/api/races") return json(await getLatestRaces(env.DB, 100));
  if (pathname.startsWith("/api/races/")) {
    const id = decodeURIComponent(pathname.slice("/api/races/".length));
    const detail = await getRaceDetail(env.DB, id);
    return detail ? json(detail) : json({ ok: false, error: "NOT_FOUND" }, 404);
  }
  if (pathname === "/api/admin/sync" && request.method === "POST") {
    if (!authorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    return json(await runSync(env, "manual"));
  }
  return null;
}
__name(handleApi, "handleApi");
var complete_default = {
  async fetch(request, env, ctx) {
    await ready(env.DB);
    const url = new URL(request.url);
    const api = await handleApi(request, env, url.pathname);
    if (api) return api;
    if (url.pathname === "/") {
      const [metrics, races] = await Promise.all([getDashboardMetrics(env.DB), getLatestRaces(env.DB)]);
      if (races.length === 0) ctx.waitUntil(runSync(env, "deploy"));
      const refresh = races.length === 0 ? '<meta http-equiv="refresh" content="12">' : "";
      return html(refresh + renderHome(metrics, races));
    }
    if (url.pathname.startsWith("/races/")) {
      const id = decodeURIComponent(url.pathname.slice("/races/".length));
      const detail = await getRaceDetail(env.DB, id);
      return detail ? html(renderRace(detail)) : html(renderNotFound(), 404);
    }
    if (url.pathname === "/performance") {
      const [metrics, rows] = await Promise.all([getDashboardMetrics(env.DB), getPerformanceRows(env.DB)]);
      return html(renderPerformance(metrics, rows));
    }
    if (url.pathname === "/methodology") return html(renderMethodology());
    if (url.pathname === "/system") return html(renderSystem(await getSystemSnapshot(env.DB)));
    if (url.pathname === "/robots.txt") return new Response("User-agent: *\nDisallow: /\n", { headers: { "content-type": "text/plain" } });
    if (url.pathname === "/favicon.ico") return new Response(null, { status: 204 });
    return html(renderNotFound(), 404);
  },
  async scheduled(_controller, env, ctx) {
    if (!isJstEntryWindow(/* @__PURE__ */ new Date())) return;
    ctx.waitUntil(runSync(env, "cron"));
  }
};

// src/v1/backtest.ts
var BACKTEST_DATE = "2026-08-01";
var BACKTEST_MODEL = "backtest-2026-08-01-multibet-v2";
async function pendingRaceIds(db, limit) {
  const rows = await db.prepare(`
    SELECT ra.race_id AS raceId
    FROM rt_races ra
    WHERE ra.race_date=? AND ra.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=ra.race_id AND p.model_version=? AND p.status='locked'
      )
    ORDER BY ra.venue, ra.race_no
    LIMIT ?
  `).bind(BACKTEST_DATE, BACKTEST_MODEL, limit).all();
  return rows.results.map((row) => row.raceId);
}
__name(pendingRaceIds, "pendingRaceIds");
async function runBacktestBatch(db, limit = 4) {
  const raceIds = await pendingRaceIds(db, limit);
  let processed = 0;
  for (const raceId of raceIds) {
    const race = await getRace(db, raceId);
    if (!race) continue;
    const runners = await getRunners(db, raceId);
    const activeWithOdds = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
    if (activeWithOdds.length < 2) continue;
    const prediction = generatePrediction(race, runners, [], BACKTEST_MODEL, 0, 2e3);
    if (prediction.runners.length === 0 || prediction.bets.length === 0) continue;
    await savePrediction(db, raceId, prediction, "locked");
    await settleRace(db, raceId);
    processed += 1;
  }
  const remainingRow = await db.prepare(`
    SELECT COUNT(*) AS count
    FROM rt_races ra
    WHERE ra.race_date=? AND ra.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=ra.race_id AND p.model_version=? AND p.status='locked'
      )
  `).bind(BACKTEST_DATE, BACKTEST_MODEL).first();
  return { processed, remaining: Number(remainingRow?.count ?? 0) };
}
__name(runBacktestBatch, "runBacktestBatch");
async function getBacktestRows(db) {
  const rows = await db.prepare(`
    SELECT ra.race_id AS raceId, ra.race_date AS raceDate, ra.venue, ra.race_no AS raceNo,
      ra.race_name AS raceName, ra.start_time_jst AS startTimeJst, ra.status,
      p.id AS predictionId, p.status AS predictionStatus,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id),0) AS stakeYen,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id),0) AS returnYen,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id),0) AS betCount,
      (SELECT horse_no FROM rt_results WHERE race_id=ra.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no WHERE rs.race_id=ra.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName
    FROM rt_races ra
    LEFT JOIN rt_predictions p ON p.race_id=ra.race_id AND p.model_version=?
    WHERE ra.race_date=?
    ORDER BY ra.venue, ra.race_no
  `).bind(BACKTEST_MODEL, BACKTEST_DATE).all();
  return rows.results;
}
__name(getBacktestRows, "getBacktestRows");
async function renderBacktest(db) {
  const rows = await getBacktestRows(db);
  const completed = rows.filter((row) => row.predictionId !== null && row.betCount > 0);
  const stake = completed.reduce((sum, row) => sum + Number(row.stakeYen || 0), 0);
  const returns = completed.reduce((sum, row) => sum + Number(row.returnYen || 0), 0);
  const hits = completed.filter((row) => Number(row.returnYen || 0) > 0).length;
  const roi = stake > 0 ? returns / stake * 100 : 0;
  const byVenue = /* @__PURE__ */ new Map();
  for (const row of rows) {
    const list = byVenue.get(row.venue) ?? [];
    list.push(row);
    byVenue.set(row.venue, list);
  }
  const venueHtml = [...byVenue.entries()].map(([venue, venueRows]) => `
    <section><h2>${escapeHtml(venue)}\u7AF6\u99AC\u5834</h2>${venueRows.map((row) => {
    const predicted = row.topHorseNo ? `${row.topHorseNo} ${escapeHtml(row.topHorseName ?? "")}` : "\u672A\u8A08\u7B97";
    const winner = row.winnerHorseNo ? `${row.winnerHorseNo} ${escapeHtml(row.winnerHorseName ?? "")}` : "\u7D50\u679C\u672A\u53D6\u5F97";
    const hit = row.returnYen > 0;
    return `<a class="race" href="/races/${encodeURIComponent(row.raceId)}"><div><b>${row.raceNo}R ${escapeHtml(row.raceName)}</b><small>${escapeHtml(row.startTimeJst ?? "")}</small></div><div>\u4E88\u60F3 \u25CE ${predicted}<br>1\u7740 ${winner}</div><div class="${hit ? "hit" : "miss"}">${row.betCount ? `${hit ? "\u7684\u4E2D" : "\u4E0D\u7684\u4E2D"}<br>${formatYen(row.returnYen)}` : "\u8A08\u7B97\u5F85\u3061"}</div></a>`;
  }).join("")}</section>`).join("");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="${completed.length < rows.length ? 12 : 300}"><title>8\u67081\u65E5 \u9061\u53CA\u691C\u8A3C\uFF5C\u30EC\u30FC\u30B9\u63A2\u5075</title><style>
  body{margin:0;background:#0b0f14;color:#eef3f8;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:900px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.hero,.metric,.race{background:#121923;border:1px solid #293649;border-radius:14px}.hero{padding:20px}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0}.metric{padding:14px}.metric b{font-size:22px;display:block}.race{display:grid;grid-template-columns:1.4fr 1fr auto;gap:10px;padding:13px;margin:8px 0;align-items:center}.race small{display:block;color:#9fb0c2}.hit{color:#4fd1a1;text-align:right}.miss{color:#ff7b72;text-align:right}.note{color:#9fb0c2;font-size:13px;line-height:1.7}h2{margin-top:26px}@media(max-width:620px){.race{grid-template-columns:1fr}.hit,.miss{text-align:left}.metrics{grid-template-columns:1fr 1fr}}
  </style></head><body><main class="wrap"><p><a href="/">\u2190 \u4E88\u60F3\u4E00\u89A7\u3078</a></p><section class="hero"><h1>2026\u5E748\u67081\u65E5 \u5168\u30EC\u30FC\u30B9\u9061\u53CA\u691C\u8A3C</h1><p class="note">\u7D50\u679C\u3092\u4E88\u60F3\u6750\u6599\u306B\u306F\u4F7F\u7528\u305B\u305A\u3001\u4FDD\u5B58\u6E08\u307F\u306E\u51FA\u8D70\u99AC\u60C5\u5831\u3068\u6700\u7D42\u53D6\u5F97\u5358\u52DD\u30AA\u30C3\u30BA\u3067\u518D\u8A08\u7B97\u3057\u3066\u3044\u307E\u3059\u3002\u5F53\u6642\u306E\u767A\u8D7015\u5206\u524D\u30AA\u30C3\u30BA\u3092\u4FDD\u5B58\u3057\u3066\u3044\u306A\u3044\u305F\u3081\u3001\u6B63\u5F0F\u306A\u4E8B\u524D\u4E88\u60F3\u6210\u7E3E\u3067\u306F\u306A\u304F\u9061\u53CA\u30B7\u30DF\u30E5\u30EC\u30FC\u30B7\u30E7\u30F3\u3067\u3059\u3002\u5404\u30EC\u30FC\u30B92,000\u5186\u4EE5\u5185\u3067\u3001\u25CE\u25CB\u25B2\u304B\u3089\u5358\u52DD\u30FB\u30EF\u30A4\u30C9\u30FB\u99AC\u9023\u30FB\u99AC\u5358\u30FB3\u9023\u8907\u3092\u4E00\u8CAB\u3057\u3066\u7D44\u307F\u7ACB\u3066\u307E\u3059\u3002</p></section><div class="metrics"><div class="metric">\u8A08\u7B97\u6E08\u307F<b>${completed.length}/${rows.length}R</b></div><div class="metric">\u7684\u4E2D<b>${hits}R</b></div><div class="metric">\u8CFC\u5165\uFF0F\u6255\u623B<b>${formatYen(stake)} / ${formatYen(returns)}</b></div><div class="metric">\u56DE\u53CE\u7387<b>${roi.toFixed(1)}%</b></div></div>${venueHtml || "<p>8\u67081\u65E5\u306E\u30C7\u30FC\u30BF\u3092\u53D6\u5F97\u4E2D\u3067\u3059\u3002</p>"}</main></body></html>`;
}
__name(renderBacktest, "renderBacktest");

// src/entry.ts
var startupReady = null;
var maintenanceRunning = null;
function prepare(db) {
  startupReady ??= ensureSchema(db).catch((error) => {
    startupReady = null;
    throw error;
  });
  return startupReady;
}
__name(prepare, "prepare");
function failureResponse(request, error) {
  console.error("WORKER_STARTUP_FAILED", error);
  const pathname = new URL(request.url).pathname;
  const detail = error instanceof Error ? error.message : String(error);
  if (pathname === "/health" || pathname.startsWith("/api/")) {
    return new Response(JSON.stringify({ ok: false, error: "WORKER_STARTUP_FAILED", detail }), {
      status: 500,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow"
      }
    });
  }
  return new Response(
    `\u30EC\u30FC\u30B9\u63A2\u5075\u306E\u8D77\u52D5\u51E6\u7406\u306B\u5931\u6557\u3057\u307E\u3057\u305F\u3002
\u30A8\u30E9\u30FC\u30B3\u30FC\u30C9: WORKER_STARTUP_FAILED
\u8A73\u7D30: ${detail}`,
    {
      status: 500,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow"
      }
    }
  );
}
__name(failureResponse, "failureResponse");
function extractOfficialRaceName(html2) {
  const match = html2.match(/<span\b[^>]*class=["'][^"']*titleRaceName[^"']*["'][^>]*>([\s\S]*?)<\/span>/i);
  if (!match?.[1]) return null;
  const name = stripHtml(match[1]).replace(/\s+/g, " ").trim();
  if (!name || /^(?:検索ウィンドウ|メニュー|出馬表|レース結果|オッズ|払戻金)$/.test(name)) return null;
  return name;
}
__name(extractOfficialRaceName, "extractOfficialRaceName");
async function repairRaceNames(db, limit = 8) {
  const rows = await db.prepare(`
    SELECT race_id AS raceId, entry_url AS entryUrl, result_url AS resultUrl, race_name AS raceName
    FROM rt_races
    WHERE race_name IN ('\u691C\u7D22\u30A6\u30A3\u30F3\u30C9\u30A6','\u30E1\u30CB\u30E5\u30FC','\u51FA\u99AC\u8868','\u30EC\u30FC\u30B9\u7D50\u679C','\u30AA\u30C3\u30BA','\u6255\u623B\u91D1')
       OR race_name GLOB '[0-9]*\u30EC\u30FC\u30B9'
    ORDER BY race_date DESC, venue, race_no
    LIMIT ?
  `).bind(limit).all();
  let repaired = 0;
  for (const row of rows.results) {
    try {
      let name = null;
      for (const url of [row.resultUrl, row.entryUrl]) {
        if (!url) continue;
        try {
          const page = await fetchJraPage(url);
          name = extractOfficialRaceName(page.html);
          if (name) break;
        } catch {
        }
      }
      if (!name) continue;
      await db.prepare(`UPDATE rt_races SET race_name=?, updated_at=CURRENT_TIMESTAMP WHERE race_id=?`).bind(name, row.raceId).run();
      repaired += 1;
    } catch (error) {
      console.error("RACE_NAME_REPAIR_FAILED", row.raceId, error);
    }
  }
  return repaired;
}
__name(repairRaceNames, "repairRaceNames");
function runMaintenance(env) {
  if (maintenanceRunning) return maintenanceRunning;
  maintenanceRunning = Promise.all([
    repairRaceNames(env.DB, 8),
    runBacktestBatch(env.DB, 4)
  ]).then(() => void 0).finally(() => {
    maintenanceRunning = null;
  });
  return maintenanceRunning;
}
__name(runMaintenance, "runMaintenance");
var entry_default = {
  async fetch(request, env, ctx) {
    try {
      await prepare(env.DB);
      const pathname = new URL(request.url).pathname;
      if (pathname === `/backtest/${BACKTEST_DATE}`) {
        await runMaintenance(env);
        return new Response(await renderBacktest(env.DB), {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff"
          }
        });
      }
      if (pathname === "/" || pathname.startsWith("/races/")) ctx.waitUntil(runMaintenance(env));
      if (!complete_default.fetch) return new Response("NOT_FOUND", { status: 404 });
      return await complete_default.fetch(request, env, ctx);
    } catch (error) {
      return failureResponse(request, error);
    }
  },
  async scheduled(controller, env, ctx) {
    try {
      await prepare(env.DB);
      if (complete_default.scheduled) await complete_default.scheduled(controller, env, ctx);
      ctx.waitUntil(runMaintenance(env));
    } catch (error) {
      console.error("SCHEDULED_STARTUP_FAILED", error);
    }
  }
};
export {
  entry_default as default
};
//# sourceMappingURL=entry.js.map
