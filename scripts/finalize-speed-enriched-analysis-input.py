import gzip
import json
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "speed-analysis-input"
SALVAGE = OUT / "salvaged-official-odds.jsonl.gz"
DATA = OUT / "completion-analysis-dataset.pkl.gz"
FINAL = OUT / "all7695-official-odds.jsonl.gz"
REPAIR_ROOT = ROOT / "artifacts" / "repair-shards"

with gzip.open(DATA, "rb") as f:
    dataset = pickle.load(f)
race_order = [x["raceId"] for x in dataset["races"]]
if len(race_order) != 7695 or len(set(race_order)) != 7695:
    raise RuntimeError("FIXED_ARCHIVE_INVALID")

records = {}
def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            records[rec["raceId"]] = rec

read(SALVAGE)
salvaged_count = len(records)
repair_paths = sorted(REPAIR_ROOT.glob("**/selected-historical-official-odds.jsonl.gz"))
for path in repair_paths:
    read(path)
missing = [rid for rid in race_order if rid not in records]
extra = sorted(set(records) - set(race_order))
if missing or extra:
    raise RuntimeError(f"FINAL_ODDS_ARCHIVE_MISMATCH:missing={len(missing)}:extra={len(extra)}:examples={missing[:20]}")

markets = ["win", "umaren", "wide", "umatan", "trio", "trifecta"]
expected = {k: 0 for k in markets}; present = {k: 0 for k in markets}
def valid(v):
    if v is None:
        return 0
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return 1
    return 1
with gzip.open(FINAL, "wt", encoding="utf-8", compresslevel=3) as f:
    for rid in race_order:
        rec = records[rid]
        for k in markets:
            vals = rec.get(k, [])
            expected[k] += len(vals)
            present[k] += sum(valid(x) for x in vals)
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
meta = {
    "races": len(race_order), "uniqueOddsRaces": len(records), "salvagedOddsRaces": salvaged_count,
    "repairRows": len(records) - salvaged_count, "repairArtifacts": len(repair_paths),
    "coveragePct": {k: (100.0 * present[k] / expected[k] if expected[k] else 0.0) for k in markets},
    "syntheticOddsUsed": False, "estimatedOddsUsed": False, "outcomeBasedRaceFiltering": False
}
(OUT / "input-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False), flush=True)
