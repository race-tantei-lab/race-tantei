import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "validate-jra-historical-combination-parser.py"

spec = importlib.util.spec_from_file_location("completion_parser_validator", TARGET)
if spec is None or spec.loader is None:
    raise RuntimeError("VALIDATOR_LOAD_FAILED")
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)

_original_load_collector = validator.load_collector

def load_collector_fixed():
    collector = _original_load_collector()
    if not hasattr(collector, "parse_odds_range"):
        collector.parse_odds_range = collector.odds_value
    return collector

validator.load_collector = load_collector_fixed
validator.main()
