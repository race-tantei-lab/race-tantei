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
    "FINAL_STATE_20260816.md",
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
    "src/v1/completed-worker-live-lock.ts",
    "src/v1/completed-worker-deadline-guard.ts",
    "src/v1/completed-final-invariants.ts",
    "src/v1/live-preview-safety.ts",
    "src/live-deadline-entry-v2.ts",
    "src/public-site-entry-v34.ts",
    "scripts/run-ten-year-auto-final-live.py",
    "scripts/ten-year-production-core.py",
    "scripts/generate-ten-year-preday-selection.py",
    "scripts/generate-ten-year-live-bets.py",
    "scripts/build-worker-completed-model-assets.py",
    "scripts/verify-worker-model-parity.ts",
    "scripts/verify-live-lock-safety.py",
    ".github/workflows/deploy.yml",
    ".github/workflows/deploy-live-deadline.yml",
    ".github/workflows/verify-live-deadline-production.yml",
    ".github/workflows/production-smoke.yml",
    ".github/workflows/verify-canonical-handoff.yml",
    ".github/workflows/verify-worker-selection-parity.yml",
    "wrangler.jsonc",
    "wrangler.live-deadline.jsonc",
    "wrangler.live-deadline-backup.jsonc",
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


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        fail(f"{label} missing marker: {needle}")


def collect_public_site_sources(path: str) -> str:
    current = Path(path)
    seen: set[str] = set()
    sources: list[str] = []
    pattern = re.compile(r'import\s+publicSite\s+from\s+["\'](\./public-site-entry-v\d+)\.js["\']')
    while True:
        key = current.as_posix()
        if key in seen:
            fail(f"public-site entry import cycle: {key}")
        seen.add(key)
        full = ROOT / current
        if not full.exists():
            fail(f"public-site entry dependency missing: {key}")
        text = full.read_text(encoding="utf-8")
        sources.append(text)
        match = pattern.search(text)
        if not match:
            break
        current = current.parent / f"{match.group(1)}.ts"
    return "\n".join(sources)


def main() -> None:
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        fail(f"missing required files: {missing}")

    for obsolete in (
        ".github/workflows/auto-final-live-bets.yml",
        ".github/workflows/drive-live-tick.yml",
    ):
        if (ROOT / obsolete).exists():
            fail(f"obsolete live workflow must remain removed: {obsolete}")

    manifest = load_json("config/canonical-production-manifest.json")
    config = load_json("config/ten-year-completed-model.json")
    audit = load_json("analysis-results/ten-year-model-completion-20260812.json")
    state_manifest = load_json("models/ten-year-production-state-manifest.json")
    runner_manifest = load_json("data/ten-year-runners/manifest.json")
    wrangler = load_json("wrangler.jsonc")
    primary = load_json("wrangler.live-deadline.jsonc")
    backup = load_json("wrangler.live-deadline-backup.jsonc")

    if manifest.get("status") != "production" or int(manifest.get("handoffVersion", 0)) < 5:
        fail("canonical manifest is not the current production handoff")
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
        fail("completed model is not marked productionChanged=true")
    expected_model_sha = manifest["model"]["weightsSha256"]
    actual_model_sha = sha256_file(manifest["model"]["weights"])
    if actual_model_sha != expected_model_sha:
        fail(f"model sha mismatch: {actual_model_sha} != {expected_model_sha}")
    if actual_model_sha != "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5":
        fail("canonical completed model SHA changed")

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
        if sha256_file(path) != str(info.get("sha256", "")):
            fail(f"state sha mismatch for {path}")

    if audit.get("completed") is not True or audit.get("allCompletionGatesPassed") is not True:
        fail("completion audit gates are not all passed")
    if int(audit.get("archive", {}).get("universeRaces", -1)) != 34566:
        fail("completion audit universe race count mismatch")
    if int(audit.get("archive", {}).get("selectedRaces", -1)) != 14410:
        fail("completion audit selected race count mismatch")
    if audit.get("raceSelectionAudit", {}).get("targetDayResultsUsedForSelection") is not False:
        fail("target-day result leakage flag is not false")
    if audit.get("raceSelectionAudit", {}).get("historicalFinalOddsUsedForSelection") is not False:
        fail("race selection unexpectedly uses historical final odds")
    if audit.get("raceSelectionAudit", {}).get("syntheticOddsUsed") is not False:
        fail("race selection synthetic odds flag is not false")

    site = manifest["site"]
    if wrangler.get("main") != site["entry"]:
        fail("wrangler main mismatch")
    vars_ = wrangler.get("vars", {})
    if vars_.get("DEPLOY_REVISION") != site["revision"]:
        fail(f"DEPLOY_REVISION mismatch: {vars_.get('DEPLOY_REVISION')} != {site['revision']}")
    if vars_.get("MODEL_VERSION") != manifest["model"]["name"]:
        fail("MODEL_VERSION mismatch")
    if "build-worker-completed-model-assets.py" not in str(wrangler.get("build", {}).get("command", "")):
        fail("wrangler build does not generate canonical Worker model assets")
    d1 = wrangler.get("d1_databases", [])
    if len(d1) != 1 or d1[0].get("database_name") != site["d1DatabaseName"] or d1[0].get("database_id") != site["d1DatabaseId"]:
        fail("public Worker D1 identity mismatch")

    prod = manifest["production"]
    expected_prod = {
        "liveDeadlineEntry": "src/live-deadline-entry-v2.ts",
        "liveDeadlinePrimaryConfig": "wrangler.live-deadline.jsonc",
        "liveDeadlineBackupConfig": "wrangler.live-deadline-backup.jsonc",
        "liveDeadlineDeployWorkflow": ".github/workflows/deploy-live-deadline.yml",
        "liveDeadlineReadinessWorkflow": ".github/workflows/verify-live-deadline-production.yml",
        "publicLiveMutationEnabled": False,
        "previewOpenMinutes": 90,
        "previewRequiredMinutes": 30,
        "normalLockMinutes": 25,
        "deadlineGuardArmMinutes": 20,
        "hardDeadlineMinutes": 15,
        "officialOddsOnly": True,
        "syntheticOddsForbidden": True,
    }
    for key, expected in expected_prod.items():
        if prod.get(key) != expected:
            fail(f"production live architecture mismatch for {key}: {prod.get(key)!r} != {expected!r}")

    if primary.get("name") != "race-tantei-live-deadline" or primary.get("main") != prod["liveDeadlineEntry"]:
        fail("primary live deadline Worker identity mismatch")
    if primary.get("triggers", {}).get("crons") != ["* * * * *"]:
        fail("primary live deadline cron mismatch")
    if backup.get("name") != "race-tantei-live-deadline-backup" or backup.get("main") != prod["liveDeadlineEntry"]:
        fail("backup live deadline Worker identity mismatch")
    if backup.get("triggers", {}).get("crons") != ["2-59/5 * * * *"]:
        fail("backup live deadline cron mismatch")
    for cfg in (primary, backup):
        bindings = cfg.get("d1_databases", [])
        if len(bindings) != 1 or bindings[0].get("database_id") != site["d1DatabaseId"]:
            fail("live deadline Worker D1 binding mismatch")

    active_ui_sources = collect_public_site_sources(site["entry"])
    for needle in (
        "予想ロジック",
        "JRA公式オッズ",
        "公開した買い目と結果は後から変更しません",
        "予想のしくみ",
    ):
        require(active_ui_sources, needle, "active public-site chain")

    top_public = read(site["entry"])
    for forbidden in ("runCompletedWorkerLiveLock", "runCompletedWorkerDeadlineGuard", "runDirectLiveTick"):
        if forbidden in top_public:
            fail(f"public top entry must not own live prediction mutation: {forbidden}")
    if 'pathname === "/_ops/live-tick"' not in top_public or 'status: 404' not in top_public:
        fail("public legacy live-tick endpoint is not hard-disabled")

    live_entry = read(prod["liveDeadlineEntry"])
    live_worker = read(prod["workerLiveLock"])
    live_safety = read("src/v1/live-preview-safety.ts")
    deadline_guard = read("src/v1/completed-worker-deadline-guard.ts")
    invariants = read("src/v1/completed-final-invariants.ts")

    for needle in (
        "acquireLiveDeadlineLease",
        "restoreNewestOfficialPreviewArchives",
        "auditLiveDeadlineSla",
        "LIVE_DEADLINE_HARD_T15_BREACH",
        "selection_critical",
        "predeadline_critical",
    ):
        require(live_entry, needle, "live deadline entry")
    if "/_ops/live-tick" in live_entry:
        fail("isolated live deadline Worker must not expose a public mutation endpoint")

    for needle in (
        "const PREVIEW_OPEN_MS = 90 * 60 * 1000;",
        "const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;",
        "const NORMAL_LOCK_MS = 25 * 60 * 1000;",
        "const DEADLINE_MS = 15 * 60 * 1000;",
        'new Set(["jra-fast-official", "jra-crawl-official"])',
        "WORKER_HARD_T15_MISSED",
    ):
        require(live_worker, needle, "live lock")

    for needle in (
        "rt_live_preview_archive",
        "rt_live_deadline_lease",
        "previewMissingByT40RaceIds",
        "previewMissingByT30RaceIds",
        "finalMissingByT25RaceIds",
        "finalMissingByT20RaceIds",
        "deadlineMissedRaceIds",
    ):
        require(live_safety, needle, "live safety")

    for needle in (
        "DEADLINE_GUARD_ARM_MS = 20 * 60 * 1000",
        "remainingMs >= DEADLINE_GUARD_MS",
        "isDeadlineGuardMissed",
    ):
        require(deadline_guard, needle, "deadline guard")

    for needle in (
        "FINAL_BET_DEADLINE_PASSED",
        "FINAL_STATE_DEADLINE_PASSED",
        "OFFICIAL_JRA_ODDS_REQUIRED",
        "PROBABILITY_FALLBACK_FORBIDDEN",
    ):
        require(invariants, needle, "D1 invariant")

    deploy_live = read(prod["liveDeadlineDeployWorkflow"])
    for needle in ("Deploy primary live deadline Worker", "Deploy backup live deadline Worker", "production/live-deadline"):
        require(deploy_live, needle, "live deadline deploy workflow")
    readiness = read(prod["liveDeadlineReadinessWorkflow"])
    for needle in ("/health", "_ops/live-tick", "rt_live_preview_archive", "production/live-deadline-readiness"):
        require(readiness, needle, "live deadline readiness workflow")

    deploy_workflow = read(prod["deployWorkflow"])
    for needle in (
        "build-worker-completed-model-assets.py",
        "verify-worker-model-parity.ts",
        "Verify historical race APIs and detail",
        "Verify live result ingestion and settlement",
        "verify-live-lock-safety.py",
    ):
        require(deploy_workflow, needle, "production deploy")

    public_summary = read(manifest["publicHistory"]["summary"])
    if "14410" not in public_summary or "431.6505898681471" not in public_summary:
        fail("public summary is not canonical 14,410R / 431.6505898681471%")
    if int(runner_manifest.get("races", -1)) != manifest["publicHistory"]["historyRaces"]:
        fail("runner archive race count mismatch")
    if int(runner_manifest.get("runners", -1)) != manifest["publicHistory"]["runnerRows"]:
        fail("runner archive runner count mismatch")

    deployment_log = read(site["deploymentLog"])
    if site["url"] not in deployment_log:
        fail("deployment log does not contain production URL")
    for needle in (manifest["model"]["name"], site["d1DatabaseName"]):
        require(deployment_log, needle, "deployment log")
    if not re.search(r"Current Version ID:\s*([0-9a-fA-F-]{36})", deployment_log):
        fail("deployment log does not contain a valid Current Version ID")

    readme = read("README.md")
    handoff = read("HANDOFF.md")

    for needle in (
        "HANDOFF.md",
        "canonical-production-manifest.json",
        "completed-model-methodology-audit-20260813.md",
        "src/public-site-entry-v34.ts",
        "src/live-deadline-entry-v2.ts",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "**T-90**",
        "**T-25**",
        "**T-20**",
        "**T-15**",
        "CANONICAL_HANDOFF_OK",
    ):
        require(readme, needle, "README")

    for needle in (
        "handoff version: **5**",
        "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5",
        "wrangler.jsonc.main",
        "431.6505898681471%",
        "src/live-deadline-entry-v2.ts",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "public live mutation: **disabled**",
        "**T-90**",
        "**T-30**",
        "**T-25**",
        "**T-20**",
        "**T-15**",
        "historical baseline",
        "verify-canonical-handoff.py",
        "CANONICAL_HANDOFF_OK",
    ):
        require(handoff, needle, "HANDOFF")

    for stale in (
        "handoff version: **4**",
        ".github/workflows/auto-final-live-bets.yml",
        "scripts/run-stored-preview-deadline-backup.py",
        "現行T-15自動backup",
    ):
        if stale in handoff:
            fail(f"HANDOFF still contains obsolete current-architecture marker: {stale}")

    verify_workflow = read(".github/workflows/verify-canonical-handoff.yml")
    for needle in (
        "production/canonical-handoff",
        "src/live-deadline-entry-v2.ts",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "Verify v5 handoff documentation markers",
    ):
        require(verify_workflow, needle, "canonical handoff workflow")

    print(
        "CANONICAL_HANDOFF_OK",
        f"model_sha={actual_model_sha}",
        f"site_entry={wrangler['main']}",
        "handoff_version=5",
        "selected_races=14410",
        "roi_pct=431.6505898681471",
        "live_primary=1m",
        "live_backup=5m_staggered",
        "preview_open=90m",
        "normal_lock=25m",
        "hard_deadline=15m",
        "public_live_mutation=false",
        "official_jra_odds_only=true",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CANONICAL_HANDOFF_FAIL: {exc}", file=sys.stderr)
        raise
