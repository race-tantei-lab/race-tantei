#!/usr/bin/env python3
import argparse
import importlib.util
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_fetcher():
    path = ROOT / "scripts" / "research-fetch-demanded-official-odds.py"
    spec = importlib.util.spec_from_file_location("research_demanded_odds_fetcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", required=True)
    ap.add_argument("--meta-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--passes", type=int, default=4)
    args = ap.parse_args()

    demand_rows = {}
    with (ROOT / args.demand).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            rid = str(row.get("raceId") or "")
            if rid:
                demand_rows[rid] = row

    meta_paths = sorted((ROOT / args.meta_dir).glob("research-demanded-odds-*-meta.json"))
    if len(meta_paths) != 11:
        raise RuntimeError(f"ODDS_META_COUNT_INVALID:{len(meta_paths)}")

    initial_failures = {}
    completed_base = 0
    for path in meta_paths:
        meta = json.loads(path.read_text(encoding="utf-8"))
        completed_base += int(meta.get("completedRaces") or 0)
        for failure in meta.get("failures") or []:
            rid = str(failure.get("raceId") or "")
            if rid:
                initial_failures[rid] = failure

    targets = []
    missing_manifest = []
    for rid in sorted(initial_failures):
        row = demand_rows.get(rid)
        if row is None:
            missing_manifest.append(rid)
        else:
            targets.append(row)
    if missing_manifest:
        raise RuntimeError(f"FAILED_RACE_NOT_IN_DEMAND:{missing_manifest[:20]}:count={len(missing_manifest)}")

    fetcher = load_fetcher()
    repaired = {}
    last_errors = {rid: str(initial_failures[rid].get("error") or "") for rid in initial_failures}
    remaining = {str(row["raceId"]): row for row in targets}
    pass_summaries = []

    max_passes = max(1, min(8, args.passes))
    for pass_no in range(1, max_passes + 1):
        if not remaining:
            break
        attempted = len(remaining)
        recovered_this_pass = 0
        next_remaining = {}
        for index, rid in enumerate(sorted(remaining), 1):
            row = remaining[rid]
            try:
                result = fetcher.fetch_race(row)
                repaired[rid] = result
                recovered_this_pass += 1
            except Exception as exc:
                last_errors[rid] = f"{type(exc).__name__}:{exc}"
                next_remaining[rid] = row
            if index % 10 == 0 or index == attempted:
                print(json.dumps({
                    "pass": pass_no,
                    "processed": index,
                    "attempted": attempted,
                    "recoveredTotal": len(repaired),
                    "remainingThisPass": len(next_remaining),
                }, ensure_ascii=False), flush=True)
            time.sleep(0.10 + random.random() * 0.12)
        pass_summaries.append({
            "pass": pass_no,
            "attempted": attempted,
            "recovered": recovered_this_pass,
            "remaining": len(next_remaining),
        })
        remaining = next_remaining
        if remaining and pass_no < max_passes:
            time.sleep(min(20.0, 2.5 * pass_no) + random.random())

    out_path = ROOT / args.out
    meta_path = ROOT / args.meta
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(repaired.values(), key=lambda row: (row.get("raceDate"), row.get("venue"), int(row.get("raceNo") or 0), row.get("raceId")))
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")

    unresolved = [
        {
            "raceId": rid,
            "raceDate": remaining[rid].get("raceDate"),
            "venue": remaining[rid].get("venue"),
            "raceNo": remaining[rid].get("raceNo"),
            "requiredMarkets": remaining[rid].get("requiredMarkets"),
            "resultUrl": remaining[rid].get("resultUrl"),
            "error": last_errors.get(rid),
        }
        for rid in sorted(remaining)
    ]
    meta = {
        "purpose": "research_only_targeted_demanded_odds_repair",
        "baseCompletedRaces": completed_base,
        "initialFailureCount": len(initial_failures),
        "repairTargetCount": len(targets),
        "repairedCount": len(repaired),
        "unresolvedCount": len(unresolved),
        "unresolved": unresolved,
        "passes": pass_summaries,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    if unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
