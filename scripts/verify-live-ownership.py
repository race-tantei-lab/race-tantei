#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_json(path: str):
    return json.loads(read(path))


def collect_public_fetch_chain(entry: str) -> str:
    current = Path(entry)
    seen: set[str] = set()
    out: list[str] = []
    pattern = re.compile(r'import\s+publicSite\s+from\s+["\'](\./public-site-entry-v\d+)\.js["\']')
    while True:
        key = current.as_posix()
        if key in seen:
            fail(f"public entry import cycle: {key}")
        seen.add(key)
        text = read(key)
        out.append(text)
        match = pattern.search(text)
        if not match:
            break
        current = current.parent / f"{match.group(1)}.ts"
    return "\n".join(out)


def main() -> None:
    manifest = load_json("config/canonical-production-manifest.json")
    wrangler = load_json("wrangler.jsonc")
    primary = load_json("wrangler.live-deadline.jsonc")
    backup = load_json("wrangler.live-deadline-backup.jsonc")

    entry = str(wrangler.get("main") or "")
    if entry != manifest["site"]["entry"]:
        fail(f"public entry identity mismatch: {entry} != {manifest['site']['entry']}")
    if entry != "src/public-site-entry-v34.ts":
        fail(f"unexpected canonical public entry: {entry}")

    top = read(entry)
    chain = collect_public_fetch_chain(entry)

    # Fetch may keep the historical wrapper chain for UI compatibility, but the
    # public cron must terminate at the audited maintenance-only v19 chain.
    required_public = (
        'import maintenanceSite from "./public-site-entry-v19.js";',
        "maintenanceSite.scheduled",
        "runCompletedWin5Scheduled",
        "runUpcomingEntryWorkerRepair",
        "runUpcomingEntryDerivedRepair",
    )
    for needle in required_public:
        if needle not in top:
            fail(f"public exclusive-owner marker missing: {needle}")

    forbidden_public = (
        "publicSite.scheduled",
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "freezeCompletedWorkerSelectionIfNeeded",
        "runDirectLiveTick",
    )
    for needle in forbidden_public:
        if needle in top:
            fail(f"public cron can reach normal-race mutation marker: {needle}")

    if 'pathname === "/_ops/live-tick"' not in chain or 'status: 404' not in chain:
        fail("legacy public live-tick route is not hard-disabled")

    live_entry_path = str(manifest["production"]["liveDeadlineEntry"])
    live_entry = read(live_entry_path)
    for cfg, label in ((primary, "primary"), (backup, "backup")):
        if cfg.get("main") != live_entry_path:
            fail(f"{label} live-deadline entry mismatch")
        bindings = cfg.get("d1_databases", [])
        if len(bindings) != 1 or bindings[0].get("database_id") != manifest["site"]["d1DatabaseId"]:
            fail(f"{label} live-deadline D1 mismatch")

    required_live = (
        "acquireLiveDeadlineLease",
        "freezeCompletedWorkerSelectionIfNeeded",
        "runCompletedWorkerLiveLock",
        "runCompletedWorkerDeadlineGuard",
        "verifyPriorDayLearningReady",
        "PRIOR_LEARNING_FAIL_OPEN_MINUTE_JST",
        'status: "waiting_prior_learning"',
        "PRIOR_DAY_LEARNING_FAIL_OPEN",
        "LIVE_DEADLINE_HARD_T15_BREACH",
    )
    for needle in required_live:
        if needle not in live_entry:
            fail(f"isolated live owner marker missing: {needle}")

    if "/_ops/live-tick" in live_entry:
        fail("isolated live-deadline Worker exposes a mutation endpoint")

    if manifest["production"].get("publicLiveMutationEnabled") is not False:
        fail("manifest publicLiveMutationEnabled must remain false")

    print(
        "LIVE_OWNERSHIP_OK",
        f"public={entry}",
        f"live={live_entry_path}",
        "public_cron=maintenance_only",
        "normal_race_mutation=isolated_only",
        "prior_learning_gate=isolated",
    )


if __name__ == "__main__":
    main()
