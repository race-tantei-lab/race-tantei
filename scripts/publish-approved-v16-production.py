import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "scripts" / "publish-official-odds-roi200-production.py"
APPROVED_POLICY = ROOT / "scripts" / "final-course-policy.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load("approved_v16_official_odds_runner", BASE_SCRIPT)
runner.policy = load("approved_v16_final_policy", APPROVED_POLICY)

required = (
    "MODEL_VERSION",
    "OFFICIAL_ODDS_SOURCE",
    "COURSE_TARGET_STAKES",
    "DEFAULT_CALIBRATION",
    "selected_race_ids",
    "build_bets",
)
for name in required:
    if not hasattr(runner.policy, name):
        raise RuntimeError(f"APPROVED_POLICY_INTERFACE_MISSING:{name}")

if runner.policy.MODEL_VERSION != "v16":
    raise RuntimeError(f"APPROVED_POLICY_VERSION_INVALID:{runner.policy.MODEL_VERSION}")
if runner.policy.OFFICIAL_ODDS_SOURCE != "jra_official":
    raise RuntimeError("APPROVED_POLICY_OFFICIAL_ODDS_SOURCE_INVALID")


if __name__ == "__main__":
    runner.main()
