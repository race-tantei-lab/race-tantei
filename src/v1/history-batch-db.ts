import type { RaceBundle } from "./types.js";
import { nowIso } from "./utils.js";

export interface HistoryBundlePair {
  entry: RaceBundle;
  result: RaceBundle;
}

export async function getCompleteHistoryRaceIds(
  db: D1Database,
  raceIds: string[]
): Promise<Set<string>> {
  const uniqueIds = [...new Set(raceIds.filter(Boolean))];
  if (uniqueIds.length === 0) return new Set<string>();
  const result = await db.prepare(`
    SELECT r.race_id AS raceId,
      COUNT(DISTINCT CASE WHEN ru.runner_status='active' AND ru.win_odds IS NOT NULL THEN ru.horse_no END) AS runners,
      COUNT(DISTINCT rs.horse_no) AS results,
      COUNT(DISTINCT rp.bet_type || ':' || rp.combination) AS payouts
    FROM rt_races r
    LEFT JOIN rt_runners ru ON ru.race_id=r.race_id
    LEFT JOIN rt_results rs ON rs.race_id=r.race_id
    LEFT JOIN rt_payouts rp ON rp.race_id=r.race_id
    WHERE r.race_id IN (SELECT value FROM json_each(?)) AND r.status='finished'
    GROUP BY r.race_id
    HAVING runners >= 2 AND results >= 2 AND payouts >= 1
  `).bind(JSON.stringify(uniqueIds)).all<{ raceId: string }>();
  return new Set(result.results.map((row) => row.raceId));
}

export async function saveHistoryBundlePairsBatch(
  db: D1Database,
  pairs: HistoryBundlePair[]
): Promise<{ races: number; statements: number }> {
  if (pairs.length === 0) return { races: 0, statements: 0 };
  const timestamp = nowIso();
  const races = pairs.map(({ result }) => ({
    raceId: result.race.raceId,
    raceDate: result.race.raceDate,
    venue: result.race.venue,
    meetingNo: result.race.meetingNo,
    meetingDay: result.race.meetingDay,
    raceNo: result.race.raceNo,
    raceName: result.race.raceName,
    conditions: result.race.conditions,
    surface: result.race.surface,
    distanceM: result.race.distanceM,
    direction: result.race.direction,
    startTimeJst: result.race.startTimeJst,
    startTimeUtc: result.race.startTimeUtc,
    weather: result.race.weather,
    trackCondition: result.race.trackCondition,
    entryUrl: result.race.entryUrl,
    resultUrl: result.race.resultUrl,
    refundHorseNosJson: JSON.stringify(result.refundHorseNos),
    timestamp
  }));
  const runners = pairs.flatMap(({ entry }) => entry.runners.map((runner) => ({
    raceId: entry.race.raceId,
    horseNo: runner.horseNo,
    frameNo: runner.frameNo,
    horseName: runner.horseName,
    sexAge: runner.sexAge,
    coatColor: runner.coatColor,
    horseWeight: runner.horseWeight,
    weightChange: runner.weightChange,
    jockey: runner.jockey,
    assignedWeight: runner.assignedWeight,
    trainer: runner.trainer,
    stable: runner.stable,
    winOdds: runner.winOdds,
    popularity: runner.popularity,
    runnerStatus: runner.runnerStatus
  })));
  const results = pairs.flatMap(({ result }) => result.results.map((row) => ({
    raceId: result.race.raceId,
    horseNo: row.horseNo,
    finishPosition: row.finishPosition,
    resultStatus: row.resultStatus,
    timeText: row.timeText,
    marginText: row.marginText,
    final3f: row.final3f
  })));
  const payouts = pairs.flatMap(({ result }) => result.payouts.map((row) => ({
    raceId: result.race.raceId,
    betType: row.betType,
    combination: row.combination,
    payoutYen: row.payoutYen,
    popularity: row.popularity
  })));

  const statements = [
    db.prepare(`
      INSERT INTO rt_races (
        race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name, conditions,
        surface, distance_m, direction, start_time_jst, start_time_utc, weather, track_condition,
        entry_url, result_url, status, refund_horse_nos_json, entry_updated_at, result_updated_at
      )
      SELECT
        json_extract(value,'$.raceId'), json_extract(value,'$.raceDate'), json_extract(value,'$.venue'),
        json_extract(value,'$.meetingNo'), json_extract(value,'$.meetingDay'), json_extract(value,'$.raceNo'),
        json_extract(value,'$.raceName'), json_extract(value,'$.conditions'), json_extract(value,'$.surface'),
        json_extract(value,'$.distanceM'), json_extract(value,'$.direction'), json_extract(value,'$.startTimeJst'),
        json_extract(value,'$.startTimeUtc'), json_extract(value,'$.weather'), json_extract(value,'$.trackCondition'),
        json_extract(value,'$.entryUrl'), json_extract(value,'$.resultUrl'), 'finished',
        json_extract(value,'$.refundHorseNosJson'), json_extract(value,'$.timestamp'), json_extract(value,'$.timestamp')
      FROM json_each(?) WHERE 1
      ON CONFLICT(race_id) DO UPDATE SET
        race_date=excluded.race_date, venue=excluded.venue, meeting_no=excluded.meeting_no,
        meeting_day=excluded.meeting_day, race_no=excluded.race_no, race_name=excluded.race_name,
        conditions=excluded.conditions, surface=excluded.surface, distance_m=excluded.distance_m,
        direction=excluded.direction, start_time_jst=excluded.start_time_jst,
        start_time_utc=excluded.start_time_utc, weather=excluded.weather,
        track_condition=excluded.track_condition, entry_url=excluded.entry_url,
        result_url=excluded.result_url, status='finished', refund_horse_nos_json=excluded.refund_horse_nos_json,
        entry_updated_at=excluded.entry_updated_at, result_updated_at=excluded.result_updated_at,
        updated_at=CURRENT_TIMESTAMP
    `).bind(JSON.stringify(races)),
    db.prepare(`
      INSERT INTO rt_runners (
        race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight, weight_change,
        jockey, assigned_weight, trainer, stable, win_odds, popularity, runner_status
      )
      SELECT
        json_extract(value,'$.raceId'), json_extract(value,'$.horseNo'), json_extract(value,'$.frameNo'),
        json_extract(value,'$.horseName'), json_extract(value,'$.sexAge'), json_extract(value,'$.coatColor'),
        json_extract(value,'$.horseWeight'), json_extract(value,'$.weightChange'), json_extract(value,'$.jockey'),
        json_extract(value,'$.assignedWeight'), json_extract(value,'$.trainer'), json_extract(value,'$.stable'),
        json_extract(value,'$.winOdds'), json_extract(value,'$.popularity'), json_extract(value,'$.runnerStatus')
      FROM json_each(?) WHERE 1
      ON CONFLICT(race_id, horse_no) DO UPDATE SET
        frame_no=excluded.frame_no, horse_name=excluded.horse_name, sex_age=excluded.sex_age,
        coat_color=excluded.coat_color, horse_weight=excluded.horse_weight, weight_change=excluded.weight_change,
        jockey=excluded.jockey, assigned_weight=excluded.assigned_weight, trainer=excluded.trainer,
        stable=excluded.stable, win_odds=excluded.win_odds, popularity=excluded.popularity,
        runner_status=excluded.runner_status, updated_at=CURRENT_TIMESTAMP
    `).bind(JSON.stringify(runners)),
    db.prepare(`
      INSERT INTO rt_results (race_id, horse_no, finish_position, result_status, time_text, margin_text, final3f)
      SELECT json_extract(value,'$.raceId'), json_extract(value,'$.horseNo'), json_extract(value,'$.finishPosition'),
        json_extract(value,'$.resultStatus'), json_extract(value,'$.timeText'), json_extract(value,'$.marginText'),
        json_extract(value,'$.final3f')
      FROM json_each(?) WHERE 1
      ON CONFLICT(race_id, horse_no) DO UPDATE SET
        finish_position=excluded.finish_position, result_status=excluded.result_status,
        time_text=excluded.time_text, margin_text=excluded.margin_text,
        final3f=excluded.final3f, updated_at=CURRENT_TIMESTAMP
    `).bind(JSON.stringify(results)),
    db.prepare(`
      INSERT INTO rt_payouts (race_id, bet_type, combination, payout_yen, popularity)
      SELECT json_extract(value,'$.raceId'), json_extract(value,'$.betType'), json_extract(value,'$.combination'),
        json_extract(value,'$.payoutYen'), json_extract(value,'$.popularity')
      FROM json_each(?) WHERE 1
      ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET
        payout_yen=excluded.payout_yen, popularity=excluded.popularity, updated_at=CURRENT_TIMESTAMP
    `).bind(JSON.stringify(payouts))
  ];
  await db.batch(statements);
  return { races: pairs.length, statements: statements.length };
}

export async function setHistoryStatesBatch(
  db: D1Database,
  values: Array<{ key: string; value: string }>
): Promise<void> {
  if (values.length === 0) return;
  await db.prepare(`
    INSERT INTO rt_system_state (state_key, state_value)
    SELECT json_extract(value,'$.key'), json_extract(value,'$.value')
    FROM json_each(?) WHERE 1
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at=CURRENT_TIMESTAMP
  `).bind(JSON.stringify(values)).run();
}
