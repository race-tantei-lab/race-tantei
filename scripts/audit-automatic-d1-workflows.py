#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

# These are the only workflows allowed to access production D1 automatically.
# Everything else that can touch production D1 must be manual-only.
ALLOW_AUTOMATIC_D1 = {
    "deploy.yml",
    "deploy-live-deadline.yml",
    "verify-upcoming-production-program.yml",
    "race-day-bootstrap.yml",
    "sync-upcoming-entries-direct.yml",  # bounded pre-race fallback; heavy sync only when entry readiness is incomplete
    "critical-auto-bet-generation.yml",  # bounded T-45..T-15 per-race recovery
    "continuous-final-rule-learning.yml",  # weekly Tuesday night only
    "adhoc-race-predict.yml",  # isolated 3/day hard cap; checks account D1 headroom before heavy prediction
}

D1_MARKERS = (
    "CLOUDFLARE_D1_DATABASE_ID",
    "wrangler d1 execute",
    "/d1/database/",
    "race-tantei-phase0.race-tantei.workers.dev/api/",
)

def trigger_block(text: str) -> str:
    m = re.search(r"(?ms)^on:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", text)
    return m.group("body") if m else ""

def has_auto_trigger(text: str) -> bool:
    block = trigger_block(text)
    return bool(re.search(r"(?m)^\s{2}(?:push|schedule):", block))

def auto_modes(text: str) -> list[str]:
    block = trigger_block(text)
    out = []
    if re.search(r"(?m)^\s{2}push:", block):
        out.append("push")
    if re.search(r"(?m)^\s{2}schedule:", block):
        out.append("schedule")
    return out

def d1_markers(text: str) -> list[str]:
    low = text.lower()
    found = []
    for marker in D1_MARKERS:
        if marker.lower() in low:
            found.append(marker)
    return found

rows = []
violations = []
for path in sorted(WF.glob("*.y*ml")):
    text = path.read_text(encoding="utf-8")
    if not has_auto_trigger(text):
        continue
    markers = d1_markers(text)
    if not markers:
        continue
    row = {
        "workflow": path.name,
        "automatic": auto_modes(text),
        "markers": markers,
        "allowlisted": path.name in ALLOW_AUTOMATIC_D1,
    }
    rows.append(row)
    if not row["allowlisted"]:
        violations.append(row)

print(json.dumps({
    "automaticProductionD1Workflows": rows,
    "violations": violations,
    "allowlist": sorted(ALLOW_AUTOMATIC_D1),
}, ensure_ascii=False, indent=2))

# The sole newly authorized ad-hoc automatic reader must preserve a strict
# D1 headroom check, per-job row budget and canonical-write block. Fail closed
# if anyone removes one of these guards later.
adhoc = ROOT / "scripts" / "adhoc-race-runner.mjs"
adhoc_workflow = WF / "adhoc-race-predict.yml"
if adhoc_workflow.exists() and adhoc.exists():
    runner = adhoc.read_text(encoding="utf-8")
    workflow = adhoc_workflow.read_text(encoding="utf-8")
    for symbol in ("MAX_BEFORE_ROWS", "MAX_JOB_ROWS", "checkAccountBudget()", "CANONICAL_D1_WRITE_BLOCKED", "assertBefore(cutoffMs)", "claim(task.raceId)"):
        if symbol not in runner:
            violations.append({"workflow": adhoc_workflow.name, "guardMissing": symbol})
    if "steps.peek.outputs.pending == 'yes'" not in workflow:
        violations.append({"workflow": adhoc_workflow.name, "guardMissing": "queue_pending_gate"})
else:
    violations.append({"workflow": "adhoc-race-predict.yml", "guardMissing": "guarded_runner_or_workflow_file"})

if violations:
    print("\nAUTO_D1_POLICY_VIOLATION", file=sys.stderr)
    for row in violations:
        print(f"- {row['workflow']} auto={','.join(row['automatic'])} markers={','.join(row['markers'])}", file=sys.stderr)
    sys.exit(2)

print("AUTO_D1_POLICY_OK")
