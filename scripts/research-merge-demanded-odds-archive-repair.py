#!/usr/bin/env python3
import argparse
import gzip
import itertools
import json
from pathlib import Path

MARKETS = ("win", "umaren", "wide", "umatan", "trio", "trifecta")
ARCHIVE_ARTIFACT_ID = 9018047154


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def combos(horses, market):
    if market == "win":
        return [(h,) for h in horses]
    if market in {"umaren", "wide"}:
        return list(itertools.combinations(horses, 2))
    if market == "umatan":
        return [(a, b) for a in horses for b in horses if a != b]
    if market == "trio":
        return list(itertools.combinations(horses, 3))
    if market == "trifecta":
        return [(a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3]
    raise KeyError(market)


def key_for(market, combo):
    if market == "win":
        return str(combo[0])
    return "-".join(str(x) for x in combo)


def convert_archive_row(rec, failure):
    rid = str(failure["raceId"])
    if str(rec.get("raceId")) != rid:
        raise RuntimeError(f"ARCHIVE_RACE_ID_MISMATCH:{rid}:{rec.get('raceId')}")
    for field in ("raceDate", "venue", "raceNo"):
        if str(rec.get(field)) != str(failure.get(field)):
            raise RuntimeError(f"ARCHIVE_IDENTITY_MISMATCH:{rid}:{field}:{rec.get(field)}:{failure.get(field)}")

    horses = [int(x) for x in rec.get("horses") or []]
    if horses != sorted(set(horses)) or len(horses) < 3:
        raise RuntimeError(f"ARCHIVE_HORSES_INVALID:{rid}:{horses}")

    required = [m for m in MARKETS if m in set(failure.get("requiredMarkets") or [])]
    if "win" not in required:
        raise RuntimeError(f"ARCHIVE_REQUIRED_MARKETS_INVALID:{rid}:{required}")

    official = {}
    coverage = {}
    for market in required:
        expected_combos = combos(horses, market)
        values = rec.get(market)
        if not isinstance(values, list) or len(values) != len(expected_combos):
            raise RuntimeError(
                f"ARCHIVE_VECTOR_LENGTH:{rid}:{market}:{len(values) if isinstance(values,list) else -1}:{len(expected_combos)}"
            )
        mapped = {key_for(market, combo): value for combo, value in zip(expected_combos, values)}
        present = sum(value is not None for value in values)
        if market == "win" and present != len(values):
            raise RuntimeError(f"ARCHIVE_WIN_INCOMPLETE:{rid}:{present}:{len(values)}")
        if market != "win" and present == 0:
            raise RuntimeError(f"ARCHIVE_MARKET_EMPTY:{rid}:{market}")
        official[market] = mapped
        coverage[market] = {
            "expected": len(values),
            "present": present,
            "ratio": present / len(values) if values else 0.0,
        }

    return {
        "raceId": rid,
        "raceDate": str(rec["raceDate"]),
        "venue": str(rec["venue"]),
        "raceNo": int(rec["raceNo"]),
        "requiredMarkets": required,
        "horses": horses,
        "officialOdds": official,
        "officialOddsCoverage": coverage,
        "provenance": {
            "resultUrl": failure.get("resultUrl"),
            "officialOddsSource": "jra_historical_official_final_odds_archive_20260808",
            "archivedSource": rec.get("source"),
            "archiveArtifactId": ARCHIVE_ARTIFACT_ID,
            "vectorOrdering": "audited_exporter_itertools_order",
            "syntheticOddsUsed": False,
            "estimatedOddsUsed": False,
            "productionDatabaseWritten": False,
            "productionModelChanged": False,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-jsonl", required=True)
    ap.add_argument("--current-meta", required=True)
    ap.add_argument("--archive-gz", required=True)
    ap.add_argument("--archive-meta", required=True)
    ap.add_argument("--out-jsonl", required=True)
    ap.add_argument("--out-meta", required=True)
    args = ap.parse_args()

    current_rows = read_jsonl(args.current_jsonl)
    current_meta = read_json(args.current_meta)
    archive_meta = read_json(args.archive_meta)
    failures = current_meta.get("failures") or []
    failed_by_id = {str(row["raceId"]): row for row in failures}

    if archive_meta.get("syntheticOddsUsed") is not False:
        raise RuntimeError("ARCHIVE_SYNTHETIC_ODDS_NOT_FALSE")
    if archive_meta.get("estimatedOddsUsed") is not False:
        raise RuntimeError("ARCHIVE_ESTIMATED_ODDS_NOT_FALSE")
    if int(archive_meta.get("races") or 0) != 7695 or int(archive_meta.get("uniqueOddsRaces") or 0) != 7695:
        raise RuntimeError(f"ARCHIVE_RACE_COUNT_INVALID:{archive_meta}")

    archive_rows = {}
    with gzip.open(args.archive_gz, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            rid = str(rec.get("raceId") or "")
            if rid in failed_by_id:
                archive_rows[rid] = rec

    missing = sorted(set(failed_by_id) - set(archive_rows))
    if missing:
        raise RuntimeError(f"ARCHIVE_FAILED_RACES_MISSING:{len(missing)}:{missing[:20]}")

    converted = [convert_archive_row(archive_rows[rid], failed_by_id[rid]) for rid in sorted(failed_by_id)]
    combined = {}
    for row in current_rows + converted:
        rid = str(row["raceId"])
        if rid in combined:
            raise RuntimeError(f"DUPLICATE_REPAIR_RACE:{rid}")
        combined[rid] = row

    expected = int(current_meta.get("inputDemandRaces") or 0)
    if len(combined) != expected:
        raise RuntimeError(f"REPAIR_COUNT_MISMATCH:{len(combined)}:{expected}")

    out_jsonl = Path(args.out_jsonl)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for rid in sorted(combined):
            f.write(json.dumps(combined[rid], ensure_ascii=False, separators=(",", ":")) + "\n")

    meta = {
        "purpose": "research_only_selective_official_final_odds_repair_with_audited_archive_fallback",
        "inputDemandRaces": expected,
        "completedRaces": len(combined),
        "networkRepairedRaces": len(current_rows),
        "archiveRepairedRaces": len(converted),
        "archiveArtifactId": ARCHIVE_ARTIFACT_ID,
        "archiveRaces": int(archive_meta["races"]),
        "archiveCoveragePct": archive_meta.get("coveragePct"),
        "failures": [],
        "syntheticOddsUsed": False,
        "estimatedOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    Path(args.out_meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
