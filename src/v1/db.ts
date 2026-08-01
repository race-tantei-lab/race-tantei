import type {
  DashboardMetrics,
  PayoutRecord,
  PredictionOutput,
  RaceBundle,
  RaceRecord,
  ResultRecord,
  RunnerHistoryStats,
  RunnerRecord
} from "./types.js";
import { nowIso } from "./utils.js";

const SCHEMA = [
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

export async function ensureSchema(db: D1Database): Promise<void> {
  for (const statement of SCHEMA) await db.prepare(statement).run();
}

export async function getState(db: D1Database, key: string): Promise<string | null> {
  const row = await db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key = ?`).bind(key).first<{ value: string }>();
  return row?.value ?? null;
}

export async function setState(db: D1Database, key: string, value: string): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state (state_key, state_value, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value, updated_at = CURRENT_TIMESTAMP
  `).bind(key, value).run();
}

export async function beginSyncRun(db: D1Database, triggerType: string): Promise<number> {
  await db.prepare(`INSERT INTO rt_sync_runs (started_at, trigger_type) VALUES (?, ?)`).bind(nowIso(), triggerType).run();
  const row = await db.prepare(`SELECT last_insert_rowid() AS id`).first<{ id: number }>();
  return row?.id ?? 0;
}

export async function finishSyncRun(
  db: D1Database,
  id: number,
  counts: { discovered: number; processed: number; success: number; errors: number; errorMessage?: string }
): Promise<void> {
  await db.prepare(`
    UPDATE rt_sync_runs SET finished_at = ?, discovered_count = ?, processed_count = ?, success_count = ?, error_count = ?, error_message = ?
    WHERE id = ?
  `).bind(nowIso(), counts.discovered, counts.processed, counts.success, counts.errors, counts.errorMessage ?? null, id).run();
}

export async function upsertRaceSources(db: D1Database, entryUrls: string[], resultUrlFor: (entry: string) => string): Promise<void> {
  if (entryUrls.length === 0) return;
  const now = nowIso();
  const statements = entryUrls.map((entryUrl) => db.prepare(`
    INSERT INTO rt_race_sources (entry_url, result_url, next_fetch_at, updated_at)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(entry_url) DO UPDATE SET result_url = excluded.result_url, updated_at = CURRENT_TIMESTAMP
  `).bind(entryUrl, resultUrlFor(entryUrl), now));
  await db.batch(statements);
}

export async function resetRaceSourcesForDiscoveryRevision(db: D1Database): Promise<void> {
  await db.prepare(`
    UPDATE rt_race_sources
    SET status = 'discovered', next_fetch_at = ?, failure_count = 0,
        last_error = NULL, updated_at = CURRENT_TIMESTAMP
  `).bind(nowIso()).run();
}

export interface RaceSourceRow {
  entryUrl: string;
  resultUrl: string;
  raceId: string | null;
  status: string;
  nextFetchAt: string;
  failureCount: number;
}

export async function getDueRaceSources(db: D1Database, limit: number): Promise<RaceSourceRow[]> {
  const result = await db.prepare(`
    SELECT entry_url AS entryUrl, result_url AS resultUrl, race_id AS raceId, status,
           next_fetch_at AS nextFetchAt, failure_count AS failureCount
    FROM rt_race_sources
    WHERE status != 'complete' AND next_fetch_at <= ?
    ORDER BY CASE status WHEN 'awaiting_result' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, next_fetch_at
    LIMIT ?
  `).bind(nowIso(), limit).all<RaceSourceRow>();
  return result.results;
}

export async function updateRaceSource(
  db: D1Database,
  entryUrl: string,
  values: { raceId?: string | null; status: string; nextFetchAt: string; entryFetched?: boolean; resultFetched?: boolean; error?: string | null }
): Promise<void> {
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

function raceValues(race: RaceRecord): unknown[] {
  return [
    race.raceId, race.raceDate, race.venue, race.meetingNo, race.meetingDay, race.raceNo, race.raceName,
    race.conditions, race.surface, race.distanceM, race.direction, race.startTimeJst, race.startTimeUtc,
    race.weather, race.trackCondition, race.entryUrl, race.resultUrl, race.status
  ];
}

export async function saveEntryBundle(db: D1Database, bundle: RaceBundle): Promise<void> {
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
    race.raceId, runner.horseNo, runner.frameNo, runner.horseName, runner.sexAge, runner.coatColor,
    runner.horseWeight, runner.weightChange, runner.jockey, runner.assignedWeight, runner.trainer,
    runner.stable, runner.winOdds, runner.popularity, runner.runnerStatus
  ));
  if (statements.length > 0) await db.batch(statements);
}

export async function saveResultBundle(db: D1Database, bundle: RaceBundle): Promise<void> {
  const race = bundle.race;
  await db.prepare(`
    UPDATE rt_races SET status='finished', weather=?, track_condition=?, refund_horse_nos_json=?,
      result_updated_at=?, updated_at=CURRENT_TIMESTAMP
    WHERE race_id=?
  `).bind(race.weather, race.trackCondition, JSON.stringify(bundle.refundHorseNos), nowIso(), race.raceId).run();

  const resultStatements = bundle.results.map((result: ResultRecord) => db.prepare(`
    INSERT INTO rt_results (race_id, horse_no, finish_position, result_status, time_text, margin_text, final3f, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, horse_no) DO UPDATE SET finish_position=excluded.finish_position,
      result_status=excluded.result_status, time_text=excluded.time_text, margin_text=excluded.margin_text,
      final3f=excluded.final3f, updated_at=CURRENT_TIMESTAMP
  `).bind(race.raceId, result.horseNo, result.finishPosition, result.resultStatus, result.timeText, result.marginText, result.final3f));
  if (resultStatements.length > 0) await db.batch(resultStatements);

  const payoutStatements = bundle.payouts.map((payout: PayoutRecord) => db.prepare(`
    INSERT INTO rt_payouts (race_id, bet_type, combination, payout_yen, popularity, updated_at)
    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET payout_yen=excluded.payout_yen,
      popularity=excluded.popularity, updated_at=CURRENT_TIMESTAMP
  `).bind(race.raceId, payout.betType, payout.combination, payout.payoutYen, payout.popularity));
  if (payoutStatements.length > 0) await db.batch(payoutStatements);
}

export async function getRace(db: D1Database, raceId: string): Promise<RaceRecord | null> {
  return await db.prepare(`
    SELECT race_id AS raceId, race_date AS raceDate, venue, meeting_no AS meetingNo,
      meeting_day AS meetingDay, race_no AS raceNo, race_name AS raceName, conditions,
      surface, distance_m AS distanceM, direction, start_time_jst AS startTimeJst,
      start_time_utc AS startTimeUtc, weather, track_condition AS trackCondition,
      entry_url AS entryUrl, result_url AS resultUrl, status
    FROM rt_races WHERE race_id=?
  `).bind(raceId).first<RaceRecord>();
}

export async function getRunners(db: D1Database, raceId: string): Promise<RunnerRecord[]> {
  const result = await db.prepare(`
    SELECT horse_no AS horseNo, frame_no AS frameNo, horse_name AS horseName, sex_age AS sexAge,
      coat_color AS coatColor, horse_weight AS horseWeight, weight_change AS weightChange,
      jockey, assigned_weight AS assignedWeight, trainer, stable, win_odds AS winOdds,
      popularity, runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  return result.results;
}

export async function getRunnerHistoryStats(db: D1Database, race: RaceRecord, _runners: RunnerRecord[]): Promise<RunnerHistoryStats[]> {
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
  `).bind(race.raceId).all<RunnerHistoryStats>();
  return result.results;
}

export async function savePrediction(
  db: D1Database,
  raceId: string,
  prediction: PredictionOutput,
  status: "draft" | "locked"
): Promise<{ saved: boolean; predictionId: number | null }> {
  const existing = await db.prepare(`
    SELECT id, status FROM rt_predictions WHERE race_id=? AND model_version=?
  `).bind(raceId, prediction.modelVersion).first<{ id: number; status: string }>();
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

  const row = await db.prepare(`SELECT id, status FROM rt_predictions WHERE race_id=? AND model_version=?`)
    .bind(raceId, prediction.modelVersion).first<{ id: number; status: string }>();
  if (!row) return { saved: false, predictionId: null };

  await db.prepare(`DELETE FROM rt_prediction_runners WHERE prediction_id=?`).bind(row.id).run();
  await db.prepare(`DELETE FROM rt_bets WHERE prediction_id=? AND settlement_status='pending'`).bind(row.id).run();

  const runnerStatements = prediction.runners.map((runner) => db.prepare(`
    INSERT INTO rt_prediction_runners (
      prediction_id, horse_no, horse_name, predicted_order, win_probability, place_probability,
      fair_odds, current_odds, expected_value_pct, explanation
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    row.id, runner.horseNo, runner.horseName, runner.predictedOrder, runner.winProbability,
    runner.placeProbability, runner.fairOdds, runner.currentOdds, runner.expectedValuePct, runner.explanation
  ));
  if (runnerStatements.length > 0) await db.batch(runnerStatements);

  const betStatements = prediction.bets.map((bet) => db.prepare(`
    INSERT INTO rt_bets (
      prediction_id, race_id, bet_type, combination, stake_yen, assumed_odds,
      hit_probability, expected_value_pct, settlement_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
  `).bind(
    row.id, raceId, bet.betType, bet.combination, bet.stakeYen, bet.assumedOdds,
    bet.hitProbability, bet.expectedValuePct
  ));
  if (betStatements.length > 0) await db.batch(betStatements);
  return { saved: true, predictionId: row.id };
}

export async function settleRace(db: D1Database, raceId: string): Promise<number> {
  const race = await db.prepare(`SELECT refund_horse_nos_json AS refunds FROM rt_races WHERE race_id=? AND status='finished'`)
    .bind(raceId).first<{ refunds: string }>();
  if (!race) return 0;
  const refunds = new Set<number>(JSON.parse(race.refunds || "[]") as number[]);
  const winner = await db.prepare(`SELECT horse_no AS horseNo FROM rt_results WHERE race_id=? AND finish_position=1`)
    .bind(raceId).first<{ horseNo: number }>();
  const payoutRows = await db.prepare(`SELECT bet_type AS betType, combination, payout_yen AS payoutYen FROM rt_payouts WHERE race_id=?`)
    .bind(raceId).all<{ betType: string; combination: string; payoutYen: number }>();
  const payoutMap = new Map(payoutRows.results.map((row) => [`${row.betType}:${row.combination}`, row.payoutYen]));
  const pending = await db.prepare(`
    SELECT b.id, b.bet_type AS betType, b.combination, b.stake_yen AS stakeYen
    FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
    WHERE b.race_id=? AND b.settlement_status='pending' AND p.status='locked'
  `).bind(raceId).all<{ id: number; betType: string; combination: string; stakeYen: number }>();

  for (const bet of pending.results) {
    const horseNo = Number(bet.combination);
    let returnYen = 0;
    if (refunds.has(horseNo)) returnYen = bet.stakeYen;
    else if (bet.betType === "単勝" && winner?.horseNo === horseNo) {
      const payout = payoutMap.get(`単勝:${bet.combination}`) ?? 0;
      returnYen = Math.round((bet.stakeYen / 100) * payout);
    }
    await db.prepare(`
      UPDATE rt_bets SET settlement_status='settled', return_yen=?, settled_at=? WHERE id=?
    `).bind(returnYen, nowIso(), bet.id).run();
  }
  return pending.results.length;
}

export async function getDashboardMetrics(db: D1Database): Promise<DashboardMetrics> {
  const raceCount = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races`).first<{ count: number }>();
  const predictionCount = await db.prepare(`SELECT COUNT(*) AS count FROM rt_predictions WHERE status='locked'`).first<{ count: number }>();
  const bets = await db.prepare(`
    SELECT COUNT(*) AS count, COALESCE(SUM(stake_yen),0) AS stake,
      COALESCE(SUM(return_yen),0) AS returns,
      COALESCE(SUM(CASE WHEN return_yen > 0 THEN 1 ELSE 0 END),0) AS hits
    FROM rt_bets WHERE settlement_status='settled'
  `).first<{ count: number; stake: number; returns: number; hits: number }>();
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
    roiPct: stake > 0 ? (returns / stake) * 100 : null,
    hitRatePct: count > 0 ? ((bets?.hits ?? 0) / count) * 100 : null
  };
}

export interface RaceListRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  status: string;
  predictionStatus: string | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  betCount: number;
}

export async function getLatestRaces(db: D1Database, limit = 80): Promise<RaceListRow[]> {
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
  `).bind(limit).all<RaceListRow>();
  return result.results;
}

export interface RaceDetail {
  race: RaceRecord;
  runners: Array<RunnerRecord & { finishPosition: number | null }>;
  prediction: { id: number; status: string; modelVersion: string; generatedAt: string; lockedAt: string | null } | null;
  predictedRunners: Array<{
    horseNo: number; horseName: string; predictedOrder: number; winProbability: number;
    placeProbability: number; fairOdds: number; currentOdds: number | null; expectedValuePct: number | null; explanation: string;
  }>;
  bets: Array<{ betType: string; combination: string; stakeYen: number; assumedOdds: number; expectedValuePct: number; settlementStatus: string; returnYen: number | null }>;
}

export async function getRaceDetail(db: D1Database, raceId: string): Promise<RaceDetail | null> {
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
  `).bind(raceId).all<RunnerRecord & { finishPosition: number | null }>();
  const prediction = await db.prepare(`
    SELECT id, status, model_version AS modelVersion, generated_at AS generatedAt, locked_at AS lockedAt
    FROM rt_predictions WHERE race_id=? ORDER BY id DESC LIMIT 1
  `).bind(raceId).first<{ id: number; status: string; modelVersion: string; generatedAt: string; lockedAt: string | null }>();
  if (!prediction) return { race, runners: runnersResult.results, prediction: null, predictedRunners: [], bets: [] };
  const predicted = await db.prepare(`
    SELECT horse_no AS horseNo, horse_name AS horseName, predicted_order AS predictedOrder,
      win_probability AS winProbability, place_probability AS placeProbability, fair_odds AS fairOdds,
      current_odds AS currentOdds, expected_value_pct AS expectedValuePct, explanation
    FROM rt_prediction_runners WHERE prediction_id=? ORDER BY predicted_order
  `).bind(prediction.id).all<RaceDetail["predictedRunners"][number]>();
  const bets = await db.prepare(`
    SELECT bet_type AS betType, combination, stake_yen AS stakeYen, assumed_odds AS assumedOdds,
      expected_value_pct AS expectedValuePct, settlement_status AS settlementStatus, return_yen AS returnYen
    FROM rt_bets WHERE prediction_id=? ORDER BY expected_value_pct DESC
  `).bind(prediction.id).all<RaceDetail["bets"][number]>();
  return { race, runners: runnersResult.results, prediction, predictedRunners: predicted.results, bets: bets.results };
}

export async function getPerformanceRows(db: D1Database): Promise<Array<{ label: string; bets: number; stake: number; returns: number; roi: number | null }>> {
  const result = await db.prepare(`
    SELECT substr(ra.race_date,1,7) AS label, COUNT(b.id) AS rt_bets,
      COALESCE(SUM(b.stake_yen),0) AS stake, COALESCE(SUM(b.return_yen),0) AS returns
    FROM rt_bets b JOIN rt_races ra ON ra.race_id=b.race_id
    WHERE b.settlement_status='settled'
    GROUP BY substr(ra.race_date,1,7) ORDER BY label DESC
  `).all<{ label: string; bets: number; stake: number; returns: number }>();
  return result.results.map((row) => ({ ...row, roi: row.stake > 0 ? row.returns / row.stake * 100 : null }));
}

export async function getSystemSnapshot(db: D1Database): Promise<unknown> {
  const lastSync = await db.prepare(`SELECT * FROM rt_sync_runs ORDER BY id DESC LIMIT 1`).first<Record<string, unknown>>();
  const sourceCounts = await db.prepare(`SELECT status, COUNT(*) AS count FROM rt_race_sources GROUP BY status`).all<Record<string, unknown>>();
  const lastRace = await db.prepare(`SELECT race_id, updated_at FROM rt_races ORDER BY updated_at DESC LIMIT 1`).first<Record<string, unknown>>();
  return { lastSync, sourceCounts: sourceCounts.results, lastRace, now: nowIso() };
}
