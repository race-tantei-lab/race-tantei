import importlib.util
import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-all-bet-odds-probe.json"

TARGET = ("2025-01-05", "中京", 12)
START_CNAME = "pw151ou1007202501011220250105Z/FE"
REQUIRED = {"単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"}


def load_collector():
    spec = importlib.util.spec_from_file_location("historical_all_bet_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compact_hint(value: str) -> str:
    return " ".join((value or "").split())[:300]


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    queue = deque([(START_CNAME, "単勝 複勝 オッズ")])
    seen = set()
    pages = []
    by_type = {}

    while queue and len(seen) < 80:
        cname, hint = queue.popleft()
        if cname in seen:
            continue
        seen.add(cname)
        try:
            html = collector.fetch_url(collector.JRA_ODDS_URL, cname=cname)
        except Exception as exc:
            pages.append({"cname": cname, "hint": compact_hint(hint), "error": f"{type(exc).__name__}:{exc}"})
            continue

        identity = collector.parse_page_identity(html)
        bet_type = collector.detect_bet_type(html, hint)
        parsed = collector.parse_odds_rows(html, bet_type) if bet_type else []
        actions = collector.action_links(html)
        row = {
            "cname": cname,
            "hint": compact_hint(hint),
            "identity": list(identity) if identity else None,
            "betType": bet_type,
            "parsedRows": len(parsed),
            "sample": [
                {"combination": combination, "oddsMin": low, "oddsMax": high}
                for combination, low, high in parsed[:5]
            ],
            "nextOddsLinks": [
                {"cname": next_cname, "hint": compact_hint(context)}
                for next_cname, context in actions[:20]
            ],
        }
        pages.append(row)

        if identity == TARGET and bet_type in REQUIRED and parsed:
            current = by_type.get(bet_type)
            if current is None or len(parsed) > current["parsedRows"]:
                by_type[bet_type] = row

        # action_links() only matches /JRADB/accessO.html and returns
        # (cname, JRA-visible link context), so preserve that context as the
        # authoritative hint for the destination odds page.
        for next_cname, context in actions:
            if next_cname in seen:
                continue
            queue.append((next_cname, context))

    report = {
        "target": {"raceDate": TARGET[0], "venue": TARGET[1], "raceNo": TARGET[2]},
        "startCname": START_CNAME,
        "pagesVisited": len(seen),
        "requiredBetTypes": sorted(REQUIRED),
        "foundBetTypes": sorted(by_type),
        "allRequiredBetTypesReadable": REQUIRED.issubset(by_type),
        "byType": by_type,
        "pages": pages,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pagesVisited": len(seen),
        "foundBetTypes": sorted(by_type),
        "allRequiredBetTypesReadable": REQUIRED.issubset(by_type),
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
