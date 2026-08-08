import gzip
import json
import pickle
import shutil
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads" / "speed-analysis"
OUT = ROOT / "artifacts" / "speed-analysis-input"
OUT.mkdir(parents=True, exist_ok=True)


def first(pattern):
    files = sorted(DOWNLOADS.glob(pattern))
    if not files:
        raise RuntimeError(f"INPUT_NOT_FOUND:{pattern}")
    return files[0]


def tolerant_jsonl_gzip(path):
    handle = gzip.open(path, "rt", encoding="utf-8")
    try:
        while True:
            try:
                line = handle.readline()
            except (EOFError, OSError, zlib.error, gzip.BadGzipFile):
                break
            if not line:
                break
            try:
                record = json.loads(line)
            except Exception:
                continue
            if isinstance(record, dict) and record.get("raceId"):
                yield record
    finally:
        try:
            handle.close()
        except Exception:
            pass


dataset_path = first("completion/**/completion-analysis-dataset.pkl.gz")
context_path = first("context/**/fixed-race-context.json.gz")
with gzip.open(dataset_path, "rb") as f:
    dataset = pickle.load(f)
race_order = [r["raceId"] for r in dataset["races"]]
if len(race_order) != 7695 or len(set(race_order)) != 7695:
    raise RuntimeError(f"FIXED_ARCHIVE_MISMATCH:{len(race_order)}:{len(set(race_order))}")
race_set = set(race_order)

records = {}
source_counts = {"full_partial": 0, "selected_3210": 0, "mobile_76": 0}
for path in sorted(DOWNLOADS.glob("full-*/**/selected-historical-official-odds.jsonl.gz")):
    for rec in tolerant_jsonl_gzip(path):
        records[rec["raceId"]] = rec
        source_counts["full_partial"] += 1
for path in sorted(DOWNLOADS.glob("selected-*/**/selected-historical-official-odds.jsonl.gz")):
    for rec in tolerant_jsonl_gzip(path):
        records.setdefault(rec["raceId"], rec)
        source_counts["selected_3210"] += 1
mobile_path = first("mobile/**/all-mobile-full-retry.jsonl.gz")
mobile_ids = set()
for rec in tolerant_jsonl_gzip(mobile_path):
    records[rec["raceId"]] = rec
    mobile_ids.add(rec["raceId"])
    source_counts["mobile_76"] += 1
if len(mobile_ids) != 76:
    raise RuntimeError(f"MOBILE_RETRY_COUNT_MISMATCH:{len(mobile_ids)}")
extra = sorted(set(records) - race_set)
if extra:
    raise RuntimeError(f"OFFICIAL_ODDS_EXTRA_RACES:{len(extra)}")
missing = [rid for rid in race_order if rid not in records]

# Persist every safely recovered complete record, even when cancelled gzip shards are truncated.
with gzip.open(OUT / "salvaged-official-odds.jsonl.gz", "wt", encoding="utf-8", compresslevel=3) as f:
    for rid in race_order:
        if rid in records:
            f.write(json.dumps(records[rid], ensure_ascii=False, separators=(",", ":")) + "\n")
(OUT / "missing-race-ids.json").write_text(
    json.dumps({"count": len(missing), "raceIds": missing}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
shutil.copy2(dataset_path, OUT / "completion-analysis-dataset.pkl.gz")
shutil.copy2(context_path, OUT / "fixed-race-context.json.gz")
meta = {
    "fixedArchiveRaces": len(race_order), "recoveredOddsRaces": len(records), "missingOddsRaces": len(missing),
    "mobileRetryRaces": len(mobile_ids), "sourceLineCounts": source_counts,
    "syntheticOddsUsed": False, "estimatedOddsUsed": False, "outcomeBasedRaceFiltering": False,
    "missingExamples": missing[:30],
    "sourceRuns": {"completionDataset":31230407200,"fixedRaceContext":31242369738,
                   "allArchivePartialOdds":31239730632,"selected3210Odds":31237880023,"mobileFull76":31241615354}
}
(OUT / "salvage-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False), flush=True)
