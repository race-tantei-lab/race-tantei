import type { RaceBundle } from "./types.js";
import { nowIso } from "./utils.js";

const MAX_BOUND_PARAMETERS = 100;
const MAX_RACE_IDS_PER_QUERY = 80;

export interface HistoryBundlePair {
  entry: RaceBundle;
  result: RaceBundle;
}

function placeholders(count: number): string {
  return Array.from({ length: count }, () => "?").join(", ");
}

function rowPlaceholders(columns: number, rows: number): string {
  return Array.from({ length: rows }, () => `(${placeholders(columns)})`).join(", ");
}

function chunkRows<T>(rows: T[], columns: number): T[][] {
  const size = Math.max(1, Math.floor(MAX_BOUND_PARAMETERS / columns));
  const chunks: T[][] = [];
  for (let offset = 0; offset < rows.length; offset += size) chunks.push(rows.slice(offset, offset + size));
  return chunks;
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
      SELECT r.race_id AS raceId,
        COUNT(DISTINCT CASE WHEN ru.runner_status='active' AND ru.win_odds IS NOT NULL THEN ru.horse_no END) AS runners,
        COUNT(DISTINCT rs.horse_no) AS results,
        COUNT(DISTINCT rp.bet_type || ':' || rp.combination) AS payouts
      FROM rt_races r
      LEFT JOIN rt_runners ru ON ru.race_id=r.race_id
      LEFT JOIN rt_results rs ON rs.race_id=r.race_id
      LEFT JOIN rt_payouts rp ON rp.race_id=r.race_id
      WHERE r.race_id IN (${placeholders(chunk.length)}) AND r.status='finished'
      GROUP BY r.race_id
      HAVING runners >= 2 AND results >= 2 AND payouts >= 1
    `).bind(...chunk).all<{ raceId: string }>();
    for (const row of result.results) complete.add(row.raceId);
  }

  return complete;
}

export async function saveHistoryBundlePairsBatch(
  db: D1Database,
  pairs: HistoryBundlePair[]
): Promise<{ races: number; statements: number }> {
  if (pairs.length === 0) return { races: 0, statements: 0 };
  const statements: D1PreparedStatement[] = [];
  const timestamp = nowIso();

  const raceRows = pairs.map(({ entry, result }) => {
    const race = result.race;
    return [
      race.raceId, race.raceDate, race.venue, race.meetingNo, race.meetingDay, race.raceNo,
      race.raceName, race.conditions, race.surface, race.distanceM, race.direction, race.startTimeJst,
      race.startTimeUtc, race.weather, race.trackCondition, race.entryUrl, race.resultUrl, "finished",
      JSON.stringify(result.refundHorseNos), timestamp, timestamp
    ];
  });
  for (const chunk of chunkRows(raceRows, 21)) {
    statements.push(db.prepare(`
      INSERT INTO rt_races (
        race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name, conditions,
        surface, distance_m, direction, start_time_jst, start_time_utc, weather, track_condition,
        entry_url, result_url, status, refund_horse_nos_json, entry_updated_at, result_updated_at
      ) VALUES ${rowPlaceholders(21, chunk.length)}
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
    `).bind(...chunk.flat()));
  }

  const runnerRows = pairs.flatMap(({ entry }) => entry.runners.map((runner) => [
    entry.race.raceId, runner.horseNo, runner.frameNo, runner.horseName, runner.sexAge,
    runner.coatColor, runner.horseWeight, runner.weightChange, runner.jockey, runner.assignedWeight,
    runner.trainer, runner.stable, runner.winOdds, runner.popularity, runner.runnerStatus
  ]));
  for (const chunk of chunkRows(runnerRows, 15)) {
    statements.push(db.prepare(`
      INSERT INTO rt_runners (
        race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight, weight_change,
        jockey, assigned_weight, trainer, stable, win_odds, popularity, runner_status
      ) VALUES ${rowPlaceholders(15, chunk.length)}
      ON CONFLICT(race_id, horse_no) DO UPDATE SET
        frame_no=excluded.frame_no, horse_name=excluded.horse_name, sex_age=excluded.sex_age,
        coat_color=excluded.coat_color, horse_weight=excluded.horse_weight, weight_change=excluded.weight_change,
        jockey=excluded.jockey, assigned_weight=excluded.assigned_weight, trainer=excluded.trainer,
        stable=excluded.stable, win_odds=excluded.win_odds, popularity=excluded.popularity,
        runner_status=excluded.runner_status, updated_at=CURRENT_TIMESTAMP
    `).bind(...chunk.flat()));
  }

  const resultRows = pairs.flatMap(({ result }) => result.results.map((row) => [
    result.race.raceId, row.horseNo, row.finishPosition, row.resultStatus, row.timeText, row.marginText, row.final3f
  ]));
  for (const chunk of chunkRows(resultRows, 7)) {
    statements.push(db.prepare(`
      INSERT INTO rt_results (race_id, horse_no, finish_position, result_status, time_text, margin_text, final3f)
      VALUES ${rowPlaceholders(7, chunk.length)}
      ON CONFLICT(race_id, horse_no) DO UPDATE SET
        finish_position=excluded.finish_position, result_status=excluded.result_status,
        time_text=excluded.time_text, margin_text=excluded.margin_text,
        final3f=excluded.final3f, updated_at=CURRENT_TIMESTAMP
    `).bind(...chunk.flat()));
  }

  const payoutRows = pairs.flatMap(({ result }) => result.payouts.map((row) => [
    result.race.raceId, row.betType, row.combination, row.payoutYen, row.popularity
  ]));
  for (const chunk of chunkRows(payoutRows, 5)) {
    statements.push(db.prepare(`
      INSERT INTO rt_payouts (race_id, bet_type, combination, payout_yen, popularity)
      VALUES ${rowPlaceholders(5, chunk.length)}
      ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET
        payout_yen=excluded.payout_yen, popularity=excluded.popularity, updated_at=CURRENT_TIMESTAMP
    `).bind(...chunk.flat()));
  }

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
    VALUES ${rowPlaceholders(2, values.length)}
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at=CURRENT_TIMESTAMP
  `).bind(...values.flatMap(({ key, value }) => [key, value])).run();
}
