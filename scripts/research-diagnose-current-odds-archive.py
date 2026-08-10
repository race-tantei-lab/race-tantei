#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.parse
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "scripts" / "collect-current-jra-official-odds.py"


def load_current():
    os.environ.setdefault("CLOUDFLARE_ACCOUNT_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_D1_DATABASE_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_API_TOKEN", "research-unused")
    spec = importlib.util.spec_from_file_location("diagnostic_current_odds", CURRENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("CURRENT_MODULE_LOAD_FAILED")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.self_test()
    return mod


def cname_tokens(page):
    clean = page.replace("\\u0026", "&").replace("\\/", "/")
    values = []
    patterns = [
        r"(?:CNAME|cname)\s*[=:]\s*['\"]?([^'\"&<>\s)]+)",
        r"((?:pw|sw)15[1-8][A-Za-z0-9_/.-]{6,})",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, clean, re.I):
            value = urllib.parse.unquote(m.group(1)).strip().rstrip(";,)")
            if value and value not in values:
                values.append(value)
    return values


def compact_matches(values, date_digits, race_no):
    out = []
    for value in values:
        decoded = urllib.parse.unquote(value)
        if date_digits in decoded:
            out.append(value)
        elif re.search(rf"(?:^|\D){race_no:02d}(?:\D|$)", decoded) and re.search(r"(?:pw|sw)15[1-8]", decoded, re.I):
            out.append(value)
    return out[:100]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry-url", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--venue", required=True)
    ap.add_argument("--race-no", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=180)
    args = ap.parse_args()

    current = load_current()
    runtime = current.runtime
    base = runtime.base
    date_digits = args.date.replace("-", "")

    entry_html = runtime.fetch_url(args.entry_url)
    entry_action = [c for c, _ in base.action_links(entry_html)]
    entry_tokens = cname_tokens(entry_html)

    queue = deque([base.JRA_ODDS_HOME_CNAME])
    seen = set()
    found = []
    pages = 0
    errors = []
    while queue and pages < max(1, args.max_pages):
        cname = queue.popleft()
        if cname in seen:
            continue
        seen.add(cname)
        try:
            page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
            pages += 1
            identity = runtime.parse_page_identity(page, cname)
            bet_type = base.detect_bet_type(page, "")
            if identity == (args.date, args.venue, args.race_no):
                rows = runtime.parse_odds_rows(page, bet_type) if bet_type else []
                found.append({"cname": cname, "identity": identity, "betType": bet_type, "parsedRows": len(rows)})
            for child, _context in base.action_links(page):
                decoded = urllib.parse.unquote(child)
                # Follow only odds navigation. Prioritize target date links first.
                if re.match(r"^(?:pw|sw)15", decoded, re.I) and child not in seen:
                    if date_digits in decoded:
                        queue.appendleft(child)
                    else:
                        queue.append(child)
        except Exception as exc:
            errors.append(f"{cname}:{type(exc).__name__}:{exc}")

    result = {
        "purpose": "research_only_recent_historical_odds_route_diagnostic",
        "target": {"date": args.date, "venue": args.venue, "raceNo": args.race_no},
        "entryUrl": args.entry_url,
        "entryActionLinkCount": len(entry_action),
        "entryActionTargetDate": compact_matches(entry_action, date_digits, args.race_no),
        "entryCnameTokenCount": len(entry_tokens),
        "entryCnameTokensTargetDate": compact_matches(entry_tokens, date_digits, args.race_no),
        "oddsHomePagesFetched": pages,
        "oddsHomeQueueRemaining": len(queue),
        "targetOddsPagesFound": found,
        "errors": errors[:50],
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
