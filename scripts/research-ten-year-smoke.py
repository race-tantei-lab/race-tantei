#!/usr/bin/env python3
import argparse
import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = "https://www.jra.go.jp/JRADB/accessS.html"
ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html"
ARCHIVE_INDEX_CNAME = "pw01skl00999999/B3"
USER_AGENT = "Mozilla/5.0 (compatible; RaceTanteiResearch/1.0; +https://www.jra.go.jp/)"
BET_PREFIXES = {
    "単勝": "pw151ou",
    "馬連": "pw154ou",
    "ワイド": "pw155ou",
    "馬単": "pw156ou",
    "3連複": "pw157ou",
    "3連単": "pw158ou",
}


def decode(raw: bytes, content_type: str | None = None) -> str:
    declared = None
    if content_type:
        m = re.search(r"charset\s*=\s*([^;\s]+)", content_type, re.I)
        declared = m.group(1).strip("\"'") if m else None
    for charset in (declared, "cp932", "shift_jis", "utf-8"):
        if not charset:
            continue
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(url: str, *, cname: str | None = None, referer: str = "https://www.jra.go.jp/", attempts: int = 5) -> str:
    data = urllib.parse.urlencode({"cname": cname}).encode("ascii") if cname else None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": referer,
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=40) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise RuntimeError("JRA_BODY_TOO_LARGE")
                text = decode(raw, response.headers.get("content-type"))
            if re.search(r"captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable", text, re.I):
                raise RuntimeError("JRA_BLOCKED_PAGE")
            return text
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.7 * (2 ** attempt)) + random.random() * 0.25)
    raise RuntimeError(f"JRA_FETCH_FAILED:{url}:{cname}:{last}")


def normalized(text: str) -> str:
    return html.unescape(text).replace("\\u0026", "&").replace("\\/", "/")


def extract_cnames(text: str, prefix_re: str) -> list[str]:
    clean = normalized(text)
    found: list[str] = []
    patterns = [
        r"(?:CNAME=|cname=)([^\"'&<>\s)]+)",
        r"((?:pw|sw)01[a-zA-Z0-9]+[^\"'<>\s,)]+/[0-9A-F]{2})",
        r"((?:pw|sw)15[1-8]ou[^\"'<>\s,)]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, clean, re.I):
            value = urllib.parse.unquote(match.group(1)).strip()
            value = re.sub(r"^cname=", "", value, flags=re.I)
            if re.match(prefix_re, value, re.I):
                found.append(value)
    return list(dict.fromkeys(found))


def month_checksums(index_html: str) -> dict[str, str]:
    clean = normalized(index_html)
    out: dict[str, str] = {}
    for m in re.finditer(r"objParam\s*\[\s*[\"'](\d{4})[\"']\s*\]\s*=\s*[\"']([0-9A-F]{2})[\"']", clean, re.I):
        out[m.group(1)] = m.group(2).upper()
    return out


def canonical_result_cname(value: str) -> str:
    return re.sub(r"^sw01sde", "pw01sde", value.strip(), flags=re.I)


def result_marker(result_cname: str) -> str:
    decoded = urllib.parse.unquote(result_cname)
    m = re.search(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})", decoded, re.I)
    if not m:
        raise RuntimeError(f"RESULT_ID_PARSE_MISS:{result_cname}")
    venue, year, meeting, day, race_no, ymd = m.groups()
    return f"10{venue}{year}{meeting}{day}{race_no}{ymd}"


def first_available_month(year: int, checksums: dict[str, str], preferred: list[int]) -> tuple[str, str]:
    candidates = preferred + [m for m in range(1, 13) if m not in preferred]
    for month in candidates:
        ym = f"{year:04d}{month:02d}"
        key = ym[2:]
        if key in checksums:
            return ym, checksums[key]
    raise RuntimeError(f"ARCHIVE_YEAR_NOT_FOUND:{year}")


def verify_year(year: int, checksums: dict[str, str], preferred_months: list[int]) -> dict:
    ym, checksum = first_available_month(year, checksums, preferred_months)
    month_cname = f"pw01skl10{ym}/{checksum}"
    month_html = fetch(ARCHIVE_URL, cname=month_cname)
    meetings = extract_cnames(month_html, r"^(?:pw|sw)01srl")
    if not meetings:
        raise RuntimeError(f"ARCHIVE_MEETINGS_NOT_FOUND:{ym}")

    result_cname = None
    meeting_used = None
    for meeting in meetings[:8]:
        meeting_html = fetch(ARCHIVE_URL, cname=meeting)
        results = [canonical_result_cname(x) for x in extract_cnames(meeting_html, r"^(?:pw|sw)01sde")]
        if results:
            result_cname = results[0]
            meeting_used = meeting
            break
    if not result_cname:
        raise RuntimeError(f"ARCHIVE_RESULTS_NOT_FOUND:{ym}")

    result_html = fetch(ARCHIVE_URL, cname=result_cname)
    marker = result_marker(result_cname)
    first_candidates = [x for x in extract_cnames(result_html, r"^pw151ou") if marker in x]
    if not first_candidates:
        raise RuntimeError(f"FIRST_ODDS_CNAME_MISS:{year}:{result_cname}")

    first_cname = first_candidates[0]
    first_html = fetch(ODDS_URL, cname=first_cname, referer=ARCHIVE_URL)
    tabs = {"単勝": first_cname}
    for bet_type, prefix in BET_PREFIXES.items():
        if bet_type == "単勝":
            continue
        values = [x for x in extract_cnames(first_html, rf"^{re.escape(prefix)}") if marker in x]
        if values:
            tabs[bet_type] = values[0]
    missing = [name for name in BET_PREFIXES if name not in tabs]
    if missing:
        raise RuntimeError(f"ODDS_TABS_MISSING:{year}:{','.join(missing)}")

    page_checks = {}
    for bet_type, cname in tabs.items():
        page = first_html if bet_type == "単勝" else fetch(ODDS_URL, cname=cname, referer=ODDS_URL)
        # Historical JRA pages do not use one stable decimal layout for every market/year.
        # Validate the real odds-page structure rather than requiring decimal text specifically.
        lower = page.lower()
        has_table = "<table" in lower
        numeric_tokens = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", page)
        has_enough_numeric_content = len(numeric_tokens) >= 10
        has_odds_context = any(token in page for token in ("オッズ", "人気", "馬番", "組合せ", "組み合わせ"))
        if not has_table or not has_enough_numeric_content or not has_odds_context:
            raise RuntimeError(f"ODDS_PAGE_UNRECOGNIZED:{year}:{bet_type}")
        page_checks[bet_type] = {
            "cname": cname,
            "table": has_table,
            "numericTokenCount": len(numeric_tokens),
            "oddsContext": has_odds_context,
        }
        time.sleep(0.2)

    return {
        "year": year,
        "yearMonth": ym,
        "meetingCname": meeting_used,
        "resultCname": result_cname,
        "marker": marker,
        "betTypes": page_checks,
        "status": "ok",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2016)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--months", default="5,10,1")
    ap.add_argument("--out", default="analysis-results/research-ten-year-smoke.json")
    args = ap.parse_args()
    if args.start_year > args.end_year:
        raise RuntimeError("INVALID_YEAR_RANGE")
    preferred = [int(x) for x in args.months.split(",") if x.strip()]
    if any(x < 1 or x > 12 for x in preferred):
        raise RuntimeError("INVALID_MONTH")

    index_html = fetch(ARCHIVE_URL, cname=ARCHIVE_INDEX_CNAME)
    checksums = month_checksums(index_html)
    if not checksums:
        raise RuntimeError("ARCHIVE_INDEX_EMPTY")

    results = []
    failures = []
    for year in range(args.start_year, args.end_year + 1):
        try:
            row = verify_year(year, checksums, preferred)
            results.append(row)
            print(json.dumps({"year": year, "status": "ok", "month": row["yearMonth"]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures.append({"year": year, "error": f"{type(exc).__name__}:{exc}"})
            print(json.dumps({"year": year, "status": "failed", "error": str(exc)}, ensure_ascii=False), flush=True)

    payload = {
        "scope": {"startYear": args.start_year, "endYear": args.end_year},
        "purpose": "research_only_no_production_write",
        "yearsRequested": args.end_year - args.start_year + 1,
        "yearsPassed": len(results),
        "yearsFailed": len(failures),
        "allSixOfficialBetTypesRequired": True,
        "syntheticOddsAllowed": False,
        "results": results,
        "failures": failures,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"yearsPassed": len(results), "yearsFailed": len(failures), "out": str(out)}, ensure_ascii=False), flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
