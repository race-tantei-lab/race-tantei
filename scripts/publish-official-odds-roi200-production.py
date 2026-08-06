import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "publish-nonlinear-v4-production.py"
POLICY_PATH = ROOT / "scripts" / "official-odds-roi200-policy.py"
CALIBRATION_PATH = ROOT / "config" / "official-odds-calibration.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("official_odds_roi200_base", BASE_PATH)
policy = load_module("official_odds_roi200_policy", POLICY_PATH)


def ensure_schema():
    statements = [
        """
        CREATE TABLE IF NOT EXISTS rt_official_odds_snapshots (
          race_id TEXT NOT NULL, bet_type TEXT NOT NULL, combination TEXT NOT NULL,
          odds_min REAL NOT NULL, odds_max REAL NOT NULL, captured_at_utc TEXT NOT NULL,
          race_start_time_utc TEXT, seconds_to_start INTEGER, source_url TEXT NOT NULL,
          source_cname TEXT NOT NULL, source_hash TEXT NOT NULL,
          odds_source TEXT NOT NULL DEFAULT 'jra_official', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, bet_type, combination, captured_at_utc)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rt_official_odds_latest (
          race_id TEXT NOT NULL, bet_type TEXT NOT NULL, combination TEXT NOT NULL,
          odds_min REAL NOT NULL, odds_max REAL NOT NULL, captured_at_utc TEXT NOT NULL,
          race_start_time_utc TEXT, seconds_to_start INTEGER, source_url TEXT NOT NULL,
          source_cname TEXT NOT NULL, source_hash TEXT NOT NULL,
          odds_source TEXT NOT NULL DEFAULT 'jra_official', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, bet_type, combination)
        )
        """,
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
        """,
    ]
    for statement in statements:
        base.sql(statement)
    columns = {row["name"] for row in base.sql("PRAGMA table_info(rt_bets)")}
    if "official_odds" not in columns:
        base.sql("ALTER TABLE rt_bets ADD COLUMN official_odds REAL")
    if "odds_source" not in columns:
        base.sql("ALTER TABLE rt_bets ADD COLUMN odds_source TEXT")


def calibration_config():
    if not CALIBRATION_PATH.exists():
        return dict(policy.DEFAULT_CALIBRATION)
    raw = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    if raw.get("approved") is not True:
        return dict(policy.DEFAULT_CALIBRATION)
    values = raw.get("calibrationFactors")
    if not isinstance(values, dict):
        return dict(policy.DEFAULT_CALIBRATION)
    result = dict(policy.DEFAULT_CALIBRATION)
    for bet_type in result:
        if bet_type in values:
            result[bet_type] = max(0.20, min(1.00, float(values[bet_type])))
    return result


def official_rows():
    return base.sql(
        """
        SELECT race_id raceId, bet_type betType, combination,
               odds_min oddsMin, captured_at_utc capturedAtUtc,
               seconds_to_start secondsToStart
        FROM rt_official_odds_latest
        WHERE odds_source='jra_official'
          AND (seconds_to_start IS NULL OR seconds_to_start >= 0)
        ORDER BY race_id, bet_type, combination
        """
    )


def attach_official_odds(races):
    rows_by_race = defaultdict(list)
    for row in official_rows():
        rows_by_race[row["raceId"]].append(row)
    calibration = calibration_config()
    for race in races:
        rows = rows_by_race.get(race["raceId"], [])
        odds = {
            f'{row["betType"]}:{row["combination"]}': float(row["oddsMin"])
            for row in rows
            if float(row.get("oddsMin") or 0) > 1.0
        }
        if not odds:
            race["oddsSource"] = None
            race["officialOdds"] = {}
            race["officialOddsCapturedAt"] = None
            continue
        race["oddsSource"] = policy.OFFICIAL_ODDS_SOURCE
        race["officialOdds"] = odds
        race["officialOddsCapturedAt"] = max(str(row["capturedAtUtc"]) for row in rows)
        race["officialOddsCalibration"] = calibration
    return races


def persist_candidates(races):
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
                    row["projectedRoiPct"], row["predictedRankSum"],
                    row["includesModelFirst"],
                ],
            )
            written += 1
    return written


def forbid_synthetic_odds(*_args, **_kwargs):
    raise RuntimeError("SYNTHETIC_ODDS_FORBIDDEN:ONLY_JRA_OFFICIAL_ODDS_MAY_BE_USED")


def configure():
    ensure_schema()
    original_attach = base.attach_predictions

    def attach_with_official_odds(model, races):
        predicted = original_attach(model, races)
        attach_official_odds(predicted)
        persist_candidates(predicted)
        return predicted

    base.MODEL_VERSION = policy.MODEL_VERSION
    base.COURSE_BUDGETS = dict(policy.COURSE_TARGET_STAKES)
    base.attach_predictions = attach_with_official_odds
    base.selected_race_ids = policy.selected_race_ids
    base.build_bets = policy.build_bets
    base.assumed_odds = forbid_synthetic_odds


def mark_bets_as_official():
    base.sql(
        """
        UPDATE rt_bets
        SET official_odds=assumed_odds, odds_source='jra_official'
        WHERE prediction_id IN (
          SELECT id FROM rt_predictions WHERE model_version=?
        )
          AND EXISTS (
            SELECT 1 FROM rt_official_odds_latest o
            WHERE o.race_id=rt_bets.race_id
              AND o.bet_type=CASE
                WHEN instr(rt_bets.bet_type, '｜') > 0 THEN substr(rt_bets.bet_type, instr(rt_bets.bet_type, '｜') + 1)
                ELSE rt_bets.bet_type
              END
              AND o.combination=rt_bets.combination
              AND o.odds_source='jra_official'
          )
        """,
        [policy.MODEL_VERSION],
    )
    invalid = base.sql(
        """
        SELECT COUNT(*) count
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        WHERE p.model_version=?
          AND (b.odds_source!='jra_official' OR b.official_odds IS NULL)
        """,
        [policy.MODEL_VERSION],
    )
    count = int(invalid[0]["count"]) if invalid else 0
    if count:
        raise RuntimeError(f"NON_OFFICIAL_PRODUCTION_BETS_FOUND:{count}")


def main():
    configure()
    base.main()
    mark_bets_as_official()


if __name__ == "__main__":
    main()
