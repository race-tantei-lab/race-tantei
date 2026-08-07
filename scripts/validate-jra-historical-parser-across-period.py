import html as html_module
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate-jra-historical-combination-parser.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-parser-across-period-validation.json"
TARGET_DATES = ("2024-05-04", "2025-01-05", "2026-08-02")
ODDS_ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    re.I,
)
URL_RE = re.compile(r"https?://[^\"'<>\s]+", re.I)


def load_validator():
    spec = importlib.util.spec_from_file_location("historical_parser_period_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("VALIDATOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_validator()
collector = validator.load_collector()


def fetch_get_retry(url, attempts=7):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return collector.fetch_url(url)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                raise
        except Exception as exc:
            last = exc
            if attempt == attempts:
                raise
        time.sleep(min(20, 2 * attempt))
    raise RuntimeError(f"GET_RETRY_EXHAUSTED:{last}")


def embedded_odds_cnames(page_html):
    found = []
    for match in ODDS_ACTION_RE.finditer(page_html):
        cname = html_module.unescape(match.group(1))
        if cname not in found:
            found.append(cname)
    return found


def canonical_jradb_urls(page_html):
    found = []
    decoded = html_module.unescape(page_html)
    for raw in URL_RE.findall(decoded):
        url = raw.rstrip("),.;")
        if "jra.go.jp/JRADB/" not in url:
            continue
        if url not in found:
            found.append(url)
    for match in re.finditer(r"(?:href|action)\s*=\s*['\"]([^'\"]*\/JRADB\/[^'\"]+)['\"]", decoded, re.I):
        raw = match.group(1)
        url = urllib.parse.urljoin("https://www.jra.go.jp/", raw)
        if url not in found:
            found.append(url)
    return found


def discover_race_odds_cname(result_url):
    html = fetch_get_retry(result_url)
    cnames = embedded_odds_cnames(html)
    if cnames:
        return cnames[0], result_url, "direct-result-action"

    # Mobile result pages may expose a canonical desktop JRADB URL. Follow only
    # links physically present in the JRA page; never synthesize a desktop URL.
    for linked_url in canonical_jradb_urls(html):
        try:
            linked_html = fetch_get_retry(linked_url)
        except Exception:
            continue
        linked_cnames = embedded_odds_cnames(linked_html)
        if linked_cnames:
            return linked_cnames[0], linked_url, "linked-jradb-action"
    raise RuntimeError("JRA_RESULT_PAGE_HAS_NO_DISCOVERABLE_ODDS_ACTION")


def discover_venue_day_cname(race_odds_cname):
    page = validator.fetch_retry(collector, race_odds_cname)
    candidates = collector.action_links(page)
    for cname, _context in candidates:
        if "orl" in cname.lower():
            return cname, "explicit-orl-action"

    # Fallback: test only JRA-provided odds actions and accept a page when it
    # contains a complete venue-day label grid. This still does not invent a URL.
    for cname, _context in candidates[:40]:
        try:
            candidate_page = validator.fetch_retry(collector, cname, attempts=3)
        except Exception:
            continue
        actions = validator.actions_by_label(candidate_page)
        if sum(len(actions.get(label) or []) for label in validator.LABELS) >= 50:
            return cname, "detected-venue-day-grid"
    raise RuntimeError("VENUE_DAY_ODDS_ACTION_NOT_DISCOVERED")


def sample_races():
    rows = []
    for race_date in TARGET_DATES:
        result = collector.d1_query(
            "SELECT race_id, race_date, venue, race_no, result_url "
            "FROM rt_races WHERE race_date = ? AND status = 'finished' "
            "AND result_url IS NOT NULL AND result_url <> '' "
            "ORDER BY venue, race_no LIMIT 1",
            [race_date],
        )
        if not result:
            rows.append({"raceDate": race_date, "error": "NO_FINISHED_RACE_WITH_RESULT_URL"})
        else:
            rows.append(result[0])
    return rows


def validate_sample(sample):
    if sample.get("error"):
        return dict(sample)
    race_no = int(sample["race_no"])
    result_url = str(sample["result_url"])
    report = {
        "raceId": sample["race_id"],
        "raceDate": sample["race_date"],
        "venue": sample["venue"],
        "raceNo": race_no,
        "resultUrl": result_url,
        "validations": {},
        "allMatrixBetTypesValidated": False,
    }
    try:
        race_odds_cname, discovered_from, discovery_mode = discover_race_odds_cname(result_url)
        venue_cname, venue_mode = discover_venue_day_cname(race_odds_cname)
        venue_html = validator.fetch_retry(collector, venue_cname)
        actions = validator.actions_by_label(venue_html)
        pages = {}
        for label in validator.LABELS:
            cnames = actions.get(label) or []
            if len(cnames) < race_no:
                report["validations"][label] = {
                    "validated": False,
                    "error": f"TARGET_ACTION_MISSING:{len(cnames)}",
                }
                continue
            pages[label] = validator.fetch_retry(collector, cnames[race_no - 1])
        if "単勝" not in pages:
            raise RuntimeError("WIN_ODDS_PAGE_MISSING")
        horses = validator.active_horses(collector, pages["単勝"])
        report.update({
            "raceOddsCname": race_odds_cname,
            "raceOddsDiscoveredFrom": discovered_from,
            "raceOddsDiscoveryMode": discovery_mode,
            "venueDayCname": venue_cname,
            "venueDayDiscoveryMode": venue_mode,
            "activeHorses": horses,
            "activeHorseCount": len(horses),
        })
        for label in validator.MATRIX_LABELS:
            if label not in pages:
                report["validations"].setdefault(label, {"validated": False, "error": "PAGE_MISSING"})
                continue
            matrix_rows = validator.odds_matrix_rows(collector, pages[label])
            report["validations"][label] = validator.validate_label(label, horses, matrix_rows)
        report["allMatrixBetTypesValidated"] = all(
            report["validations"].get(label, {}).get("validated") is True
            for label in validator.MATRIX_LABELS
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}:{exc}"
    return report


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    samples = [validate_sample(row) for row in sample_races()]
    report = {
        "targetDates": list(TARGET_DATES),
        "samples": samples,
        "allPeriodsValidated": len(samples) == len(TARGET_DATES) and all(
            sample.get("allMatrixBetTypesValidated") is True for sample in samples
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "allPeriodsValidated": report["allPeriodsValidated"],
        "samples": [
            {
                "raceDate": sample.get("raceDate"),
                "venue": sample.get("venue"),
                "raceNo": sample.get("raceNo"),
                "activeHorseCount": sample.get("activeHorseCount"),
                "allMatrixBetTypesValidated": sample.get("allMatrixBetTypesValidated"),
                "error": sample.get("error"),
            }
            for sample in samples
        ],
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
