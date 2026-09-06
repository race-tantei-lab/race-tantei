#!/usr/bin/env bash
set -euo pipefail
python3 -c 'from pathlib import Path; p=Path("scripts/verify-live-lock-safety.py"); s=p.read_text(); s=s.replace("backup_wrangler.get(\"triggers\", {}).get(\"crons\", []) != [\"* * * * *\"]", "backup_wrangler.get(\"triggers\", {}).get(\"crons\", []) != [\"2-59/5 * * * *\"]"); s=s.replace("backup standby must check primary health every minute", "backup standby must check primary health every five minutes"); marker="        \"WORKER_HARD_T15_START_MISSED\",\n"; addition=marker+"        \"ids.length !== 15\",\n        \"counts.size !== 3\",\n        \"startMs - generationStartedMs <= DEADLINE_MS\",\n        \"if (remaining <= DEADLINE_MS)\",\n"; s=s.replace(marker, addition, 1) if "ids.length !== 15" not in s else s; p.write_text(s)'
grep -F '2-59/5 * * * *' scripts/verify-live-lock-safety.py
grep -F 'ids.length !== 15' scripts/verify-live-lock-safety.py
grep -F 'startMs - generationStartedMs <= DEADLINE_MS' scripts/verify-live-lock-safety.py
