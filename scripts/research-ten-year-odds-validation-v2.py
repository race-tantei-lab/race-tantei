import html as html_module
import importlib.util
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "research-ten-year-odds-validation.py"


def load_base():
    spec = importlib.util.spec_from_file_location("research_ten_year_odds_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("TEN_YEAR_ODDS_BASE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()
period = base.period
collector = base.collector


def cname_race_no(cname: str):
    decoded = urllib.parse.unquote(html_module.unescape(cname))
    values = [
        int(value)
        for value in re.findall(r"(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:/|$))", decoded)
    ]
    return next((value for value in reversed(values) if 1 <= value <= 12), None)


def page_identity(page_html: str, source_cname: str | None = None):
    text = collector.page_text(page_html)
    date_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    venue_match = re.search(rf"\d+回({collector.VENUES})\d+日", text)
    race_values = [int(value) for value in re.findall(r"(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)", text)]
    race_no = next((value for value in race_values if 1 <= value <= 12), None)
    if race_no is None and source_cname:
        race_no = cname_race_no(source_cname)
    if date_match is None or venue_match is None or race_no is None:
        return None
    race_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    return race_date, venue_match.group(1), race_no


def cname_matches(cname: str, race_date: str, race_no: int):
    decoded = urllib.parse.unquote(html_module.unescape(cname))
    digits = race_date.replace("-", "")
    return digits in decoded and cname_race_no(decoded) == race_no


def race_specific_odds_cname(result_url: str):
    result_html = period.fetch_get_retry(result_url)
    result_cname = urllib.parse.unquote(urllib.parse.urlparse(result_url).query)
    result_identity = page_identity(result_html, result_cname)
    if result_identity is None:
        raise RuntimeError("RESULT_IDENTITY_NOT_FOUND")
    race_date, _venue, race_no = result_identity

    direct = [
        cname for cname in period.embedded_odds_cnames(result_html)
        if cname_matches(cname, race_date, race_no)
    ]
    if direct:
        return direct[0], result_url, "direct-result-race-action"

    for linked_url in period.canonical_jradb_urls(result_html):
        try:
            linked_html = period.fetch_get_retry(linked_url)
        except Exception:
            continue
        candidates = [
            cname for cname in period.embedded_odds_cnames(linked_html)
            if cname_matches(cname, race_date, race_no)
        ]
        if candidates:
            return candidates[0], linked_url, "linked-jradb-race-action"
    raise RuntimeError(f"RACE_SPECIFIC_ODDS_ACTION_NOT_FOUND:{race_date}:{race_no}")


period.discover_race_odds_cname = race_specific_odds_cname

if __name__ == "__main__":
    base.main()
