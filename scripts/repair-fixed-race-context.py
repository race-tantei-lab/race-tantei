import concurrent.futures
import gzip
import html
import io
import json
import os
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "fixed-race-context.json.gz"
META = ROOT / "artifacts" / "fixed-race-context-meta.json"
START = "2024-05-04"
END_EXCLUSIVE = "2026-08-03"
EXPECTED_RACES = 7695
PDF_WORKERS = 18
PAGE_WORKERS = 18

VENUE_ROMAN = {
    "01": "sapporo",
    "02": "hakodate",
    "03": "fukushima",
    "04": "niigata",
    "05": "tokyo",
    "06": "nakayama",
    "07": "chukyo",
    "08": "kyoto",
    "09": "hanshin",
    "10": "kokura",
}

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def d1(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read().decode())
    if not payload.get("success"):
        raise RuntimeError(f"D1_ERROR:{payload.get('errors')}")
    return payload.get("result", [{}])[0].get("results", [])


def compact(text):
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


def http_bytes(url, attempts=5, timeout=60):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; RaceTanteiContext/2.0; +https://www.jra.go.jp/)",
                    "Accept-Language": "ja,en;q=0.8",
                    "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
                    "Referer": "https://www.jra.go.jp/",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get_content_charset()
        except urllib.error.HTTPError as e:
            last = f"HTTP_{e.code}"
            if e.code not in {429, 500, 502, 503, 504}:
                break
        except Exception as e:
            last = f"{type(e).__name__}:{e}"
        time.sleep(min(10.0, 0.5 * (2 ** attempt)) + random.random() * 0.25)
    raise RuntimeError(last or "FETCH_FAILED")


def result_url_parts(url):
    if not url:
        return None
    decoded = urllib.parse.unquote(str(url))
    m = re.search(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})", decoded)
    if not m:
        return None
    venue_code, year, meeting, day, race_no, ymd = m.groups()
    roman = VENUE_ROMAN.get(venue_code)
    if not roman:
        return None
    return {
        "venueCode": venue_code,
        "year": int(year),
        "meeting": int(meeting),
        "day": int(day),
        "raceNo": int(race_no),
        "ymd": ymd,
        "pdfUrl": f"https://www.jra.go.jp/datafile/seiseki/report/{year}/{year}-{int(meeting)}{roman}{int(day)}.pdf",
    }


def normalized_pdf_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return unicodedata.normalize("NFKC", "\n".join(parts))


def parse_pdf_races(pdf_bytes):
    text = normalized_pdf_text(pdf_bytes)
    anchors = []
    for m in re.finditer(r"第\s*(\d{1,2})\s*競走", text):
        race_no = int(m.group(1))
        if 1 <= race_no <= 12:
            anchors.append((m.start(), race_no))
    # Some page headers repeat the previous race text. Keep the first occurrence for each race.
    first_anchor = {}
    for pos, race_no in anchors:
        first_anchor.setdefault(race_no, pos)
    ordered = sorted((pos, race_no) for race_no, pos in first_anchor.items())
    parsed = {}
    for idx, (pos, race_no) in enumerate(ordered):
        end = ordered[idx + 1][0] if idx + 1 < len(ordered) else min(len(text), pos + 12000)
        block = text[pos:end]
        header_end = block.find("発走")
        header = block[: header_end + 160 if header_end >= 0 else 700]

        surface = None
        direction = None
        sm = re.search(r"[\(（]\s*(芝|ダート|障害)\s*[・･\s]*(右|左|直線)?[^\)）]{0,40}[\)）]", header)
        if sm:
            surface = sm.group(1)
            direction = sm.group(2) or None
        else:
            sm = re.search(r"(芝|ダート|障害).{0,30}?(右|左|直線)", header)
            if sm:
                surface = sm.group(1)
                direction = sm.group(2)

        before_start = block[:header_end] if header_end >= 0 else block[:500]
        nums = []
        for n in re.findall(r"(?<!\d)(\d{3,5})(?!\d)", before_start.replace(",", "")):
            value = int(n)
            if 800 <= value <= 5000:
                nums.append(value)
        distance = nums[-1] if nums else None

        weather = ""
        track = ""
        wm = re.search(r"(\d{1,2})月\s*(\d{1,2})日\s*(晴|曇|雨|雪|小雨|小雪)?\s*(良|稍重|重|不良)?", text[max(0, pos - 160): pos + 180])
        if wm:
            weather = wm.group(3) or ""
            track = wm.group(4) or ""

        race_name = ""
        conditions = ""
        nm = re.search(r"第\s*\d{1,2}\s*競走\s*(.*?)\s+(\d{3,5})(?:\s|[^0-9])", before_start.replace(",", ""), re.S)
        if nm:
            race_name = compact(nm.group(1))[:120]
            conditions = race_name

        parsed[race_no] = {
            "surface": surface,
            "distanceM": distance,
            "direction": direction,
            "raceName": race_name,
            "conditions": conditions,
            "weather": weather,
            "trackCondition": track,
            "courseText": compact(header)[:240],
            "parsed": bool(surface and distance),
        }
    return parsed


def fetch_pdf_group(pdf_url):
    try:
        body, _ = http_bytes(pdf_url, attempts=5, timeout=75)
        if not body.startswith(b"%PDF"):
            return pdf_url, {}, "NOT_PDF"
        parsed = parse_pdf_races(body)
        return pdf_url, parsed, None
    except Exception as e:
        return pdf_url, {}, f"{type(e).__name__}:{e}"


def parse_context_html(page, row):
    soup = BeautifulSoup(page, "html.parser")
    text = compact(soup.get_text(" ", strip=True))
    distance = None
    surface = None
    direction = None
    course_inside = ""

    m = re.search(r"コース\s*[：:]\s*([0-9,]+)\s*メートル\s*[（(]([^）)]{1,100})[）)]", text)
    if m:
        distance = int(m.group(1).replace(",", ""))
        course_inside = compact(m.group(2))
        if "ダート" in course_inside:
            surface = "ダート"
        elif "芝" in course_inside:
            surface = "芝"
        elif "障害" in course_inside:
            surface = "障害"
        if "右" in course_inside:
            direction = "右"
        elif "左" in course_inside:
            direction = "左"
        elif "直線" in course_inside:
            direction = "直線"

    weather = ""
    wm = re.search(r"天候\s*[：:]?\s*([晴曇雨雪小雨小雪]+)", text)
    if wm:
        weather = wm.group(1)
    track = ""
    tm = re.search(r"(?:芝|ダート)\s*[：:]?\s*(良|稍重|重|不良)", text)
    if tm:
        track = tm.group(1)

    return {
        "raceId": row["raceId"], "raceDate": row["raceDate"], "venue": row["venue"],
        "raceNo": int(row["raceNo"]), "surface": surface, "distanceM": distance,
        "direction": direction, "raceName": compact(row.get("raceName")),
        "conditions": compact(row.get("conditions")), "weather": weather or compact(row.get("weather")),
        "trackCondition": track or compact(row.get("trackCondition")), "courseText": course_inside,
        "sourceUrl": row.get("resultUrl"), "parsed": bool(surface and distance),
    }


def fetch_one_page(row):
    url = row.get("resultUrl")
    if not url:
        return {"raceId": row["raceId"], "parsed": False, "error": "NO_RESULT_URL"}
    try:
        body, charset = http_bytes(url, attempts=5, timeout=45)
        page = body.decode(charset or "utf-8", errors="replace")
        result = parse_context_html(page, row)
        if not result.get("parsed"):
            result["error"] = "PARSE_MISS"
        return result
    except Exception as e:
        return {
            "raceId": row["raceId"], "raceDate": row.get("raceDate"), "venue": row.get("venue"),
            "raceNo": row.get("raceNo"), "parsed": False, "sourceUrl": url,
            "error": f"{type(e).__name__}:{e}",
        }


rows = d1(
    """
    SELECT race_id raceId, race_date raceDate, venue, race_no raceNo,
           result_url resultUrl, surface, distance_m distanceM, direction,
           race_name raceName, conditions, weather, track_condition trackCondition
    FROM rt_races
    WHERE race_date >= ? AND race_date < ? AND status='finished'
    ORDER BY race_date, venue, race_no
    """,
    [START, END_EXCLUSIVE],
)
if len(rows) != EXPECTED_RACES:
    raise RuntimeError(f"FIXED_ARCHIVE_COUNT_MISMATCH:{len(rows)}")

# Build one official JRA PDF request per meeting-day. The result URL itself contains
# venue code, year, meeting number and meeting day; no result-derived inference is used.
pdf_groups = defaultdict(list)
no_pdf_key = []
for row in rows:
    parts = result_url_parts(row.get("resultUrl"))
    if parts:
        pdf_groups[parts["pdfUrl"]].append(row)
    else:
        no_pdf_key.append(row)

print(json.dumps({
    "archive": len(rows), "meetingDayPdfs": len(pdf_groups), "rowsWithoutPdfKey": len(no_pdf_key),
    "pdfWorkers": PDF_WORKERS
}, ensure_ascii=False), flush=True)

pdf_results = {}
pdf_errors = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=PDF_WORKERS) as pool:
    futures = {pool.submit(fetch_pdf_group, url): url for url in pdf_groups}
    for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
        url, parsed, error = future.result()
        pdf_results[url] = parsed
        if error:
            pdf_errors[url] = error
        if index % 50 == 0:
            print(json.dumps({"pdfsCompleted": index, "pdfsParsed": sum(bool(x) for x in pdf_results.values()), "pdfErrors": len(pdf_errors)}, ensure_ascii=False), flush=True)

results = []
fallback = []
pdf_parsed_rows = 0
for row in rows:
    parts = result_url_parts(row.get("resultUrl"))
    parsed = pdf_results.get(parts["pdfUrl"], {}).get(int(row["raceNo"])) if parts else None
    if parsed and parsed.get("parsed"):
        results.append({
            "raceId": row["raceId"], "raceDate": row["raceDate"], "venue": row["venue"],
            "raceNo": int(row["raceNo"]), "surface": parsed["surface"], "distanceM": int(parsed["distanceM"]),
            "direction": parsed.get("direction") or compact(row.get("direction")) or None,
            "raceName": parsed.get("raceName") or compact(row.get("raceName")),
            "conditions": parsed.get("conditions") or compact(row.get("conditions")),
            "weather": parsed.get("weather") or compact(row.get("weather")),
            "trackCondition": parsed.get("trackCondition") or compact(row.get("trackCondition")),
            "courseText": parsed.get("courseText") or "", "sourceUrl": parts["pdfUrl"],
            "parsed": True, "source": "jra_official_daily_pdf",
        })
        pdf_parsed_rows += 1
        continue

    try:
        distance = int(row.get("distanceM") or 0)
    except Exception:
        distance = 0
    surface = compact(row.get("surface"))
    if surface and distance > 0:
        results.append({
            "raceId": row["raceId"], "raceDate": row["raceDate"], "venue": row["venue"],
            "raceNo": int(row["raceNo"]), "surface": surface, "distanceM": distance,
            "direction": compact(row.get("direction")) or None,
            "raceName": compact(row.get("raceName")), "conditions": compact(row.get("conditions")),
            "weather": compact(row.get("weather")), "trackCondition": compact(row.get("trackCondition")),
            "courseText": "", "sourceUrl": row.get("resultUrl"), "parsed": True, "source": "existing_d1",
        })
    else:
        fallback.append(row)

print(json.dumps({
    "pdfParsedRows": pdf_parsed_rows, "fallbackPages": len(fallback), "pdfErrors": len(pdf_errors),
    "pageWorkers": PAGE_WORKERS
}, ensure_ascii=False), flush=True)

if fallback:
    with concurrent.futures.ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
        futures = [pool.submit(fetch_one_page, row) for row in fallback]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result.get("parsed"):
                result["source"] = "jra_result_page_fallback"
            results.append(result)
            if index % 250 == 0:
                print(json.dumps({"fallbackCompleted": index}, ensure_ascii=False), flush=True)

results.sort(key=lambda r: (str(r.get("raceDate") or ""), str(r.get("venue") or ""), int(r.get("raceNo") or 0)))
parsed = [r for r in results if r.get("parsed")]
failed = [r for r in results if not r.get("parsed")]
coverage = len(parsed) / EXPECTED_RACES
surface_counts = {}
source_counts = {}
for row in parsed:
    surface_counts[row.get("surface") or ""] = surface_counts.get(row.get("surface") or "", 0) + 1
    source_counts[row.get("source") or ""] = source_counts.get(row.get("source") or "", 0) + 1

OUT.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=6) as f:
    json.dump({"schema": 3, "fixedArchiveOnly": True, "rows": results}, f, ensure_ascii=False)
META.write_text(json.dumps({
    "races": EXPECTED_RACES,
    "parsed": len(parsed), "failed": len(failed), "coveragePct": coverage * 100.0,
    "surfaceCounts": surface_counts, "sourceCounts": source_counts,
    "meetingDayPdfs": len(pdf_groups), "pdfErrors": len(pdf_errors),
    "pdfErrorExamples": list(pdf_errors.items())[:20],
    "start": START, "end": "2026-08-02",
    "failedExamples": [
        {"raceId": r.get("raceId"), "date": r.get("raceDate"), "venue": r.get("venue"),
         "raceNo": r.get("raceNo"), "url": r.get("sourceUrl"), "error": r.get("error")}
        for r in failed[:50]
    ],
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "parsed": len(parsed), "failed": len(failed), "coveragePct": coverage * 100.0,
    "surfaceCounts": surface_counts, "sourceCounts": source_counts,
}, ensure_ascii=False), flush=True)
if coverage < 0.98:
    raise RuntimeError(f"FIXED_CONTEXT_COVERAGE_TOO_LOW:{coverage:.6f}")
