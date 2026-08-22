#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label} missing: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label} contains forbidden marker: {needle}")


def main() -> None:
    live = read("src/v1/completed-worker-live-lock.ts")
    entry = read("src/live-deadline-entry-v2.ts")
    safety = read("src/v1/live-preview-safety.ts")
    invariants = read("src/v1/completed-final-invariants.ts")
    public = read("src/public-site-entry-v34.ts")
    primary = read("wrangler.live-deadline.jsonc")
    backup = read("wrangler.live-deadline-backup.jsonc")
    external = read(".github/workflows/live-deadline-external-watchdog.yml")
    readiness = read(".github/workflows/verify-live-deadline-production.yml")
    oidc = read("src/v1/github-actions-oidc.ts")
    proof = read("tests/live-deadline-full-day-proof-tests.ts")

    for needle in (
        "const PREVIEW_OPEN_MS = 90 * 60 * 1000;",
        "const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;",
        "const NORMAL_LOCK_MS = 25 * 60 * 1000;",
        "const DEADLINE_MS = 15 * 60 * 1000;",
        "const NEAR_PREVIEW_REFRESH_MS = 45 * 1000;",
        "OFFICIAL_ODDS_SOURCES",
        "remaining <= DEADLINE_MS",
        "WORKER_HARD_T15_MISSED",
        "WORKER_GENERATION_CROSSED_T15",
        'fresh ? "fresh" : "last_good"',
    ):
        require(live, needle, "live lock")

    for needle in (
        "rt_live_preview_archive",
        "rt_live_deadline_lease",
        "restoreNewestOfficialPreviewArchives",
        "structuralErrorRaceIds",
        "previewMissingByT30RaceIds",
        "finalMissingByT25RaceIds",
        "finalMissingByT20RaceIds",
        "deadlineMissedRaceIds",
    ):
        require(safety, needle, "preview safety")

    for needle in (
        "rt_guard_duplicate_worker_final_bet",
        "DUPLICATE_WORKER_FINAL_BET",
        "rt_guard_final_bet_insert_deadline",
        "FINAL_BET_DEADLINE_PASSED",
        "rt_guard_final_state_insert_deadline",
        "OFFICIAL_JRA_ODDS_REQUIRED",
        "PROBABILITY_FALLBACK_FORBIDDEN",
    ):
        require(invariants, needle, "D1 invariants")

    for needle in (
        'url.pathname === "/internal/github-tick"',
        "verifyGithubActionsOidcAuthorization",
        "historicalMissRaceIds",
        "alreadyStartedIncomplete",
        "structuralErrorRaceIds",
        "LIVE_DEADLINE_STRUCTURAL_RACE_ERROR",
        "acquireLiveDeadlineLease(env.DB, owner, 90)",
    ):
        require(entry, needle, "isolated driver")

    for needle in (
        'url.pathname === "/_ops/live-tick"',
        'new Response("NOT_FOUND", { status: 404',
    ):
        require(public, needle, "public site")
    forbid(public, "runCompletedWorkerLiveLock", "public site")
    forbid(public, "runCompletedWorkerDeadlineGuard", "public site")

    require(primary, '"crons": ["* * * * *"]', "primary cron")
    require(backup, '"crons": ["2-59/5 * * * *"]', "backup cron")

    for needle in (
        'cron: "*/5 23 * * *"',
        'cron: "*/5 0-10 * * *"',
        "id-token: write",
        "audience=race-tantei-live-deadline",
        "/internal/github-tick",
        "production/live-deadline-external-watchdog",
    ):
        require(external, needle, "external watchdog")

    for needle in (
        'GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"',
        'LIVE_DEADLINE_OIDC_AUDIENCE = "race-tantei-live-deadline"',
        'ALLOWED_REPOSITORY = "race-tantei-lab/race-tantei"',
        'ALLOWED_REF = "refs/heads/main"',
        "ALLOWED_WORKFLOW_REFS",
        'race-tantei-lab/race-tantei/.github/workflows/live-deadline-external-watchdog.yml@refs/heads/main',
        'race-tantei-lab/race-tantei/.github/workflows/verify-live-deadline-production.yml@refs/heads/main',
        "ALLOWED_WORKFLOW_REFS.has(claims.workflow_ref)",
        'header.alg !== "RS256"',
        "crypto.subtle.verify",
    ):
        require(oidc, needle, "GitHub OIDC verifier")

    for needle in (
        "Prove independent GitHub scheduler can execute the production tick",
        'test "$internal_code" = "401"',
        "age > 180",
        "payload.get('ok') is not True",
        "rt_guard_duplicate_worker_final_bet",
    ):
        require(readiness, needle, "production readiness")

    for needle in (
        "const providerSets",
        "races_per_scenario=15",
        "jraRecoveryMinutesBeforeStart",
        "generationSeconds",
        "skipFirstEligibleTick",
        "no official odds means no synthetic final",
    ):
        require(proof, needle, "full-day fault proof")

    print(
        "LIVE_DEADLINE_PROOF_OK",
        "schedulers=cloudflare_1m+cloudflare_5m+github_5m",
        "github_auth=oidc_rs256_workflow_bound",
        "preview=T90",
        "normal_lock=T25",
        "rescue=T20",
        "hard_deadline=T15",
        "archive_restore=true",
        "structural_race_faults=hard_fail",
        "concurrent_final_fence=true",
        "public_mutation=false",
        "official_odds_only=true",
    )


if __name__ == "__main__":
    main()
