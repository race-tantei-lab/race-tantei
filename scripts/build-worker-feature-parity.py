#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import pathlib
import sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "ten-year-production-core.py"
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "worker-feature-parity.json"


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def race_for_json(race: dict) -> dict:
    return {
        "raceId": str(race["raceId"]), "raceDate": str(race["raceDate"]), "venue": str(race.get("venue") or ""),
        "meetingNo": int(race.get("meetingNo") or 0), "meetingDay": int(race.get("meetingDay") or 0), "raceNo": int(race.get("raceNo") or 0),
        "raceName": str(race.get("raceName") or ""), "conditions": race.get("conditions"), "surface": race.get("surface"), "distanceM": race.get("distanceM"),
        "direction": race.get("direction"), "startTimeJst": race.get("startTimeJst"), "startTimeUtc": race.get("startTimeUtc"), "weather": race.get("weather"),
        "trackCondition": race.get("trackCondition"), "entryUrl": str(race.get("entryUrl") or ""), "resultUrl": str(race.get("resultUrl") or ""),
        "status": str(race.get("status") or "scheduled"),
    }


def runner_for_json(row: dict) -> dict:
    return {
        "horseNo": int(row.get("horseNo") or 0), "frameNo": row.get("frameNo"), "horseName": str(row.get("horseName") or ""), "sexAge": row.get("sexAge"),
        "coatColor": row.get("coatColor"), "horseWeight": row.get("horseWeight"), "weightChange": row.get("weightChange"), "jockey": row.get("jockey"),
        "assignedWeight": row.get("assignedWeight"), "trainer": row.get("trainer"), "stable": row.get("stable"), "winOdds": row.get("winOdds"),
        "popularity": row.get("popularity"), "runnerStatus": str(row.get("runnerStatus") or "active"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat())
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"):
        if not os.environ.get(key):
            raise RuntimeError(f"MISSING_ENV:{key}")
    collector = load(COLLECTOR_PATH, "worker_feature_parity_collector")
    core = load(CORE_PATH, "worker_feature_parity_core")
    state = core.load_feature_state()
    frozen_through = str(state["throughDate"])
    delta = core.delta_bundles(collector, frozen_through, args.date)
    core.advance_feature_state(state, delta)
    targets = core.target_bundles(collector, args.date)
    if not targets:
        raise RuntimeError(f"NO_TARGET_RACES:{args.date}")

    active_bundles = []
    horse_names: set[str] = set()
    jockeys: set[str] = set()
    trainers: set[str] = set()
    expected: list[dict] = []
    for bundle in targets:
        race = bundle["race"]
        runners = [r for r in bundle.get("runners", []) if (r.get("runnerStatus") or "active") == "active"]
        runners.sort(key=lambda row: int(row.get("horseNo") or 0))
        if len(runners) < 2:
            continue
        active_bundles.append({"race": race_for_json(race), "runners": [runner_for_json(row) for row in runners]})
        for runner in runners:
            name = str(runner.get("horseName") or f"__{race['raceId']}:{runner.get('horseNo')}")
            horse_names.add(name)
            jockeys.add(str(runner.get("jockey") or ""))
            trainers.add(str(runner.get("trainer") or ""))
            record = core.ml_feature_row(state, race, runner, len(runners))
            expected.append({"raceId": str(race["raceId"]), "horseNo": int(runner["horseNo"]), "features": record})

    horse_hist = {}
    horse_total = {}
    horse_surface = []
    horse_dist = []
    horse_venue = []
    pair = []
    for horse in sorted(horse_names):
        history = state["horse_hist"].get(horse, ())
        horse_hist[horse] = [
            {**row, "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"])} for row in history
        ]
        if horse in state["horse_total"]:
            horse_total[horse] = list(state["horse_total"][horse])
    for (horse, surface), stat in state["horse_surface"].items():
        if horse in horse_names and any(stat): horse_surface.append([horse, surface, *list(stat)])
    for (horse, dist_bin), stat in state["horse_dist"].items():
        if horse in horse_names and any(stat): horse_dist.append([horse, int(dist_bin), *list(stat)])
    for (horse, venue), stat in state["horse_venue"].items():
        if horse in horse_names and any(stat): horse_venue.append([horse, venue, *list(stat)])
    for (horse, jockey), stat in state["pair"].items():
        if horse in horse_names and jockey in jockeys and any(stat): pair.append([horse, jockey, *list(stat)])

    payload = {
        "date": args.date,
        "frozenThroughDate": frozen_through,
        "advancedThroughDate": str(state["throughDate"]),
        "deltaRaceCount": len(delta),
        "raceCount": len(active_bundles),
        "runnerCount": len(expected),
        "state": {
            "generation": "python-parity",
            "throughDate": str(state["throughDate"]),
            "horseHist": horse_hist,
            "horseTotal": horse_total,
            "horseSurface": horse_surface,
            "horseDist": horse_dist,
            "horseVenue": horse_venue,
            "jockey": {name: list(state["jockey"].get(name, [0, 0, 0])) for name in sorted(jockeys) if name in state["jockey"]},
            "trainer": {name: list(state["trainer"].get(name, [0, 0, 0])) for name in sorted(trainers) if name in state["trainer"]},
            "pair": pair,
        },
        "bundles": active_bundles,
        "expected": expected,
    }
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("date", "frozenThroughDate", "advancedThroughDate", "deltaRaceCount", "raceCount", "runnerCount")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
