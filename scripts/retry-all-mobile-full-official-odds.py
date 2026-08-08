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
OUT = ROOT / 'artifacts' / 'all-mobile-full-retry.jsonl.gz'
META = ROOT / 'artifacts' / 'all-mobile-full-retry-meta.json'
WORKERS = 6


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


def open_retry(opener, req, attempts=8, timeout=60):
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
        time.sleep(min(15, 0.7 * (2 ** attempt)) + random.random() * 0.4)
    raise last or RuntimeError('fetch failed')


def post_mobile(opener, fields, referer):
    data = urllib.parse.urlencode(fields).encode('ascii')
    req = urllib.request.Request(
        'https://sp.jra.jp/JRADB/accessO.html', data=data,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.2; +https://www.jra.go.jp/)',
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


def parse_pair(soup, wide=False, ordered=False):
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
                key = (a, b) if ordered else tuple(sorted((a, b)))
                out[key] = v
    return out


def parse_triples(soup, ordered=False):
    text = ' '.join(soup.stripped_strings)
    out = {}
    pattern = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})-(\d{1,2})\s+(票数なし|[0-9,.]+)')
    for a, b, c, val in pattern.findall(text):
        a, b, c = int(a), int(b), int(c)
        if len({a, b, c}) != 3:
            continue
        v = odds_float(val)
        if v is None:
            continue
        key = (a, b, c) if ordered else tuple(sorted((a, b, c)))
        out[key] = v
    return out


def select_values(soup, selector_id):
    sel = soup.find('select', id=selector_id)
    if not sel:
        raise RuntimeError(f'MOBILE_SELECTOR_MISS:{selector_id}')
    vals = []
    for opt in sel.find_all('option'):
        v = (opt.get('value') or '').strip()
        if not v or v == '#' or v.lower().startswith('javascript'):
            continue
        vals.append(v)
    # Preserve page order while de-duplicating.
    return list(dict.fromkeys(vals))


def fetch_race(row):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.2; +https://www.jra.go.jp/)',
        'Accept-Language': 'ja'
    }
    raw, _ = open_retry(opener, urllib.request.Request(row['resultUrl'], headers=headers))
    result_html = raw.decode('cp932', 'replace')
    first = re.search(r'(sw151ou[0-9A-Za-z_/.-]+)', result_html)
    if not first:
        raise RuntimeError('MOBILE_FIRST_ODDS_CNAME_MISS')

    h151, u151 = post_mobile(opener, {'cname': first.group(1)}, row['resultUrl'])
    soup151 = BeautifulSoup(h151, 'html.parser')
    tokens = sorted(set(re.findall(r'sw15[1-8][A-Za-z0-9_/.-]+', h151)))
    tabs = {}
    for prefix in ('154', '155', '156', '157', '158'):
        cand = [x for x in tokens if x.startswith('sw' + prefix + 'ou')]
        if cand:
            tabs[prefix] = min(cand, key=len)
    if any(k not in tabs for k in ('154', '155', '156', '157', '158')):
        raise RuntimeError('MOBILE_FULL_TAB_MISS:' + ','.join(sorted(tabs)))

    win = parse_win(soup151)
    horses = sorted(win)
    if len(horses) < 5:
        raise RuntimeError(f'MOBILE_WIN_PARSE_TOO_SMALL:{len(horses)}')

    h154, _ = post_mobile(opener, {'cname': tabs['154']}, u151)
    h155, _ = post_mobile(opener, {'cname': tabs['155']}, u151)
    h156, _ = post_mobile(opener, {'cname': tabs['156']}, u151)
    quinella = parse_pair(BeautifulSoup(h154, 'html.parser'), wide=False, ordered=False)
    wide = parse_pair(BeautifulSoup(h155, 'html.parser'), wide=True, ordered=False)
    exacta = parse_pair(BeautifulSoup(h156, 'html.parser'), wide=False, ordered=True)

    # Trio: the mobile page requires one axis-horse selector request. Each returned
    # page contains every trio involving that axis. Union all official responses.
    h157, u157 = post_mobile(opener, {'cname': tabs['157']}, u151)
    s157 = BeautifulSoup(h157, 'html.parser')
    trio_axes = select_values(s157, 'jikuuma')
    trio = {}
    for axis in trio_axes:
        h, _ = post_mobile(opener, {'cname': axis}, u157)
        trio.update(parse_triples(BeautifulSoup(h, 'html.parser'), ordered=False))

    # Trifecta: the mobile page requires an axis horse (jubn) and its finishing
    # position (chaku). Each response contains all ordered triples for that fixed
    # horse/position. Union all official responses; no odds are synthesized.
    h158, u158 = post_mobile(opener, {'cname': tabs['158']}, u151)
    s158 = BeautifulSoup(h158, 'html.parser')
    horse_axes = select_values(s158, 'jubn')
    positions = select_values(s158, 'chaku')
    trifecta = {}
    for axis in horse_axes:
        for pos in positions:
            h, _ = post_mobile(opener, {'cname': tabs['158'], 'jubn': axis, 'chaku': pos}, u158)
            trifecta.update(parse_triples(BeautifulSoup(h, 'html.parser'), ordered=True))

    pairs = list(itertools.combinations(horses, 2))
    exactas = [(a, b) for a in horses for b in horses if a != b]
    trios = list(itertools.combinations(horses, 3))
    trifectas = [(a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3]
    rec = {
        'raceId': row['raceId'], 'raceDate': row['raceDate'], 'venue': row['venue'], 'raceNo': int(row['raceNo']),
        'horses': horses,
        'win': [win.get(h) for h in horses],
        'umaren': [quinella.get(tuple(sorted(p))) for p in pairs],
        'wide': [wide.get(tuple(sorted(p))) for p in pairs],
        'umatan': [exacta.get(p) for p in exactas],
        'trio': [trio.get(tuple(sorted(t))) for t in trios],
        'trifecta': [trifecta.get(t) for t in trifectas],
        'source': 'jra_historical_official_odds_mobile_full_retry'
    }
    expected = {
        'win': len(horses), 'umaren': len(pairs), 'wide': len(pairs),
        'umatan': len(exactas), 'trio': len(trios), 'trifecta': len(trifectas)
    }
    present = {k: sum(v is not None for v in rec[k]) for k in expected}
    rec['expected'], rec['present'] = expected, present

    # Low-order markets must be complete. Higher-order pages can legitimately
    # contain no-vote combinations; require strong parser coverage without filling them.
    for k in ('win', 'umaren', 'wide'):
        if present[k] != expected[k]:
            raise RuntimeError(f'MOBILE_LOW_ORDER_INCOMPLETE:{k}:{present[k]}/{expected[k]}')
    for k, floor in (('umatan', 0.98), ('trio', 0.98), ('trifecta', 0.95)):
        cov = present[k] / expected[k] if expected[k] else 1.0
        if cov < floor:
            raise RuntimeError(f'MOBILE_HIGH_ORDER_PARSE_LOW:{k}:{present[k]}/{expected[k]}')
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
present_totals = {k: 0 for k in ('win', 'umaren', 'wide', 'umatan', 'trio', 'trifecta')}
expected_totals = {k: 0 for k in present_totals}
started = time.time()
with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=5) as fh, concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    future_map = {pool.submit(fetch_race, row): row for row in rows}
    for i, fut in enumerate(concurrent.futures.as_completed(future_map), 1):
        row = future_map[fut]
        try:
            rec = fut.result()
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')
            ok += 1
            for k in present_totals:
                present_totals[k] += rec['present'][k]
                expected_totals[k] += rec['expected'][k]
        except Exception as e:
            failures.append({'raceId': row['raceId'], 'error': f'{type(e).__name__}:{e}'})
        print(json.dumps({'done': i, 'success': ok, 'failures': len(failures), 'elapsedSec': round(time.time() - started, 1)}, ensure_ascii=False), flush=True)

meta = {
    'lockedRetryRaces': len(rows), 'successRaces': ok, 'failedRaces': len(failures),
    'expectedTotals': expected_totals, 'presentTotals': present_totals,
    'combinationCoveragePct': {
        k: (100.0 * present_totals[k] / expected_totals[k] if expected_totals[k] else 0.0)
        for k in present_totals
    },
    'failures': failures, 'source': 'JRA official mobile historical odds pages',
    'outcomesUsedToChooseRetryIds': False, 'syntheticOddsUsed': False, 'estimatedOddsUsed': False
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False), flush=True)
if ok != len(rows):
    raise RuntimeError(f'MOBILE_FULL_RETRY_INCOMPLETE:{ok}/{len(rows)}')
