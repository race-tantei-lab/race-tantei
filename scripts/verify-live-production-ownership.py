from pathlib import Path


def text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

public29 = text("src/public-site-entry-v29.ts")
public34 = text("src/public-site-entry-v34.ts")
entry = text("src/live-deadline-entry-v2.ts")

for forbidden in [
    "runCompletedWorkerLiveLock",
    "runCompletedWorkerDeadlineGuard",
    "ensureCompletedRaceFinalAtDeadline",
    "probability_fallback",
]:
    if forbidden in public29:
        raise SystemExit(f"PUBLIC29_LIVE_MUTATION_STILL_PRESENT:{forbidden}")

for forbidden in ["runCompletedWorkerLiveLock", "runCompletedWorkerDeadlineGuard", "runDirectLiveTick", "shouldOpportunisticallyDrive"]:
    if forbidden in public34:
        raise SystemExit(f"PUBLIC34_LIVE_MUTATION_STILL_PRESENT:{forbidden}")

if 'pathname === "/_ops/live-tick"' not in public34 or 'status: 404' not in public34:
    raise SystemExit("PUBLIC_LIVE_TICK_ENDPOINT_NOT_HARD_DISABLED")

if "/_ops/live-tick" in entry:
    raise SystemExit("ISOLATED_DRIVER_MUST_NOT_EXPOSE_MUTATION_ENDPOINT")

for obsolete in [
    ".github/workflows/drive-live-tick.yml",
    ".github/workflows/auto-final-live-bets.yml",
]:
    if Path(obsolete).exists():
        raise SystemExit(f"OBSOLETE_LIVE_WORKFLOW_PRESENT:{obsolete}")

print("verify-live-production-ownership: ok")
