#!/usr/bin/env python3
import argparse
import concurrent.futures
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


def open_retry(opener, req, attempts=6, timeout=60):
    last = None
    for attempt in range(attempts):
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in {429, 500, 502, 503, 504}:
                raise
        except Exception as e:
            last = e
        if attempt + 1 < attempts:
            time.sleep(min(10, 0.5 * (2 ** attempt)) + random.random() * 0.3)
    raise last or RuntimeError("fetch failed")


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


def odds_float(text):
    s = str(text or "").strip().replace(",", "")
    if not s or s in {"---", "取消", "除外"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_win(soup):
    tables = soup.find_all("table", class_=lambda x: x and "basic" in x)
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        head = [" ".join(x.stripped_strings) for x in rows[0].find_all(["th", "td"])]
        if "馬番" not in head or not any("単勝" in cell for cell in head):
            continue
        out = {}
        for tr in rows[1:]:
            cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
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
        m = re.match(r"\s*(\d+)\b", text)
        if not m:
            continue
        first = int(m.group(1))
        for tr in table.find_all("tr"):
            cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
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
                val = [low, high] if low is not None and high is not None else None
            else:
                val = odds_float(cells[1])
            if val is None:
                continue
            key = (first, second) if ordered else tuple(sorted((first, second)))
            out[key] = val
    return out


def parse_trio(soup):
    out = {}
    for table in soup.find_all("table"):
        if "fuku3" not in (table.get("class") or []):
            continue
        li = table.find_parent("li")
        text = " ".join(li.stripped_strings) if li else ""
        m = re.match(r"\s*(\d+)\s*-\s*(\d+)\b", text)
        if not m:
            continue
        a, b = map(int, m.groups())
        for tr in table.find_all("tr"):
            cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0]); value = odds_float(cells[1])
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
        m = re.search(r"1着\s*(\d+)\s*2着\s*(\d+)\s*3着", text)
        if not m:
            continue
        a, b = map(int, m.groups())
        for tr in table.find_all("tr"):
            cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0]); value = odds_float(cells[1])
            if value is not None and len({a, b, c}) == 3:
                out[(a, b, c)] = value
    return out


def vectorize(horses, win, umaren, wide, umatan, trio, trifecta):
    pairs = list(itertools.combinations(horses, 2))
    exactas = [(a, b) for a in horses for b in horses if a != b]
    trios = list(itertools.combinations(horses, 3))
    trifectas = [(a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3]
    return {
        "horses": horses,
        "win": [win.get(h) for h in horses],
        "umaren": [umaren.get(tuple(sorted(x))) for x in pairs],
        "wide": [wide.get(tuple(sorted(x))) for x in pairs],
        "umatan": [umatan.get(x) for x in exactas],
        "trio": [trio.get(tuple(sorted(x))) for x in trios],
        "trifecta": [trifecta.get(x) for x in trifectas],
    }


def fetch_race(bundle):
    result_url = bundle["race"]["resultUrl"]
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(result_url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
    raw, _ = open_retry(opener, req)
    page = raw.decode("cp932", "replace")
    decoded = urllib.parse.unquote(result_url)
    rm = re.search(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})", decoded, re.I)
    if not rm:
        raise RuntimeError("RESULT_ID_PARSE_MISS")
    venue, year, meeting, day, race_no, ymd = rm.groups()
    marker = f"10{venue}{year}{meeting}{day}{race_no}{ymd}"
    first = re.search(r"pw151ou" + re.escape(marker) + r"[^'\"<>,)\s]+", page)
    if not first:
        raise RuntimeError("FIRST_ODDS_CNAME_MISS")
    first_cname = first.group(0)
    html151, url151 = post_odds(opener, first_cname, result_url)
    soup151 = BeautifulSoup(html151, "html.parser")
    tabs = {"151": first_cname}
    for tag in soup151.find_all(onclick=True):
        m = re.search(r"(pw15([4-8])ou[^'\"<>,)\s]+)", tag.get("onclick", ""))
        if m and marker in m.group(1):
            tabs[m.group(2)] = m.group(1)
    missing_tabs = [x for x in ("154", "155", "156", "157", "158") if x not in tabs]
    if missing_tabs:
        raise RuntimeError("REQUIRED_TAB_CNAME_MISS:" + ",".join(missing_tabs))

    win = parse_win(soup151)
    pages = {}
    for code in ("154", "155", "156", "157", "158"):
        text, _ = post_odds(opener, tabs[code], url151)
        pages[code] = BeautifulSoup(text, "html.parser")
    umaren = parse_pair_page(pages["154"], "umaren")
    wide = parse_pair_page(pages["155"], "wide", wide=True)
    umatan = parse_pair_page(pages["156"], "umatan", ordered=True)
    trio = parse_trio(pages["157"])
    trifecta = parse_trifecta(pages["158"])
    horses = sorted(win)
    if len(horses) < 2:
        raise RuntimeError(f"WIN_ODDS_INCOMPLETE:{len(horses)}")
    vec = vectorize(horses, win, umaren, wide, umatan, trio, trifecta)
    expected = {
        "win": len(horses),
        "umaren": len(list(itertools.combinations(horses, 2))),
        "wide": len(list(itertools.combinations(horses, 2))),
        "umatan": len(horses) * max(0, len(horses) - 1),
        "trio": len(list(itertools.combinations(horses, 3))),
        "trifecta": len(horses) * max(0, len(horses) - 1) * max(0, len(horses) - 2),
    }
    present = {key: sum(v is not None for v in vec[key]) for key in MARKETS}
    enriched = dict(bundle)
    enriched["officialOdds"] = vec
    enriched["officialOddsCoverage"] = {"expected": expected, "present": present}
    enriched["provenance"] = {
        **bundle.get("provenance", {}),
        "officialOddsSource": "jra_historical_official_odds",
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
    }
    return enriched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    input_path = ROOT / args.input
    rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    success, failures = [], []
    totals_expected = {k: 0 for k in MARKETS}
    totals_present = {k: 0 for k in MARKETS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as pool:
        futures = {pool.submit(fetch_race, row): row for row in rows}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = futures[future]
            try:
                enriched = future.result()
                success.append(enriched)
                cov = enriched["officialOddsCoverage"]
                for key in MARKETS:
                    totals_expected[key] += int(cov["expected"][key])
                    totals_present[key] += int(cov["present"][key])
            except Exception as exc:
                failures.append({"raceId": row.get("race", {}).get("raceId"), "error": f"{type(exc).__name__}:{exc}"})
            if i % 10 == 0 or i == len(rows):
                print(json.dumps({"processed": i, "total": len(rows), "success": len(success), "failures": len(failures)}, ensure_ascii=False), flush=True)
    success.sort(key=lambda x: (x["race"]["raceDate"], x["race"]["venue"], x["race"]["raceNo"]))
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in success), encoding="utf-8")
    coverage = {key: (totals_present[key] / totals_expected[key] if totals_expected[key] else 0.0) for key in MARKETS}
    meta = {
        "purpose": "research_only_no_production_write",
        "inputRaces": len(rows),
        "completed": len(success),
        "failures": failures,
        "coverage": coverage,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
    }
    (ROOT / args.meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    if failures or any(value < 0.999 for value in coverage.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
