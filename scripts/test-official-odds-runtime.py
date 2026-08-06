import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("CLOUDFLARE_ACCOUNT_ID", "test")
os.environ.setdefault("CLOUDFLARE_D1_DATABASE_ID", "test")
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "test")
os.environ.setdefault("JRA_ODDS_D1_BATCH_ROWS", "40")

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "collect-jra-official-odds-runtime.py"
spec = importlib.util.spec_from_file_location("official_odds_runtime", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("OFFICIAL_ODDS_RUNTIME_IMPORT_FAILED")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def expect(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def main():
    cname = "pw15oren0101202601051120260808/AA"
    expect(runtime.race_no_from_cname(cname), 11, "race-number")
    expect(
        runtime.parse_page_identity("2026年8月8日 1回札幌5日", cname),
        ("2026-08-08", "札幌", 11),
        "page-identity",
    )
    expect(runtime.base.normalize_combination("馬連", [7, 2]), "2-7", "unordered-combination")
    expect(runtime.base.normalize_combination("馬単", [7, 2]), "7-2", "ordered-combination")

    calls = []
    original = runtime.base.d1_query
    runtime.base.d1_query = lambda sql, params=None: calls.append((sql, params or [])) or []
    try:
        rows = [
            {
                "raceId": "2026-08-08-sapporo-11",
                "betType": "馬連",
                "combination": f"1-{(index % 17) + 2}",
                "oddsMin": 10.0 + index,
                "oddsMax": 10.0 + index,
                "capturedAtUtc": "2026-08-07T00:00:00+00:00",
                "startTimeUtc": "2026-08-08T06:30:00+00:00",
                "secondsToStart": 109800,
                "sourceCname": cname,
                "sourceHash": "a" * 64,
            }
            for index in range(41)
        ]
        runtime.insert_rows(rows)
    finally:
        runtime.base.d1_query = original

    expect(len(calls), 4, "two statements per batch")
    expect(len(calls[0][1]), 40 * 11, "first batch parameter count")
    expect(len(calls[2][1]), 11, "second batch parameter count")
    if "jra_official" not in calls[0][0] or "ON CONFLICT" not in calls[1][0]:
        raise AssertionError("official odds persistence SQL is incomplete")
    print("official odds runtime tests: ok")


if __name__ == "__main__":
    main()
