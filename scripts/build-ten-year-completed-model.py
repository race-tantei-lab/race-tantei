#!/usr/bin/env python3
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
from lightgbm import LGBMClassifier


def read_demand_ids(path: Path):
    ids = set()
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive, archive.open("demand.jsonl") as fh:
            for raw in fh:
                if raw.strip():
                    ids.add(str(json.loads(raw)["raceId"]))
    else:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    ids.add(str(json.loads(line)["raceId"]))
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--demand", required=True)
    ap.add_argument("--config", default="config/ten-year-completed-model.json")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    model_cfg = cfg["runnerProbabilityModel"]
    features = list(model_cfg["features"])
    expected = str(model_cfg["modelWeightsSha256"])
    demand_ids = read_demand_ids(Path(args.demand))

    if len(demand_ids) != int(cfg["frozenArchive"]["selectedRaces"]):
        raise RuntimeError(f"DEMAND_RACE_COUNT_INVALID:{len(demand_ids)}")

    usecols = ["raceId", "labelWin", *features]
    frame = pd.read_csv(args.features, usecols=usecols)
    frame["raceId"] = frame["raceId"].astype(str)
    train = frame[frame["raceId"].isin(demand_ids)]

    if train["raceId"].nunique() != len(demand_ids):
        raise RuntimeError(f"TRAIN_RACE_COUNT_INVALID:{train['raceId'].nunique()}")

    params = dict(model_cfg["params"])
    # The completed canonical model was serialized with LightGBM verbosity=-1.
    # This does not change the fitted trees; it is required for byte-identical weights.
    params["verbosity"] = -1
    model = LGBMClassifier(**params)
    model.fit(train[features], train["labelWin"].astype(int))
    text = model.booster_.model_to_string()
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    if sha != expected:
        raise RuntimeError(f"MODEL_SHA_MISMATCH:{sha}:{expected}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({
        "selectedRaces": len(demand_ids),
        "trainingRows": len(train),
        "featureCount": len(features),
        "sha256": sha,
        "match": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
