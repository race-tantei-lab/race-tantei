import html as html_module
import importlib.util
import itertools
import json
import re
import sys
import time
import urllib.error
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "jra-historical-combination-parser-validation.json"
VENUE_DAY_CNAME = "pw15orl10072025010120250105/E2"
TARGET_RACE_NO = 12
LABELS = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")
MATRIX_LABELS = ("ワイド", "馬連", "馬単", "3連複", "3連単")
ACTION_RE = re.compile(
    r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    re.I,
)


def load_collector():
    spec = importlib.util.spec_from_file_location("historical_combination_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fetch_retry(collector, cname, attempts=8):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return collector.fetch_url(collector.JRA_ODDS_URL, cname=cname)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                raise
        except Exception as exc:
            last = exc
            if attempt == attempts:
                raise
        time.sleep(min(25, 2 * attempt))
    raise RuntimeError(f"JRA_FETCH_RETRY_EXHAUSTED:{last}")


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
    if not text.isdigit():
        return None
    horse = int(text)
    return horse if 1 <= horse <= 30 else None


def active_horses(collector, win_html):
    parsed = collector.parse_odds_rows(win_html, "単勝")
    horses = []
    for combination, low, high in parsed:
        if len(combination) != 1 or low <= 0 or high <= 0:
            continue
        horse = int(combination[0])
        if horse not in horses:
            horses.append(horse)
    return sorted(horses)


def odds_matrix_rows(collector, page_html):
    rows = []
    for cells in collector.parsed_rows(page_html):
        if len(cells) < 2:
            continue
        odds_index = None
        odds_range = None
        for index, cell in enumerate(cells):
            parsed = collector.parse_odds_range(cell)
            if parsed:
                odds_index = index
                odds_range = parsed
                break
        if odds_index is None or odds_range is None:
            continue
        displayed = None
        for cell in cells[:odds_index]:
            horse = as_horse_no(cell)
            if horse is not None:
                displayed = horse
                break
        if displayed is None:
            continue
        rows.append({
            "displayedHorse": displayed,
            "oddsMin": float(odds_range[0]),
            "oddsMax": float(odds_range[1]),
            "cells": cells[:8],
        })
    return rows


def expected_combinations(label, horses):
    if label in {"ワイド", "馬連"}:
        return list(itertools.combinations(horses, 2))
    if label == "馬単":
        return list(itertools.permutations(horses, 2))
    if label == "3連複":
        return list(itertools.combinations(horses, 3))
    if label == "3連単":
        return list(itertools.permutations(horses, 3))
    raise ValueError(label)


def validate_label(label, horses, rows):
    expected = expected_combinations(label, horses)
    compared = min(len(expected), len(rows))
    mismatches = []
    for index in range(compared):
        expected_horse = int(expected[index][-1])
        actual_horse = int(rows[index]["displayedHorse"])
        if expected_horse != actual_horse:
            mismatches.append({
                "index": index,
                "expectedCombination": list(expected[index]),
                "expectedDisplayedHorse": expected_horse,
                "actualDisplayedHorse": actual_horse,
                "cells": rows[index]["cells"],
            })
            if len(mismatches) >= 25:
                break
    count_matches = len(rows) == len(expected)
    sequence_matches = count_matches and not mismatches
    return {
        "expectedCombinationCount": len(expected),
        "parsedMatrixRowCount": len(rows),
        "rowCountMatches": count_matches,
        "displayedHorseSequenceMatches": sequence_matches,
        "validated": count_matches and sequence_matches,
        "mismatches": mismatches,
        "sample": [
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
    report = {
        "targetRaceNo": TARGET_RACE_NO,
        "venueDayCname": VENUE_DAY_CNAME,
        "activeHorses": [],
        "pages": {},
        "validations": {},
        "allMatrixBetTypesValidated": False,
    }
    try:
        venue_html = fetch_retry(collector, VENUE_DAY_CNAME)
        actions = actions_by_label(venue_html)
        pages = {}
        for label in LABELS:
            cnames = actions.get(label) or []
            if len(cnames) < TARGET_RACE_NO:
                report["pages"][label] = {"error": f"TARGET_ACTION_MISSING:{len(cnames)}"}
                continue
            cname = cnames[TARGET_RACE_NO - 1]
            try:
                html = fetch_retry(collector, cname)
                pages[label] = html
                identity = collector.parse_page_identity(html)
                report["pages"][label] = {
                    "cname": cname,
                    "identity": list(identity) if identity else None,
                    "pageBytes": len(html.encode("utf-8")),
                }
            except Exception as exc:
                report["pages"][label] = {"cname": cname, "error": f"{type(exc).__name__}:{exc}"}

        if "単勝" in pages:
            horses = active_horses(collector, pages["単勝"])
            report["activeHorses"] = horses
            report["activeHorseCount"] = len(horses)
            for label in MATRIX_LABELS:
                if label not in pages:
                    report["validations"][label] = {"validated": False, "error": "PAGE_MISSING"}
                    continue
                rows = odds_matrix_rows(collector, pages[label])
                report["validations"][label] = validate_label(label, horses, rows)
            report["allMatrixBetTypesValidated"] = all(
                report["validations"].get(label, {}).get("validated") is True
                for label in MATRIX_LABELS
            )
        else:
            report["error"] = "WIN_PAGE_MISSING"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}:{exc}"

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "activeHorseCount": report.get("activeHorseCount"),
        "allMatrixBetTypesValidated": report["allMatrixBetTypesValidated"],
        "validationSummary": {
            label: {
                "validated": row.get("validated"),
                "expected": row.get("expectedCombinationCount"),
                "parsed": row.get("parsedMatrixRowCount"),
            }
            for label, row in report["validations"].items()
        },
        "error": report.get("error"),
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
