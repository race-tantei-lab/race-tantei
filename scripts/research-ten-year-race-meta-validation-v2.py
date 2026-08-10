import importlib.util
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "research-ten-year-odds-validation.py"
OUTPUT = ROOT / "analysis-results" / "research-ten-year-race-meta-validation.json"
YEARS = range(2016, 2027)
VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉"


def load_base():
    spec = importlib.util.spec_from_file_location("research_ten_year_meta_v2_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("META_BASE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()
period = base.period
collector = base.collector


def result_cname(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    return urllib.parse.unquote((query.get("CNAME") or query.get("cname") or [""])[0])


def cname_date_and_race(url: str):
    cname = result_cname(url)
    dates = re.findall(r"20\d{6}", cname)
    race_values = [
        int(value)
        for value in re.findall(r"(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:/|$))", cname)
    ]
    race_no = next((value for value in reversed(race_values) if 1 <= value <= 12), None)
    date = None
    if dates:
        raw = dates[-1]
        date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return date, race_no


def normalize_class(text: str):
    compact = text.replace(" ", "")
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


def context(text: str, token: str, radius=160):
    index = text.find(token)
    if index < 0:
        return None
    return text[max(0, index-radius):min(len(text), index+radius)]


def parse_meta(page_html: str, url: str):
    text = collector.page_text(page_html)
    compact = " ".join(text.split())
    fallback_date, fallback_race_no = cname_date_and_race(url)

    date_match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", compact)
    race_date = (
        f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        if date_match else fallback_date
    )

    venue_patterns = [
        rf"\d+回\s*({VENUES})\s*\d+日",
        rf"({VENUES})\s*競馬場",
        rf"({VENUES})\s*第?\s*\d+レース",
    ]
    venue = None
    for pattern in venue_patterns:
        match = re.search(pattern, compact)
        if match:
            venue = match.group(1)
            break

    race_values = [int(value) for value in re.findall(r"(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)", compact)]
    race_no = next((value for value in race_values if 1 <= value <= 12), fallback_race_no)

    course_patterns = [
        r"(芝|ダート|障害)\s*[・･]?\s*(?:右|左|直線)?\s*(?:外|内)?\s*(\d{1,2},?\d{3}|\d{3,4})\s*(?:m|メートル)",
        r"(芝|ダート|障害)[^0-9]{0,50}(\d{1,2},?\d{3}|\d{3,4})\s*(?:m|メートル)",
    ]
    course = None
    for pattern in course_patterns:
        match = re.search(pattern, compact)
        if match:
            course = match
            break
    surface = course.group(1) if course else None
    distance = int(course.group(2).replace(",", "")) if course else None

    direction = None
    direction_patterns = [
        r"(?:芝|ダート|障害)\s*[・･]?\s*(右|左|直線)",
        r"(?:コース|回り)\s*[:：]?\s*(右|左|直線)",
        r"(右|左|直線)\s*(?:回り|外|内)?\s*(?:\d{1,2},?\d{3}|\d{3,4})\s*(?:m|メートル)",
    ]
    for pattern in direction_patterns:
        match = re.search(pattern, compact)
        if match:
            direction = match.group(1)
            break

    weather = None
    for pattern in [r"天候\s*[:：]?\s*(晴|曇|雨|小雨|雪|小雪)", r"天気\s*[:：]?\s*(晴|曇|雨|小雨|雪|小雪)"]:
        match = re.search(pattern, compact)
        if match:
            weather = match.group(1)
            break

    track = None
    for pattern in [
        r"(?:芝|ダート|馬場)\s*[:：]?\s*(良|稍重|重|不良)",
        r"馬場状態\s*[:：]?\s*(良|稍重|重|不良)",
    ]:
        match = re.search(pattern, compact)
        if match:
            track = match.group(1)
            break

    class_label, class_bin = normalize_class(compact)
    return {
        "raceDate": race_date,
        "venue": venue,
        "raceNo": race_no,
        "surface": surface,
        "distanceM": distance,
        "direction": direction,
        "weather": weather,
        "trackCondition": track,
        "classLabel": class_label,
        "classBin": class_bin,
        "diagnostic": {
            "date": context(compact, "年"),
            "venue": next((context(compact, name) for name in VENUES.split("|") if name in compact), None),
            "surface": context(compact, "芝") or context(compact, "ダート") or context(compact, "障害"),
            "weather": context(compact, "天候") or context(compact, "天気"),
            "track": context(compact, "馬場"),
        },
    }


def validate_year(year: int):
    urls = base.result_urls_for_year(year)
    errors = []
    for url in urls[:10]:
        try:
            html = period.fetch_get_retry(url)
            meta = parse_meta(html, url)
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
        "validatedYears": sum(row.get("validated") is True for row in samples),
        "historicalClassNormalization": {"500万下": "1勝クラス", "1000万下": "2勝クラス", "1600万下": "3勝クラス"},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allYearsValidated": report["allYearsValidated"], "validatedYears": report["validatedYears"]}, ensure_ascii=False))
    if not report["allYearsValidated"]:
        raise SystemExit("TEN_YEAR_RACE_META_VALIDATION_INCOMPLETE")


if __name__ == "__main__":
    main()
