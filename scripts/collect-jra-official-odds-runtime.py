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
    for attempt in range(5):
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
        if attempt < 4:
            time.sleep(2.0 * (attempt + 1))
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


def _class_table_matches(page_html: str, token: str):
    pattern = re.compile(
        rf"<table\b[^>]*class=(['\"])[^'\"]*(?:^|\s){re.escape(token)}(?:\s|$)[^'\"]*\1[^>]*>([\s\S]*?)</table>",
        re.I,
    )
    matches = list(pattern.finditer(page_html))
    if matches:
        return matches
    # JRA may include multiple classes without whitespace boundaries exactly as expected.
    return list(re.finditer(
        rf"<table\b[^>]*class=(['\"])[^'\"]*{re.escape(token)}[^'\"]*\1[^>]*>([\s\S]*?)</table>",
        page_html,
        re.I,
    ))


def _caption_numbers(table_body: str) -> list[int]:
    match = re.search(r"<caption\b[^>]*>([\s\S]*?)</caption>", table_body, re.I)
    if not match:
        return []
    return [int(value) for value in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", base.strip_tags(match.group(1))) if 1 <= int(value) <= 18]


def _row_horse_and_odds(row_html: str) -> tuple[int, tuple[float, float]] | None:
    th = re.search(r"<th\b[^>]*>([\s\S]*?)</th>", row_html, re.I)
    if not th:
        return None
    nums = [int(value) for value in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", base.strip_tags(th.group(1))) if 1 <= int(value) <= 18]
    if not nums:
        return None
    horse = nums[-1]
    td_values = [base.strip_tags(m.group(1)) for m in re.finditer(r"<td\b[^>]*>([\s\S]*?)</td>", row_html, re.I)]
    for text in td_values:
        value = base.odds_value(text)
        if value is not None:
            return horse, value
    return None


def _parse_grouped_table(page_html: str, bet_type: str, class_token: str, caption_arity: int) -> list[tuple[str, float, float]]:
    parsed: dict[str, tuple[float, float]] = {}
    for table in _class_table_matches(page_html, class_token):
        body = table.group(2)
        prefix = _caption_numbers(body)
        if len(prefix) < caption_arity:
            continue
        prefix = prefix[-caption_arity:]
        for row in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", body, re.I):
            item = _row_horse_and_odds(row.group(1))
            if item is None:
                continue
            horse, value = item
            horses = [*prefix, horse]
            if len(set(horses)) != len(horses):
                continue
            combination = base.normalize_combination(bet_type, horses)
            previous = parsed.get(combination)
            if previous is None or value[0] < previous[0]:
                parsed[combination] = value
    return [(key, low, high) for key, (low, high) in sorted(parsed.items())]


def _parse_trifecta(page_html: str) -> list[tuple[str, float, float]]:
    parsed: dict[str, tuple[float, float]] = {}
    for table in _class_table_matches(page_html, "tan3"):
        body = table.group(2)
        before = page_html[max(0, table.start() - 2600):table.start()]
        li_start = before.rfind("<li")
        if li_start >= 0:
            before = before[li_start:]
        # JRA tan3 groups explicitly show 1着 and 2着 in p_line divs before the table.
        first_match = re.search(r"1着[\s\S]{0,600}?<div\b[^>]*class=(['\"])[^'\"]*\bnum\b[^'\"]*\1[^>]*>\s*(\d{1,2})\s*</div>", before, re.I)
        second_match = re.search(r"2着[\s\S]{0,600}?<div\b[^>]*class=(['\"])[^'\"]*\bnum\b[^'\"]*\1[^>]*>\s*(\d{1,2})\s*</div>", before, re.I)
        if first_match and second_match:
            first, second = int(first_match.group(2)), int(second_match.group(2))
        else:
            nums = [int(v) for v in re.findall(r"<div\b[^>]*class=(?:['\"])[^'\"]*\bnum\b[^'\"]*(?:['\"])[^>]*>\s*(\d{1,2})\s*</div>", before, re.I)]
            if len(nums) < 2:
                continue
            first, second = nums[-2], nums[-1]
        if not (1 <= first <= 18 and 1 <= second <= 18) or first == second:
            continue
        for row in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", body, re.I):
            item = _row_horse_and_odds(row.group(1))
            if item is None:
                continue
            third, value = item
            if third in {first, second}:
                continue
            combination = f"{first}-{second}-{third}"
            parsed[combination] = value
    return [(key, low, high) for key, (low, high) in sorted(parsed.items())]


def parse_odds_rows(page_html: str, bet_type: str) -> list[tuple[str, float, float]]:
    if bet_type == "単勝":
        return base.parse_odds_rows(page_html, bet_type)
    if bet_type == "馬連":
        return _parse_grouped_table(page_html, bet_type, "umaren", 1)
    if bet_type == "ワイド":
        return _parse_grouped_table(page_html, bet_type, "wide", 1)
    if bet_type == "馬単":
        return _parse_grouped_table(page_html, bet_type, "umatan", 1)
    if bet_type == "3連複":
        return _parse_grouped_table(page_html, bet_type, "fuku3", 2)
    if bet_type == "3連単":
        return _parse_trifecta(page_html)
    return []


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
                for combination, low, high in parse_odds_rows(page, bet_type):
                    records[(race["raceId"], bet_type, combination)] = {
                        "raceId": race["raceId"], "betType": bet_type, "combination": combination,
                        "oddsMin": low, "oddsMax": high, "capturedAtUtc": captured_iso,
                        "startTimeUtc": race.get("startTimeUtc"),
                        "secondsToStart": base.seconds_to_start(race.get("startTimeUtc"), captured),
                        "sourceCname": cname, "sourceHash": source_hash,
                    }
            time.sleep(max(base.REQUEST_PAUSE_SECONDS, 0.35))
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
