import html as html_module
import importlib.util
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERIOD_PATH = ROOT / "scripts" / "validate-jra-historical-parser-across-period.py"
OUTPUT = ROOT / "analysis-results" / "research-ten-year-odds-validation.json"
ARCHIVE_ENDPOINT = "https://www.jra.go.jp/JRADB/accessS.html"
ARCHIVE_INDEX_CNAME = "pw01skl00999999/B3"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36"
YEARS = tuple(range(2016, 2027))


def load_period():
    spec = importlib.util.spec_from_file_location("research_ten_year_period", PERIOD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PERIOD_VALIDATOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


period = load_period()
validator = period.validator
collector = period.collector


def decode_jra(raw: bytes, content_type: str | None) -> str:
    candidates = []
    if content_type:
        match = re.search(r"charset\s*=\s*([^;\s]+)", content_type, re.I)
        if match:
            candidates.append(match.group(1).strip("\"'"))
    probe = raw[:8192].decode("latin1", errors="ignore")
    match = re.search(r"charset=[\"']?([^\"'\s/>]+)", probe, re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(["cp932", "shift_jis", "utf-8"])
    for charset in candidates:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_archive(cname: str) -> str:
    data = urllib.parse.urlencode({"cname": cname}).encode("ascii")
    req = urllib.request.Request(
        ARCHIVE_ENDPOINT,
        data=data,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.jra.go.jp/",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise RuntimeError("ARCHIVE_BODY_TOO_LARGE")
        text = decode_jra(raw, response.headers.get("content-type"))
    if re.search(r"captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable", text, re.I):
        raise RuntimeError("ARCHIVE_BLOCKED_PAGE")
    return html_module.unescape(text)


def extract_cnames(page_html: str, prefix_pattern: str):
    found = []
    for match in re.finditer(r"(?:CNAME=|cname=)([^\"'&<>\s)]+)", page_html, re.I):
        value = urllib.parse.unquote(match.group(1)).strip()
        if re.match(prefix_pattern, value, re.I):
            found.append(value)
    for match in re.finditer(r"(?:pw|sw)01[a-zA-Z0-9]+[^\"'<>\s,)]+/[0-9A-F]{2}", page_html, re.I):
        value = match.group(0).strip()
        if re.match(prefix_pattern, value, re.I):
            found.append(value)
    return list(dict.fromkeys(found))


def result_urls_for_year(year: int):
    index = fetch_archive(ARCHIVE_INDEX_CNAME)
    key = f"{year % 100:02d}01"
    match = re.search(
        rf"objParam\s*\[\s*[\"']{key}[\"']\s*\]\s*=\s*[\"']([0-9A-F]{{2}})[\"']",
        index,
        re.I,
    )
    if not match:
        raise RuntimeError(f"ARCHIVE_CHECKSUM_NOT_FOUND:{year}")
    month = f"{year}01"
    month_html = fetch_archive(f"pw01skl10{month}/{match.group(1).upper()}")
    meetings = extract_cnames(month_html, r"^(?:pw|sw)01srl")
    if not meetings:
        raise RuntimeError(f"ARCHIVE_MEETINGS_NOT_FOUND:{year}")
    results = []
    for meeting in meetings[:3]:
        meeting_html = fetch_archive(meeting)
        for cname in extract_cnames(meeting_html, r"^(?:pw|sw)01sde"):
            desktop = re.sub(r"^sw01sde", "pw01sde", cname, flags=re.I)
            url = f"{ARCHIVE_ENDPOINT}?CNAME={urllib.parse.quote(desktop, safe='') }"
            if url not in results:
                results.append(url)
        if len(results) >= 12:
            break
    if not results:
        raise RuntimeError(f"ARCHIVE_RESULTS_NOT_FOUND:{year}")
    return results


def validate_result_url(year: int, result_url: str):
    race_odds_cname, discovered_from, discovery_mode = period.discover_race_odds_cname(result_url)
    race_odds_html = validator.fetch_retry(collector, race_odds_cname)
    identity = collector.parse_page_identity(race_odds_html)
    if not identity or len(identity) < 3:
        raise RuntimeError("ODDS_IDENTITY_NOT_FOUND")
    race_date, venue, race_no = identity
    race_no = int(race_no)
    if int(str(race_date)[:4]) != year:
        raise RuntimeError(f"YEAR_IDENTITY_MISMATCH:{race_date}")

    venue_cname, venue_mode = period.discover_venue_day_cname(race_odds_cname)
    venue_html = validator.fetch_retry(collector, venue_cname)
    actions = validator.actions_by_label(venue_html)
    pages = {}
    for label in validator.LABELS:
        choices = actions.get(label) or []
        if len(choices) < race_no:
            raise RuntimeError(f"TARGET_ACTION_MISSING:{label}:{len(choices)}:{race_no}")
        pages[label] = validator.fetch_retry(collector, choices[race_no - 1])
        time.sleep(0.35)

    horses = validator.active_horses(collector, pages["単勝"])
    if len(horses) < 2:
        raise RuntimeError(f"ACTIVE_HORSES_TOO_FEW:{len(horses)}")
    validations = {}
    for label in validator.MATRIX_LABELS:
        rows = validator.odds_matrix_rows(collector, pages[label])
        validations[label] = validator.validate_label(label, horses, rows)
    all_valid = all(validations[label].get("validated") is True for label in validator.MATRIX_LABELS)
    if not all_valid:
        raise RuntimeError(
            "MATRIX_VALIDATION_FAILED:"
            + json.dumps({label: {"expected": row.get("expectedCombinationCount"), "parsed": row.get("parsedMatrixRowCount")} for label, row in validations.items()}, ensure_ascii=False)
        )
    return {
        "year": year,
        "raceDate": race_date,
        "venue": venue,
        "raceNo": race_no,
        "activeHorseCount": len(horses),
        "raceOddsDiscoveryMode": discovery_mode,
        "venueDayDiscoveryMode": venue_mode,
        "allMatrixBetTypesValidated": True,
        "validationCounts": {
            label: {
                "expected": row.get("expectedCombinationCount"),
                "parsed": row.get("parsedMatrixRowCount"),
            }
            for label, row in validations.items()
        },
    }


def validate_year(year: int):
    errors = []
    try:
        urls = result_urls_for_year(year)
    except Exception as error:
        return {"year": year, "validated": False, "errors": [f"ARCHIVE:{type(error).__name__}:{error}"]}
    for result_url in urls[:6]:
        try:
            sample = validate_result_url(year, result_url)
            sample["validated"] = True
            sample["attemptedResultPages"] = len(errors) + 1
            return sample
        except Exception as error:
            errors.append(f"{type(error).__name__}:{error}")
            time.sleep(0.7)
    return {"year": year, "validated": False, "attemptedResultPages": min(6, len(urls)), "errors": errors}


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for year in YEARS:
        sample = validate_year(year)
        samples.append(sample)
        print(json.dumps(sample, ensure_ascii=False), flush=True)
        time.sleep(0.8)
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "targetYears": list(YEARS),
        "samples": samples,
        "allYearsValidated": all(sample.get("validated") is True for sample in samples),
        "validatedYearCount": sum(sample.get("validated") is True for sample in samples),
        "betTypes": list(validator.LABELS),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allYearsValidated": report["allYearsValidated"], "validatedYearCount": report["validatedYearCount"], "report": str(OUTPUT.relative_to(ROOT))}, ensure_ascii=False))
    if not report["allYearsValidated"]:
        raise SystemExit("TEN_YEAR_ODDS_VALIDATION_INCOMPLETE")


if __name__ == "__main__":
    main()
