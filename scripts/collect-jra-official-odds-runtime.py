import http.cookiejar
import importlib.util
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "collect-jra-official-odds.py"
spec = importlib.util.spec_from_file_location("official_odds_collector_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("OFFICIAL_ODDS_BASE_IMPORT_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
D1_BATCH_ROWS = int(base.os.environ.get("JRA_ODDS_D1_BATCH_ROWS", "40"))


def fetch_url(url: str, *, cname: str | None = None, referer: str | None = None) -> str:
    data = None
    headers = {
        "User-Agent": base.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": referer or "https://www.jra.go.jp/",
        "Upgrade-Insecure-Requests": "1",
    }
    if cname is not None:
        data = urllib.parse.urlencode({"cname": cname}).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with OPENER.open(request, timeout=35) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise RuntimeError("JRA_ODDS_BODY_TOO_LARGE")
                text = base.decode_body(raw, response.headers.get("content-type"))
            if re.search(r"captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable", text, re.I):
                raise RuntimeError("JRA_ODDS_PAGE_BLOCKED")
            return text
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            last_error = error
            if isinstance(error, RuntimeError) and str(error) != "JRA_ODDS_PAGE_BLOCKED":
                raise
        if attempt < 2:
            time.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"JRA_ODDS_FETCH_FAILED:{type(last_error).__name__}:{last_error}")


def race_no_from_cname(cname: str) -> int | None:
    decoded = urllib.parse.unquote(base.html_module.unescape(cname))
    values = [int(value) for value in re.findall(r"(\d{2})(?=20\d{6}(?:/|$))", decoded)]
    return next((value for value in reversed(values) if 1 <= value <= 12), None)


def parse_page_identity(page_html: str, cname: str) -> tuple[str, str, int] | None:
    text = base.page_text(page_html)
    date_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    venue_match = re.search(rf"\d+回({base.VENUES})\d+日", text)
    race_no = race_no_from_cname(cname)
    if race_no is None:
        values = [int(value) for value in re.findall(r"(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)", text)]
        race_no = next((value for value in values if 1 <= value <= 12), None)
    if not date_match or not venue_match or race_no is None:
        return None
    race_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    return race_date, venue_match.group(1), race_no


def insert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    for start in range(0, len(rows), max(1, D1_BATCH_ROWS)):
        chunk = rows[start : start + max(1, D1_BATCH_ROWS)]
        placeholders = ",".join(["(?,?,?,?,?,?,?,?,?,?,?,'jra_official')"] * len(chunk))
        params: list[object] = []
        for row in chunk:
            params.extend([
                row["raceId"], row["betType"], row["combination"], row["oddsMin"],
                row["oddsMax"], row["capturedAtUtc"], row.get("startTimeUtc"),
                row.get("secondsToStart"),
                f"{base.JRA_ODDS_URL}?CNAME={urllib.parse.quote(row['sourceCname'], safe='')}",
                row["sourceCname"], row["sourceHash"],
            ])
        base.d1_query("""
            INSERT OR IGNORE INTO rt_official_odds_snapshots (
              race_id, bet_type, combination, odds_min, odds_max, captured_at_utc,
              race_start_time_utc, seconds_to_start, source_url, source_cname, source_hash, odds_source
            ) VALUES
            """ + placeholders, params)
        base.d1_query("""
            INSERT INTO rt_official_odds_latest (
              race_id, bet_type, combination, odds_min, odds_max, captured_at_utc,
              race_start_time_utc, seconds_to_start, source_url, source_cname, source_hash, odds_source
            ) VALUES
            """ + placeholders + """
            ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET
              odds_min=excluded.odds_min, odds_max=excluded.odds_max,
              captured_at_utc=excluded.captured_at_utc,
              race_start_time_utc=excluded.race_start_time_utc,
              seconds_to_start=excluded.seconds_to_start,
              source_url=excluded.source_url, source_cname=excluded.source_cname,
              source_hash=excluded.source_hash, odds_source='jra_official',
              updated_at=CURRENT_TIMESTAMP
            WHERE excluded.captured_at_utc >= rt_official_odds_latest.captured_at_utc
            """, params)


def main() -> None:
    base.ensure_schema()
    races = base.upcoming_races()
    captured = base.datetime.now(base.timezone.utc)
    captured_iso = captured.isoformat()
    target_by_identity = {(row["raceDate"], row["venue"], int(row["raceNo"])): row for row in races}
    queue = base.deque([base.JRA_ODDS_HOME_CNAME])
    hints = {base.JRA_ODDS_HOME_CNAME: "今週のオッズ"}
    seen: set[str] = set()
    errors: list[str] = []
    pages_fetched = 0
    records: dict[tuple[str, str, str], dict] = {}
    for race in races:
        entry_url = race.get("entryUrl")
        if not entry_url:
            continue
        try:
            entry_html = fetch_url(entry_url)
            for cname, context in base.action_links(entry_html):
                if cname not in seen:
                    queue.append(cname); hints.setdefault(cname, context)
        except Exception as error:
            errors.append(f"ENTRY:{race['raceId']}:{type(error).__name__}:{error}")
    while queue and pages_fetched < base.MAX_PAGES:
        cname = queue.popleft()
        if cname in seen:
            continue
        seen.add(cname)
        try:
            page = fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
            pages_fetched += 1
            source_hash = base.hashlib.sha256(page.encode("utf-8", errors="replace")).hexdigest()
            for child, context in base.action_links(page):
                hints.setdefault(child, context)
                if child not in seen: queue.append(child)
            identity = parse_page_identity(page, cname)
            bet_type = base.detect_bet_type(page, hints.get(cname, ""))
            if identity in target_by_identity and bet_type:
                race = target_by_identity[identity]
                for combination, low, high in base.parse_odds_rows(page, bet_type):
                    records[(race["raceId"], bet_type, combination)] = {
                        "raceId": race["raceId"], "betType": bet_type, "combination": combination,
                        "oddsMin": low, "oddsMax": high, "capturedAtUtc": captured_iso,
                        "startTimeUtc": race.get("startTimeUtc"),
                        "secondsToStart": base.seconds_to_start(race.get("startTimeUtc"), captured),
                        "sourceCname": cname, "sourceHash": source_hash,
                    }
            time.sleep(base.REQUEST_PAUSE_SECONDS)
        except Exception as error:
            errors.append(f"ODDS:{cname}:{type(error).__name__}:{error}")
    rows = list(records.values()); insert_rows(rows)
    counts_by_type = base.defaultdict(int); races_by_type = base.defaultdict(set)
    for row in rows:
        counts_by_type[row["betType"]] += 1; races_by_type[row["betType"]].add(row["raceId"])
    report = {"generatedAt": captured_iso,"status":"stored_official_odds" if rows else "waiting_for_official_odds","oddsSource":"jra_official","upcomingRaceCount":len(races),"pagesFetched":pages_fetched,"cnamesSeen":len(seen),"storedOddsRows":len(rows),"coveredRaces":len({row["raceId"] for row in rows}),"rowsByBetType":dict(sorted(counts_by_type.items())),"racesByBetType":{k:len(v) for k,v in sorted(races_by_type.items())},"errors":errors[:100],"errorCount":len(errors)}
    base.REPORT_PATH.write_text(base.json.dumps(report, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print(base.json.dumps(report, ensure_ascii=False, indent=2))
    if races and pages_fetched == 0: raise RuntimeError("JRA_OFFICIAL_ODDS_PAGES_UNREACHABLE")

if __name__ == "__main__":
    main()
