import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "finished-race-source-columns-probe.json"

DATES = ("2024-05-04", "2025-01-05", "2026-08-02")


def load_collector():
    spec = importlib.util.spec_from_file_location("finished_race_source_probe_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    columns = collector.d1_query("PRAGMA table_info(rt_races)")
    names = [str(row.get("name")) for row in columns]
    url_like = [name for name in names if any(token in name.lower() for token in ("url", "source", "jra", "entry"))]
    identity_like = [name for name in names if any(token in name.lower() for token in ("race_id", "race_date", "venue", "race_no", "status"))]

    safe_columns = []
    for name in [*identity_like, *url_like]:
        if name and name not in safe_columns:
            safe_columns.append(name)
    select = ", ".join(f'"{name}"' for name in safe_columns) if safe_columns else "*"

    samples = {}
    for race_date in DATES:
        samples[race_date] = collector.d1_query(
            f"SELECT {select} FROM rt_races WHERE race_date = ? AND status = 'finished' ORDER BY venue, race_no LIMIT 5",
            [race_date],
        )

    report = {
        "table": "rt_races",
        "columns": names,
        "urlOrSourceColumns": url_like,
        "identityColumns": identity_like,
        "samples": samples,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "columnCount": len(names),
        "urlOrSourceColumns": url_like,
        "sampleCounts": {key: len(value) for key, value in samples.items()},
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
