#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

ALLOW_AUTOMATIC_D1 = {
    "deploy.yml",
    "deploy-live-deadline.yml",
    "verify-live-deadline-production.yml",
    "verify-upcoming-production-program.yml",
    "race-day-bootstrap.yml",
    "continuous-final-rule-learning.yml",
    "guard-automatic-production-d1.yml",
    "normalize-automatic-production-d1.yml",
}

D1_MARKERS = (
    "CLOUDFLARE_D1_DATABASE_ID",
    "wrangler d1 execute",
    "/d1/database/",
    "race-tantei-phase0.race-tantei.workers.dev/api/validation/",
    "race-tantei-phase0.race-tantei.workers.dev/api/public/",
)

def trigger_span(lines: list[str]) -> tuple[int, int] | None:
    start = next((i for i, line in enumerate(lines) if line.rstrip("\n") == "on:"), None)
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1] not in (" ", "\t"):
            end = i
            break
    return start, end

def trigger_text(text: str) -> str:
    lines = text.splitlines(keepends=True)
    span = trigger_span(lines)
    if not span:
        return ""
    a, b = span
    return "".join(lines[a:b])

def has_auto_trigger(text: str) -> bool:
    block = trigger_text(text)
    return bool(re.search(r"(?m)^\s{2}(?:push|schedule):", block))

def touches_prod_d1(text: str) -> bool:
    low = text.lower()
    return any(marker.lower() in low for marker in D1_MARKERS)

def manual_only(text: str) -> str:
    lines = text.splitlines(keepends=True)
    span = trigger_span(lines)
    if not span:
        raise RuntimeError("ON_BLOCK_NOT_FOUND")
    a, b = span
    replacement = ["on:\n", "  workflow_dispatch:\n", "\n"]
    return "".join(lines[:a] + replacement + lines[b:])

changed = []
for path in sorted(WF.glob("*.y*ml")):
    if path.name in ALLOW_AUTOMATIC_D1:
        continue
    text = path.read_text(encoding="utf-8")
    if not has_auto_trigger(text) or not touches_prod_d1(text):
        continue
    new = manual_only(text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed.append(path.name)

print(f"NORMALIZED_AUTOMATIC_PROD_D1_WORKFLOWS={len(changed)}")
for name in changed:
    print(name)
