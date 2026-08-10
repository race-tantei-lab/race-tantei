import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2_PATH = ROOT / "scripts" / "research-ten-year-odds-validation-v2.py"


def load_v2():
    spec = importlib.util.spec_from_file_location("research_ten_year_odds_v2", V2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("TEN_YEAR_ODDS_V2_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v2 = load_v2()
collector = v2.collector
validator = v2.base.validator


def odds_matrix_rows_current(collector_module, page_html):
    rows = []
    for cells in collector_module.parsed_rows(page_html):
        odds_index = None
        odds_range = None
        for index, cell in enumerate(cells):
            parsed = collector_module.odds_value(cell)
            if parsed is not None:
                odds_index = index
                odds_range = parsed
                break
        if odds_index is None or odds_range is None:
            continue
        displayed = None
        for cell in cells[:odds_index]:
            horse = validator.as_horse_no(cell)
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


validator.odds_matrix_rows = odds_matrix_rows_current

if __name__ == "__main__":
    v2.base.main()
