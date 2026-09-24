from pathlib import Path

def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"LIVE_HARDENING_POLICY_MISSING:{label}:{token}")

def forbid(text: str, token: str, label: str) -> None:
    if token in text:
        raise SystemExit(f"LIVE_HARDENING_POLICY_FORBIDDEN:{label}:{token}")

live = read("src/v1/completed-worker-live-lock.ts")
guard = read("src/v1/completed-worker-deadline-guard.ts")
safety = read("src/v1/live-preview-safety.ts")
entry = read("src/live-deadline-entry-v2.ts")
wrapper = read("src/live-deadline-entry-v3.ts")
migration = read("scripts/install-race-day-runtime-guards.sql")
primary = read("wrangler.live-deadline.jsonc")
backup = read("wrangler.live-deadline-backup.jsonc")
deploy = read(".github/workflows/deploy-live-deadline.yml")

for token, label in [
    ("WHERE race_date=? AND start_time_utc>?", "selection-driven-future-coverage"),
    ("MAX_PREVIEW_GENERATIONS_PER_TICK = 1", "generation-budget"),
    ("MAX_PREVIEW_ATTEMPTS_PER_TICK = 1", "attempt-budget"),
    ("BODY_WEIGHT_ATTEMPT_OPEN_MS = 45 * 60 * 1000", "deferred-bodyweight"),
    ("BODYWEIGHT_DEFERRED_UNTIL_T45", "deferred-bodyweight-audit"),
    ("VERY_EARLY_PREVIEW_REFRESH_MS = 6 * 60 * 60 * 1000", "very-early-refresh"),
    ("EARLY_PREVIEW_REFRESH_MS = 20 * 60 * 1000", "early-refresh"),
    ("MID_PREVIEW_REFRESH_MS = 5 * 60 * 1000", "mid-refresh"),
    ("NEAR_PREVIEW_REFRESH_MS = 3 * 60 * 1000", "near-refresh"),
    ("INSERT INTO rt_live_preview_archive", "first-good-archive"),
    ("WORKER_HARD_T15_START_MISSED", "no-post-t15-generation"),
    ("WORKER_GENERATION_CROSSED_T15", "generation-cross-boundary-block"),
    ('new Set(["jra-fast-official", "jra-crawl-official"])', "official-odds-only"),
    ("loadCompletedRecencyLearning(", "canonical-recency"),
    ("completedRecencyBetFactor(", "canonical-bet-recency"),
]:
    require(live, token, label)
forbid(live, "PREVIEW_OPEN_MS", "fixed-preview-window")
forbid(live, "start_time_utc<=?", "fixed-preview-upper-bound")

for token, label in [
    ("DEADLINE_GUARD_MS = 15 * 60 * 1000", "hard-t15"),
    ("DEADLINE_GUARD_ARM_MS = 25 * 60 * 1000", "guard-arm-t25"),
    ("MAX_OFFICIAL_PREVIEW_AGE_MS = 12 * 60 * 60 * 1000", "same-day-last-good"),
    ("This path is deliberately tiny", "critical-window-only"),
    ("remaining < DEADLINE_GUARD_MS", "miss-audit"),
    ("await latestOfficialPreview(env.DB, raceId, now, startMs)", "stored-official-only"),
]:
    require(guard, token, label)
forbid(guard, "chooseCompletedProbabilityFallbackTickets", "fake-probability-final")
forbid(guard, 'oddsMode: "probability_fallback"', "fake-probability-final")

for token, label in [
    ("rt_live_preview_archive", "preview-archive-table"),
    ("rt_guard_probability_fallback_final_insert", "db-fake-odds-block"),
    ("PROBABILITY_FALLBACK_FORBIDDEN", "db-fake-odds-error"),
    ("rt_guard_official_odds_final_insert", "db-official-odds-guard"),
    ("OFFICIAL_JRA_ODDS_REQUIRED", "db-official-odds-error"),
]:
    require(migration, token, label)

for token, label in [
    ("acquireNamedLiveDeadlineLease", "named-guard-lease"),
    ("releaseNamedLiveDeadlineLease", "named-guard-release"),
    ("restoreNewestOfficialPreviewArchives", "archive-restore"),
]:
    require(safety, token, label)

for token, label in [
    ("runCompletedWorkerLiveLock", "isolated-heavy-live"),
    ("Heavy work is intentionally isolated from critical finalization", "heavy-isolation-comment"),
    ('status: "lease_busy"', "lease-busy-state"),
]:
    require(entry, token, label)
forbid(entry, "runCompletedWorkerDeadlineGuard", "heavy-driver-critical-guard")
forbid(entry, "restoreNewestOfficialPreviewArchives", "heavy-driver-archive-rescue")
forbid(entry, "auditLiveDeadlineSla", "heavy-driver-postwork-sla")

for token, label in [
    ('CRITICAL_GUARD_LEASE_KEY = "live_deadline_critical_guard:v1"', "critical-guard-lease"),
    ("runCriticalDeadlineProtection", "critical-guard"),
    ("runCompletedWorkerDeadlineGuard", "critical-guard-call"),
    ("restoreNewestOfficialPreviewArchives", "critical-archive-rescue"),
    ("runIsolatedLiveDeadlineTick", "heavy-driver-call"),
    ('PRIMARY_HEARTBEAT_KEY = "live_deadline_primary_heartbeat:v2"', "truthful-primary-heartbeat"),
    ('if (role === "backup" && await primaryIsAlive(env.DB)) return;', "backup-standby-after-guard"),
    ('String(result.status || "") !== "lease_busy"', "lease-busy-no-heartbeat"),
]:
    require(wrapper, token, label)
if wrapper.index("runCriticalDeadlineProtection") > wrapper.index("runIsolatedLiveDeadlineTick(liveEnv"):
    raise SystemExit("LIVE_HARDENING_POLICY_ORDER:critical-guard-must-run-before-heavy")

for token, label in [
    ('"main": "src/live-deadline-entry-v3.ts"', "primary-v3"),
    ('"crons": ["* * * * *"]', "primary-minute-cron"),
]:
    require(primary, token, label)
for token, label in [
    ('"main": "src/live-deadline-entry-v3.ts"', "backup-v3"),
    ('"crons": ["1-59/2 * * * *"]', "backup-two-minute-cron"),
]:
    require(backup, token, label)

for token, label in [
    ("Deploy primary live deadline Worker", "primary-deploy"),
    ("Deploy backup live deadline Worker", "backup-deploy"),
]:
    require(deploy, token, label)

print("verify-live-hardening-policy: ok")
