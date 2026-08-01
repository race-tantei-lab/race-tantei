const LEGACY_RACES = "legacy_phase1_races";
const LEGACY_RUNNERS = "legacy_phase1_runners";

interface ColumnRow {
  name: string;
}

async function columns(db: D1Database, table: string): Promise<Set<string>> {
  const allowed = new Set([
    "races",
    "runners",
    "race_results",
    LEGACY_RACES,
    LEGACY_RUNNERS
  ]);
  if (!allowed.has(table)) throw new Error(`UNSAFE_TABLE_NAME:${table}`);
  const result = await db.prepare(`PRAGMA table_info(${table})`).all<ColumnRow>();
  return new Set(result.results.map((row) => row.name));
}

async function tableExists(db: D1Database, table: string): Promise<boolean> {
  return (await columns(db, table)).size > 0;
}

async function moveLegacyTable(
  db: D1Database,
  current: "races" | "runners",
  legacy: typeof LEGACY_RACES | typeof LEGACY_RUNNERS,
  indexes: string[]
): Promise<void> {
  for (const index of indexes) await db.exec(`DROP INDEX IF EXISTS ${index}`);

  if (!(await tableExists(db, current))) return;
  if (await tableExists(db, legacy)) {
    // A prior interrupted deploy already preserved the pilot data.
    await db.exec(`DROP TABLE ${current}`);
    return;
  }
  await db.exec(`ALTER TABLE ${current} RENAME TO ${legacy}`);
}

/** Preserve incompatible pilot tables before creating the v1 schema. */
export async function prepareLegacySchema(db: D1Database): Promise<void> {
  const raceColumns = await columns(db, "races");
  if (raceColumns.size > 0 && (!raceColumns.has("status") || raceColumns.has("race_status"))) {
    await moveLegacyTable(db, "races", LEGACY_RACES, ["idx_races_date"]);
  }

  const runnerColumns = await columns(db, "runners");
  if (runnerColumns.size > 0 && (!runnerColumns.has("win_odds") || runnerColumns.has("final_odds"))) {
    await moveLegacyTable(db, "runners", LEGACY_RUNNERS, [
      "idx_runners_horse",
      "idx_runners_jockey",
      "idx_runners_trainer"
    ]);
  }
}

/** Copy compatible pilot data into the new schema. Safe to run repeatedly. */
export async function migrateLegacyData(db: D1Database): Promise<void> {
  if (await tableExists(db, LEGACY_RACES)) {
    await db.exec(`
      INSERT OR IGNORE INTO races (
        race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name,
        conditions, surface, distance_m, direction, start_time_jst, start_time_utc,
        weather, track_condition, entry_url, result_url, status,
        refund_horse_nos_json, entry_updated_at, result_updated_at, created_at, updated_at
      )
      SELECT
        race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name,
        conditions, surface, distance_m, direction, start_time_jst, NULL,
        NULL, NULL, entry_url, result_url,
        CASE WHEN race_status IN ('result_confirmed', 'finished') THEN 'finished' ELSE 'scheduled' END,
        '[]', updated_at,
        CASE WHEN race_status IN ('result_confirmed', 'finished') THEN updated_at ELSE NULL END,
        created_at, updated_at
      FROM ${LEGACY_RACES}
    `);
  }

  if (await tableExists(db, LEGACY_RUNNERS)) {
    await db.exec(`
      INSERT OR IGNORE INTO runners (
        race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight,
        weight_change, jockey, assigned_weight, trainer, stable, win_odds,
        popularity, runner_status, updated_at
      )
      SELECT
        race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight,
        weight_change, jockey, assigned_weight, trainer, stable, final_odds,
        popularity, runner_status, updated_at
      FROM ${LEGACY_RUNNERS}
    `);
  }

  if (await tableExists(db, "race_results")) {
    await db.exec(`
      INSERT OR IGNORE INTO results (
        race_id, horse_no, finish_position, result_status, time_text,
        margin_text, final3f, updated_at
      )
      SELECT
        race_id, horse_no, finish_position, result_status, time_text,
        margin_text, final_3f, updated_at
      FROM race_results
    `);
  }

  await db.prepare(`
    INSERT INTO system_state (state_key, state_value, updated_at)
    VALUES ('schema_version', '1.1.0', CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET
      state_value = excluded.state_value,
      updated_at = CURRENT_TIMESTAMP
  `).run();
}
