import concurrent.futures
import gzip
import html
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

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
WORKERS = 6

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def d1(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
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


def parse_context(page, row):
    soup = BeautifulSoup(page, "html.parser")
    text = compact(soup.get_text(" ", strip=True))

    course_match = re.search(
        r"コース\s*[：:]\s*([0-9,]+)\s*メートル\s*[（(]([^）)]{1,80})[）)]",
        text,
    )
    distance = None
    surface = None
    direction = None
    course_inside = ""
    if course_match:
        distance = int(course_match.group(1).replace(",", ""))
        course_inside = compact(course_match.group(2))
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

    # Find the DOM node that contains the course line, then use the closest preceding
    # race heading and the text immediately before "コース" as race conditions.
    course_node = soup.find(string=re.compile(r"コース\s*[：:]"))
    race_name = ""
    conditions = ""
    if course_node is not None:
        heading = course_node.find_previous(["h1", "h2", "h3"])
        if heading is not None:
            candidate = compact(heading.get_text(" ", strip=True))
            if candidate and "レース結果" not in candidate and "検索" not in candidate:
                race_name = candidate
        parent_text = compact(course_node.parent.get_text(" ", strip=True)) if course_node.parent else compact(course_node)
        before = re.split(r"コース\s*[：:]", parent_text, maxsplit=1)[0].strip()
        if 0 < len(before) <= 180:
            conditions = before

    if not race_name:
        # Fallback: select the last meaningful heading before the first course text.
        headings = [compact(tag.get_text(" ", strip=True)) for tag in soup.find_all(["h1", "h2", "h3"])]
        headings = [x for x in headings if x and "レース結果" not in x and "検索" not in x and len(x) <= 80]
        if headings:
            race_name = headings[-1]

    weather = ""
    m = re.search(r"天候\s*([晴曇雨雪小雨小雪]+)", text)
    if m:
        weather = m.group(1)

    track = ""
    # On result pages the header normally renders like "ダート 良" or "芝 稍重".
    m = re.search(r"(?:芝|ダート)\s*(良|稍重|重|不良)", text)
    if m:
        track = m.group(1)

    return {
        "raceId": row["raceId"],
        "raceDate": row["raceDate"],
        "venue": row["venue"],
        "raceNo": int(row["raceNo"]),
        "surface": surface,
        "distanceM": distance,
        "direction": direction,
        "raceName": race_name,
        "conditions": conditions,
        "weather": weather,
        "trackCondition": track,
        "courseText": course_inside,
        "sourceUrl": row["resultUrl"],
        "parsed": bool(surface and distance),
    }


def fetch_one(row):
    url = row.get("resultUrl")
    if not url:
        return {"raceId": row["raceId"], "parsed": False, "error": "NO_RESULT_URL"}
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RaceTanteiContext/1.0; +https://www.jra.go.jp/)",
                "Accept-Language": "ja,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=45) as r:
                page = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
            result = parse_context(page, row)
            if result["parsed"]:
                return result
            last = "PARSE_MISS"
        except urllib.error.HTTPError as e:
            last = f"HTTP_{e.code}"
            if e.code not in {429, 500, 502, 503, 504}:
                break
        except Exception as e:
            last = f"{type(e).__name__}:{e}"
        time.sleep(min(12.0, 0.6 * (2 ** attempt)) + random.random() * 0.35)
    return {"raceId": row["raceId"], "raceDate": row.get("raceDate"), "venue": row.get("venue"), "raceNo": row.get("raceNo"), "parsed": False, "sourceUrl": url, "error": last}


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

# Preserve already valid D1 context and fetch only the missing historical rows.
results = []
missing = []
for row in rows:
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
            "courseText": "", "sourceUrl": row.get("resultUrl"), "parsed": True,
            "source": "existing_d1",
        })
    else:
        missing.append(row)

print(json.dumps({"archive": len(rows), "alreadyValid": len(results), "toFetch": len(missing), "workers": WORKERS}, ensure_ascii=False), flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    futures = [pool.submit(fetch_one, row) for row in missing]
    for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
        result = future.result()
        if result.get("parsed"):
            result["source"] = "jra_result_page"
        results.append(result)
        if index % 500 == 0:
            good = sum(bool(x.get("parsed")) for x in results)
            print(json.dumps({"completedFetches": index, "parsedTotal": good}, ensure_ascii=False), flush=True)

results.sort(key=lambda r: (str(r.get("raceDate") or ""), str(r.get("venue") or ""), int(r.get("raceNo") or 0)))
parsed = [r for r in results if r.get("parsed")]
failed = [r for r in results if not r.get("parsed")]
coverage = len(parsed) / EXPECTED_RACES
OUT.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=6) as f:
    json.dump({"schema": 1, "fixedArchiveOnly": True, "rows": results}, f, ensure_ascii=False)
META.write_text(json.dumps({
    "races": EXPECTED_RACES,
    "parsed": len(parsed),
    "failed": len(failed),
    "coveragePct": coverage * 100.0,
    "start": START,
    "end": "2026-08-02",
    "workers": WORKERS,
    "failedRaceIds": [r.get("raceId") for r in failed[:100]],
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"parsed": len(parsed), "failed": len(failed), "coveragePct": coverage * 100.0, "output": str(OUT)}, ensure_ascii=False), flush=True)
if coverage < 0.98:
    raise RuntimeError(f"FIXED_CONTEXT_COVERAGE_TOO_LOW:{coverage:.6f}")
