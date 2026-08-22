#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL_SHA = "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    body = text("src/v1/bodyweight-refresh.ts")
    live = text("src/v1/completed-worker-live-lock.ts")
    guard = text("src/v1/completed-worker-deadline-guard.ts")
    public = text("src/public-site-entry-v34.ts")
    driver = text("src/live-deadline-entry-v2.ts")
    direct = text("scripts/sync-upcoming-entries-direct.mjs")
    primary = json.loads(text("wrangler.live-deadline.jsonc"))
    backup = json.loads(text("wrangler.live-deadline-backup.jsonc"))

    require("fetchJraPage" in body and "parseEntryPage" in body and "pageLooksLikeEntry" in body, "BODYWEIGHT_DIRECT_JRA_PARSER_MISSING")
    require("sp.jra.jp" in body and "www.jra.go.jp" in body, "BODYWEIGHT_ALTERNATE_JRA_HOST_MISSING")
    require("BODYWEIGHT_NOT_PUBLISHED" in body, "BODYWEIGHT_PUBLISH_RETRY_SIGNAL_MISSING")
    require("worker_bodyweight_snapshot:" in body, "BODYWEIGHT_PROVENANCE_STATE_MISSING")
    require("BODYWEIGHT_D1_VERIFY_FAILED" in body, "BODYWEIGHT_D1_REREAD_VERIFY_MISSING")

    require("const BODY_WEIGHT_REFRESH_OPEN_MS = 100 * 60 * 1000;" in live, "BODYWEIGHT_T100_REFRESH_WINDOW_MISSING")
    require("const PREVIEW_OPEN_MS = 90 * 60 * 1000;" in live, "BODYWEIGHT_T90_PREVIEW_WINDOW_MISSING")
    require("const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;" in live, "BODYWEIGHT_T30_PREVIEW_REQUIRED_MISSING")
    require("const NORMAL_LOCK_MS = 25 * 60 * 1000;" in live, "BODYWEIGHT_T25_NORMAL_LOCK_MISSING")
    require("const DEADLINE_MS = 15 * 60 * 1000;" in live, "BODYWEIGHT_T15_DEADLINE_MISSING")
    require("const FINALIZE_OPEN_MS" not in live, "BODYWEIGHT_OLD_POST_DEADLINE_FINALIZE_WINDOW_REINTRODUCED")
    require("bodyWeightApplied?: boolean" in live and "bodyWeightSnapshot?: OfficialBodyWeightSnapshot | null" in live, "BODYWEIGHT_PREVIEW_PROVENANCE_MISSING")
    require("bodyWeightError = errorText(error)" in live, "BODYWEIGHT_FETCH_FAILURE_NOT_CAPTURED")
    require("latestOfficialBodyWeightPreview" in live, "BODYWEIGHT_LAST_GOOD_WEIGHTED_PREVIEW_MISSING")
    require("bodyWeightBreachRaceIds" in live, "BODYWEIGHT_BREACH_AUDIT_MISSING")
    require("bodyWeightFetchedAt:" in live and "bodyWeightSnapshotSha256:" in live and "bodyWeights:" in live, "BODYWEIGHT_FINAL_AUDIT_PROVENANCE_MISSING")
    require("WORKER_FINAL_BODYWEIGHT_MISMATCH" not in live, "BODYWEIGHT_MISSING_STILL_BLOCKS_FINAL_BETS")

    # T-15 is a hard assertion boundary. The live owner may report a miss but
    # must not fetch, infer, recompute, or create a new final at/after T-15.
    t15_start = live.index("if (remaining <= DEADLINE_MS)")
    t15_end = live.index("const existingPreview", t15_start)
    t15 = live[t15_start:t15_end]
    require("WORKER_HARD_T15_MISSED" in t15, "BODYWEIGHT_T15_ASSERTION_MISSING")
    for forbidden in (
        "resolveOfficialBodyWeights(",
        "refreshOfficialBodyWeights(",
        "generatePreview(",
        "fetchFastJraOfficialOddsForRace(",
        "loadCompletedFeatureStateForRace(",
        "loadCompletedRecencyLearning(",
        "commitSnapshot(",
        "INSERT INTO rt_public_bets",
    ):
        require(forbidden not in t15, f"BODYWEIGHT_T15_NETWORK_RECOMPUTE_OR_WRITE_REINTRODUCED:{forbidden}")

    # Body weight resolution must happen before the race is re-read and before
    # feature-vector/model work, so official weights affect the intended preview.
    body_try = live.find("bodyWeightSnapshot = await resolveOfficialBodyWeights")
    body_catch = live.find("bodyWeightError = errorText(error)", body_try)
    reread = live.find("const refreshed = await loadRace", body_catch)
    feature = live.find("loadCompletedFeatureStateForRace", reread)
    vector = live.find("completedFeatureVector", feature)
    require(0 <= body_try < body_catch < reread < feature < vector, "BODYWEIGHT_REFRESH_NOT_ATTEMPTED_BEFORE_FEATURE_VECTOR")

    require("snapshot.bodyWeightApplied === true" in guard, "DEADLINE_GUARD_BODYWEIGHT_PROVENANCE_MISSING")
    require("bodyWeightFetchedAt: body?.fetchedAt ?? null" in guard, "DEADLINE_GUARD_BODYWEIGHT_FETCH_TIME_MISSING")
    require("bodyWeightSnapshotSha256: body?.snapshotSha256 ?? null" in guard, "DEADLINE_GUARD_BODYWEIGHT_SHA_MISSING")
    require("remainingMs >= DEADLINE_GUARD_MS" in guard and "remainingMs <= DEADLINE_GUARD_ARM_MS" in guard, "DEADLINE_GUARD_T20_T15_WINDOW_INVALID")
    require("isDeadlineGuardMissed" in guard, "DEADLINE_GUARD_T15_MISS_AUDIT_MISSING")
    for forbidden in (
        "resolveOfficialBodyWeights(",
        "refreshOfficialBodyWeights(",
        "fetchFastJraOfficialOddsForRace(",
        "loadCompletedFeatureStateForRace(",
        "loadCompletedRecencyLearning(",
    ):
        require(forbidden not in guard, f"DEADLINE_GUARD_BODYWEIGHT_NETWORK_OR_RECOMPUTE_REINTRODUCED:{forbidden}")

    # Normal-race mutation is isolated. Public cron must never use the retired
    # v20 critical/live-lock path; both primary and backup own the same driver.
    require("publicSite.scheduled" not in public, "PUBLIC_CRON_REINTRODUCES_RETIRED_LIVE_PATH")
    require('import maintenanceSite from "./public-site-entry-v19.js";' in public, "PUBLIC_MAINTENANCE_ONLY_BASE_MISSING")
    require("runCompletedWorkerLiveLock" in driver and "runCompletedWorkerDeadlineGuard" in driver, "ISOLATED_LIVE_OWNER_MISSING")
    require(primary.get("main") == "src/live-deadline-entry-v2.ts", "PRIMARY_LIVE_DRIVER_MISMATCH")
    require(backup.get("main") == "src/live-deadline-entry-v2.ts", "BACKUP_LIVE_DRIVER_MISMATCH")

    # Removed GitHub stored-preview workflows/scripts must stay removed. The
    # T-20 rescue now runs inside the isolated Worker and D1 invariant layer.
    require(not (ROOT / ".github/workflows/auto-final-live-bets.yml").exists(), "OBSOLETE_GITHUB_FINALIZER_REINTRODUCED")
    require(not (ROOT / "scripts/run-stored-preview-deadline-backup.py").exists(), "OBSOLETE_STORED_PREVIEW_BACKUP_REINTRODUCED")
    require("horse_weight=COALESCE(excluded.horse_weight,rt_runners.horse_weight)" in direct, "DIRECT_SYNC_CAN_ERASE_CONFIRMED_BODYWEIGHT")

    cfg = json.loads(text("config/ten-year-completed-model.json"))
    require(str(cfg["runnerProbabilityModel"]["modelWeightsSha256"]) == EXPECTED_MODEL_SHA, "MODEL_CONFIG_SHA_CHANGED")
    require(sha256("models/ten-year-completed-model.txt") == EXPECTED_MODEL_SHA, "MODEL_WEIGHTS_CHANGED")
    require(len(cfg["runnerProbabilityModel"]["features"]) == 56, "MODEL_FEATURE_COUNT_CHANGED")

    print(json.dumps({
        "status": "BODYWEIGHT_ISOLATED_PREDEADLINE_LOCK_OK",
        "modelSha256": EXPECTED_MODEL_SHA,
        "featureCount": 56,
        "bodyweightRefreshOpenMinutes": 100,
        "previewOpenMinutes": 90,
        "previewRequiredMinutes": 30,
        "normalLockMinutes": 25,
        "deadlineGuardArmMinutes": 20,
        "hardDeadlineMinutes": 15,
        "postDeadlineBodyweightFetch": False,
        "postDeadlinePredictionRecompute": False,
        "postDeadlineFinalCreation": False,
        "publicNormalRaceMutation": False,
        "isolatedPrimaryBackup": True,
        "bodyweightAppliedWhenAvailable": True,
        "bodyweightFailureDoesNotSuppressPredeadlineOfficialPreview": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
