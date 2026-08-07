import gzip
import importlib.util
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V7_PATH = ROOT / "scripts" / "analyze-v7-enriched-ranking.py"
OUTPUT = ROOT / "artifacts" / "completion-search-dataset.pkl.gz"
META = ROOT / "artifacts" / "completion-search-dataset-meta.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v7 = load_module("completion_export_v7", V7_PATH)
v4 = v7.v4
v4.HOLDOUT_END = "2026-08-31"

rows, payouts = v4.load_data()
base_races = v4.build_dataset(rows, payouts)
extra_rows = v7.load_extra_rows()
races = v7.enrich_races(base_races, extra_rows)
races.sort(key=lambda r: (r["raceDate"], r["venue"], int(r["raceNo"])))

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "schema": 1,
    "source": "existing Cloudflare D1 finished-race archive; no new ingestion",
    "races": races,
}
with gzip.open(OUTPUT, "wb", compresslevel=5) as handle:
    pickle.dump(payload, handle, protocol=5)

feature_lengths = sorted({len(runner["features"]) for race in races for runner in race["runners"]})
meta = {
    "races": len(races),
    "start": min(r["raceDate"] for r in races),
    "end": max(r["raceDate"] for r in races),
    "runners": sum(len(r["runners"]) for r in races),
    "featureLengths": feature_lengths,
    "bytes": OUTPUT.stat().st_size,
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
