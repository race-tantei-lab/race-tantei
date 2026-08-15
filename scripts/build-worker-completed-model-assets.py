#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import re
import struct
from typing import Any

import lightgbm as lgb
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "ten-year-completed-model.txt"
CONFIG_PATH = ROOT / "config" / "ten-year-completed-model.json"
MAGIC = b"RTLMOD01"
VERSION = 1
HEADER_STRUCT = struct.Struct("<8sIIIIdII")
NODE_STRUCT = struct.Struct("<BBBBiidI")
MISSING_TYPES = {"None": 0, "NaN": 1, "Zero": 2}


def model_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sigmoid(objective: str) -> float:
    match = re.search(r"(?:^|\s)sigmoid:([0-9.eE+\-]+)", objective)
    return float(match.group(1)) if match else 1.0


def flatten_model(dump: dict[str, Any]) -> tuple[list[int], list[tuple[int, int, int, int, int, int, float, int]], dict[str, int]]:
    nodes: list[tuple[int, int, int, int, int, int, float, int] | None] = []
    roots: list[int] = []
    stats = {"split": 0, "leaf": 0, "missingNone": 0, "missingNaN": 0, "missingZero": 0}

    def visit(node: dict[str, Any]) -> int:
        index = len(nodes)
        nodes.append(None)
        if "leaf_value" in node:
            value = float(node["leaf_value"])
            if not math.isfinite(value):
                raise RuntimeError(f"non-finite leaf value at node {index}")
            nodes[index] = (1, 0, 0, 0, -1, -1, value, 0)
            stats["leaf"] += 1
            return index
        decision_type = str(node.get("decision_type", ""))
        if decision_type != "<=":
            raise RuntimeError(f"unsupported LightGBM decision_type={decision_type!r} at node {index}")
        feature = int(node["split_feature"])
        threshold = node["threshold"]
        if not 0 <= feature <= 255 or isinstance(threshold, str):
            raise RuntimeError(f"unsupported LightGBM split at node {index}")
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value):
            raise RuntimeError(f"non-finite threshold at node {index}")
        missing_name = str(node.get("missing_type", "None"))
        if missing_name not in MISSING_TYPES:
            raise RuntimeError(f"unsupported LightGBM missing_type={missing_name!r} at node {index}")
        flags = 1 if bool(node.get("default_left", False)) else 0
        left = visit(node["left_child"])
        right = visit(node["right_child"])
        nodes[index] = (0, feature, flags, MISSING_TYPES[missing_name], left, right, threshold_value, 0)
        stats["split"] += 1
        stats[f"missing{missing_name}"] += 1
        return index

    for tree in dump.get("tree_info", []):
        roots.append(visit(tree["tree_structure"]))
    if any(node is None for node in nodes):
        raise RuntimeError("internal error: unfilled model node")
    return roots, [node for node in nodes if node is not None], stats


def build_vectors(feature_count: int) -> list[list[float]]:
    rng = np.random.default_rng(20260815)
    rows: list[np.ndarray] = [
        np.zeros(feature_count, dtype=np.float64),
        np.ones(feature_count, dtype=np.float64),
        np.linspace(0.0, 1.0, feature_count, dtype=np.float64),
        np.linspace(1.0, 100.0, feature_count, dtype=np.float64),
    ]
    rows.extend(rng.normal(0.0, 3.0, size=(256, feature_count)))
    rows.extend(rng.uniform(-2.0, 8.0, size=(256, feature_count)))
    rows.extend(rng.exponential(4.0, size=(128, feature_count)))
    return [[float(value) for value in row] for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "worker-assets" / "_internal" / "completed-model"))
    args = parser.parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    probability_model = config.get("runnerProbabilityModel") or {}
    expected_sha = str(probability_model.get("modelWeightsSha256", ""))
    if not expected_sha:
        raise RuntimeError("completed model config is missing runnerProbabilityModel.modelWeightsSha256")
    actual_sha = model_sha256(MODEL_PATH)
    if expected_sha != actual_sha:
        raise RuntimeError(f"completed model SHA256 mismatch: expected {expected_sha}, got {actual_sha}")

    feature_names = probability_model.get("features")
    if not isinstance(feature_names, list) or len(feature_names) != 56 or not all(isinstance(x, str) for x in feature_names):
        raise RuntimeError("completed model config must expose exactly 56 string features")
    feature_names = list(feature_names)

    booster = lgb.Booster(model_file=str(MODEL_PATH))
    if list(booster.feature_name()) != feature_names:
        raise RuntimeError("LightGBM model feature order does not match completed config features")
    dump = booster.dump_model()
    objective = str(dump.get("objective", "binary"))
    if not objective.startswith("binary"):
        raise RuntimeError(f"expected binary LightGBM objective, got {objective!r}")
    sigmoid_scale = parse_sigmoid(objective)
    average_output = bool(dump.get("average_output", False))
    roots, nodes, stats = flatten_model(dump)
    if not roots:
        raise RuntimeError("completed model has no trees")
    if stats["missingNaN"] or stats["missingZero"] or stats["missingNone"] != stats["split"]:
        raise RuntimeError(f"completed model unexpectedly contains missing-value splits: {stats}")

    model_bin = output_dir / "model.bin"
    with model_bin.open("wb") as handle:
        handle.write(HEADER_STRUCT.pack(MAGIC, VERSION, len(feature_names), len(roots), len(nodes), sigmoid_scale, 1 if average_output else 0, 0))
        for root in roots:
            handle.write(struct.pack("<I", root))
        for node in nodes:
            handle.write(NODE_STRUCT.pack(*node))

    vectors = build_vectors(len(feature_names))
    predictions = np.asarray(booster.predict(np.asarray(vectors, dtype=np.float64)), dtype=np.float64)
    predictions = np.clip(predictions, 1e-6, 1.0 - 1e-6)
    parity = {
        "modelVersion": "ten-year-completed-model",
        "modelSha256": actual_sha,
        "featureNames": feature_names,
        "vectors": vectors,
        "expected": [float(value) for value in predictions],
    }
    (output_dir / "parity.json").write_text(json.dumps(parity, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    metadata = {
        "format": MAGIC.decode("ascii"), "version": VERSION, "modelVersion": "ten-year-completed-model",
        "sourceSha256": actual_sha, "featureCount": len(feature_names), "treeCount": len(roots), "nodeCount": len(nodes),
        "sigmoid": sigmoid_scale, "averageOutput": average_output, "binaryBytes": model_bin.stat().st_size, "nodeStats": stats,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
