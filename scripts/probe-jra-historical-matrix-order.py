import html as html_module
import importlib.util
import itertools
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-matrix-order-probe.json"
VENUE_DAY_CNAME = "pw15orl10072025010120250105/E2"
TARGET_RACE_NO = 12
LABELS = ("単勝", "ワイド", "馬連", "馬単", "3連複")
ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    re.I,
)


def load_collector():
    spec = importlib.util.spec_from_file_location("matrix_order_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_text(value):
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def actions_by_label(page_html):
    rows = defaultdict(list)
    for line in page_html.splitlines():
        if "doAction" not in line or "accessO.html" not in line:
            continue
        match = ACTION_RE.search(line)
        if not match:
            continue
        text = clean_text(line)
        for label in LABELS:
            if label in text:
                rows[label].append(match.group(1))
    return rows


def as_horse_no(value):
    text = str(value or "").strip()
    return int(text) if text.isdigit() and 1 <= int(text) <= 30 else None


def active_horses(collector, win_html):
    parsed = collector.parse_odds_rows(win_html, "単勝")
    horses = []
    for combination, _low, _high in parsed:
        if len(combination) != 1:
            continue
        horse = int(combination[0])
        if horse not in horses:
            horses.append(horse)
    return sorted(horses)


def matrix_rows(collector, page_html):
    rows = []
    for cells in collector.parsed_rows(page_html):
        if len(cells) < 2:
            continue
        displayed = as_horse_no(cells[0])
        if displayed is None:
            continue
        odds = None
        for cell in cells[1:]:
            odds = collector.parse_odds_range(cell)
            if odds:
                break
        if odds is None:
            continue
        rows.append({"displayedHorse": displayed, "oddsMin": odds[0], "oddsMax": odds[1]})
    return rows


def expected_combinations(label, horses):
    if label in {"ワイド", "馬連"}:
        return list(itertools.combinations(horses, 2))
    if label == "馬単":
        return [(first, second) for first in horses for second in horses if second != first]
    if label == "3連複":
        return list(itertools.combinations(horses, 3))
    return []


def evaluate_order(label, horses, rows):
    expected = expected_combinations(label, horses)
    compared = min(len(expected), len(rows))
    mismatches = []
    for index in range(compared):
        combination = expected[index]
        displayed_expected = combination[-1]
        displayed_actual = rows[index]["displayedHorse"]
        if displayed_expected != displayed_actual:
            mismatches.append({
                "index": index,
                "expectedCombination": list(combination),
                "expectedDisplayedHorse": displayed_expected,
                "actualDisplayedHorse": displayed_actual,
            })
            if len(mismatches) >= 20:
                break
    return {
        "expectedCombinationCount": len(expected),
        "matrixRowCount": len(rows),
        "rowCountMatches": len(expected) == len(rows),
        "displayedHorseSequenceMatches": len(mismatches) == 0 and compared == len(expected),
        "mismatches": mismatches,
        "sampleResolved": [
            {
                "combination": list(expected[index]),
                "displayedHorse": rows[index]["displayedHorse"],
                "oddsMin": rows[index]["oddsMin"],
                "oddsMax": rows[index]["oddsMax"],
            }
            for index in range(min(12, compared))
        ],
    }


def main():
    collector = load_collector()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=VENUE_DAY_CNAME)
    actions = actions_by_label(venue_html)
    pages = {}
    for label in LABELS:
        cnames = actions.get(label) or []
        if len(cnames) < TARGET_RACE_NO:
            raise RuntimeError(f"TARGET_ACTION_MISSING:{label}:{len(cnames)}")
        pages[label] = collector.fetch_url(collector.JRA_ODDS_URL, cname=cnames[TARGET_RACE_NO - 1])

    horses = active_horses(collector, pages["単勝"])
    evaluations = {}
    for label in ("ワイド", "馬連", "馬単", "3連複"):
        rows = matrix_rows(collector, pages[label])
        evaluations[label] = evaluate_order(label, horses, rows)

    report = {
        "targetRaceNo": TARGET_RACE_NO,
        "activeHorses": horses,
        "activeHorseCount": len(horses),
        "evaluations": evaluations,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "activeHorseCount": len(horses),
        "checks": {
            label: {
                "rowCountMatches": row["rowCountMatches"],
                "displayedHorseSequenceMatches": row["displayedHorseSequenceMatches"],
                "matrixRowCount": row["matrixRowCount"],
            }
            for label, row in evaluations.items()
        },
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
