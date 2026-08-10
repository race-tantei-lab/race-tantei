#!/usr/bin/env python3
import importlib.util
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "research-fetch-demanded-official-odds.py"


def load_base():
    spec = importlib.util.spec_from_file_location("research_base_demanded_odds", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{BASE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def flexible_result_marker(result_url):
    decoded = urllib.parse.unquote(str(result_url or ""))
    match = re.search(
        r"(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})",
        decoded,
        re.I,
    )
    if not match:
        raise RuntimeError("RESULT_ID_PARSE_MISS")
    venue, year, meeting, day, race_no, ymd = match.groups()
    # Historical and current JRA odds CNAMEs may differ in the layout prefix
    # (01 vs 10). The race identity body below is invariant and uniquely
    # identifies the target race inside pw/sw151-158 odds CNAMEs.
    return f"{venue}{year}{meeting}{day}{race_no}{ymd}"


def main():
    base = load_base()
    base.result_marker = flexible_result_marker
    base.main()


if __name__ == "__main__":
    main()
