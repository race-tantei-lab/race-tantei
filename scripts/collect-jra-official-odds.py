import hashlib
import html as html_module
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "official-odds-collection-report.json"
JRA_ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html"
JRA_ODDS_HOME_CNAME = "pw15oli00/6D"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36"
BET_TYPES = ("3連単", "3連複", "馬単", "馬連", "ワイド", "単勝")
UNORDERED_TYPES = {"ワイド", "馬連", "3連複"}
ARITY = {"単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 2, "3連複": 3, "3連単": 3}
VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉"
MAX_PAGES = int(os.environ.get("JRA_ODDS_MAX_PAGES", "600"))
REQUEST_PAUSE_SECONDS = float(os.environ.get("JRA_ODDS_REQUEST_PAUSE_SECONDS", "0.12"))
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def decode_body(raw: bytes, content_type: str | None = None) -> str:
    declared = None
    if content_type:
        match = re.search(r"charset\s*=\s*([^;\s]+)", content_type, re.I)
        declared = match.group(1).strip("\"'") if match else None
    probe = raw[:8192].decode("latin1", errors="ignore")
    meta = re.search(r"charset=[\"']?([^\"'\s/>]+)", probe, re.I)
    for charset in (declared, meta.group(1) if meta else None, "cp932", "shift_jis", "utf-8"):
        if not charset:
            continue
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_url(url: str, *, cname: str | None = None) -> str:
    data = None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.jra.go.jp/",
    }
    if cname is not None:
        data = urllib.parse.urlencode({"cname": cname}).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise RuntimeError("JRA_ODDS_BODY_TOO_LARGE")
        text = decode_body(raw, response.headers.get("content-type"))
    if re.search(r"captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable", text, re.I):
        raise RuntimeError("JRA_ODDS_PAGE_BLOCKED")
    return text


def d1_query(sql: str, params: list | None = None) -> list[dict]:
    payload = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        D1_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def ensure_schema() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS rt_official_odds_snapshots (
          race_id TEXT NOT NULL,
          bet_type TEXT NOT NULL,
          combination TEXT NOT NULL,
          odds_min REAL NOT NULL,
          odds_max REAL NOT NULL,
          captured_at_utc TEXT NOT NULL,
          race_start_time_utc TEXT,
          seconds_to_start INTEGER,
          source_url TEXT NOT NULL,
          source_cname TEXT NOT NULL,
          source_hash TEXT NOT NULL,
          odds_source TEXT NOT NULL DEFAULT 'jra_official',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, bet_type, combination, captured_at_utc)
        )
        """,
        "CREATE INDEX IF NOT EXISTS rt_idx_official_odds_snapshot_race_time ON rt_official_odds_snapshots(race_id, captured_at_utc DESC)",
        """
        CREATE TABLE IF NOT EXISTS rt_official_odds_latest (
          race_id TEXT NOT NULL,
          bet_type TEXT NOT NULL,
          combination TEXT NOT NULL,
          odds_min REAL NOT NULL,
          odds_max REAL NOT NULL,
          captured_at_utc TEXT NOT NULL,
          race_start_time_utc TEXT,
          seconds_to_start INTEGER,
          source_url TEXT NOT NULL,
          source_cname TEXT NOT NULL,
          source_hash TEXT NOT NULL,
          odds_source TEXT NOT NULL DEFAULT 'jra_official',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, bet_type, combination)
        )
        """,
        "CREATE INDEX IF NOT EXISTS rt_idx_official_odds_latest_race ON rt_official_odds_latest(race_id, bet_type)",
        """
        CREATE TABLE IF NOT EXISTS rt_official_value_candidates (
          race_id TEXT NOT NULL,
          model_version TEXT NOT NULL,
          captured_at_utc TEXT NOT NULL,
          bet_type TEXT NOT NULL,
          combination TEXT NOT NULL,
          model_probability REAL NOT NULL,
          conservative_probability REAL NOT NULL,
          official_odds REAL NOT NULL,
          projected_roi_pct REAL NOT NULL,
          predicted_rank_sum INTEGER NOT NULL,
          includes_model_first INTEGER NOT NULL,
          odds_source TEXT NOT NULL DEFAULT 'jra_official',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (race_id, model_version, captured_at_utc, bet_type, combination)
        )
        """,
        "CREATE INDEX IF NOT EXISTS rt_idx_value_candidates_settlement ON rt_official_value_candidates(race_id, model_version, captured_at_utc)",
    ]
    for statement in statements:
        d1_query(statement)


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style\b[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_module.unescape(value)).strip()


def action_links(page_html: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    pattern = re.compile(
        r"doAction\(\s*['\"]\/JRADB\/accessO\.html['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
        re.I,
    )
    for match in pattern.finditer(page_html):
        start = page_html.rfind("<a", max(0, match.start() - 1000), match.start())
        end = page_html.find("</a>", match.end(), min(len(page_html), match.end() + 1500))
        context = strip_tags(page_html[start : end + 4] if start >= 0 and end >= 0 else page_html[max(0, match.start() - 250) : match.end() + 250])
        rows.append((html_module.unescape(match.group(1)), context))
    return rows


def page_text(page_html: str) -> str:
    normalized = re.sub(r"<\s*br\s*\/?>|</(?:tr|td|th|li|p|div|section|h[1-6])>", "\n", page_html, flags=re.I)
    return "\n".join(line.strip() for line in strip_tags(normalized).splitlines() if line.strip())


def heading_text(page_html: str) -> str:
    values = []
    for pattern in (r"<title[^>]*>([\s\S]*?)</title>", r"<h[1-4][^>]*>([\s\S]*?)</h[1-4]>"):
        values.extend(strip_tags(match.group(1)) for match in re.finditer(pattern, page_html, re.I))
    return " | ".join(value for value in values if value)


def detect_bet_type(page_html: str, hint: str = "") -> str | None:
    target = f"{heading_text(page_html)} | {hint}"
    for bet_type in BET_TYPES:
        if bet_type in target and "オッズ" in target:
            return bet_type
    compact = page_text(page_html)[:3500]
    for bet_type in BET_TYPES:
        if re.search(rf"{re.escape(bet_type)}\s*オッズ", compact):
            return bet_type
    return None


def parse_page_identity(page_html: str) -> tuple[str, str, int] | None:
    text = page_text(page_html)
    date_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    venue_match = re.search(rf"\d+回({VENUES})\d+日", text)
    race_matches = [int(value) for value in re.findall(r"(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)", text)]
    race_no = next((value for value in race_matches if 1 <= value <= 12), None)
    if not date_match or not venue_match or race_no is None:
        return None
    race_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    return race_date, venue_match.group(1), race_no


def normalize_combination(bet_type: str, horses: list[int]) -> str:
    values = sorted(horses) if bet_type in UNORDERED_TYPES else horses
    return "-".join(str(value) for value in values)


def odds_value(value: str) -> tuple[float, float] | None:
    compact = value.replace(",", "").replace("倍", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:[-－–〜～]\s*(\d+(?:\.\d+)?))?", compact)
    if not match:
        return None
    low = float(match.group(1))
    high = float(match.group(2) or match.group(1))
    if low <= 1.0 or high < low or high > 100000:
        return None
    return low, high


def parsed_rows(page_html: str) -> list[list[str]]:
    output: list[list[str]] = []
    for row in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", page_html, re.I):
        cells = [strip_tags(match.group(1)) for match in re.finditer(r"<t[dh]\b[^>]*>([\s\S]*?)</t[dh]>", row.group(1), re.I)]
        if cells:
            output.append(cells)
    return output


def parse_odds_rows(page_html: str, bet_type: str) -> list[tuple[str, float, float]]:
    arity = ARITY[bet_type]
    parsed: dict[str, tuple[float, float]] = {}
    for cells in parsed_rows(page_html):
        for odds_index, cell in enumerate(cells):
            value = odds_value(cell)
            if value is None:
                continue
            before = " ".join(cells[:odds_index])
            integers = [int(token) for token in re.findall(r"(?<![.\d])(\d{1,2})(?![.\d])", before)]
            horses = [number for number in integers if 1 <= number <= 18]
            if len(horses) < arity:
                same_cell = [int(token) for token in re.findall(r"(?<![.\d])(\d{1,2})(?![.\d])", cell)]
                horses.extend(number for number in same_cell if 1 <= number <= 18)
            if len(horses) < arity:
                continue
            combination_horses = horses[-arity:]
            if len(set(combination_horses)) != arity:
                continue
            combination = normalize_combination(bet_type, combination_horses)
            previous = parsed.get(combination)
            if previous is None or value[0] < previous[0]:
                parsed[combination] = value
    return [(combination, low, high) for combination, (low, high) in sorted(parsed.items())]


def upcoming_races() -> list[dict]:
    return d1_query(
        """
        SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo,
               start_time_utc AS startTimeUtc, entry_url AS entryUrl
        FROM rt_races
        WHERE status != 'finished'
          AND start_time_utc IS NOT NULL
          AND datetime(start_time_utc) >= datetime('now', '-2 hours')
          AND datetime(start_time_utc) <= datetime('now', '+5 days')
        ORDER BY start_time_utc, venue, race_no
        """
    )


def seconds_to_start(start_time_utc: str | None, captured: datetime) -> int | None:
    if not start_time_utc:
        return None
    try:
        value = datetime.fromisoformat(start_time_utc.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int((value - captured).total_seconds())
    except ValueError:
        return None


def insert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    snapshot_sql = """
      INSERT OR IGNORE INTO rt_official_odds_snapshots (
        race_id, bet_type, combination, odds_min, odds_max, captured_at_utc,
        race_start_time_utc, seconds_to_start, source_url, source_cname, source_hash, odds_source
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'jra_official')
    """
    latest_sql = """
      INSERT INTO rt_official_odds_latest (
        race_id, bet_type, combination, odds_min, odds_max, captured_at_utc,
        race_start_time_utc, seconds_to_start, source_url, source_cname, source_hash, odds_source, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'jra_official', CURRENT_TIMESTAMP)
      ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET
        odds_min=excluded.odds_min, odds_max=excluded.odds_max,
        captured_at_utc=excluded.captured_at_utc,
        race_start_time_utc=excluded.race_start_time_utc,
        seconds_to_start=excluded.seconds_to_start,
        source_url=excluded.source_url, source_cname=excluded.source_cname,
        source_hash=excluded.source_hash, odds_source='jra_official', updated_at=CURRENT_TIMESTAMP
      WHERE excluded.captured_at_utc >= rt_official_odds_latest.captured_at_utc
    """
    for row in rows:
        params = [
            row["raceId"], row["betType"], row["combination"], row["oddsMin"], row["oddsMax"],
            row["capturedAtUtc"], row.get("startTimeUtc"), row.get("secondsToStart"),
            JRA_ODDS_URL, row["sourceCname"], row["sourceHash"],
        ]
        d1_query(snapshot_sql, params)
        d1_query(latest_sql, params)


def main() -> None:
    ensure_schema()
    races = upcoming_races()
    captured = datetime.now(timezone.utc)
    captured_iso = captured.isoformat()
    target_by_identity = {(row["raceDate"], row["venue"], int(row["raceNo"])): row for row in races}
    queue: deque[str] = deque([JRA_ODDS_HOME_CNAME])
    hints: dict[str, str] = {JRA_ODDS_HOME_CNAME: "今週のオッズ"}
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
            for cname, context in action_links(entry_html):
                if cname not in seen:
                    queue.append(cname)
                    hints.setdefault(cname, context)
        except Exception as error:
            errors.append(f"ENTRY:{race['raceId']}:{type(error).__name__}:{error}")

    while queue and pages_fetched < MAX_PAGES:
        cname = queue.popleft()
        if cname in seen:
            continue
        seen.add(cname)
        try:
            page = fetch_url(JRA_ODDS_URL, cname=cname)
            pages_fetched += 1
            source_hash = hashlib.sha256(page.encode("utf-8", errors="replace")).hexdigest()
            for child, context in action_links(page):
                hints.setdefault(child, context)
                if child not in seen:
                    queue.append(child)
            identity = parse_page_identity(page)
            bet_type = detect_bet_type(page, hints.get(cname, ""))
            if identity in target_by_identity and bet_type:
                race = target_by_identity[identity]
                for combination, low, high in parse_odds_rows(page, bet_type):
                    key = (race["raceId"], bet_type, combination)
                    records[key] = {
                        "raceId": race["raceId"],
                        "betType": bet_type,
                        "combination": combination,
                        "oddsMin": low,
                        "oddsMax": high,
                        "capturedAtUtc": captured_iso,
                        "startTimeUtc": race.get("startTimeUtc"),
                        "secondsToStart": seconds_to_start(race.get("startTimeUtc"), captured),
                        "sourceCname": cname,
                        "sourceHash": source_hash,
                    }
            time.sleep(REQUEST_PAUSE_SECONDS)
        except Exception as error:
            errors.append(f"ODDS:{cname}:{type(error).__name__}:{error}")

    rows = list(records.values())
    insert_rows(rows)
    counts_by_type: dict[str, int] = defaultdict(int)
    races_by_type: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        counts_by_type[row["betType"]] += 1
        races_by_type[row["betType"]].add(row["raceId"])
    report = {
        "generatedAt": captured_iso,
        "oddsSource": "jra_official",
        "upcomingRaceCount": len(races),
        "pagesFetched": pages_fetched,
        "cnamesSeen": len(seen),
        "storedOddsRows": len(rows),
        "coveredRaces": len({row["raceId"] for row in rows}),
        "rowsByBetType": dict(sorted(counts_by_type.items())),
        "racesByBetType": {key: len(value) for key, value in sorted(races_by_type.items())},
        "errors": errors[:100],
        "errorCount": len(errors),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
