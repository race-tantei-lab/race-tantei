#!/usr/bin/env python3
from __future__ import annotations

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
    "analysis-results/completed-model-methodology-audit-20260813.md",
    "analysis-results/production-deployment.log",
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
    ".github/workflows/production-smoke.yml",
    ".github/workflows/verify-canonical-handoff.yml",
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
    methodology_audit = read("analysis-results/completed-model-methodology-audit-20260813.md")
    production_smoke = read(".github/workflows/production-smoke.yml")
    verify_workflow = read(".github/workflows/verify-canonical-handoff.yml")
    manifest = load_json("config/canonical-production-manifest.json")
    config = load_json("config/ten-year-completed-model.json")
    audit = load_json("analysis-results/ten-year-model-completion-20260812.json")
    state_manifest = load_json("models/ten-year-production-state-manifest.json")
    runner_manifest = load_json("data/ten-year-runners/manifest.json")
    wrangler = load_json("wrangler.jsonc")
    deployment_log = read("analysis-results/production-deployment.log")

    if manifest.get("status") != "production":
        fail("canonical manifest status is not production")
    if int(manifest.get("handoffVersion", 0)) < 2:
        fail("canonical handoffVersion is not completed version 2+")
    if manifest.get("sourceOfTruth") != "HANDOFF.md":
        fail("canonical manifest sourceOfTruth mismatch")

    verification = manifest.get("handoffVerification", {})
    if verification.get("script") != "scripts/verify-canonical-handoff.py":
        fail("canonical handoff verifier path mismatch")
    if verification.get("workflow") != ".github/workflows/verify-canonical-handoff.yml":
        fail("canonical handoff workflow path mismatch")
    if verification.get("requiredResult") != "CANONICAL_HANDOFF_OK":
        fail("canonical handoff required result mismatch")

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

    source_ids = {
        "history": int(state_manifest.get("sourceHistoryArtifactId", -1)),
        "runnerFeatures": int(state_manifest.get("canonicalFeatureArtifactId", -1)),
        "demand": int(state_manifest.get("canonicalDemandArtifactId", -1)),
    }
    if source_ids != manifest["model"]["sourceArtifactIds"]:
        fail(f"source artifact IDs mismatch: {source_ids}")

    state_files = state_manifest.get("files", {})
    for path in (manifest["model"]["runnerFeatureState"], manifest["model"]["raceSelectionState"]):
        info = state_files.get(path)
        if not isinstance(info, dict):
            fail(f"state manifest missing file entry: {path}")
        expected = str(info.get("sha256", ""))
        actual = sha256_file(path)
        if actual != expected:
            fail(f"state sha mismatch for {path}: {actual} != {expected}")

    if audit.get("completed") is not True or audit.get("allCompletionGatesPassed") is not True:
        fail("completion audit gates are not all passed")
    if int(audit.get("archive", {}).get("universeRaces", -1)) != 34566:
        fail("completion audit universe race count mismatch")
    if int(audit.get("archive", {}).get("selectedRaces", -1)) != 14410:
        fail("completion audit selected race count mismatch")
    if audit.get("probabilityModel", {}).get("trainingMode") != "full frozen archive uniform discovery":
        fail("completion audit trainingMode changed unexpectedly")
    if audit.get("raceSelectionAudit", {}).get("targetDayResultsUsedForSelection") is not False:
        fail("target-day result leakage flag is not false")
    if audit.get("raceSelectionAudit", {}).get("historicalFinalOddsUsedForSelection") is not False:
        fail("race selection unexpectedly uses historical final odds")
    if audit.get("raceSelectionAudit", {}).get("syntheticOddsUsed") is not False:
        fail("race selection synthetic odds flag is not false")

    for needle in (
        "431.6505898681471%",
        "full frozen archive uniform discovery",
        "完全OOF成績",
        "acf44ad91c83e30f3a3e0363b43bbc8fb4a51a2c",
        "timestamp",
        "0.4",
    ):
        if needle not in methodology_audit:
            fail(f"methodology audit missing transparency marker: {needle}")

    if wrangler.get("main") != manifest["site"]["entry"]:
        fail(f"wrangler main mismatch: {wrangler.get('main')} != {manifest['site']['entry']}")
    vars_ = wrangler.get("vars", {})
    if vars_.get("DEPLOY_REVISION") != manifest["site"]["revision"]:
        fail("DEPLOY_REVISION mismatch")
    if vars_.get("MODEL_VERSION") != manifest["model"]["name"]:
        fail("MODEL_VERSION mismatch")

    d1 = wrangler.get("d1_databases", [])
    if len(d1) != 1:
        fail("expected exactly one D1 binding")
    if d1[0].get("database_name") != manifest["site"]["d1DatabaseName"]:
        fail("D1 database name mismatch")
    if d1[0].get("database_id") != manifest["site"]["d1DatabaseId"]:
        fail("D1 database ID mismatch")

    conditions_entry = read(manifest["site"]["entry"])
    for needle in (
        "予想ロジック",
        "上位5頭",
        "選定用の仮買い目",
        "Plackett-Luce",
        "ln(予測確率) + 0.4 × ln(JRA公式オッズ)",
        "431.7%",
        "54.4%",
        "未使用データだけで検証した成績ではありません",
        "データ更新のタイミング",
        "公開した買い目と結果は後から変更しません",
    ):
        if needle not in conditions_entry:
            fail(f"conditions page missing product/methodology marker: {needle}")

    for needle in (
        "conditionsMethodology",
        "day8ApiShape",
        "day9ApiShape",
        "未使用データだけで検証した成績ではありません",
        "ln(予測確率) + 0.4 × ln(JRA公式オッズ)",
    ):
        if needle not in production_smoke:
            fail(f"production smoke missing canonical marker: {needle}")
    for stale in ("296.8%", "297.6%", "297.0%", "3225R", "len(aug8)==15", "len(aug9)==15"):
        if stale in production_smoke:
            fail(f"production smoke contains stale assertion: {stale}")
    if ".github/workflows/production-smoke.yml" not in verify_workflow:
        fail("canonical verifier workflow does not watch production smoke")

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

    if int(runner_manifest.get("races", -1)) != manifest["publicHistory"]["historyRaces"]:
        fail("runner archive race count mismatch")
    if int(runner_manifest.get("runners", -1)) != manifest["publicHistory"]["runnerRows"]:
        fail("runner archive runner count mismatch")

    history_loader = read(manifest["publicHistory"]["loader"])
    if "34566" not in history_loader:
        fail("ten-year history loader does not contain canonical race count")

    if manifest["site"]["url"] not in deployment_log:
        fail("deployment log does not contain canonical production URL")
    for needle in (
        manifest["site"]["revision"],
        manifest["model"]["name"],
        manifest["site"]["d1DatabaseName"],
    ):
        if needle not in deployment_log:
            fail(f"deployment log missing canonical marker: {needle}")
    version_match = re.search(r"Current Version ID:\s*([0-9a-fA-F-]{36})", deployment_log)
    if not version_match:
        fail("deployment log does not contain a valid Current Version ID")
    worker_version = version_match.group(1)

    if "HANDOFF.md" not in readme:
        fail("README does not point to HANDOFF.md")
    if "canonical-production-manifest.json" not in readme:
        fail("README does not point to canonical production manifest")
    if "completed-model-methodology-audit-20260813.md" not in readme:
        fail("README does not point to methodology audit")

    for needle in (
        "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5",
        "run-ten-year-auto-final-live.py",
        "wrangler.jsonc.main",
        "431.6505898681471%",
        "verify-canonical-handoff.py",
        "CANONICAL_HANDOFF_OK",
        "completed-model-methodology-audit-20260813.md",
        "完全OOF",
    ):
        if needle not in handoff:
            fail(f"HANDOFF missing canonical marker: {needle}")

    print(
        "CANONICAL_HANDOFF_OK",
        f"model_sha={actual_model_sha}",
        f"site_entry={wrangler['main']}",
        f"worker_version={worker_version}",
        "selected_races=14410",
        "roi_pct=431.6505898681471",
        "methodology_audit=20260813",
        "production_smoke=canonical",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CANONICAL_HANDOFF_FAIL: {exc}", file=sys.stderr)
        raise
