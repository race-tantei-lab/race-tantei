from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text()


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"LIVE_HARDENING_POLICY_MISSING:{label}:{token}")


live = read("src/v1/completed-worker-live-lock.ts")
guard = read("src/v1/completed-worker-deadline-guard.ts")
invariants = read("src/v1/completed-final-invariants.ts")
safety = read("src/v1/live-preview-safety.ts")
entry = read("src/live-deadline-entry-v2.ts")
fast = read("src/v1/jra-official-odds-fetch.ts")
crawl = read("src/v1/jra-official-odds.ts")
primary = read("wrangler.live-deadline.jsonc")
backup = read("wrangler.live-deadline-backup.jsonc")

for token, label in [
    ("const PREVIEW_OPEN_MS = 90 * 60 * 1000;", "preview-opens-t90"),
    ("const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;", "preview-required-t30"),
    ("const NORMAL_LOCK_MS = 25 * 60 * 1000;", "normal-final-t25"),
    ("const DEADLINE_MS = 15 * 60 * 1000;", "hard-t15"),
    ('new Set(["jra-fast-official", "jra-crawl-official"])', "official-odds-only"),
    ("cachedWorkerModel", "model-runtime-cache"),
    ("WORKER_HARD_T15_MISSED", "no-post-t15-generation"),
    ("WORKER_GENERATION_CROSSED_T15", "generation-cross-boundary-block"),
    ("previewMissingUrgentRaceIds", "t30-preview-critical"),
]:
    require(live, token, label)

for token, label in [
    ("remainingMs >= DEADLINE_GUARD_MS", "guard-lower-bound-t15"),
    ("remainingMs <= DEADLINE_GUARD_ARM_MS", "guard-upper-bound-t20"),
    ("isDeadlineGuardMissed", "guard-hard-miss"),
    ("deadlineMissedRaceIds", "guard-miss-audit"),
]:
    require(guard, token, label)

for token, label in [
    ("FINAL_BET_DEADLINE_PASSED", "db-final-bet-deadline"),
    ("FINAL_STATE_DEADLINE_PASSED", "db-final-state-deadline"),
    ("OFFICIAL_JRA_ODDS_REQUIRED", "db-official-odds"),
    ("PROBABILITY_FALLBACK_FORBIDDEN", "db-fake-odds-forbidden"),
]:
    require(invariants, token, label)

for token, label in [
    ("rt_live_preview_archive", "append-only-preview-archive"),
    ("rt_archive_live_preview_insert", "preview-insert-archive-trigger"),
    ("rt_archive_live_preview_update", "preview-update-archive-trigger"),
    ("rt_live_deadline_lease", "driver-lease"),
    ("restoreNewestOfficialPreviewArchives", "last-good-preview-restore"),
    ("previewMissingByT40RaceIds", "sla-t40"),
    ("previewMissingByT30RaceIds", "sla-t30"),
    ("finalMissingByT25RaceIds", "sla-t25"),
    ("finalMissingByT20RaceIds", "sla-t20"),
    ("deadlineMissedRaceIds", "sla-t15"),
]:
    require(safety, token, label)

for token, label in [
    ("acquireLiveDeadlineLease", "entry-lease"),
    ("restoreNewestOfficialPreviewArchives", "entry-archive-restore"),
    ("auditLiveDeadlineSla", "entry-sla"),
    ("new Date()", "entry-wall-clock"),
    ('return new Response("NOT_FOUND", { status: 404 });', "no-public-mutation-endpoint"),
]:
    require(entry, token, label)
if "/_ops/live-tick" in entry:
    raise SystemExit("LIVE_HARDENING_POLICY_FORBIDDEN:public-live-tick-endpoint")

for token, label in [
    ('"main": "src/live-deadline-entry-v2.ts"', "primary-v2-entry"),
    ('"crons": ["* * * * *"]', "primary-every-minute"),
]:
    require(primary, token, label)
for token, label in [
    ('"name": "race-tantei-live-deadline-backup"', "backup-worker"),
    ('"main": "src/live-deadline-entry-v2.ts"', "backup-v2-entry"),
    ('"crons": ["2-59/5 * * * *"]', "backup-staggered-five-minute"),
]:
    require(backup, token, label)

for token, label in [
    ("const FETCH_BUDGET_MS = 25_000;", "jra-total-budget"),
    ("JRA_ODDS_FETCH_BUDGET_EXHAUSTED", "jra-fast-budget-enforcement"),
    ("deadlineMs", "jra-fast-deadline-propagation"),
]:
    require(fast, token, label)
for token, label in [
    ("const CRAWL_PAGE_TIMEOUT_MS = 3_500;", "jra-crawl-page-timeout"),
    ("deadlineMs = Number.POSITIVE_INFINITY", "jra-crawl-deadline"),
    ("JRA_ODDS_CRAWL_BUDGET_EXHAUSTED", "jra-crawl-budget-enforcement"),
]:
    require(crawl, token, label)

print("verify-live-hardening-policy: ok")
