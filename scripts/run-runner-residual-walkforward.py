import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "search-runner-residual-walkforward.py"

spec = importlib.util.spec_from_file_location("runner_residual_search", TARGET)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SEED = 20260808
# Preserve the full parameter ranges but evaluate a deterministic evenly spaced
# subset so the walk-forward search finishes well inside the Actions timeout.
module.FAMILIES = module.FAMILIES[::6]
module.main()
