from pathlib import Path


def replace_once(path, old, new):
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'{path}: expected one match, got {count}: {old[:100]!r}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')
    print('fixed',path)

# A race is learnable when official result rows exist. The ingestion status label
# is operational metadata and must never suppress already-confirmed results.
replace_once('scripts/live-recency-learning.py',
"          AND r.status='finished'\n          AND r.start_time_utc IS NOT NULL",
"          AND r.start_time_utc IS NOT NULL")

replace_once('src/v1/completed-recency-learning.ts',
"        AND r.status='finished'\n        AND r.start_time_utc IS NOT NULL",
"        AND r.start_time_utc IS NOT NULL")

replace_once('src/v1/completed-feature-runtime.ts',
"(ra.race_date=? AND ra.status='finished' AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?))",
"(ra.race_date=? AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=ra.race_id AND rr.finish_position IS NOT NULL))")

replace_once('scripts/generate-ten-year-live-bets.py',
"same_day=core.bundles_from_d1(collector,\"race_date=? AND status='finished' AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?)\",[a.date,generated_at])",
"same_day=core.bundles_from_d1(collector,\"race_date=? AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=rt_races.race_id AND rr.finish_position IS NOT NULL)\",[a.date,generated_at])")

replace_once('scripts/audit-canonical-recency-learning.py',
"races=collector.d1_query(\"SELECT race_id AS raceId,race_date AS raceDate,venue,surface,race_no AS raceNo,start_time_utc AS startTimeUtc,status FROM rt_races WHERE race_date=? AND status='finished' AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?) ORDER BY start_time_utc\",[today,cutoff])",
"races=collector.d1_query(\"SELECT race_id AS raceId,race_date AS raceDate,venue,surface,race_no AS raceNo,start_time_utc AS startTimeUtc,status FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=rt_races.race_id AND rr.finish_position IS NOT NULL) ORDER BY start_time_utc\",[today,cutoff])")

print('RECENCY_FIXUP_APPLIED')
