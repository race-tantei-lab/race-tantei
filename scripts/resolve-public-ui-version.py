#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_RE = re.compile(r'''import(?:\s+[\s\S]*?\s+from\s+|\s+)["'](\.[^"']+)["']''')
UI_VERSION_RE = re.compile(r'''const\s+UI_VERSION\s*=\s*["']([^"']+)["']''')
HEADER_MARKERS = (
    'headers.set("x-race-ui-version", UI_VERSION)',
    "headers.set('x-race-ui-version', UI_VERSION)",
    '"x-race-ui-version": UI_VERSION',
    "'x-race-ui-version': UI_VERSION",
)


def load_wrangler() -> dict:
    return json.loads((ROOT / "wrangler.jsonc").read_text(encoding="utf-8"))


def resolve_import(current: Path, specifier: str) -> Path | None:
    target = (current.parent / specifier).resolve()
    candidates: list[Path] = []
    if target.suffix == ".js":
        candidates.append(target.with_suffix(".ts"))
    elif target.suffix:
        candidates.append(target)
    else:
        candidates.extend([target.with_suffix(".ts"), target / "index.ts"])
    root = ROOT.resolve()
    for candidate in candidates:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def resolve_ui_version(entry: str) -> tuple[str, str]:
    start = (ROOT / entry).resolve()
    if not start.exists():
        raise RuntimeError(f"PUBLIC_UI_ENTRY_MISSING:{entry}")

    queue: deque[Path] = deque([start])
    seen: set[Path] = set()
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        source = path.read_text(encoding="utf-8")
        version = UI_VERSION_RE.search(source)
        if version and any(marker in source for marker in HEADER_MARKERS):
            return path.relative_to(ROOT.resolve()).as_posix(), version.group(1)
        for specifier in IMPORT_RE.findall(source):
            resolved = resolve_import(path, specifier)
            if resolved is not None and resolved not in seen:
                queue.append(resolved)
    raise RuntimeError(f"PUBLIC_UI_VERSION_HEADER_SOURCE_NOT_FOUND:{entry}")


def main() -> None:
    cfg = load_wrangler()
    entry = str(cfg.get("main") or "")
    deploy_revision = str(cfg.get("vars", {}).get("DEPLOY_REVISION") or "")
    if not entry:
        raise RuntimeError("PUBLIC_UI_WRANGLER_MAIN_MISSING")
    if not deploy_revision:
        raise RuntimeError("PUBLIC_UI_DEPLOY_REVISION_MISSING")
    source, ui_version = resolve_ui_version(entry)
    payload = {
        "entry": entry,
        "uiVersionSource": source,
        "uiVersion": ui_version,
        "deployRevision": deploy_revision,
    }
    if "--github-env" in sys.argv:
        import os
        env_path = os.environ.get("GITHUB_ENV", "")
        if not env_path:
            raise RuntimeError("GITHUB_ENV_MISSING")
        with open(env_path, "a", encoding="utf-8") as handle:
            handle.write(f"EXPECTED_UI_VERSION={ui_version}\n")
            handle.write(f"EXPECTED_UI_ENTRY={entry}\n")
            handle.write(f"EXPECTED_UI_SOURCE={source}\n")
            handle.write(f"EXPECTED_DEPLOY_REVISION={deploy_revision}\n")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
