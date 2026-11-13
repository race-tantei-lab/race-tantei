#!/usr/bin/env python3
"""Read-only D1 audit of August-November archived odds availability."""
import importlib.util,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location("d1ro",R/"scripts/postaug-support-aug-nov-frozen-policy-recheck.py")
m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
def query(sql):
 try:
  return m.d1_query(sql,[])
 except Exception as e:
  return {"error":str(e)[:450]}
def main():
 for name in ("rt_official_odds_latest","rt_official_odds_snapshots","rt_runners"):
  print("D1_ODDS_SCHEMA",json.dumps({"table":name,"columns":query(f"PRAGMA table_info({name})")},ensure_ascii=False),flush=True)
 for tab in ("rt_official_odds_latest","rt_official_odds_snapshots"):
  for month in ("2026-08","2026-09","2026-10","2026-11"):
   print("D1_ODDS_COVERAGE",json.dumps({"table":tab,"month":month,
     "rows":query(f"SELECT COUNT(*) n,COUNT(DISTINCT race_id) races FROM {tab} WHERE race_id >= '{month}-' AND race_id < '{month}-~'"),
     "win":query(f"SELECT COUNT(*) n,COUNT(DISTINCT race_id) races FROM {tab} WHERE race_id >= '{month}-' AND race_id < '{month}-~' AND bet_type='単勝'")},ensure_ascii=False),flush=True)
 for month in ("2026-08","2026-09","2026-10","2026-11"):
  print("D1_RUNNER_WIN_ODDS_COVERAGE",json.dumps({"month":month,"rows":query(
    f"SELECT COUNT(*) total, SUM(CASE WHEN win_odds IS NOT NULL AND win_odds>=1 THEN 1 ELSE 0 END) quoted, COUNT(DISTINCT race_id) races FROM rt_runners WHERE race_id >= '{month}-' AND race_id < '{month}-~'")},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
