import html as html_module
import importlib.util
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-trifecta-params-probe.json"
VENUE_DAY_CNAME = "pw15orl10072025010120250105/E2"
TARGET_RACE_NO = 12
ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"](?P<tail>[^)]*)\)",
    re.I,
)
QUOTED_RE = re.compile(r"['\"]([^'\"]*)['\"]")


def load_collector():
    spec = importlib.util.spec_from_file_location("trifecta_param_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_text(value):
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def trifecta_actions(page_html):
    rows = []
    for line in page_html.splitlines():
        if "3連単" not in line or "doAction" not in line or "accessO.html" not in line:
            continue
        match = ACTION_RE.search(line)
        if not match:
            continue
        rows.append({
            "cname": html_module.unescape(match.group(1)),
            "extras": QUOTED_RE.findall(match.group("tail") or ""),
            "context": clean_text(line)[:500],
        })
    return rows


def fetch_post(collector, cname, extras):
    params = {"cname": cname}
    for index, value in enumerate(extras[:3], start=1):
        params[f"juma{index}"] = value
    request = urllib.request.Request(
        collector.JRA_ODDS_URL,
        data=urllib.parse.urlencode(params).encode("ascii"),
        headers={
            "User-Agent": collector.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Referer": "https://www.jra.go.jp/JRADB/accessO.html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(4_000_001)
        return collector.decode_body(raw, response.headers.get("content-type"))


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=VENUE_DAY_CNAME)
    actions = trifecta_actions(venue_html)
    if len(actions) < TARGET_RACE_NO:
        raise RuntimeError(f"TRIFECTA_ACTION_MISSING:{len(actions)}")
    action = actions[TARGET_RACE_NO - 1]
    variants = []
    for use_extras in (False, True):
        page = fetch_post(collector, action["cname"], action["extras"] if use_extras else [])
        rows = collector.parsed_rows(page)
        numeric_rows = [row for row in rows if any(re.search(r"\d", cell) for cell in row)]
        variants.append({
            "useExtras": use_extras,
            "postedExtras": action["extras"][:3] if use_extras else [],
            "pageBytes": len(page.encode("utf-8")),
            "identity": list(collector.parse_page_identity(page) or []),
            "detectedBetType": collector.detect_bet_type(page, "3連単"),
            "rowCount": len(rows),
            "numericRowCount": len(numeric_rows),
            "sampleRows": numeric_rows[:40],
        })
    report = {
        "targetRaceNo": TARGET_RACE_NO,
        "trifectaActionCount": len(actions),
        "targetAction": action,
        "variants": variants,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "trifectaActionCount": len(actions),
        "targetCname": action["cname"],
        "extraCount": len(action["extras"]),
        "variants": [
            {"useExtras": row["useExtras"], "pageBytes": row["pageBytes"], "numericRowCount": row["numericRowCount"]}
            for row in variants
        ],
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
