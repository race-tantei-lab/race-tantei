#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
CORE_PATH = ROOT / "scripts" / "ten-year-production-core.py"
MAGIC = b"RTLMOD01"
VERSION = 1
HEADER_STRUCT = struct.Struct("<8sIIIIdII")
NODE_STRUCT = struct.Struct("<BBBBiidI")
MISSING_TYPES = {"None": 0, "NaN": 1, "Zero": 2}


def load_core_feature_names() -> list[str]:
    spec = importlib.util.spec_from_file_location("ten_year_production_core_for_asset", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ten-year production core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = getattr(module, "FEATURE_NAMES", None)
    if not isinstance(names, list) or not names or not all(isinstance(x, str) for x in names):
        raise RuntimeError("FEATURE_NAMES is missing from ten-year production core")
    return list(names)


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
        if not 0 <= feature <= 255:
            raise RuntimeError(f"feature index out of binary range: {feature}")
        threshold = node["threshold"]
        if isinstance(threshold, str):
            raise RuntimeError(f"categorical/string threshold is unsupported at node {index}: {threshold!r}")
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value):
            raise RuntimeError(f"non-finite threshold at node {index}")

        missing_name = str(node.get("missing_type", "None"))
        if missing_name not in MISSING_TYPES:
            raise RuntimeError(f"unsupported LightGBM missing_type={missing_name!r} at node {index}")
        missing_code = MISSING_TYPES[missing_name]
        flags = 1 if bool(node.get("default_left", False)) else 0
        left = visit(node["left_child"])
        right = visit(node["right_child"])
        nodes[index] = (0, feature, flags, missing_code, left, right, threshold_value, 0)
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
    rows.extend(rng.normal(0.0, 3.0, size=(128, feature_count)))
    rows.extend(rng.uniform(-2.0, 8.0, size=(128, feature_count)))
    rows.extend(rng.exponential(4.0, size=(64, feature_count)))
    # Exercise default/missing routing without depending on JSON NaN syntax.
    for feature in range(min(feature_count, 56)):
        row = np.zeros(feature_count, dtype=np.float64)
        row[feature] = np.nan
        rows.append(row)
    return [[float(value) for value in row] for row in rows]


def json_safe_vector(row: list[float]) -> list[float | None]:
    return [None if math.isnan(value) else value for value in row]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "worker-assets" / "_internal" / "completed-model"))
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    expected_sha = str(config.get("modelSha256") or config.get("modelSHA256") or config.get("model_sha256") or "")
    actual_sha = model_sha256(MODEL_PATH)
    if expected_sha and expected_sha != actual_sha:
        raise RuntimeError(f"completed model SHA256 mismatch: expected {expected_sha}, got {actual_sha}")

    feature_names = load_core_feature_names()
    if len(feature_names) != 56:
        raise RuntimeError(f"completed model production core must have 56 features, got {len(feature_names)}")

    booster = lgb.Booster(model_file=str(MODEL_PATH))
    booster_names = list(booster.feature_name())
    if booster_names != feature_names:
        raise RuntimeError("LightGBM model feature order does not match production FEATURE_NAMES")

    dump = booster.dump_model()
    objective = str(dump.get("objective", "binary"))
    if not objective.startswith("binary"):
        raise RuntimeError(f"expected binary LightGBM objective, got {objective!r}")
    sigmoid_scale = parse_sigmoid(objective)
    average_output = bool(dump.get("average_output", False))
    roots, nodes, stats = flatten_model(dump)
    if not roots:
        raise RuntimeError("completed model has no trees")

    model_bin = output_dir / "model.bin"
    with model_bin.open("wb") as handle:
        handle.write(
            HEADER_STRUCT.pack(
                MAGIC,
                VERSION,
                len(feature_names),
                len(roots),
                len(nodes),
                sigmoid_scale,
                1 if average_output else 0,
                0,
            )
        )
        for root in roots:
            handle.write(struct.pack("<I", root))
        for node in nodes:
            handle.write(NODE_STRUCT.pack(*node))

    vectors = build_vectors(len(feature_names))
    matrix = np.asarray(vectors, dtype=np.float64)
    predictions = np.asarray(booster.predict(matrix), dtype=np.float64)
    predictions = np.clip(predictions, 1e-6, 1.0 - 1e-6)
    parity = {
        "modelVersion": "ten-year-completed-model",
        "modelSha256": actual_sha,
        "featureNames": feature_names,
        "vectors": [json_safe_vector(row) for row in vectors],
        "expected": [float(value) for value in predictions],
    }
    (output_dir / "parity.json").write_text(json.dumps(parity, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    metadata = {
        "format": MAGIC.decode("ascii"),
        "version": VERSION,
        "modelVersion": "ten-year-completed-model",
        "sourceSha256": actual_sha,
        "featureCount": len(feature_names),
        "treeCount": len(roots),
        "nodeCount": len(nodes),
        "sigmoid": sigmoid_scale,
        "averageOutput": average_output,
        "binaryBytes": model_bin.stat().st_size,
        "nodeStats": stats,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
