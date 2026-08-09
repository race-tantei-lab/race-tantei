import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "generate-final-live-bets.py"
spec = importlib.util.spec_from_file_location("final_live_snapshot_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("FINAL_LIVE_BASE_IMPORT_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def arg_value(name: str, default: str) -> str:
    try:
        i = sys.argv.index(name)
        return sys.argv[i + 1]
    except (ValueError, IndexError):
        return default

selection_path = pathlib.Path(arg_value("--selection", "analysis-results/final-aug9-selection.json"))
if not selection_path.is_absolute():
    selection_path = ROOT / selection_path
selection = json.loads(selection_path.read_text(encoding="utf-8"))
SNAPSHOT = {str(r["raceId"]): r for r in selection.get("selected", [])}
if len(SNAPSHOT) != 15:
    raise RuntimeError(f"SELECTION_SNAPSHOT_INVALID:{len(SNAPSHOT)}")

_original_load_collector = base.load_collector


def load_collector_with_snapshot(repo):
    collector = _original_load_collector(repo)
    original_query = collector.d1_query

    def d1_query(sql, params=None):
        rows = original_query(sql, params)
        normalized = " ".join(str(sql).split())
        structural_query = (
            "race_name AS raceName" in normalized
            and "distance_m AS distanceM" in normalized
            and "FROM rt_races WHERE race_id IN" in normalized
        )
        if not structural_query:
            return rows
        fixed = []
        for row in rows:
            rid = str(row.get("raceId", ""))
            snap = SNAPSHOT.get(rid)
            if not snap:
                fixed.append(row)
                continue
            merged = dict(row)
            for key in ("raceName", "conditions", "surface", "distanceM", "direction", "startTimeJst"):
                if key in snap:
                    merged[key] = snap.get(key)
            fixed.append(merged)
        return fixed

    collector.d1_query = d1_query
    return collector


base.load_collector = load_collector_with_snapshot

if __name__ == "__main__":
    base.main()
