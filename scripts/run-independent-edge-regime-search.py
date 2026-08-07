import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATH = ROOT / "scripts" / "analyze-independent-edge-regime-search.py"
BASE_REGIME_PATH = ROOT / "scripts" / "analyze-regime-online-search.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


search = load("independent_edge_search_runner", SEARCH_PATH)
fresh_regime = load("independent_edge_fresh_regime", BASE_REGIME_PATH)


def fixed_edge_regime_keys(race):
    keys = fresh_regime.regime_keys(race)
    runners = race.get("runners", [])
    top = runners[0] if runners else {}
    top_edge = search.number(top.get("edge"), 1.0)
    max_edge = max((search.number(row.get("edge"), 1.0) for row in runners[:8]), default=1.0)
    market_rank = int(search.number(top.get("popularity"), 18.0))
    disagreement = sum(
        abs(search.number(row.get("probability")) - search.number(row.get("market")))
        for row in runners
    )
    surface = str(race.get("surface") or "unknown")
    distance = fresh_regime.distance_band(race.get("distanceM"))
    keys["edge"] = (
        "edge",
        search.edge_bucket(top_edge),
        search.edge_bucket(max_edge),
        search.disagreement_bucket(disagreement),
        fresh_regime.bucket(market_rank, (2, 4, 7, 11)),
    )
    keys["edgeContext"] = (
        "edgeContext",
        surface,
        distance,
        search.edge_bucket(max_edge),
        fresh_regime.bucket(market_rank, (2, 4, 7, 11)),
    )
    return keys


search.regime.regime_keys = fixed_edge_regime_keys
search.main()
