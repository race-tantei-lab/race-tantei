#!/usr/bin/env python3
import importlib.util
import os
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / "scripts" / "research-fetch-demanded-official-odds.py"
CURRENT = ROOT / "scripts" / "collect-current-jra-official-odds.py"

JP_BY_EN = {
    "win": "単勝", "umaren": "馬連", "wide": "ワイド",
    "umatan": "馬単", "trio": "3連複", "trifecta": "3連単",
}
PREFIX_BY_EN = {
    "win": "151", "umaren": "154", "wide": "155",
    "umatan": "156", "trio": "157", "trifecta": "158",
}

# Verified against live official JRA pages on 2026-08-08 (dde10) and
# 2026-08-09 (dde01). These are checksum deltas from the entry CNAME's
# final hexadecimal byte to the horse-number-order odds CNAME's final byte.
# Every derived page is still fetched from JRA and its date/venue/race identity
# is verified below before any odds are accepted.
ENTRY_ODDS_DELTA_BY_LAYOUT = {
    "01": {
        "win": 0xDD,
        "umaren": 0x69,
        "wide": 0xED,
        "umatan": 0x71,
        "trio": 0x57,
        "trifecta": 0x79,
    },
    "10": {
        "win": 0xFE,
        "umaren": 0x8A,
        "wide": 0x0E,
        "umatan": 0x92,
        "trio": 0x78,
        "trifecta": 0x9A,
    },
}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def flexible_result_marker(result_url):
    decoded = urllib.parse.unquote(str(result_url or ""))
    match = re.search(
        r"(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})",
        decoded, re.I,
    )
    if not match:
        raise RuntimeError("RESULT_ID_PARSE_MISS")
    venue, year, meeting, day, race_no, ymd = match.groups()
    return f"{venue}{year}{meeting}{day}{race_no}{ymd}"


def cname_from_url(url):
    try:
        return urllib.parse.unquote(
            urllib.parse.parse_qs(urllib.parse.urlparse(str(url or "")).query).get("CNAME", [""])[0]
        )
    except Exception:
        return ""


def prefix_match(cname, code):
    value = str(cname or "").lower()
    return value.startswith(f"pw{code}ou") or value.startswith(f"sw{code}ou")


def odds_value(low, high):
    lo, hi = float(low), float(high)
    return lo if abs(lo - hi) < 1e-12 else [lo, hi]


def derive_entry_odds_cnames(entry_url):
    cname = cname_from_url(entry_url)
    match = re.match(
        r"^(?:pw|sw)01dde(01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/([0-9A-F]{2})$",
        cname, re.I,
    )
    if not match:
        raise RuntimeError(f"CURRENT_ENTRY_CNAME_PARSE_MISS:{cname}")
    layout, venue, year, meeting, day, race_no, ymd, raw_checksum = match.groups()
    checksum = int(raw_checksum, 16)
    identity = f"{venue}{year}{meeting}{day}{race_no}{ymd}"
    deltas = ENTRY_ODDS_DELTA_BY_LAYOUT[layout]
    out = {}
    for market, code in PREFIX_BY_EN.items():
        suffix = "Z99" if market == "trio" else "Z"
        market_checksum = (checksum + deltas[market]) % 256
        out[market] = f"pw{code}ou10{identity}{suffix}/{market_checksum:02X}"
    return out


def entry_derivation_self_test():
    cases = [
        (
            "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0107202602060120260809%2FE2",
            {
                "win": "pw151ou1007202602060120260809Z/BF",
                "umaren": "pw154ou1007202602060120260809Z/4B",
                "wide": "pw155ou1007202602060120260809Z/CF",
                "umatan": "pw156ou1007202602060120260809Z/53",
                "trio": "pw157ou1007202602060120260809Z99/39",
                "trifecta": "pw158ou1007202602060120260809Z/5B",
            },
        ),
        (
            "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde1001202601050120260808%2FA4",
            {
                "win": "pw151ou1001202601050120260808Z/A2",
                "umaren": "pw154ou1001202601050120260808Z/2E",
                "wide": "pw155ou1001202601050120260808Z/B2",
                "umatan": "pw156ou1001202601050120260808Z/36",
                "trio": "pw157ou1001202601050120260808Z99/1C",
                "trifecta": "pw158ou1001202601050120260808Z/3E",
            },
        ),
    ]
    for url, expected in cases:
        got = derive_entry_odds_cnames(url)
        if got != expected:
            raise AssertionError(f"ENTRY_CNAME_DERIVATION:{url}:{got}:{expected}")


def current_fetch(row, historical, current):
    runtime = current.runtime
    base = runtime.base
    entry_url = str(row.get("entryUrl") or "")
    result_url = str(row.get("resultUrl") or "")
    race_date = str(row.get("raceDate") or "")
    date_digits = race_date.replace("-", "")
    venue = str(row.get("venue") or "")
    race_no = int(row.get("raceNo") or 0)
    required = tuple(m for m in historical.MARKETS if m in set(row.get("requiredMarkets") or ()))
    if not required or "win" not in required:
        raise RuntimeError(f"REQUIRED_MARKETS_INVALID:{required}")
    if not entry_url:
        raise RuntimeError("CURRENT_ENTRY_URL_MISSING")

    def same_race(cname):
        decoded = urllib.parse.unquote(str(cname or ""))
        return date_digits in decoded and current.current_race_no_from_cname(decoded) == race_no

    derived = derive_entry_odds_cnames(entry_url)
    entry_actions = []
    try:
        entry_html = runtime.fetch_url(entry_url)
        entry_actions = [c for c, _ in base.action_links(entry_html) if same_race(c)]
    except Exception:
        entry_actions = []

    win_seeds = [c for c in entry_actions if prefix_match(c, PREFIX_BY_EN["win"])]
    win_cname = win_seeds[0] if win_seeds else derived["win"]
    win_page = runtime.fetch_url(base.JRA_ODDS_URL, cname=win_cname, referer=entry_url)
    identity = runtime.parse_page_identity(win_page, win_cname)
    if identity != (race_date, venue, race_no):
        raise RuntimeError(
            f"CURRENT_WIN_IDENTITY_MISMATCH:{identity}:{race_date}:{venue}:{race_no}:{win_cname}"
        )

    win_rows = runtime.parse_odds_rows(win_page, "単勝")
    if not win_rows:
        raise RuntimeError("CURRENT_WIN_ROWS_EMPTY")
    horses = sorted({int(combo) for combo, _, _ in win_rows if str(combo).isdigit()})
    if len(horses) < 2:
        raise RuntimeError(f"CURRENT_WIN_HORSES_TOO_FEW:{len(horses)}")

    all_actions = list(entry_actions)
    for cname, _ in base.action_links(win_page):
        if same_race(cname) and cname not in all_actions:
            all_actions.append(cname)

    parsed_by_market = {"win": win_rows}
    source_cnames = {"win": win_cname}
    derived_markets = {"win": not bool(win_seeds)}
    for market in required:
        if market == "win":
            continue
        code = PREFIX_BY_EN[market]
        candidates = [c for c in all_actions if prefix_match(c, code)]
        cname = candidates[0] if candidates else derived[market]
        page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
        page_identity = runtime.parse_page_identity(page, cname)
        if page_identity != (race_date, venue, race_no):
            raise RuntimeError(f"CURRENT_{market.upper()}_IDENTITY_MISMATCH:{page_identity}:{cname}")
        rows = runtime.parse_odds_rows(page, JP_BY_EN[market])
        if not rows:
            raise RuntimeError(f"CURRENT_{market.upper()}_ROWS_EMPTY")
        parsed_by_market[market] = rows
        source_cnames[market] = cname
        derived_markets[market] = not bool(candidates)

    official = {}
    coverage = {}
    for market in required:
        values = {str(combo): odds_value(low, high) for combo, low, high in parsed_by_market[market]}
        expected = historical.expected_count(market, horses)
        present = len(values)
        official[market] = values
        coverage[market] = {
            "expected": expected,
            "present": present,
            "ratio": present / expected if expected else 0.0,
        }

    return {
        "raceId": row["raceId"],
        "raceDate": race_date,
        "venue": venue,
        "raceNo": race_no,
        "requiredMarkets": list(required),
        "horses": horses,
        "officialOdds": official,
        "officialOddsCoverage": coverage,
        "provenance": {
            "resultUrl": result_url,
            "entryUrl": entry_url,
            "officialOddsSource": "jra_official_final_odds_entry_checksum_verified",
            "sourceCnames": source_cnames,
            "derivedCnameMarkets": [m for m, used in derived_markets.items() if used],
            "officialPageIdentityVerified": True,
            "syntheticOddsUsed": False,
            "productionDatabaseWritten": False,
        },
    }


def main():
    historical = load_module(HISTORICAL, "research_base_demanded_odds")
    historical.result_marker = flexible_result_marker
    original_fetch = historical.fetch_race

    os.environ.setdefault("CLOUDFLARE_ACCOUNT_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_D1_DATABASE_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_API_TOKEN", "research-unused")
    current = load_module(CURRENT, "research_current_official_odds")
    current.self_test()
    entry_derivation_self_test()

    def dispatch(row):
        if row.get("resultUrlResolutionMethod") == "validated_current_direct_desktop":
            return current_fetch(row, historical, current)
        return original_fetch(row)

    historical.fetch_race = dispatch
    historical.main()


if __name__ == "__main__":
    main()
