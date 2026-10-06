#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_CONFIGS = (
    "wrangler.jsonc",
    "wrangler.live-deadline.jsonc",
    "wrangler.live-deadline-backup.jsonc",
    "wrangler.win5.jsonc",
    "wrangler.win5-backup.jsonc",
    "wrangler.entry-maintenance.jsonc",
)
IMPORT_RE = re.compile(r'(?ms)^\s*import\s+(?!type\b).*?\s+from\s+["\'](\.[^"\']+)["\']\s*;?')
SIDE_EFFECT_RE = re.compile(r'(?m)^\s*import\s+["\'](\.[^"\']+)["\']\s*;?')

def resolve(source: Path, spec: str) -> Path | None:
    base = (source.parent / spec).resolve()
    candidates = [base]
    if base.suffix == ".js":
        candidates.extend([base.with_suffix(".ts"), base.with_suffix(".tsx")])
    elif not base.suffix:
        candidates.extend([Path(str(base) + ".ts"), Path(str(base) + ".tsx"), base / "index.ts"])
    for candidate in candidates:
        try:
            rel = candidate.relative_to(ROOT)
        except ValueError:
            continue
        if candidate.exists():
            return rel
    return None

def imports(path: Path) -> list[Path]:
    full = ROOT / path
    text = full.read_text(encoding="utf-8")
    specs = IMPORT_RE.findall(text) + SIDE_EFFECT_RE.findall(text)
    out: list[Path] = []
    for spec in specs:
        resolved = resolve(full, spec)
        if resolved is not None:
            out.append(resolved)
    return out

def closure(entry: Path) -> set[Path]:
    seen: set[Path] = set()
    stack = [entry]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix in {".ts", ".tsx"}:
            stack.extend(imports(path))
    return seen

def forbid(path: str, needles: tuple[str, ...], violations: list[tuple[str, str]]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle in text:
            violations.append((path, needle))

def main() -> None:
    configs: dict[str, Path] = {}
    for cfg_name in ENTRY_CONFIGS:
        cfg = json.loads((ROOT / cfg_name).read_text(encoding="utf-8"))
        configs[cfg_name] = Path(str(cfg["main"]))
    closures = {name: closure(entry) for name, entry in configs.items()}
    live = closures["wrangler.live-deadline.jsonc"] | closures["wrangler.live-deadline-backup.jsonc"]
    win5 = closures["wrangler.win5.jsonc"] | closures["wrangler.win5-backup.jsonc"]
    public = closures["wrangler.jsonc"]

    canonical_recency = Path("src/v1/completed-recency-learning.ts")
    if canonical_recency not in live:
        raise AssertionError("canonical recency module is not runtime-reachable from live Worker")
    if canonical_recency in win5:
        raise AssertionError("canonical recency module is runtime-reachable from WIN5 Worker")

    violations: list[tuple[str, str]] = []
    forbid("src/public-site-entry.ts", ("runPublicDataSync(", "ctx.waitUntil("), violations)
    forbid("src/public-site-entry-v2.ts", ("syncOfficialCalendarDay(", "syncCalendarWindow(", "expandRecentDiscovery(", "ctx.waitUntil(", "ensureSchema("), violations)
    forbid("src/public-site-entry-v3.ts", ("syncOfficialCalendarDay(", "handleCanonicalHistorySeed(", "/internal/refresh-current"), violations)
    forbid("src/public-site-entry-v8.ts", ("date('now','-14 days')", "settlePublicBets("), violations)
    forbid("src/public-site-entry-v9.ts", ("date('now','-14 days')", "syncAndSettle(", "syncFinishedPayouts(", "settleFinishedBets("), violations)
    if violations:
        raise AssertionError("public request runtime forbidden D1/mutation paths: " + repr(violations))

    print(json.dumps({
        "PRODUCTION_RUNTIME_REACHABILITY_OK": True,
        "publicModules": len(public),
        "liveModules": len(live),
        "win5Modules": len(win5),
        "canonicalRecencyInPublic": canonical_recency in public,
        "canonicalRecencyInLive": canonical_recency in live,
        "canonicalRecencyInWin5": canonical_recency in win5,
        "publicRequestMutationViolations": violations,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
