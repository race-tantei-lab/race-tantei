import gzip
import importlib.util
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4_PATH = ROOT / "scripts" / "train-nonlinear-market-blend-v4.py"
OUTPUT = ROOT / "artifacts" / "fixed-categorical-context.pkl.gz"
META = ROOT / "artifacts" / "fixed-categorical-context-meta.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v4 = load_module("categorical_export_v4", V4_PATH)
v4.HOLDOUT_END = "2026-08-31"

rows = []
for start, end in v4.month_ranges(v4.CONTEXT_START, v4.HOLDOUT_END):
    rows.extend(
        v4.sql(
            """
            SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
                   r.race_name raceName,r.conditions,r.surface,r.distance_m distanceM,
                   r.direction,r.weather,r.track_condition trackCondition,
                   rr.horse_no horseNo,rr.horse_name horseName,rr.jockey,rr.trainer,rr.stable,
                   rr.sex_age sexAge,rr.frame_no frameNo,rr.assigned_weight assignedWeight,
                   rr.horse_weight horseWeight,rr.weight_change weightChange,
                   rr.win_odds winOdds,rr.popularity,rr.runner_status runnerStatus,
                   rs.finish_position finishPosition,rs.final3f
            FROM rt_races r
            JOIN rt_runners rr ON rr.race_id=r.race_id
            LEFT JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=rr.horse_no
            WHERE r.race_date>=? AND r.race_date<? AND r.status='finished'
            ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
            """,
            [start, end],
        )
    )

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(OUTPUT, "wb", compresslevel=5) as handle:
    pickle.dump({"schema": 1, "rows": rows}, handle, protocol=5)

meta = {
    "rows": len(rows),
    "races": len({(str(r.get('raceDate')), str(r.get('venue')), int(r.get('raceNo') or 0)) for r in rows}),
    "start": min(str(r.get("raceDate")) for r in rows),
    "end": max(str(r.get("raceDate")) for r in rows),
    "nonEmptySurfaceRows": sum(bool(r.get("surface")) for r in rows),
    "nonZeroDistanceRows": sum(int(r.get("distanceM") or 0) > 0 for r in rows),
    "nonEmptyJockeyRows": sum(bool(r.get("jockey")) for r in rows),
    "nonEmptyTrainerRows": sum(bool(r.get("trainer")) for r in rows),
    "bytes": OUTPUT.stat().st_size,
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
