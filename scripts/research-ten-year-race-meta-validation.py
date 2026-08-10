import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "research-ten-year-odds-validation.py"
OUTPUT = ROOT / "analysis-results" / "research-ten-year-race-meta-validation.json"
YEARS = range(2016, 2027)
VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉"


def load_base():
    spec = importlib.util.spec_from_file_location("research_ten_year_meta_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("META_BASE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()
period = base.period
collector = base.collector


def header_text(page_html: str):
    text = collector.page_text(page_html)
    markers = [text.find(value) for value in ("着順", "払戻", "コーナー通過順位") if text.find(value) >= 0]
    end = min(markers) if markers else min(len(text), 5000)
    return text[:end]


def normalize_class(header: str):
    compact = header.replace(" ", "")
    if re.search(r"\(GI\)|GⅠ|ＧⅠ", compact): return "G1", 8
    if re.search(r"\(GII\)|GⅡ|ＧⅡ", compact): return "G2", 7
    if re.search(r"\(GIII\)|GⅢ|ＧⅢ", compact): return "G3", 6
    if "新馬" in compact: return "新馬", 0
    if "未勝利" in compact: return "未勝利", 1
    if "1勝" in compact or "500万下" in compact: return "1勝クラス", 2
    if "2勝" in compact or "1000万下" in compact: return "2勝クラス", 3
    if "3勝" in compact or "1600万下" in compact: return "3勝クラス", 4
    if "(L)" in compact or "オープン" in compact or re.search(r"(?:^|[^A-Z])OP(?:[^A-Z]|$)", compact): return "OP/L", 5
    return "その他", 9


def parse_meta(page_html: str):
    header = header_text(page_html)
    compact = " ".join(header.split())
    date = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", compact)
    venue = re.search(rf"\d+回({VENUES})\d+日", compact)
    race_numbers = [int(value) for value in re.findall(r"(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)", compact)]
    race_no = next((value for value in race_numbers if 1 <= value <= 12), None)
    course = re.search(r"(芝|ダート|障害)[^0-9]{0,40}(\d{3,4})m", compact)
    if course is None:
        course = re.search(r"(芝|ダート|障害)[^0-9]{0,40}(\d{3,4})メートル", compact)
    surface = course.group(1) if course else None
    distance = int(course.group(2)) if course else None
    direction_match = re.search(r"(?:芝|ダート|障害)[^0-9\n]{0,40}(右|左|直線)", compact)
    if direction_match is None:
        direction_match = re.search(r"(右|左|直線)[^0-9]{0,20}\d{3,4}m", compact)
    direction = direction_match.group(1) if direction_match else None
    weather_match = re.search(r"天候\s*[:：]?\s*(晴|曇|雨|小雨|雪|小雪)", compact)
    weather = weather_match.group(1) if weather_match else None
    track_match = re.search(r"(?:馬場|芝|ダート)\s*[:：]?\s*(良|稍重|重|不良)", compact)
    track = track_match.group(1) if track_match else None
    class_label, class_bin = normalize_class(compact)
    return {
        "raceDate": f"{int(date.group(1)):04d}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None,
        "venue": venue.group(1) if venue else None,
        "raceNo": race_no,
        "surface": surface,
        "distanceM": distance,
        "direction": direction,
        "weather": weather,
        "trackCondition": track,
        "classLabel": class_label,
        "classBin": class_bin,
        "headerSample": compact[:800],
    }


def validate_year(year: int):
    urls = base.result_urls_for_year(year)
    errors = []
    for url in urls[:8]:
        try:
            html = period.fetch_get_retry(url)
            meta = parse_meta(html)
            required = [meta["raceDate"], meta["venue"], meta["surface"], meta["distanceM"], meta["weather"], meta["trackCondition"]]
            if not all(value is not None for value in required):
                raise RuntimeError("META_INCOMPLETE:" + json.dumps(meta, ensure_ascii=False))
            if int(str(meta["raceDate"])[:4]) != year:
                raise RuntimeError(f"YEAR_MISMATCH:{meta['raceDate']}")
            meta.update({"year": year, "validated": True, "sourceUrl": url})
            return meta
        except Exception as error:
            errors.append(f"{type(error).__name__}:{error}")
    return {"year": year, "validated": False, "errors": errors}


def main():
    samples = []
    for year in YEARS:
        row = validate_year(year)
        samples.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "samples": samples,
        "allYearsValidated": all(row.get("validated") is True for row in samples),
        "historicalClassNormalization": {"500万下": "1勝クラス", "1000万下": "2勝クラス", "1600万下": "3勝クラス"},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allYearsValidated": report["allYearsValidated"], "validatedYears": sum(row.get("validated") is True for row in samples)}, ensure_ascii=False))
    if not report["allYearsValidated"]:
        raise SystemExit("TEN_YEAR_RACE_META_VALIDATION_INCOMPLETE")


if __name__ == "__main__":
    main()
