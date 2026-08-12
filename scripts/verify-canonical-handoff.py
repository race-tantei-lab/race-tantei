#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "HANDOFF.md",
    "README.md",
    "config/canonical-production-manifest.json",
    "config/ten-year-completed-model.json",
    "analysis-results/ten-year-model-completion-20260812.json",
    "models/ten-year-completed-model.txt",
    "models/ten-year-production-state-manifest.json",
    "models/ten-year-runner-feature-state.json.gz",
    "models/ten-year-race-selection-state.json.gz",
    "data/ten-year-runners/manifest.json",
    "src/v1/ten-year-public-summary.ts",
    "src/v1/ten-year-history.ts",
    "scripts/run-ten-year-auto-final-live.py",
    "scripts/ten-year-production-core.py",
    "scripts/generate-ten-year-preday-selection.py",
    "scripts/generate-ten-year-live-bets.py",
    ".github/workflows/auto-final-live-bets.yml",
    "wrangler.jsonc",
]


def fail(msg: str) -> None:
    raise AssertionError(msg)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_json(path: str):
    return json.loads(read(path))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with (ROOT / path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        fail(f"missing required files: {missing}")

    handoff = read("HANDOFF.md")
    readme = read("README.md")
    manifest = load_json("config/canonical-production-manifest.json")
    config = load_json("config/ten-year-completed-model.json")
    audit = load_json("analysis-results/ten-year-model-completion-20260812.json")
    state_manifest = load_json("models/ten-year-production-state-manifest.json")
    runner_manifest = load_json("data/ten-year-runners/manifest.json")
    wrangler = load_json("wrangler.jsonc")

    if manifest.get("status") != "production":
        fail("canonical manifest status is not production")
    if manifest.get("sourceOfTruth") != "HANDOFF.md":
        fail("canonical manifest sourceOfTruth mismatch")

    if config.get("status") != "completed" or config.get("name") != "ten-year-completed-model":
        fail("completed model config identity mismatch")
    if config.get("productionChanged") is not True:
        fail("completed model config is not marked productionChanged=true")

    expected_model_sha = manifest["model"]["weightsSha256"]
    actual_model_sha = sha256_file(manifest["model"]["weights"])
    if actual_model_sha != expected_model_sha:
        fail(f"model sha mismatch: {actual_model_sha} != {expected_model_sha}")

    if state_manifest.get("throughDate") != manifest["model"]["stateThroughDate"]:
        fail("production state throughDate mismatch")
    source_ids = state_manifest.get("sourceArtifactIds", {})
    if source_ids != manifest["model"]["sourceArtifactIds"]:
        fail(f"source artifact IDs mismatch: {source_ids}")

    state_shas = state_manifest.get("stateSha256", {})
    for path, expected in state_shas.items():
        actual = sha256_file(path)
        if actual != expected:
            fail(f"state sha mismatch for {path}: {actual} != {expected}")

    if audit.get("completed") is not True or audit.get("allCompletionGatesPassed") is not True:
        fail("completion audit gates are not all passed")
    if int(audit.get("archive", {}).get("universeRaces", -1)) != 34566:
        fail("completion audit universe race count mismatch")
    if int(audit.get("archive", {}).get("selectedRaces", -1)) != 14410:
        fail("completion audit selected race count mismatch")

    if wrangler.get("main") != manifest["site"]["entry"]:
        fail(f"wrangler main mismatch: {wrangler.get('main')} != {manifest['site']['entry']}")
    vars_ = wrangler.get("vars", {})
    if vars_.get("DEPLOY_REVISION") != manifest["site"]["revision"]:
        fail("DEPLOY_REVISION mismatch")
    if vars_.get("MODEL_VERSION") != manifest["model"]["name"]:
        fail("MODEL_VERSION mismatch")

    auto_workflow = read(manifest["production"]["autoWorkflow"])
    if "run-ten-year-auto-final-live.py" not in auto_workflow:
        fail("auto workflow does not invoke canonical ten-year runner")

    wrapper = read(manifest["production"]["runner"])
    for needle in ("generate-ten-year-preday-selection.py", "generate-ten-year-live-bets.py"):
        if needle not in wrapper:
            fail(f"canonical wrapper missing {needle}")

    public_summary = read(manifest["publicHistory"]["summary"])
    if "14410" not in public_summary or "431.6505898681471" not in public_summary:
        fail("public summary is not canonical 14,410R / 431.6505898681471%")

    if int(runner_manifest.get("races", -1)) != 34566:
        fail("runner archive race count mismatch")
    if int(runner_manifest.get("runners", -1)) != 480441:
        fail("runner archive runner count mismatch")

    history_loader = read(manifest["publicHistory"]["loader"])
    if "34566" not in history_loader:
        fail("ten-year history loader does not contain canonical race count")

    if "HANDOFF.md" not in readme:
        fail("README does not point to HANDOFF.md")
    if "canonical-production-manifest.json" not in readme:
        fail("README does not point to canonical production manifest")

    for needle in (
        "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5",
        "run-ten-year-auto-final-live.py",
        "wrangler.jsonc.main",
        "431.6505898681471%",
    ):
        if needle not in handoff:
            fail(f"HANDOFF missing canonical marker: {needle}")

    print(
        "CANONICAL_HANDOFF_OK",
        f"model_sha={actual_model_sha}",
        f"site_entry={wrangler['main']}",
        "selected_races=14410",
        "roi_pct=431.6505898681471",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CANONICAL_HANDOFF_FAIL: {exc}", file=sys.stderr)
        raise
