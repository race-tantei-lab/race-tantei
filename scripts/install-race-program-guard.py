import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'scripts'/'collect-jra-official-odds.py'
spec=importlib.util.spec_from_file_location('guard_collector',P)
if spec is None or spec.loader is None: raise RuntimeError('COLLECTOR_LOAD_FAILED')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

m.d1_query('DROP TRIGGER IF EXISTS rt_guard_malformed_race_program')
m.d1_query('''
CREATE TRIGGER rt_guard_malformed_race_program
BEFORE UPDATE OF race_name,surface,distance_m,conditions,direction,start_time_jst,start_time_utc ON rt_races
WHEN
  OLD.distance_m IS NOT NULL AND OLD.distance_m > 0
  AND OLD.surface IN ('芝','ダート','障害')
  AND TRIM(COALESCE(OLD.race_name,'')) NOT IN ('','検索ウィンドウ','検索','オッズ','出馬表')
  AND (
    NEW.distance_m IS NULL OR NEW.distance_m <= 0
    OR NEW.surface IS NULL OR NEW.surface NOT IN ('芝','ダート','障害')
    OR TRIM(COALESCE(NEW.race_name,'')) IN ('','検索ウィンドウ','検索','オッズ','出馬表','レース検索')
  )
BEGIN
  SELECT RAISE(IGNORE);
END
''')
rows=m.d1_query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name='rt_guard_malformed_race_program'")
if len(rows)!=1: raise RuntimeError('RACE_PROGRAM_GUARD_NOT_INSTALLED')
print({'installed':True,'trigger':rows[0]['name']})
