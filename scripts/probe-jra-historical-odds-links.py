import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-odds-probe.json"

# Fixed historical race. This probe only checks whether JRA still exposes
# official odds navigation for a completed race; it does not use race outcome
# to choose any model rule.
RESULT_URL = (
    "https://www.jra.go.jp/JRADB/accessS.html?"
    "CNAME=pw01sde1007202501011220250105%2FBC"
)


def load_collector():
    spec = importlib.util.spec_from_file_location("historical_odds_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def odds_actions(html: str):
    pattern = re.compile(
        r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
        re.I,
    )
    rows = []
    seen = set()
    for match in pattern.finditer(html):
        cname = match.group(1)
        if cname in seen:
            continue
        seen.add(cname)
        context = html[max(0, match.start() - 500): min(len(html), match.end() + 500)]
        rows.append({"cname": cname, "context": context})
    return rows


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result_html = collector.fetch_url(RESULT_URL)
    actions = odds_actions(result_html)
    tested = []
    for action in actions[:30]:
        cname = action["cname"]
        try:
            page = collector.fetch_url(collector.JRA_ODDS_URL, cname=cname)
            bet_type = collector.detect_bet_type(page, action["context"])
            identity = collector.parse_page_identity(page)
            parsed = collector.parse_odds_rows(page, bet_type) if bet_type else []
            tested.append({
                "cname": cname,
                "betType": bet_type,
                "identity": list(identity) if identity else None,
                "parsedRows": len(parsed),
                "sample": [
                    {"combination": combination, "oddsMin": low, "oddsMax": high}
                    for combination, low, high in parsed[:5]
                ],
                "officialHistoricalOddsReadable": bool(identity and bet_type and parsed),
            })
        except Exception as exc:
            tested.append({
                "cname": cname,
                "error": f"{type(exc).__name__}:{exc}",
                "officialHistoricalOddsReadable": False,
            })

    readable = [row for row in tested if row.get("officialHistoricalOddsReadable")]
    report = {
        "probeRace": "2025-01-05 中京12R",
        "resultUrl": RESULT_URL,
        "resultPageBytes": len(result_html.encode("utf-8")),
        "oddsActionLinksFound": len(actions),
        "actionsTested": len(tested),
        "readableOfficialHistoricalOddsPages": len(readable),
        "historicalOfficialOddsRetrievalPossible": bool(readable),
        "tested": tested,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "oddsActionLinksFound": len(actions),
        "readableOfficialHistoricalOddsPages": len(readable),
        "historicalOfficialOddsRetrievalPossible": bool(readable),
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
