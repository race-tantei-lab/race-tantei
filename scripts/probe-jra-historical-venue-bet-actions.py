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
OUTPUT = ROOT / "analysis-results" / "jra-historical-venue-bet-actions-probe.json"

TARGET = ("2025-01-05", "中京", 12)
VENUE_DAY_CNAME = "pw15orl10072025010120250105/E2"
REQUIRED = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")
ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"](?P<tail>[^)]*)\)",
    re.I,
)
QUOTED_RE = re.compile(r"['\"]([^'\"]*)['\"]")


def load_collector():
    spec = importlib.util.spec_from_file_location("historical_venue_bet_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fetch_params(collector, params):
    body = urllib.parse.urlencode(params).encode("ascii")
    request = urllib.request.Request(
        collector.JRA_ODDS_URL,
        data=body,
        headers={
            "User-Agent": collector.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.jra.go.jp/JRADB/accessO.html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise RuntimeError("JRA_ODDS_BODY_TOO_LARGE")
        return collector.decode_body(raw, response.headers.get("content-type"))


def action_records(page_html):
    rows = []
    for line in page_html.splitlines():
        if "doAction" not in line or "accessO.html" not in line:
            continue
        match = ACTION_RE.search(line)
        if not match:
            continue
        text = html_module.unescape(re.sub(r"<[^>]+>", " ", line))
        text = " ".join(text.split())
        labels = [bet_type for bet_type in REQUIRED if bet_type in text]
        if not labels:
            continue
        extras = QUOTED_RE.findall(match.group("tail") or "")
        rows.append({
            "cname": html_module.unescape(match.group(1)),
            "extras": extras,
            "labels": labels,
            "context": text[:500],
        })
    return rows


def request_params(action):
    params = {"cname": action["cname"]}
    extras = list(action.get("extras") or [])
    # JRA's multi-horse pages pass three extra values through doAction;
    # the site's JavaScript posts them as juma1/juma2/juma3.
    for index, value in enumerate(extras[:3], start=1):
        params[f"juma{index}"] = value
    return params


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=VENUE_DAY_CNAME)
    actions = action_records(venue_html)

    results = {}
    tested = []
    for action in actions:
        for label in action["labels"]:
            if label in results:
                continue
            params = request_params(action)
            try:
                page = fetch_params(collector, params)
                identity = collector.parse_page_identity(page)
                detected = collector.detect_bet_type(page, label)
                parsed = collector.parse_odds_rows(page, label)
                row = {
                    "label": label,
                    "cname": action["cname"],
                    "extraParameterCount": len(action["extras"]),
                    "identity": list(identity) if identity else None,
                    "detectedBetType": detected,
                    "parsedRows": len(parsed),
                    "sample": [
                        {"combination": combination, "oddsMin": low, "oddsMax": high}
                        for combination, low, high in parsed[:5]
                    ],
                    "targetRaceMatched": identity == TARGET,
                }
                tested.append(row)
                if identity == TARGET and parsed:
                    results[label] = row
            except Exception as exc:
                tested.append({
                    "label": label,
                    "cname": action["cname"],
                    "extraParameterCount": len(action["extras"]),
                    "error": f"{type(exc).__name__}:{exc}",
                })

    report = {
        "target": {"raceDate": TARGET[0], "venue": TARGET[1], "raceNo": TARGET[2]},
        "venueDayCname": VENUE_DAY_CNAME,
        "venuePageBytes": len(venue_html.encode("utf-8")),
        "labeledActionsFound": len(actions),
        "labelsFoundInVenueHtml": sorted({label for row in actions for label in row["labels"]}),
        "targetReadableBetTypes": sorted(results),
        "allRequiredBetTypesReadable": set(REQUIRED).issubset(results),
        "actions": actions[:200],
        "targetResults": results,
        "tested": tested[:300],
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "labeledActionsFound": len(actions),
        "labelsFoundInVenueHtml": report["labelsFoundInVenueHtml"],
        "targetReadableBetTypes": report["targetReadableBetTypes"],
        "allRequiredBetTypesReadable": report["allRequiredBetTypesReadable"],
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
