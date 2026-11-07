#!/usr/bin/env python3
"""Parity regression for D1 historical feature delta race selection.

Run against local SQLite only. Does NOT connect to or mutate production D1.
Compare the actual TS query from the Worker to the pre-PR#283 canonical
race-first query across dates, cutoffs, null/empty fields, and duplicates.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/v1/completed-feature-runtime.ts").read_text(encoding="utf-8")
start = SOURCE.index("const raceIds = await db.prepare(" + chr(96))
end = SOURCE.index(chr(96) + ").bind(...dateBindings", start)
TS_SQL = SOURCE[start + len("const raceIds = await db.prepare(" + chr(96)):end]
assert "FROM rt_races ra" in TS_SQL and "AND EXISTS" in TS_SQL, "date-first query missing"
assert "WITH matches AS" not in TS_SQL, "global ten-year UNION must not return"
assert "COALESCE(ru.jockey,'')" in TS_SQL and "COALESCE(ru.trainer,'')" in TS_SQL
assert "ORDER BY ra.race_date,ra.race_id" in TS_SQL

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE rt_races (race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL, start_time_utc TEXT);
CREATE TABLE rt_runners (race_id TEXT NOT NULL, horse_no INTEGER, horse_name TEXT, jockey TEXT, trainer TEXT);
CREATE TABLE rt_results (race_id TEXT NOT NULL, horse_no INTEGER, finish_position INTEGER);
CREATE INDEX rt_idx_races_date ON rt_races(race_date);
CREATE INDEX rt_idx_runners_race ON rt_runners(race_id);
CREATE INDEX rt_idx_runners_horse ON rt_runners(horse_name);
CREATE INDEX rt_idx_runners_jockey ON rt_runners(jockey);
CREATE INDEX rt_idx_runners_trainer ON rt_runners(trainer);
CREATE INDEX rt_idx_results_race ON rt_results(race_id);
""")
base = dt.date(2026, 6, 1)
for n in range(260):
    date = base + dt.timedelta(days=n // 3)
    race_id = f"r{n:04d}"
    time_utc = None if n % 37 == 0 else f"{date}T{8 + n % 6:02d}:00:00Z"
    db.execute("INSERT INTO rt_races VALUES (?,?,?)", (race_id, date.isoformat(), time_utc))
    for horse_no in range(1, 13):
        horse = f"H{(n * 3 + horse_no) % 91}" if n % 29 != 0 else ""
        jockey = None if n % 19 == 0 else ("" if n % 23 == 0 else f"J{(horse_no + n) % 19}")
        trainer = None if n % 17 == 0 else ("" if n % 31 == 0 else f"T{(horse_no + n) % 24}")
        db.execute("INSERT INTO rt_runners VALUES (?,?,?,?,?)", (race_id, horse_no, horse, jockey, trainer))
        if n % 11 != 0:
            db.execute("INSERT INTO rt_results VALUES (?,?,?)", (race_id, horse_no, horse_no))
db.commit()

pre_283 = """
 SELECT DISTINCT ra.race_id AS raceId
 FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id
 WHERE {date_window}
 AND (
   ru.horse_name IN (SELECT value FROM json_each(?))
   OR COALESCE(ru.jockey,'') IN (SELECT value FROM json_each(?))
   OR COALESCE(ru.trainer,'') IN (SELECT value FROM json_each(?))
 )
 ORDER BY ra.race_date,ra.race_id
"""
with_same_day = """
 ra.race_date>? AND (
 ra.race_date<? OR (
 ra.race_date=? AND ra.start_time_utc IS NOT NULL
 AND datetime(ra.start_time_utc)<datetime(?)
 AND EXISTS (
    SELECT 1 FROM rt_results rr
    WHERE rr.race_id=ra.race_id AND rr.finish_position IS NOT NULL
 )
 ))
"""
without_same_day = "ra.race_date>? AND ra.race_date<?"
marker = chr(36) + "{dateWindowSql}"
assert marker in TS_SQL, "source date-window binding was changed"
assert "const dateBindings = includeSameDayDelta" in SOURCE
assert ".bind(...dateBindings, horseJson, jockeyJson, trainerJson)" in SOURCE
count = 0
for include_same_day in (True, False):
    where = with_same_day if include_same_day else without_same_day
    old_sql = pre_283.format(date_window=where)
    new_sql = TS_SQL.replace(marker, where)
    for through in ("2026-06-03", "2026-07-15", "2026-08-09"):
        for target in ("2026-08-09", "2026-08-12", "2026-08-26"):
            for hour in (8, 11, 19):
                cutoff = target + f"T{hour:02d}:00:00Z"
                dates = ([through, target, target, cutoff] if include_same_day else [through, target])
                for horses, jockeys, trainers in (
                    (["H1", "H5", "H29"], ["J2", "J10"], ["T4"]),
                    ([], [""], []), ([], [], [""]),
                    (["DOES_NOT_EXIST"], ["DOES_NOT_EXIST"], ["DOES_NOT_EXIST"]),
                    (["H10"], [""], ["", "T20"]),
                ):
                    params = dates + [json.dumps(horses), json.dumps(jockeys), json.dumps(trainers)]
                    old_rows = db.execute(old_sql, params).fetchall()
                    new_rows = db.execute(new_sql, params).fetchall()
                    assert old_rows == new_rows, (
                        include_same_day, through, target, cutoff, horses, jockeys, trainers,
                        old_rows[:20], new_rows[:20],
                    )
                    count += 1

query_plan = db.execute(
    "EXPLAIN QUERY PLAN " + TS_SQL.replace(marker, without_same_day),
    ["2026-07-01","2026-08-09",json.dumps(["H1"]),json.dumps(["J2"]),json.dumps(["T3"])]
).fetchall()
assert any("SEARCH ra USING" in str(row[3]) and "rt_idx_races_date" in str(row[3]) for row in query_plan), query_plan
assert not any("SCAN rt_runners" in str(row[3]) for row in query_plan), query_plan
print("FEATURE_DELTA_DATE_FIRST_PARITY_OK", "cases="+str(count), "indexed_date_scan=true", "d1_production_queries=0")
