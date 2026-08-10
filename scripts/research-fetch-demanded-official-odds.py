#!/usr/bin/env python3
import argparse
import concurrent.futures
import html
import http.cookiejar
import itertools
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html"
USER_AGENT = "Mozilla/5.0 (compatible; RaceTanteiResearch/1.0; +https://www.jra.go.jp/)"
MARKETS = ("win", "umaren", "wide", "umatan", "trio", "trifecta")
TAB_CODES = {"win": "151", "umaren": "154", "wide": "155", "umatan": "156", "trio": "157", "trifecta": "158"}


def open_retry(opener, req, attempts=7, timeout=60):
    last = None
    for attempt in range(attempts):
        try:
            with opener.open(req, timeout=timeout) as response:
                return response.read(), response.geturl()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except Exception as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(min(12, 0.7 * (2 ** attempt)) + random.random() * 0.4)
    raise last or RuntimeError("FETCH_FAILED")


def post_odds(opener, cname, referer):
    data = urllib.parse.urlencode({"cname": cname}).encode("ascii")
    req = urllib.request.Request(
        ODDS_URL,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    raw, final = open_retry(opener, req)
    return raw.decode("cp932", "replace"), final


def extract_odds_cnames(text, prefix, marker):
    clean = html.unescape(text).replace("\\u0026", "&").replace("\\/", "/")
    found = []
    for pattern in (r"(?:CNAME=|cname=)([^\"'&<>\s)]+)", r"((?:pw|sw)15[1-8]ou[^\"'<>\s,)]+)"):
        for match in re.finditer(pattern, clean, re.I):
            value = urllib.parse.unquote(match.group(1)).strip()
            value = re.sub(r"^cname=", "", value, flags=re.I)
            if value.lower().startswith(prefix.lower()) and marker in value:
                found.append(value)
    return list(dict.fromkeys(found))


def odds_float(text):
    value = str(text or "").strip().replace(",", "")
    if not value or value in {"---", "取消", "除外"}:
        return None
    try:
        return float(value)
    except Exception:
        return None


def parse_win(soup):
    tables = soup.find_all("table", class_=lambda value: value and "basic" in value)
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        head = [" ".join(cell.stripped_strings) for cell in rows[0].find_all(["th", "td"])]
        if "馬番" not in head or not any("単勝" in cell for cell in head):
            continue
        out = {}
        for tr in rows[1:]:
            cells = [" ".join(cell.stripped_strings) for cell in tr.find_all(["th", "td"])]
            nums = [i for i, cell in enumerate(cells[:3]) if cell.isdigit()]
            if not nums:
                continue
            idx = nums[-1]
            horse = int(cells[idx])
            for candidate in cells[idx + 1:idx + 5]:
                value = odds_float(candidate)
                if value is not None and value >= 1.0:
                    out[horse] = value
                    break
        if out:
            return out
    return {}


def parse_pair_page(soup, cls, wide=False, ordered=False):
    out = {}
    for table in soup.find_all("table"):
        if cls not in (table.get("class") or []):
            continue
        li = table.find_parent("li")
        text = " ".join(li.stripped_strings) if li else ""
        match = re.match(r"\s*(\d+)\b", text)
        if not match:
            continue
        first = int(match.group(1))
        for tr in table.find_all("tr"):
            cells = [" ".join(cell.stripped_strings) for cell in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            second = int(cells[0])
            if first == second:
                continue
            if wide:
                mm = re.match(r"\s*([0-9,.]+)\s*-\s*([0-9,.]+)\s*$", cells[1])
                if not mm:
                    continue
                low, high = odds_float(mm.group(1)), odds_float(mm.group(2))
                value = [low, high] if low is not None and high is not None else None
            else:
                value = odds_float(cells[1])
            if value is None:
                continue
            key = (first, second) if ordered else tuple(sorted((first, second)))
            out[key] = value
    return out


def parse_trio(soup):
    out = {}
    for table in soup.find_all("table"):
        if "fuku3" not in (table.get("class") or []):
            continue
        li = table.find_parent("li")
        text = " ".join(li.stripped_strings) if li else ""
        match = re.match(r"\s*(\d+)\s*-\s*(\d+)\b", text)
        if not match:
            continue
        a, b = map(int, match.groups())
        for tr in table.find_all("tr"):
            cells = [" ".join(cell.stripped_strings) for cell in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0])
            value = odds_float(cells[1])
            if value is not None and len({a, b, c}) == 3:
                out[tuple(sorted((a, b, c)))] = value
    return out


def parse_trifecta(soup):
    out = {}
    for table in soup.find_all("table"):
        if "tan3" not in (table.get("class") or []):
            continue
        li = table.find_parent("li")
        text = " ".join(li.stripped_strings) if li else ""
        match = re.search(r"1着\s*(\d+)\s*2着\s*(\d+)\s*3着", text)
        if not match:
            continue
        a, b = map(int, match.groups())
        for tr in table.find_all("tr"):
            cells = [" ".join(cell.stripped_strings) for cell in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0])
            value = odds_float(cells[1])
            if value is not None and len({a, b, c}) == 3:
                out[(a, b, c)] = value
    return out


def expected_count(market, horses):
    n = len(horses)
    if market == "win":
        return n
    if market in {"umaren", "wide"}:
        return n * max(0, n - 1) // 2
    if market == "umatan":
        return n * max(0, n - 1)
    if market == "trio":
        return n * max(0, n - 1) * max(0, n - 2) // 6
    if market == "trifecta":
        return n * max(0, n - 1) * max(0, n - 2)
    raise KeyError(market)


def serialize_market(market, horses, values):
    if market == "win":
        return {str(horse): values.get(horse) for horse in horses}
    if market in {"umaren", "wide"}:
        combos = itertools.combinations(horses, 2)
    elif market == "umatan":
        combos = ((a, b) for a in horses for b in horses if a != b)
    elif market == "trio":
        combos = itertools.combinations(horses, 3)
    elif market == "trifecta":
        combos = ((a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3)
    else:
        raise KeyError(market)
    out = {}
    for combo in combos:
        key = combo if market in {"umatan", "trifecta"} else tuple(sorted(combo))
        value = values.get(key)
        out["-".join(str(x) for x in combo)] = value
    return out


def result_marker(result_url):
    decoded = urllib.parse.unquote(result_url)
    match = re.search(r"(?:pw|sw)01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})", decoded, re.I)
    if not match:
        raise RuntimeError("RESULT_ID_PARSE_MISS")
    venue, year, meeting, day, race_no, ymd = match.groups()
    return f"10{venue}{year}{meeting}{day}{race_no}{ymd}"


def fetch_race(row):
    required = tuple(market for market in MARKETS if market in set(row.get("requiredMarkets") or ()))
    if not required or "win" not in required:
        raise RuntimeError(f"REQUIRED_MARKETS_INVALID:{required}")
    result_url = str(row.get("resultUrl") or "")
    if not result_url:
        raise RuntimeError("RESULT_URL_MISSING")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(result_url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
    raw, _ = open_retry(opener, req)
    page = raw.decode("cp932", "replace")
    marker = result_marker(result_url)
    first_values = extract_odds_cnames(page, "pw151ou", marker)
    if not first_values:
        first_values = extract_odds_cnames(page, "sw151ou", marker)
    if not first_values:
        raise RuntimeError("FIRST_ODDS_CNAME_MISS")
    first_cname = first_values[0]
    html151, url151 = post_odds(opener, first_cname, result_url)
    soup151 = BeautifulSoup(html151, "html.parser")
    win = parse_win(soup151)
    horses = sorted(win)
    if len(horses) < 2:
        raise RuntimeError(f"WIN_ODDS_INCOMPLETE:{len(horses)}")

    tabs = {"win": first_cname}
    for market in required:
        if market == "win":
            continue
        code = TAB_CODES[market]
        values = extract_odds_cnames(html151, f"pw{code}ou", marker)
        if not values:
            values = extract_odds_cnames(html151, f"sw{code}ou", marker)
        if not values:
            raise RuntimeError(f"REQUIRED_TAB_CNAME_MISS:{market}")
        tabs[market] = values[0]

    parsed = {"win": win}
    for market in required:
        if market == "win":
            continue
        text, _ = post_odds(opener, tabs[market], url151)
        soup = BeautifulSoup(text, "html.parser")
        if market == "umaren":
            parsed[market] = parse_pair_page(soup, "umaren")
        elif market == "wide":
            parsed[market] = parse_pair_page(soup, "wide", wide=True)
        elif market == "umatan":
            parsed[market] = parse_pair_page(soup, "umatan", ordered=True)
        elif market == "trio":
            parsed[market] = parse_trio(soup)
        elif market == "trifecta":
            parsed[market] = parse_trifecta(soup)

    official = {}
    coverage = {}
    for market in required:
        values = serialize_market(market, horses, parsed[market])
        expected = expected_count(market, horses)
        present = sum(value is not None for value in values.values())
        official[market] = values
        coverage[market] = {"expected": expected, "present": present, "ratio": present / expected if expected else 0.0}

    return {
        "raceId": row["raceId"],
        "raceDate": row["raceDate"],
        "venue": row["venue"],
        "raceNo": row["raceNo"],
        "requiredMarkets": list(required),
        "horses": horses,
        "officialOdds": official,
        "officialOddsCoverage": coverage,
        "provenance": {
            "resultUrl": result_url,
            "officialOddsSource": "jra_historical_official_final_odds",
            "syntheticOddsUsed": False,
            "productionDatabaseWritten": False,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--year")
    ap.add_argument("--month")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    rows = []
    input_path = ROOT / args.input
    with input_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            date = str(row.get("raceDate") or "")
            if args.year and not date.startswith(str(args.year) + "-"):
                continue
            if args.month and date[5:7] != str(args.month).zfill(2):
                continue
            rows.append(row)
    if not rows:
        raise RuntimeError(f"NO_DEMAND_ROWS:{args.year}:{args.month}")

    successes = []
    failures = []
    expected_totals = collections = {market: 0 for market in MARKETS}
    present_totals = {market: 0 for market in MARKETS}
    demanded_races = {market: 0 for market in MARKETS}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as pool:
        futures = {pool.submit(fetch_race, row): row for row in rows}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = futures[future]
            try:
                result = future.result()
                successes.append(result)
                for market, cov in result["officialOddsCoverage"].items():
                    demanded_races[market] += 1
                    expected_totals[market] += int(cov["expected"])
                    present_totals[market] += int(cov["present"])
            except Exception as exc:
                failures.append({
                    "raceId": row.get("raceId"),
                    "raceDate": row.get("raceDate"),
                    "venue": row.get("venue"),
                    "raceNo": row.get("raceNo"),
                    "requiredMarkets": row.get("requiredMarkets"),
                    "resultUrl": row.get("resultUrl"),
                    "error": f"{type(exc).__name__}:{exc}",
                })
            if index % 25 == 0 or index == len(rows):
                print(json.dumps({"processed": index, "total": len(rows), "success": len(successes), "failures": len(failures)}, ensure_ascii=False), flush=True)

    successes.sort(key=lambda row: (row["raceDate"], row["venue"], row["raceNo"]))
    out_path = ROOT / args.out
    meta_path = ROOT / args.meta
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in successes), encoding="utf-8")
    coverage = {
        market: (present_totals[market] / expected_totals[market] if expected_totals[market] else None)
        for market in MARKETS
    }
    meta = {
        "purpose": "research_only_selective_official_final_odds",
        "year": args.year,
        "month": args.month,
        "inputDemandRaces": len(rows),
        "completedRaces": len(successes),
        "failures": failures,
        "demandedRacesByMarket": demanded_races,
        "coverage": coverage,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
