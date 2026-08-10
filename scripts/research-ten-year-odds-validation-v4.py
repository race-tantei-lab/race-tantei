import importlib.util
import itertools
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "research-ten-year-odds-validation.py"
EXPORTER_PATH = ROOT / "scripts" / "export-selected-historical-official-odds.py"
OUTPUT = ROOT / "analysis-results" / "research-ten-year-odds-validation.json"
YEARS = range(2016, 2027)


def load_base():
    spec = importlib.util.spec_from_file_location("research_ten_year_odds_v4_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("TEN_YEAR_ODDS_BASE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_exporter_functions():
    source = EXPORTER_PATH.read_text(encoding="utf-8")
    marker = "\nselection = json.loads(SELECTION.read_text"
    if marker not in source:
        raise RuntimeError("EXPORTER_TOP_LEVEL_MARKER_MISSING")
    prefix = source.split(marker, 1)[0]
    namespace = {"__name__": "research_historical_odds_exporter", "__file__": str(EXPORTER_PATH)}
    exec(compile(prefix, str(EXPORTER_PATH), "exec"), namespace, namespace)
    required = ["fetch_race", "parse_win", "parse_pair_page", "parse_trio", "parse_trifecta", "vectorize"]
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"EXPORTER_FUNCTIONS_MISSING:{missing}")
    return namespace


base = load_base()
exporter = load_exporter_functions()


def row_from_url(year: int, result_url: str):
    decoded = urllib.parse.unquote(result_url)
    match = re.search(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})", decoded)
    if not match:
        raise RuntimeError("RESULT_ID_PARSE_MISS")
    venue_code, parsed_year, meeting, day, race_no, ymd = match.groups()
    if int(parsed_year) != year:
        raise RuntimeError(f"YEAR_MISMATCH:{parsed_year}:{year}")
    race_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    return {
        "raceId": f"research-{ymd}-{venue_code}-{race_no}",
        "raceDate": race_date,
        "venue": f"code-{venue_code}",
        "raceNo": int(race_no),
        "resultUrl": result_url,
        "meeting": meeting,
        "day": day,
    }


def validate_record(year: int, result_url: str):
    row = row_from_url(year, result_url)
    record = exporter["fetch_race"](row)
    horses = record.get("horses") or []
    if len(horses) < 2:
        raise RuntimeError(f"HORSES_TOO_FEW:{len(horses)}")
    expected = record.get("expected") or {}
    present = record.get("present") or {}
    markets = ["win", "umaren", "wide", "umatan", "trio", "trifecta"]
    missing = {
        market: {"expected": int(expected.get(market) or 0), "present": int(present.get(market) or 0)}
        for market in markets
        if int(present.get(market) or 0) != int(expected.get(market) or 0)
    }
    if missing:
        raise RuntimeError("OFFICIAL_ODDS_INCOMPLETE:" + json.dumps(missing, ensure_ascii=False))
    return {
        "year": year,
        "raceDate": record["raceDate"],
        "raceNo": record["raceNo"],
        "horseCount": len(horses),
        "expected": {market: int(expected[market]) for market in markets},
        "present": {market: int(present[market]) for market in markets},
        "source": record.get("source"),
        "validated": True,
    }


def validate_year(year: int):
    urls = base.result_urls_for_year(year)
    errors = []
    for result_url in urls[:8]:
        try:
            sample = validate_record(year, result_url)
            sample["attemptedResultPages"] = len(errors) + 1
            return sample
        except Exception as error:
            errors.append(f"{type(error).__name__}:{error}")
    return {"year": year, "validated": False, "attemptedResultPages": min(8, len(urls)), "errors": errors}


def main():
    samples = []
    for year in YEARS:
        row = validate_year(year)
        samples.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "parser": "proven export-selected-historical-official-odds.py",
        "targetYears": list(YEARS),
        "samples": samples,
        "allYearsValidated": all(row.get("validated") is True for row in samples),
        "validatedYearCount": sum(row.get("validated") is True for row in samples),
        "betTypes": ["単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"],
        "syntheticOddsUsed": False,
        "estimatedOddsUsed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allYearsValidated": report["allYearsValidated"], "validatedYearCount": report["validatedYearCount"]}, ensure_ascii=False))
    if not report["allYearsValidated"]:
        raise SystemExit("TEN_YEAR_PROVEN_PARSER_ODDS_VALIDATION_INCOMPLETE")


if __name__ == "__main__":
    main()
