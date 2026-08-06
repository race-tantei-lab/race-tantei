import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "scripts" / "generate-official-odds-roi200-shadow.py"
POLICY_PATH = ROOT / "scripts" / "official-odds-roi200-policy-v2.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load("official_odds_shadow_runner_v2", BASE_SCRIPT)
runner.policy = load("official_odds_policy_runtime_v2", POLICY_PATH)

if __name__ == "__main__":
    runner.main()
