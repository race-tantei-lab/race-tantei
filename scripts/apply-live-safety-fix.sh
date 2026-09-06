#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path("scripts/verify-live-lock-safety.py")
s = p.read_text()
s = s.replace(
    'backup_wrangler.get("triggers", {}).get("crons", []) != ["* * * * *"]',
    'backup_wrangler.get("triggers", {}).get("crons", []) != ["2-59/5 * * * *"]',
)
s = s.replace(
    "backup standby must check primary health every minute",
    "backup standby must check primary health every five minutes",
)
marker = '        "WORKER_HARD_T15_START_MISSED",\n'
if '        "ids.length !== 15",\n' not in s:
    s = s.replace(
        marker,
        marker
        + '        "ids.length !== 15",\n'
        + '        "counts.size !== 3",\n'
        + '        "startMs - generationStartedMs <= DEADLINE_MS",\n'
        + '        "if (remaining <= DEADLINE_MS)",\n',
        1,
    )
old = '''        "Install persistent D1 runtime guards once",
        "scripts/install-race-day-runtime-guards.sql",
        "Verify persistent D1 runtime guards",
'''
s = s.replace(old, "", 1)
anchor = '''    for needle in (
        "Deploy primary live deadline Worker",
        "Deploy backup live deadline Worker",
        "src/live-deadline-entry-v3.ts",
        "wrangler.live-deadline.jsonc",
        "wrangler.live-deadline-backup.jsonc",
        "production/live-deadline",
    ):
        require(deploy, needle, "dual live deadline deploy")

'''
if 'migration = read(".github/workflows/migrate-live-runtime-guards.yml")' not in s:
    replacement = anchor + '''    for forbidden in ("wrangler d1 execute", "scripts/install-race-day-runtime-guards.sql"):
        forbid(deploy, forbidden, "normal live deploy must not touch D1 schema")

    migration = read(".github/workflows/migrate-live-runtime-guards.yml")
    for needle in (
        "scripts/install-race-day-runtime-guards.sql",
        "wrangler d1 execute race-tantei-phase0 --remote",
        "Verify required guards",
    ):
        require(migration, needle, "separate live D1 migration")

'''
    if anchor not in s:
        raise SystemExit("deploy verifier anchor not found")
    s = s.replace(anchor, replacement, 1)
p.write_text(s)
PY
grep -F '2-59/5 * * * *' scripts/verify-live-lock-safety.py
grep -F 'ids.length !== 15' scripts/verify-live-lock-safety.py
grep -F 'normal live deploy must not touch D1 schema' scripts/verify-live-lock-safety.py
grep -F 'migrate-live-runtime-guards.yml' scripts/verify-live-lock-safety.py
