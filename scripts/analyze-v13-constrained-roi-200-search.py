import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v14-historical-roi200.py"
spec = importlib.util.spec_from_file_location("v14_historical_roi200", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("V14_MODULE_LOAD_FAILED")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

if not hasattr(module.v7, "month_sequence"):
    module.v7.month_sequence = module.v7.v7.month_sequence

_original_future_predictions = module.future_predictions


def safe_future_predictions(*args, **kwargs):
    try:
        return _original_future_predictions(*args, **kwargs)
    except RuntimeError as error:
        if str(error) != "V14_SELECTED_BELOW_FIVE":
            raise
        return {
            "generated": False,
            "error": "UPCOMING_ENTRIES_BELOW_FIVE_PER_VENUE_DAY",
            "futureRaces": 0,
            "selectedRaces": 0,
            "coverage": [],
            "races": [],
        }


module.future_predictions = safe_future_predictions
module.main()
