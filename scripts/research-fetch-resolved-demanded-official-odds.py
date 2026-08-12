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


def derive_win_cname_from_result(result_url):
    """Derive JRA's official win-odds CNAME from an official result CNAME.

    Verified research evidence:
      * 37/37 archive-resolved sde10 races: win checksum = result + 0x42 mod 256.
      * 13/13 successful 2026-08-09 sde01 races: win checksum = result + 0x21 mod 256.
    The fetched odds page is still independently validated by date, venue and
    race number before any value is accepted.
    """
    cname = cname_from_url(result_url)
    match = re.match(
        r"^(?:pw|sw)01sde(01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/([0-9A-F]{2})$",
        cname, re.I,
    )
    if not match:
        raise RuntimeError(f"CURRENT_RESULT_CNAME_PARSE_MISS:{cname}")
    layout, venue, year, meeting, day, race_no, ymd, raw_checksum = match.groups()
    checksum = int(raw_checksum, 16)
    delta = 0x21 if layout == "01" else 0x42
    win_checksum = (checksum + delta) % 256
    identity = f"{venue}{year}{meeting}{day}{race_no}{ymd}"
    return f"pw151ou10{identity}Z/{win_checksum:02X}"


def result_derivation_self_test():
    cases = [
        (
            "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1002202601120620260719%2F86",
            "pw151ou1002202601120620260719Z/C8",
        ),
        (
            "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0107202602060120260809%2F9E",
            "pw151ou1007202602060120260809Z/BF",
        ),
        (
            "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1008202403110220240525%2FBF",
            "pw151ou1008202403110220240525Z/01",
        ),
    ]
    for url, expected in cases:
        got = derive_win_cname_from_result(url)
        if got != expected:
            raise AssertionError(f"RESULT_WIN_CNAME_DERIVATION:{url}:{got}:{expected}")


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
    if not result_url:
        raise RuntimeError("CURRENT_RESULT_URL_MISSING")

    def same_race(cname):
        decoded = urllib.parse.unquote(str(cname or ""))
        return date_digits in decoded and current.current_race_no_from_cname(decoded) == race_no

    win_cname = derive_win_cname_from_result(result_url)
    win_page = runtime.fetch_url(base.JRA_ODDS_URL, cname=win_cname, referer=result_url)
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

    all_actions = [c for c, _ in base.action_links(win_page) if same_race(c)]
    parsed_by_market = {"win": win_rows}
    source_cnames = {"win": win_cname}
    for market in required:
        if market == "win":
            continue
        code = PREFIX_BY_EN[market]
        candidates = [c for c in all_actions if prefix_match(c, code)]
        if not candidates:
            raise RuntimeError(f"CURRENT_{market.upper()}_TAB_CNAME_MISSING")
        cname = candidates[0]
        page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
        page_identity = runtime.parse_page_identity(page, cname)
        if page_identity != (race_date, venue, race_no):
            raise RuntimeError(f"CURRENT_{market.upper()}_IDENTITY_MISMATCH:{page_identity}:{cname}")
        rows = runtime.parse_odds_rows(page, JP_BY_EN[market])
        if not rows:
            raise RuntimeError(f"CURRENT_{market.upper()}_ROWS_EMPTY")
        parsed_by_market[market] = rows
        source_cnames[market] = cname

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
            "entryUrl": entry_url or None,
            "officialOddsSource": "jra_official_final_odds_result_checksum_verified",
            "sourceCnames": source_cnames,
            "resultToWinChecksumRule": "sde01:+0x21;sde10:+0x42",
            "officialPageIdentityVerified": True,
            "syntheticOddsUsed": False,
            "productionDatabaseWritten": False,
        },
    }


def market_is_complete(result, market, historical):
    horses = []
    for horse in result.get("horses") or ():
        try:
            number = int(horse)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 18:
            horses.append(number)
    horses = sorted(set(horses))
    if len(horses) < 2:
        return False

    expected = int(historical.expected_count(market, horses) or 0)
    values = ((result.get("officialOdds") or {}).get(market) or {})
    present = sum(1 for value in values.values() if value is not None)
    if expected <= 0 or present != expected:
        return False

    coverage = ((result.get("officialOddsCoverage") or {}).get(market) or {})
    if coverage:
        try:
            reported_expected = int(coverage.get("expected"))
            reported_present = int(coverage.get("present"))
        except (TypeError, ValueError):
            return False
        if reported_expected != expected or reported_present != expected:
            return False
    return True


def required_markets_incomplete(row, result, historical):
    required = tuple(m for m in historical.MARKETS if m in set(row.get("requiredMarkets") or ()))
    return [market for market in required if not market_is_complete(result, market, historical)]


def main():
    historical = load_module(HISTORICAL, "research_base_demanded_odds")
    historical.result_marker = flexible_result_marker
    original_fetch = historical.fetch_race

    os.environ.setdefault("CLOUDFLARE_ACCOUNT_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_D1_DATABASE_ID", "research-unused")
    os.environ.setdefault("CLOUDFLARE_API_TOKEN", "research-unused")
    current = load_module(CURRENT, "research_current_official_odds")
    current.self_test()
    result_derivation_self_test()

    def dispatch(row):
        if row.get("resultUrlResolutionMethod") == "validated_current_direct_desktop":
            result = current_fetch(row, historical, current)
            incomplete = required_markets_incomplete(row, result, historical)
            if incomplete:
                raise RuntimeError(
                    f"OFFICIAL_MARKET_INCOMPLETE_CURRENT:{','.join(incomplete)}"
                )
            return result

        result = original_fetch(row)
        incomplete = required_markets_incomplete(row, result, historical)
        if not incomplete:
            return result

        fallback = current_fetch(row, historical, current)
        still_incomplete = required_markets_incomplete(row, fallback, historical)
        if still_incomplete:
            raise RuntimeError(
                f"OFFICIAL_MARKET_INCOMPLETE_AFTER_RUNTIME_FALLBACK:{','.join(still_incomplete)}"
            )
        fallback.setdefault("provenance", {})["runtimeParserFallbackMarkets"] = incomplete
        fallback["provenance"]["runtimeParserFallbackReason"] = "legacy_parser_incomplete_market_coverage"
        return fallback

    historical.fetch_race = dispatch
    historical.main()


if __name__ == "__main__":
    main()
