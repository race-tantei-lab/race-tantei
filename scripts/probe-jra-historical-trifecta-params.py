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
            "extras": [html_module.unescape(value) for value in QUOTED_RE.findall(match.group("tail") or "")],
            "context": clean_text(line)[:800],
        })
    return rows


def fetch_post(collector, cname, params):
    values = {"cname": cname, **params}
    encoded = urllib.parse.urlencode(values, encoding="utf-8", errors="strict")
    request = urllib.request.Request(
        collector.JRA_ODDS_URL,
        data=encoded.encode("utf-8"),
        headers={
            "User-Agent": collector.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Referer": "https://www.jra.go.jp/JRADB/accessO.html",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise RuntimeError("JRA_ODDS_BODY_TOO_LARGE")
        return collector.decode_body(raw, response.headers.get("content-type"))


def parameter_variants(extras):
    variants = [("none", {})]
    if extras:
        variants.append((
            "first3",
            {f"juma{index}": value for index, value in enumerate(extras[:3], start=1)},
        ))
        variants.append((
            "last3",
            {f"juma{index}": value for index, value in enumerate(extras[-3:], start=1)},
        ))
    unique = []
    seen = set()
    for name, params in variants:
        key = tuple(params.items())
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, params))
    return unique


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=VENUE_DAY_CNAME)
    actions = trifecta_actions(venue_html)
    if len(actions) < TARGET_RACE_NO:
        raise RuntimeError(f"TRIFECTA_ACTION_MISSING:{len(actions)}")
    action = actions[TARGET_RACE_NO - 1]

    # Persist the exact JRA-provided action before any POST attempt so a
    # transport/parser error cannot hide which arguments the site supplied.
    preliminary = {
        "targetRaceNo": TARGET_RACE_NO,
        "trifectaActionCount": len(actions),
        "targetAction": action,
        "variants": [],
    }
    OUTPUT.write_text(json.dumps(preliminary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "trifectaActionCount": len(actions),
        "targetCname": action["cname"],
        "extras": action["extras"],
    }, ensure_ascii=False))

    variants = []
    for variant_name, params in parameter_variants(action["extras"]):
        try:
            page = fetch_post(collector, action["cname"], params)
            rows = collector.parsed_rows(page)
            numeric_rows = [row for row in rows if any(re.search(r"\d", cell) for cell in row)]
            variants.append({
                "variant": variant_name,
                "postedParams": params,
                "pageBytes": len(page.encode("utf-8")),
                "identity": list(collector.parse_page_identity(page) or []),
                "detectedBetType": collector.detect_bet_type(page, "3連単"),
                "rowCount": len(rows),
                "numericRowCount": len(numeric_rows),
                "sampleRows": numeric_rows[:50],
            })
        except Exception as exc:
            variants.append({
                "variant": variant_name,
                "postedParams": params,
                "error": f"{type(exc).__name__}:{exc}",
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
            {
                "variant": row["variant"],
                "pageBytes": row.get("pageBytes"),
                "numericRowCount": row.get("numericRowCount"),
                "error": row.get("error"),
            }
            for row in variants
        ],
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
