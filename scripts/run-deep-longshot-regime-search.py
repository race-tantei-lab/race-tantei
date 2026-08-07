import importlib.util
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-regime-online-search.py"

spec = importlib.util.spec_from_file_location("deep_longshot_regime", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("DEEP_LONGSHOT_REGIME_LOAD_FAILED")
search = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = search
spec.loader.exec_module(search)


def deep_catalog():
    rows = []
    for rank in range(1, 15):
        rows.append((f"S{rank}", "単勝", (rank,)))
    for first, second in itertools.combinations(range(1, 11), 2):
        rows.append((f"W{first}_{second}", "ワイド", (first, second)))
        rows.append((f"Q{first}_{second}", "馬連", (first, second)))
    for first, second in itertools.permutations(range(1, 9), 2):
        rows.append((f"E{first}_{second}", "馬単", (first, second)))
    for ranks in itertools.combinations(range(1, 11), 3):
        rows.append(("T" + "_".join(map(str, ranks)), "3連複", ranks))
    for ranks in itertools.permutations(range(1, 9), 3):
        rows.append(("X" + "_".join(map(str, ranks)), "3連単", ranks))
    return rows


primitives = deep_catalog()
search.ctx.PRIMITIVES = primitives
search.ctx.base_analysis.base.PRIMITIVES = primitives
search.ctx.base_analysis.base.PRIMITIVE_INDEX = {row[0]: index for index, row in enumerate(primitives)}
search.ctx.base_analysis.base.TYPE_BY_INDEX = {index: row[1] for index, row in enumerate(primitives)}
search.EXPLORATION_ID = "deep-longshot-regime"
search.OUTPUT = ROOT / "analysis-results" / "exploration-deep-longshot-regime.json"
search.RANK_MODES = ("balanced_form", "form_heavy")
search.PROFILE_CONFIGS = {
    key: value
    for key, value in search.PROFILE_CONFIGS.items()
    if key in {"context", "form", "tail"}
}

search.main()
