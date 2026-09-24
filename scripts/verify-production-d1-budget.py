#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def cfg(path: str) -> dict:
    return json.loads(read(path))

def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)

def require_text(text: str, needle: str, label: str) -> None:
    require(needle in text, f"{label} missing: {needle}")

def forbid_text(text: str, needle: str, label: str) -> None:
    require(needle not in text, f"{label} contains forbidden production D1 path: {needle}")

def main() -> None:
    public = cfg("wrangler.jsonc")
    live = cfg("wrangler.live-deadline.jsonc")
    live_backup = cfg("wrangler.live-deadline-backup.jsonc")
    win5 = cfg("wrangler.win5.jsonc")
    win5_backup = cfg("wrangler.win5-backup.jsonc")
    entry = cfg("wrangler.entry-maintenance.jsonc")
    guardian = cfg("wrangler.live-deadline-guardian.jsonc")
    guardian_backup = cfg("wrangler.live-deadline-guardian-backup.jsonc")

    require(public["triggers"]["crons"] == ["*/15 * * * *"], "public cron must stay 15m")
    require(live["triggers"]["crons"] == ["* * * * *"], "live primary cron must stay 1m")
    require(live_backup["triggers"]["crons"] == ["1-59/2 * * * *"], "live backup cron must stay 2m")
    require(win5["triggers"]["crons"] == ["* * * * *"], "WIN5 primary cron must stay 1m")
    require(win5_backup["triggers"]["crons"] == ["3-59/5 * * * *"], "WIN5 backup cron must stay 5m staggered")
    require(entry["triggers"]["crons"] == [], "standalone entry maintenance cron must stay disabled")
    require(guardian["triggers"]["crons"] == [], "obsolete guardian primary cron must stay disabled")
    require(guardian_backup["triggers"]["crons"] == [], "obsolete guardian backup cron must stay disabled")

    public_v13 = read("src/public-site-entry-v13.ts")
    for forbidden in ("runPublicDataSync", "syncOfficialCalendarDay", "backfillRaceNamesForDate", "backfillHistoricalRaceNames"):
        forbid_text(public_v13, forbidden, "public-v13 GET purity")

    public_v16 = read("src/public-site-entry-v16.ts")
    forbid_text(public_v16, "WHERE race_date>?", "public-v16 growing calendar GET")
    require_text(public_v16, "readPublicCalendarCache(db)", "public-v16 cached calendar GET")
    require_text(public_v16, "embeddedRecentCalendar()", "public-v16 quota-lock fallback")

    public_v37 = read("src/public-site-entry-v37-core.ts")
    for forbidden in ("CREATE INDEX IF NOT EXISTS", "await recent30(db, today)"):
        forbid_text(public_v37, forbidden, "public-v37 GET/runtime DDL")
    calendar_cache = read("src/v1/public-calendar-cache.ts")
    require_text(calendar_cache, "REFRESH_MS = 6 * 60 * 60 * 1000", "public calendar cache")
    require_text(calendar_cache, "state_key=?", "public calendar cache one-row read")

    live_runtime = read("src/v1/completed-worker-live-lock.ts")
    win5_runtime = read("src/v1/completed-win5.ts")
    require_text(live_runtime, 'from "./completed-recency-learning"', "live canonical recency module")
    require_text(win5_runtime, 'from "./completed-recency-neutral"', "WIN5 neutral recency module")
    forbid_text(live_runtime, 'from "./completed-recency-neutral"', "live neutral recency module")
    forbid_text(win5_runtime, 'neutralCompletedRecencyLearning, type', "WIN5 runtime mixed raw recency import")

    live_deploy = read(".github/workflows/deploy-live-deadline.yml")
    win5_deploy = read(".github/workflows/deploy-win5.yml")
    require_text(live_deploy, '"src/v1/completed-recency-neutral.ts"', "live deploy trigger")
    require_text(win5_deploy, '"src/v1/completed-recency-neutral.ts"', "WIN5 deploy trigger")

    # Browser GETs are display-only. The old v8/v9 mutation paths caused D1 use
    # to scale with page traffic and repeatedly scanned 14 days of bets/results.
    public_v8 = read("src/public-site-entry-v8.ts")
    public_v9 = read("src/public-site-entry-v9.ts")
    for source, label in ((public_v8, "public-v8"), (public_v9, "public-v9")):
        for forbidden in (
            "date('now','-14 days')",
            "syncAndSettle(",
            "syncFinishedPayouts(",
            "settleFinishedBets(",
            "settlePublicBets(",
        ):
            forbid_text(source, forbidden, label)

    recovery = read("src/public-site-entry-recovery-20260906.ts")
    bounded_settlement = read("src/v1/bounded-result-settlement.ts")
    require_text(recovery, "await runBoundedResultSettlement(env, now)", "public bounded settlement owner")
    require_text(bounded_settlement, "MAX_CANDIDATES_PER_TICK = 15", "bounded settlement cap")
    forbid_text(bounded_settlement, "date('now','-14 days')", "bounded settlement")
    forbid_text(bounded_settlement, "date('now','-30 days')", "bounded settlement")

    # Standard live and WIN5 race-day scoring may use only precomputed ML tables;
    # raw historical delta/recency scans are prohibited in automated Workers.
    live_lock = read("src/v1/completed-worker-live-lock.ts")
    require_text(live_lock, "{ includeHistoricalDelta: false }", "live precomputed features")
    require_text(live_lock, "LIVE_HISTORY_DISABLED_FREE_TIER_PRECOMPUTED_ONLY", "live neutral recency")
    forbid_text(live_lock, "loadCompletedRecencyLearning(", "live raw recency")

    win5_core = read("src/v1/completed-win5.ts")
    require_text(win5_core, "{ includeHistoricalDelta: false }", "WIN5 precomputed features")
    require_text(win5_core, "WIN5_HISTORY_DISABLED_FREE_TIER_PRECOMPUTED_ONLY", "WIN5 neutral recency")
    forbid_text(win5_core, "loadCompletedRecencyLearning(", "WIN5 raw recency")

    recovery_source = read("src/public-site-entry-recovery-20260906.ts")
    require_text(recovery_source, 'import { runPublishedEntryMaintenance } from "./v1/published-entry-maintenance.js";', "public owns published entry maintenance")
    require_text(recovery_source, "await runPublishedEntryMaintenance(env, now)", "public owns published entry maintenance")

    db_source = read("src/v1/db.ts")
    require_text(db_source, "UPDATE rt_races", "entry URL persistence")
    require_text(db_source, "SET entry_url=?,entry_updated_at=CURRENT_TIMESTAMP", "entry URL persistence")
    require_text(db_source, "WHERE race_id=? AND TRIM(COALESCE(entry_url,''))<>TRIM(?)", "entry URL persistence")

    entry_main = read("src/published-entry-maintenance-entry.ts")
    for needle in (
        'import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";',
        "PUBLISHED_ENTRY_NON_RACE_DAY_SKIP",
        "if (!preparationDay && !raceDay.shouldRun)",
        "await runPublishedEntryMaintenance(env, now)",
    ):
        require_text(entry_main, needle, "entry maintenance gate")
    require(
        entry_main.index("if (!preparationDay && !raceDay.shouldRun)")
        < entry_main.index("await runPublishedEntryMaintenance(env, now)"),
        "entry maintenance must gate before first D1 maintenance call",
    )

    # The race-day quota may be touched automatically only by bootstrap, the
    # bounded per-race T-45..T-15 recovery, Thu/Fri upcoming-program preflight,
    # and Tuesday-night learning. Historical audits and ad-hoc diagnostics stay manual-only.
    auto_d1 = {
        "race-day-bootstrap.yml",
        "critical-auto-bet-generation.yml",
        "verify-upcoming-production-program.yml",
        "continuous-final-rule-learning.yml",
    }
    d1_markers = (
        "CLOUDFLARE_D1_DATABASE_ID",
        "wrangler d1 execute",
        "wrangler d1 insights",
        "race-tantei-phase0 --remote",
    )
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        block_match = re.search(r"(?ms)^on:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", text)
        block = block_match.group("body") if block_match else ""
        automatic = bool(re.search(r"(?m)^\s{2}(?:push|schedule):", block))
        touches_d1 = any(marker.lower() in text.lower() for marker in d1_markers)
        if automatic and touches_d1 and path.name not in auto_d1:
            raise AssertionError(f"automatic production D1 workflow forbidden: {path.name}")

    # Research/training workflows that touch production D1 cannot auto-run from
    # source pushes. Continuous learning is permitted only on Tuesday JST.
    heavy_markers = (
        "train-payout-segment-ensemble.mjs",
        "light-barbell",
        "light-policy-aware",
        "light-specialized",
    )
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        if any(marker in lower for marker in heavy_markers):
            if path.name == "continuous-final-rule-learning.yml":
                require('cron: "37 12 * * 2"' in text or "cron: '37 12 * * 2'" in text, "continuous learning must stay Tuesday 21:37 JST")
                continue
            forbid_text(text, "push:", f"research workflow {path.name}")
            forbid_text(text, "schedule:", f"research workflow {path.name}")

    print(
        "PRODUCTION_D1_BUDGET_SAFETY_OK",
        "browser_mutation=false",
        "legacy_14d_scan=false",
        "live_canonical_learning=true",
        "win5_raw_history=false",
        "entry_cron=disabled_public15m_owner",
        "guardian_crons=disabled",
        "research_push_d1=false",
    )

if __name__ == "__main__":
    main()
