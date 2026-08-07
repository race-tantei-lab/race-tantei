import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-regime-online-search.py"

spec = importlib.util.spec_from_file_location("rich_form_regime", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("RICH_FORM_REGIME_LOAD_FAILED")
search = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = search
spec.loader.exec_module(search)

base_form_signal = search.form_signal
base_regime_keys = search.regime_keys


def rich_form_signal(runner):
    # Enriched chronological feature layout:
    # 73-75 surface stats, 76-78 distance stats, 79-81 venue stats,
    # 82-84 horse×jockey stats, 85-87 jockey×trainer stats, 88+ race context.
    return (
        base_form_signal(runner)
        + 0.55 * search.feature(runner, 73)
        + 0.85 * search.feature(runner, 74)
        + 0.65 * search.feature(runner, 76)
        + 0.95 * search.feature(runner, 77)
        + 0.45 * search.feature(runner, 79)
        + 0.70 * search.feature(runner, 80)
        + 0.70 * search.feature(runner, 82)
        + 0.90 * search.feature(runner, 83)
        + 0.55 * search.feature(runner, 85)
        + 0.75 * search.feature(runner, 86)
        + 0.20 * search.feature(runner, 88)
    )


def rich_regime_keys(race):
    keys = base_regime_keys(race)
    runners = race.get("runners", [])
    top = runners[0] if runners else {}
    second = runners[1] if len(runners) > 1 else {}
    keys["relationships"] = (
        "relationships",
        search.bucket(search.feature(top, 83), (0.15, 0.25, 0.40)),
        search.bucket(search.feature(top, 86), (0.15, 0.25, 0.40)),
        search.bucket(search.feature(second, 83), (0.15, 0.25, 0.40)),
    )
    keys["adaptation"] = (
        "adaptation",
        search.bucket(search.feature(top, 74), (0.15, 0.25, 0.40)),
        search.bucket(search.feature(top, 77), (0.15, 0.25, 0.40)),
        search.bucket(search.feature(top, 80), (0.15, 0.25, 0.40)),
    )
    return keys


search.form_signal = rich_form_signal
search.regime_keys = rich_regime_keys
search.EXPLORATION_ID = "rich-form-regime"
search.OUTPUT = ROOT / "analysis-results" / "exploration-rich-form-regime.json"
search.RANK_MODES = ("balanced_form", "form_heavy")
search.PROFILE_CONFIGS = {
    "rich-context": {
        "shrink": 75.0,
        "probPower": 0.25,
        "tailBias": 0.06,
        "weights": {
            "global": 0.14,
            "surfaceDistance": 0.14,
            "venue": 0.08,
            "marketShape": 0.15,
            "form": 0.16,
            "mixed": 0.10,
            "relationships": 0.11,
            "adaptation": 0.12,
        },
    },
    "rich-form": {
        "shrink": 55.0,
        "probPower": 0.32,
        "tailBias": 0.10,
        "weights": {
            "global": 0.10,
            "surfaceDistance": 0.12,
            "venue": 0.06,
            "marketShape": 0.11,
            "form": 0.20,
            "mixed": 0.10,
            "relationships": 0.14,
            "adaptation": 0.17,
        },
    },
    "rich-tail": {
        "shrink": 95.0,
        "probPower": 0.16,
        "tailBias": 0.20,
        "weights": {
            "global": 0.18,
            "surfaceDistance": 0.13,
            "venue": 0.08,
            "marketShape": 0.15,
            "form": 0.13,
            "mixed": 0.09,
            "relationships": 0.11,
            "adaptation": 0.13,
        },
    },
}

search.main()
