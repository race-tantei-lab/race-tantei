import type { PayoutRecord, RaceBundle, ResultRecord } from "./types.js";
import { nowIso } from "./utils.js";

const MAX_RACE_IDS_PER_QUERY = 80;

export interface HistoryBundlePair {
  entry: RaceBundle;
  result: RaceBundle;
}

function placeholders(count: number): string {
  return Array.from({ length: count }, () => "?").join(", ");
}

function raceValues(bundle: RaceBundle): unknown[] {
  const race = bundle.race;
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
    race.status,
    nowIso()
  ];
}

export async function getCompleteHistoryRaceIds(
  db: D1Database,
  raceIds: string[]
): Promise<Set<string>> {
  const uniqueIds = [...new Set(raceIds.filter(Boolean))];
  const complete = new Set<string>();

  for (let offset = 0; offset < uniqueIds.length; offset += MAX_RACE_IDS_PER_QUERY) {
    const chunk = uniqueIds.slice(offset, offset + MAX_RACE_IDS_PER_QUERY);
    if (chunk.length === 0) continue;
    const result = await db.prepare(`
      SELECT r.race_id AS raceId
      FROM rt_races r
      LEFT JOIN (
        SELECT race_id, COUNT(*) AS runners
        FROM rt_runners
        WHERE runner_status='active' AND win_odds IS NOT NULL
        GROUP BY race_id
      ) rr ON rr.race_id=r.race_id
      LEFT JOIN (
        SELECT race_id, COUNT(*) AS results
        FROM rt_results
        GROUP BY race_id
      ) rs ON rs.race_id=r.race_id
      LEFT JOIN (
        SELECT race_id, COUNT(*) AS payouts
        FROM rt_payouts
        GROUP BY race_id
      ) rp ON rp.race_id=r.race_id
      WHERE r.race_id IN (${placeholders(chunk.length)})
        AND r.status='finished'
        AND COALESCE(rr.runners, 0) >= 2
        AND COALESCE(rs.results, 0) >= 2
        AND COALESCE(rp.payouts, 0) >= 1
    `).bind(...chunk).all<{ raceId: string }>();
    for (const row of result.results) complete.add(row.raceId);
  }

  return complete;
}

function statementsForPair(db: D1Database, pair: HistoryBundlePair): D1PreparedStatement[] {
  const race = pair.entry.race;
  const resultRace = pair.result.race;
  const statements: D1PreparedStatement[] = [];

  statements.push(db.prepare(`
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
  `).bind(...raceValues(pair.entry)));

  for (const runner of pair.entry.runners) {
    statements.push(db.prepare(`
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
  }

  statements.push(db.prepare(`
    UPDATE rt_races SET status='finished', weather=?, track_condition=?, refund_horse_nos_json=?,
      result_updated_at=?, updated_at=CURRENT_TIMESTAMP
    WHERE race_id=?
  `).bind(
    resultRace.weather,
    resultRace.trackCondition,
    JSON.stringify(pair.result.refundHorseNos),
    nowIso(),
    resultRace.raceId
  ));

  for (const result of pair.result.results) {
    statements.push(db.prepare(`
      INSERT INTO rt_results (race_id, horse_no, finish_position, result_status, time_text, margin_text, final3f, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(race_id, horse_no) DO UPDATE SET finish_position=excluded.finish_position,
        result_status=excluded.result_status, time_text=excluded.time_text, margin_text=excluded.margin_text,
        final3f=excluded.final3f, updated_at=CURRENT_TIMESTAMP
    `).bind(
      resultRace.raceId,
      (result as ResultRecord).horseNo,
      (result as ResultRecord).finishPosition,
      (result as ResultRecord).resultStatus,
      (result as ResultRecord).timeText,
      (result as ResultRecord).marginText,
      (result as ResultRecord).final3f
    ));
  }

  for (const payout of pair.result.payouts) {
    statements.push(db.prepare(`
      INSERT INTO rt_payouts (race_id, bet_type, combination, payout_yen, popularity, updated_at)
      VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET payout_yen=excluded.payout_yen,
        popularity=excluded.popularity, updated_at=CURRENT_TIMESTAMP
    `).bind(
      resultRace.raceId,
      (payout as PayoutRecord).betType,
      (payout as PayoutRecord).combination,
      (payout as PayoutRecord).payoutYen,
      (payout as PayoutRecord).popularity
    ));
  }

  return statements;
}

export async function saveHistoryBundlePairsBatch(
  db: D1Database,
  pairs: HistoryBundlePair[]
): Promise<{ races: number; statements: number }> {
  if (pairs.length === 0) return { races: 0, statements: 0 };
  const statements = pairs.flatMap((pair) => statementsForPair(db, pair));
  await db.batch(statements);
  return { races: pairs.length, statements: statements.length };
}

export async function setHistoryStatesBatch(
  db: D1Database,
  values: Array<{ key: string; value: string }>
): Promise<void> {
  if (values.length === 0) return;
  const statements = values.map(({ key, value }) => db.prepare(`
    INSERT INTO rt_system_state (state_key, state_value, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at=CURRENT_TIMESTAMP
  `).bind(key, value));
  await db.batch(statements);
}
