import concurrent.futures
import gzip
import http.cookiejar
import itertools
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

TOKEN = os.environ['CLOUDFLARE_API_TOKEN']
ACCOUNT = os.environ['CLOUDFLARE_ACCOUNT_ID']
DATABASE = os.environ['CLOUDFLARE_D1_DATABASE_ID']
ENDPOINT = f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query'
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'analysis-results' / 'all-light-primary-failure-ids.json'
OUT = ROOT / 'artifacts' / 'all-light-mobile-retry.jsonl.gz'
META = ROOT / 'artifacts' / 'all-light-mobile-retry-meta.json'
WORKERS = 10


def d1(sql, params=None):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'
    }, method='POST')
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read().decode())
    if not payload.get('success'):
        raise RuntimeError(payload.get('errors'))
    return payload.get('result', [{}])[0].get('results', [])


def open_retry(opener, req, attempts=7, timeout=60):
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
        time.sleep(min(12, 0.6 * (2 ** attempt)) + random.random() * 0.3)
    raise last or RuntimeError('fetch failed')


def post_mobile(opener, cname, referer):
    data = urllib.parse.urlencode({'cname': cname}).encode('ascii')
    req = urllib.request.Request(
        'https://sp.jra.jp/JRADB/accessO.html', data=data,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.1; +https://www.jra.go.jp/)',
            'Accept-Language': 'ja', 'Referer': referer,
            'Content-Type': 'application/x-www-form-urlencoded',
        }, method='POST')
    raw, final = open_retry(opener, req)
    return raw.decode('cp932', 'replace'), final


def odds_float(text):
    s = str(text or '').strip().replace(',', '')
    if not s or s in {'---', '取消', '除外', '票数なし'}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_win(soup):
    out = {}
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows or '馬番' not in ' '.join(rows[0].stripped_strings) or '単勝' not in ' '.join(rows[0].stripped_strings):
            continue
        for tr in rows[1:]:
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            horse_idx = None
            for i, cell in enumerate(cells[:3]):
                if re.fullmatch(r'\d{1,2}', cell) and 1 <= int(cell) <= 20:
                    horse_idx = i
            if horse_idx is None or horse_idx + 2 >= len(cells):
                continue
            val = odds_float(cells[horse_idx + 2])
            if val is not None:
                out[int(cells[horse_idx])] = val
        if out:
            break
    return out


def parse_pair(soup, wide=False):
    text = ' '.join(soup.stripped_strings)
    out = {}
    if wide:
        pattern = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+([0-9,.]+)\s*-\s*([0-9,.]+)')
        for a, b, lo, hi in pattern.findall(text):
            a, b = int(a), int(b)
            vlo, vhi = odds_float(lo), odds_float(hi)
            if a != b and vlo is not None and vhi is not None:
                out[tuple(sorted((a, b)))] = [vlo, vhi]
    else:
        pattern = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+(票数なし|[0-9,.]+)')
        for a, b, val in pattern.findall(text):
            a, b = int(a), int(b)
            v = odds_float(val)
            if a != b and v is not None:
                out[tuple(sorted((a, b)))] = v
    return out


def fetch_race(row):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.1; +https://www.jra.go.jp/)', 'Accept-Language': 'ja'}
    raw, _ = open_retry(opener, urllib.request.Request(row['resultUrl'], headers=headers))
    result_html = raw.decode('cp932', 'replace')
    first = re.search(r'(sw151ou[0-9A-Za-z_/.-]+)', result_html)
    if not first:
        raise RuntimeError('MOBILE_FIRST_ODDS_CNAME_MISS')
    h151, u151 = post_mobile(opener, first.group(1), row['resultUrl'])
    soup151 = BeautifulSoup(h151, 'html.parser')
    tokens = sorted(set(re.findall(r'sw15[1-8][A-Za-z0-9_/.-]+', h151)))
    tabs = {}
    for prefix in ('154', '155'):
        cand = [x for x in tokens if x.startswith('sw' + prefix + 'ou')]
        if cand:
            tabs[prefix] = min(cand, key=len)
    if '154' not in tabs or '155' not in tabs:
        raise RuntimeError('MOBILE_LIGHT_TAB_MISS')
    win = parse_win(soup151)
    h154, _ = post_mobile(opener, tabs['154'], u151)
    h155, _ = post_mobile(opener, tabs['155'], u151)
    quinella = parse_pair(BeautifulSoup(h154, 'html.parser'), wide=False)
    wide = parse_pair(BeautifulSoup(h155, 'html.parser'), wide=True)
    horses = sorted(win)
    if len(horses) < 5:
        raise RuntimeError(f'MOBILE_WIN_PARSE_TOO_SMALL:{len(horses)}')
    pairs = list(itertools.combinations(horses, 2))
    rec = {
        'raceId': row['raceId'], 'raceDate': row['raceDate'], 'venue': row['venue'], 'raceNo': int(row['raceNo']),
        'horses': horses,
        'win': [win.get(h) for h in horses],
        'umaren': [quinella.get(tuple(sorted(p))) for p in pairs],
        'wide': [wide.get(tuple(sorted(p))) for p in pairs],
        'source': 'jra_historical_official_odds_mobile_retry'
    }
    expected = {'win': len(horses), 'umaren': len(pairs), 'wide': len(pairs)}
    present = {k: sum(v is not None for v in rec[k]) for k in expected}
    rec['expected'], rec['present'] = expected, present
    if present != expected:
        raise RuntimeError(f'MOBILE_LIGHT_COMBO_INCOMPLETE:{present}:{expected}')
    return rec


cfg = json.loads(LOCK.read_text(encoding='utf-8'))
retry_ids = list(cfg['raceIds'])
if len(retry_ids) != 76 or len(set(retry_ids)) != 76:
    raise RuntimeError(f'RETRY_ID_LOCK_INVALID:{len(retry_ids)}:{len(set(retry_ids))}')
rows = d1(
    "SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",
    ['2024-05-04', '2026-08-03']
)
by_id = {r['raceId']: r for r in rows}
missing = [rid for rid in retry_ids if rid not in by_id]
if missing:
    raise RuntimeError(f'RETRY_IDS_NOT_IN_FIXED_ARCHIVE:{missing}')
rows = [by_id[rid] for rid in retry_ids]
OUT.parent.mkdir(parents=True, exist_ok=True)
ok = 0
failures = []
started = time.time()
with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=5) as fh, concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    future_map = {pool.submit(fetch_race, row): row for row in rows}
    for i, fut in enumerate(concurrent.futures.as_completed(future_map), 1):
        row = future_map[fut]
        try:
            rec = fut.result()
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')
            ok += 1
        except Exception as e:
            failures.append({'raceId': row['raceId'], 'error': f'{type(e).__name__}:{e}'})
        print(json.dumps({'done': i, 'success': ok, 'failures': len(failures), 'elapsedSec': round(time.time() - started, 1)}, ensure_ascii=False), flush=True)
meta = {
    'lockedRetryRaces': len(rows), 'successRaces': ok, 'failedRaces': len(failures), 'failures': failures,
    'source': 'JRA official mobile historical odds pages', 'outcomesUsedToChooseRetryIds': False,
    'syntheticOddsUsed': False, 'estimatedOddsUsed': False
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False), flush=True)
if ok != len(rows):
    raise RuntimeError(f'MOBILE_LIGHT_RETRY_INCOMPLETE:{ok}/{len(rows)}')
