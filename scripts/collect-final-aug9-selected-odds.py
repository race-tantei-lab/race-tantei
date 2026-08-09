import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "analysis-results" / "final-aug9-selection.json"
COLLECTOR = ROOT / "scripts" / "collect-jra-official-odds.py"

spec = importlib.util.spec_from_file_location("race_tantei_official_odds", COLLECTOR)
if spec is None or spec.loader is None:
    raise RuntimeError("COLLECTOR_LOAD_FAILED")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

selection = json.loads(SELECTION.read_text(encoding="utf-8"))
race_ids = [str(row["raceId"]) for row in selection.get("selected", [])]
if len(race_ids) != 15 or len(set(race_ids)) != 15:
    raise RuntimeError(f"INVALID_FIXED_SELECTION:{len(race_ids)}")


def fixed_races():
    placeholders = ",".join("?" for _ in race_ids)
    return mod.d1_query(
        f"""
        SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo,
               start_time_utc AS startTimeUtc, entry_url AS entryUrl
        FROM rt_races
        WHERE race_id IN ({placeholders})
        ORDER BY race_date, venue, race_no
        """,
        race_ids,
    )


mod.upcoming_races = fixed_races
mod.MAX_PAGES = 1200
mod.REQUEST_PAUSE_SECONDS = 0.08
mod.main()
