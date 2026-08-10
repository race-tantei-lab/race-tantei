import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis-results" / "research-ten-year-readonly-audit.json"
ARCHIVE_ENDPOINT = "https://www.jra.go.jp/JRADB/accessS.html"
ARCHIVE_INDEX_CNAME = "pw01skl00999999/B3"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36"

ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def d1_query(sql: str, params=None):
    payload = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        D1_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def decode_jra(raw: bytes, content_type: str | None) -> str:
    candidates = []
    if content_type:
        match = re.search(r"charset\s*=\s*([^;\s]+)", content_type, re.I)
        if match:
            candidates.append(match.group(1).strip("\"'"))
    probe = raw[:8192].decode("latin1", errors="ignore")
    match = re.search(r"charset=[\"']?([^\"'\s/>]+)", probe, re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(["cp932", "shift_jis", "utf-8"])
    for charset in candidates:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_archive(cname: str) -> str:
    data = urllib.parse.urlencode({"cname": cname}).encode("ascii")
    req = urllib.request.Request(
        ARCHIVE_ENDPOINT,
        data=data,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.jra.go.jp/",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise RuntimeError("ARCHIVE_BODY_TOO_LARGE")
        text = decode_jra(raw, response.headers.get("content-type"))
    if re.search(r"captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable", text, re.I):
        raise RuntimeError("ARCHIVE_BLOCKED_PAGE")
    return text.replace("&amp;", "&")


def extract_cnames(html: str, prefix_pattern: str):
    found = []
    for match in re.finditer(r"(?:CNAME=|cname=)([^\"'&<>\s)]+)", html, re.I):
        value = urllib.parse.unquote(match.group(1)).strip()
        if re.match(prefix_pattern, value, re.I):
            found.append(value)
    for match in re.finditer(r"(?:pw|sw)01[a-zA-Z0-9]+[^\"'<>\s,)]+/[0-9A-F]{2}", html, re.I):
        value = match.group(0).strip()
        if re.match(prefix_pattern, value, re.I):
            found.append(value)
    return list(dict.fromkeys(found))


def archive_audit():
    index = fetch_archive(ARCHIVE_INDEX_CNAME)
    checksums = {
        match.group(1): match.group(2).upper()
        for match in re.finditer(
            r"objParam\s*\[\s*[\"'](\d{4})[\"']\s*\]\s*=\s*[\"']([0-9A-F]{2})[\"']",
            index,
            re.I,
        )
    }
    target_months = [f"{year}01" for year in range(2016, 2027)]
    samples = []
    for year_month in target_months:
        key = year_month[2:]
        row = {
            "yearMonth": year_month,
            "checksumPresent": key in checksums,
            "meetingCount": 0,
            "resultLinkCountFromFirstMeeting": 0,
            "error": None,
        }
        try:
            checksum = checksums.get(key)
            if not checksum:
                raise RuntimeError("CHECKSUM_NOT_FOUND")
            month_html = fetch_archive(f"pw01skl10{year_month}/{checksum}")
            meetings = extract_cnames(month_html, r"^(?:pw|sw)01srl")
            row["meetingCount"] = len(meetings)
            if not meetings:
                raise RuntimeError("MEETINGS_NOT_FOUND")
            meeting_html = fetch_archive(meetings[0])
            results = extract_cnames(meeting_html, r"^(?:pw|sw)01sde")
            row["resultLinkCountFromFirstMeeting"] = len(results)
            if not results:
                raise RuntimeError("RESULT_LINKS_NOT_FOUND")
        except Exception as error:
            row["error"] = f"{type(error).__name__}:{error}"
        samples.append(row)
    keys = sorted(checksums)
    return {
        "indexMonthKeyCount": len(keys),
        "oldestIndexKey": keys[0] if keys else None,
        "newestIndexKey": keys[-1] if keys else None,
        "samples": samples,
        "tenYearArchiveReachable": all(
            row["checksumPresent"]
            and row["meetingCount"] > 0
            and row["resultLinkCountFromFirstMeeting"] > 0
            and row["error"] is None
            for row in samples
        ),
    }


def d1_audit():
    range_rows = d1_query(
        """
        SELECT MIN(race_date) AS firstDate, MAX(race_date) AS lastDate,
               COUNT(*) AS races,
               SUM(CASE WHEN status='finished' THEN 1 ELSE 0 END) AS finishedRaces
        FROM rt_races
        """
    )
    years = d1_query(
        """
        SELECT substr(r.race_date,1,4) AS year,
               COUNT(DISTINCT r.race_id) AS races,
               COUNT(DISTINCT CASE WHEN r.status='finished' THEN r.race_id END) AS finishedRaces,
               COUNT(DISTINCT p.race_id) AS racesWithPayouts,
               COUNT(DISTINCT z.race_id) AS racesWithResults
        FROM rt_races r
        LEFT JOIN rt_payouts p ON p.race_id=r.race_id
        LEFT JOIN rt_results z ON z.race_id=r.race_id
        GROUP BY substr(r.race_date,1,4)
        ORDER BY year
        """
    )
    market = d1_query(
        """
        WITH per_race AS (
          SELECT r.race_id,r.race_date,
                 SUM(CASE WHEN COALESCE(u.runner_status,'active')='active' THEN 1 ELSE 0 END) AS activeRunners,
                 SUM(CASE WHEN COALESCE(u.runner_status,'active')='active' AND u.win_odds IS NOT NULL AND u.win_odds>1 THEN 1 ELSE 0 END) AS runnersWithWinOdds,
                 SUM(CASE WHEN COALESCE(u.runner_status,'active')='active' AND u.popularity IS NOT NULL THEN 1 ELSE 0 END) AS runnersWithPopularity
          FROM rt_races r
          LEFT JOIN rt_runners u ON u.race_id=r.race_id
          GROUP BY r.race_id,r.race_date
        )
        SELECT substr(race_date,1,4) AS year, COUNT(*) AS races,
               SUM(CASE WHEN activeRunners>=2 AND runnersWithWinOdds=activeRunners AND runnersWithPopularity=activeRunners THEN 1 ELSE 0 END) AS completeMarketRaces
        FROM per_race
        GROUP BY substr(race_date,1,4)
        ORDER BY year
        """
    )
    return {
        "range": range_rows[0] if range_rows else {},
        "years": years,
        "marketCoverage": market,
    }


def main():
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "productionTablesModified": False,
        "d1": d1_audit(),
        "jraArchive": archive_audit(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
