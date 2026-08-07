import html as html_module
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-odds-structure-probe.json"

VENUE_DAY_CNAME = "pw15orl10072025010120250105/E2"
TARGET_RACE_NO = 12
REQUIRED = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")
ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    re.I,
)
ODDS_NUMBER_RE = re.compile(r"(?<!\d)(?:\d{1,7}(?:\.\d)?)(?!\d)")


def load_collector():
    spec = importlib.util.spec_from_file_location("historical_odds_structure_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_text(value):
    value = html_module.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return " ".join(value.split())


def actions_by_label(page_html):
    rows = defaultdict(list)
    for line in page_html.splitlines():
        if "doAction" not in line or "accessO.html" not in line:
            continue
        match = ACTION_RE.search(line)
        if not match:
            continue
        text = clean_text(line)
        for label in REQUIRED:
            if label in text:
                rows[label].append(match.group(1))
    return rows


def structural_rows(collector, page_html, limit=30):
    output = []
    for cells in collector.parsed_rows(page_html):
        if not cells:
            continue
        joined = " | ".join(cells)
        if not re.search(r"\d", joined):
            continue
        output.append(cells[:20])
        if len(output) >= limit:
            break
    return output


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=VENUE_DAY_CNAME)
    actions = actions_by_label(venue_html)
    pages = {}
    for label in REQUIRED:
        cnames = actions.get(label) or []
        if len(cnames) < TARGET_RACE_NO:
            pages[label] = {"error": f"TARGET_ACTION_MISSING:{len(cnames)}", "actionCount": len(cnames)}
            continue
        cname = cnames[TARGET_RACE_NO - 1]
        try:
            page = collector.fetch_url(collector.JRA_ODDS_URL, cname=cname)
            parsed = collector.parse_odds_rows(page, label)
            identity = collector.parse_page_identity(page)
            pages[label] = {
                "cname": cname,
                "actionCountForLabel": len(cnames),
                "pageBytes": len(page.encode("utf-8")),
                "identity": list(identity) if identity else None,
                "detectedBetType": collector.detect_bet_type(page, label),
                "genericParsedRows": len(parsed),
                "numericTokenCount": len(ODDS_NUMBER_RE.findall(page)),
                "structuralRows": structural_rows(collector, page),
            }
        except Exception as exc:
            pages[label] = {"cname": cname, "error": f"{type(exc).__name__}:{exc}"}

    report = {
        "venueDayCname": VENUE_DAY_CNAME,
        "targetRaceNo": TARGET_RACE_NO,
        "actionCounts": {label: len(actions.get(label) or []) for label in REQUIRED},
        "pages": pages,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "actionCounts": report["actionCounts"],
        "genericParsedRows": {label: row.get("genericParsedRows") for label, row in pages.items()},
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
