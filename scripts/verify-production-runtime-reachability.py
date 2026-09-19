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
IMPORT_RE = re.compile(r'(?ms)^\\s*import\\s+(?!type\\b).*?\\s+from\\s+["\\\'](\\.[^"\\\']+)["\\\']\\s*;?')
SIDE_EFFECT_RE = re.compile(r'(?m)^\\s*import\\s+["\\\'](\\.[^"\\\']+)["\\\']\\s*;?')

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

def main() -> None:
    configs: dict[str, Path] = {}
    for cfg_name in ENTRY_CONFIGS:
        cfg = json.loads((ROOT / cfg_name).read_text(encoding="utf-8"))
        configs[cfg_name] = Path(str(cfg["main"]))
    closures = {name: closure(entry) for name, entry in configs.items()}
    live = closures["wrangler.live-deadline.jsonc"] | closures["wrangler.live-deadline-backup.jsonc"]
    win5 = closures["wrangler.win5.jsonc"] | closures["wrangler.win5-backup.jsonc"]
    public = closures["wrangler.jsonc"]
    heavy = Path("src/v1/completed-recency-learning.ts")
    if heavy in live:
        raise AssertionError("raw recency module is runtime-reachable from live Worker")
    if heavy in win5:
        raise AssertionError("raw recency module is runtime-reachable from WIN5 Worker")
    forbidden_public = (
        "date(\'now\',\'-14 days\')",
        "syncAndSettle(",
        "settlePublicBets(",
        "runPublicDataSync(",
        "syncOfficialCalendarDay(",
    )
    violations: list[tuple[str, str]] = []
    for path in sorted(public):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        for needle in forbidden_public:
            if needle in text:
                violations.append((str(path), needle))
    if violations:
        raise AssertionError("public runtime forbidden D1/mutation paths: " + repr(violations))
    print(json.dumps({
        "PRODUCTION_RUNTIME_REACHABILITY_OK": True,
        "publicModules": len(public),
        "liveModules": len(live),
        "win5Modules": len(win5),
        "rawRecencyInPublic": heavy in public,
        "rawRecencyInLive": heavy in live,
        "rawRecencyInWin5": heavy in win5,
        "publicForbiddenViolations": violations,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
