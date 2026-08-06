import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

from production_base_loader import load_production_base

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "publish-nonlinear-v4-production.py"
POLICY_PATH = ROOT / "scripts" / "official-odds-roi200-policy.py"
OUTPUT = ROOT / "official-odds-roi200-shadow.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_production_base("official_odds_shadow_base", BASE_PATH)
policy = load_module("official_odds_shadow_policy", POLICY_PATH)


def ensure_schema():
    base.sql(
        """
        CREATE TABLE IF NOT EXISTS rt_official_value_candidates (
          race_id TEXT NOT NULL, model_version TEXT NOT NULL, captured_at_utc TEXT NOT NULL,
          bet_type TEXT NOT NULL, combination TEXT NOT NULL, model_probability REAL NOT NULL,
          conservative_probability REAL NOT NULL, official_odds REAL NOT NULL,
          projected_roi_pct REAL NOT NULL, predicted_rank_sum INTEGER NOT NULL,
          includes_model_first INTEGER NOT NULL, odds_source TEXT NOT NULL DEFAULT 'jra_official',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, model_version, captured_at_utc, bet_type, combination)
        )
        """
    )


def attach_official_odds(races):
    rows = base.sql(
        """
        SELECT race_id raceId, bet_type betType, combination,
               odds_min oddsMin, captured_at_utc capturedAtUtc
        FROM rt_official_odds_latest
        WHERE odds_source='jra_official'
          AND (seconds_to_start IS NULL OR seconds_to_start >= 0)
        ORDER BY race_id, bet_type, combination
        """
    )
    by_race = defaultdict(list)
    for row in rows:
        by_race[row["raceId"]].append(row)
    for race in races:
        values = by_race.get(race["raceId"], [])
        if not values:
            race["oddsSource"] = None
            race["officialOdds"] = {}
            race["officialOddsCapturedAt"] = None
            continue
        race["oddsSource"] = policy.OFFICIAL_ODDS_SOURCE
        race["officialOdds"] = {
            f'{row["betType"]}:{row["combination"]}': float(row["oddsMin"])
            for row in values
            if float(row.get("oddsMin") or 0) > 1.0
        }
        race["officialOddsCapturedAt"] = max(str(row["capturedAtUtc"]) for row in values)
    return races


def persist(races):
    sql = """
      INSERT OR REPLACE INTO rt_official_value_candidates (
        race_id, model_version, captured_at_utc, bet_type, combination,
        model_probability, conservative_probability, official_odds,
        projected_roi_pct, predicted_rank_sum, includes_model_first, odds_source, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'jra_official', CURRENT_TIMESTAMP)
    """
    written = 0
    for race in races:
        captured_at = race.get("officialOddsCapturedAt")
        if not captured_at:
            continue
        for row in policy.candidate_audit_rows(race):
            base.sql(
                sql,
                [
                    row["raceId"], policy.MODEL_VERSION, captured_at,
                    row["betType"], row["combination"], row["modelProbability"],
                    row["conservativeProbability"], row["officialOdds"],
                    row["projectedRoiPct"], row["predictedRankSum"], row["includesModelFirst"],
                ],
            )
            written += 1
    return written


def main():
    ensure_schema()
    finished_rows = base.load_finished_rows()
    training_races, stores = base.build_training(finished_rows)
    model = base.fit_model(training_races)
    future_rows = base.load_future_rows()
    future_races = base.build_future(future_rows, stores)
    predicted = base.attach_predictions(model, future_races)
    attach_official_odds(predicted)
    written = persist(predicted)
    selected = policy.selected_race_ids(predicted)
    grouped = defaultdict(lambda: {"available": 0, "qualified": 0, "selected": 0})
    course_projected = defaultdict(list)
    for race in predicted:
        key = f'{race["raceDate"]}|{race["venue"]}'
        if race.get("officialOdds"):
            grouped[key]["available"] += 1
        summary = race.get("officialOddsRoi200Summary") or policy.plans_for_race(race)
        if summary and summary["allCoursesPass"]:
            grouped[key]["qualified"] += 1
            for course, plan in summary["plans"].items():
                course_projected[course].append(plan["projectedRoiPct"])
        if race["raceId"] in selected:
            grouped[key]["selected"] += 1
    report = {
        "modelVersion": policy.MODEL_VERSION,
        "productionChanged": False,
        "oddsSource": "jra_official",
        "targetRoiPct": policy.TARGET_ROI_PCT,
        "minimumRacesPerVenueDay": policy.MINIMUM_RACES_PER_VENUE_DAY,
        "trainingRaces": len(training_races),
        "futureRaces": len(predicted),
        "candidateRowsWritten": written,
        "selectedRaceCount": len(selected),
        "groups": dict(sorted(grouped.items())),
        "courseProjectedRoi": {
            course: {
                "qualifiedRaces": len(values),
                "minimumPct": min(values) if values else None,
                "meanPct": sum(values) / len(values) if values else None,
                "maximumPct": max(values) if values else None,
            }
            for course, values in course_projected.items()
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
