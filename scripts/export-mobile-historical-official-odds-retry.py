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
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '3c6d1826b573b2e68cb13ec37e9e8ade')
DATABASE = os.environ.get('CLOUDFLARE_D1_DATABASE_ID', '949b5e8b-d1a4-4c4e-80d1-d031afdc03de')
ENDPOINT = f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query'
ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / 'analysis-results' / 'fixed-oos-five-races-per-venue-day.json'
OUT = ROOT / 'artifacts' / 'mobile-historical-official-odds-retry.jsonl.gz'
META = ROOT / 'artifacts' / 'mobile-historical-official-odds-retry-meta.json'
START = '2024-05-04'
END_EXCLUSIVE = '2026-08-03'
WORKERS = 6

if not TOKEN:
    raise RuntimeError('CLOUDFLARE_API_TOKEN is not set')


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


def post_mobile(opener, data, referer):
    encoded = urllib.parse.urlencode(data).encode('ascii')
    req = urllib.request.Request(
        'https://sp.jra.jp/JRADB/accessO.html', data=encoded,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.0; +https://www.jra.go.jp/)',
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


def parse_mobile_win(soup):
    out = {}
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows:
            continue
        header = ' '.join(rows[0].stripped_strings)
        if '馬番' not in header or '単勝' not in header:
            continue
        for tr in rows[1:]:
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            if len(cells) < 3:
                continue
            # Locate horse number by the first plausible integer cell, allowing omitted rowspan frame cells.
            horse_idx = None
            for i, cell in enumerate(cells[:3]):
                if re.fullmatch(r'\d{1,2}', cell):
                    v = int(cell)
                    if 1 <= v <= 20:
                        horse_idx = i
            if horse_idx is None:
                continue
            horse = int(cells[horse_idx])
            # Horse name follows horse number; win odds follows horse name.
            win_idx = horse_idx + 2
            if win_idx < len(cells):
                val = odds_float(cells[win_idx])
                if val is not None:
                    out[horse] = val
        if out:
            break
    return out


def parse_pair_text(soup, wide=False, ordered=False):
    text = ' '.join(soup.stripped_strings)
    out = {}
    if wide:
        pat = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+([0-9,.]+)\s*-\s*([0-9,.]+)')
        for a, b, lo, hi in pat.findall(text):
            a = int(a); b = int(b)
            if a == b:
                continue
            vlo = odds_float(lo); vhi = odds_float(hi)
            if vlo is None or vhi is None:
                continue
            out[tuple(sorted((a, b)))] = [vlo, vhi]
    else:
        pat = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+(票数なし|[0-9,.]+)')
        for a, b, val in pat.findall(text):
            a = int(a); b = int(b)
            if a == b:
                continue
            v = odds_float(val)
            if v is None:
                continue
            key = (a, b) if ordered else tuple(sorted((a, b)))
            out[key] = v
    return out


def parse_triple_text(soup, ordered=False):
    text = ' '.join(soup.stripped_strings)
    out = {}
    pat = re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})-(\d{1,2})\s+(票数なし|[0-9,.]+)')
    for a, b, c, val in pat.findall(text):
        a = int(a); b = int(b); c = int(c)
        if len({a, b, c}) != 3:
            continue
        v = odds_float(val)
        if v is None:
            continue
        key = (a, b, c) if ordered else tuple(sorted((a, b, c)))
        out[key] = v
    return out


def vectorize(horses, win, quinella, wide, exacta, trio, trifecta):
    pairs = list(itertools.combinations(horses, 2))
    exactas = [(a, b) for a in horses for b in horses if a != b]
    trios = list(itertools.combinations(horses, 3))
    trifectas = [(a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3]
    return {
        'horses': horses,
        'win': [win.get(h) for h in horses],
        'umaren': [quinella.get(tuple(sorted(x))) for x in pairs],
        'wide': [wide.get(tuple(sorted(x))) for x in pairs],
        'umatan': [exacta.get(x) for x in exactas],
        'trio': [trio.get(tuple(sorted(x))) for x in trios],
        'trifecta': [trifecta.get(x) for x in trifectas],
    }


def fetch_race(row):
    result_url = row['resultUrl']
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.0; +https://www.jra.go.jp/)',
        'Accept-Language': 'ja'
    }
    raw, _ = open_retry(opener, urllib.request.Request(result_url, headers=headers))
    result_html = raw.decode('cp932', 'replace')
    first_m = re.search(r'(sw151ou[0-9A-Za-z_/.-]+)', result_html)
    if not first_m:
        raise RuntimeError('MOBILE_FIRST_ODDS_CNAME_MISS')

    h151, u151 = post_mobile(opener, {'cname': first_m.group(1)}, result_url)
    s151 = BeautifulSoup(h151, 'html.parser')
    tokens = sorted(set(re.findall(r'sw15[1-8][A-Za-z0-9_/.-]+', h151)))
    tab = {}
    for prefix in ['154', '155', '156', '157', '158']:
        candidates = [x for x in tokens if x.startswith('sw' + prefix + 'ou')]
        if candidates:
            # The current race appears in the first page; current-race menu token is the shortest ordinary ou token.
            ordinary = [x for x in candidates if ('Z99/' in x if prefix == '157' else True)]
            if prefix == '157' and ordinary:
                tab[prefix] = ordinary[0]
            else:
                tab[prefix] = min(candidates, key=len)
    if any(k not in tab for k in ['154', '155', '156', '157', '158']):
        raise RuntimeError('MOBILE_REQUIRED_TAB_MISS:' + ','.join(sorted(tab)))

    win = parse_mobile_win(s151)
    if len(win) < 5:
        raise RuntimeError(f'MOBILE_WIN_PARSE_TOO_SMALL:{len(win)}')

    h154, _ = post_mobile(opener, {'cname': tab['154']}, u151)
    h155, _ = post_mobile(opener, {'cname': tab['155']}, u151)
    h156, _ = post_mobile(opener, {'cname': tab['156']}, u151)
    quinella = parse_pair_text(BeautifulSoup(h154, 'html.parser'), ordered=False)
    wide = parse_pair_text(BeautifulSoup(h155, 'html.parser'), wide=True)
    exacta = parse_pair_text(BeautifulSoup(h156, 'html.parser'), ordered=True)

    # Trio: official page exposes one official CNAME per axis horse. Union axis pages, then de-duplicate triples.
    h157, u157 = post_mobile(opener, {'cname': tab['157']}, u151)
    s157 = BeautifulSoup(h157, 'html.parser')
    axis157 = [o.get('value') for o in s157.select('select#jikuuma option') if (o.get('value') or '') != '#']
    trio = {}
    # n-2 axes suffice mathematically, but fetch all official axis pages for direct completeness/auditability.
    for axis in axis157:
        h, _ = post_mobile(opener, {'cname': axis}, u157)
        trio.update(parse_triple_text(BeautifulSoup(h, 'html.parser'), ordered=False))

    # Trifecta: fixing each horse as 1st position covers every ordered triple exactly once by first horse.
    h158, u158 = post_mobile(opener, {'cname': tab['158']}, u151)
    s158 = BeautifulSoup(h158, 'html.parser')
    jubn_values = [o.get('value') for o in s158.select('select#jubn option') if o.get('value')]
    first_place = s158.select_one('select#chaku option')
    if not jubn_values or first_place is None or not first_place.get('value'):
        raise RuntimeError('MOBILE_TRIFECTA_SELECTOR_MISS')
    chaku1 = first_place.get('value')
    trifecta = {}
    for jubn in jubn_values:
        h, _ = post_mobile(opener, {'cname': tab['158'], 'jubn': jubn, 'chaku': chaku1}, u158)
        trifecta.update(parse_triple_text(BeautifulSoup(h, 'html.parser'), ordered=True))

    horses = sorted(win)
    vec = vectorize(horses, win, quinella, wide, exacta, trio, trifecta)
    n = len(horses)
    expected = {
        'win': n,
        'umaren': n * (n - 1) // 2,
        'wide': n * (n - 1) // 2,
        'umatan': n * (n - 1),
        'trio': n * (n - 1) * (n - 2) // 6,
        'trifecta': n * (n - 1) * (n - 2),
    }
    present = {k: sum(v is not None for v in vec[k]) for k in ['win', 'umaren', 'wide', 'umatan', 'trio', 'trifecta']}
    return {
        'raceId': row['raceId'], 'raceDate': row['raceDate'], 'venue': row['venue'], 'raceNo': int(row['raceNo']),
        **vec, 'expected': expected, 'present': present,
        'source': 'jra_historical_official_odds_mobile_retry'
    }


# Rebuild exactly the same deterministic 3,210-race selection used by the primary export.
raw_selection = json.loads(SELECTION.read_text(encoding='utf-8'))
requested = set(raw_selection.get('races', []))
all_rows = d1(
    "SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",
    [START, END_EXCLUSIVE]
)
by_id = {r['raceId']: r for r in all_rows}
chosen = {rid for rid in requested if rid in by_id}
groups = defaultdict(list)
for row in all_rows:
    groups[(row['raceDate'], row['venue'])].append(row)
for key, group in groups.items():
    have = [r for r in group if r['raceId'] in chosen]
    if len(have) < 5:
        for r in sorted(group, key=lambda x: int(x['raceNo'])):
            if r['raceId'] not in chosen:
                chosen.add(r['raceId']); have.append(r)
            if len(have) >= 5:
                break
    if len(have) < 5:
        raise RuntimeError(f'SELECTION_REPAIR_FAILED:{key}')
selected_rows = [by_id[rid] for rid in chosen]
mobile_rows = sorted(
    [r for r in selected_rows if 'sp.jra.jp' in (r.get('resultUrl') or '') or 'CNAME=sw' in urllib.parse.unquote(r.get('resultUrl') or '')],
    key=lambda r: (r['raceDate'], r['venue'], int(r['raceNo']))
)

OUT.parent.mkdir(parents=True, exist_ok=True)
success = 0; failures = []
present_totals = {k: 0 for k in ['win','umaren','wide','umatan','trio','trifecta']}
expected_totals = {k: 0 for k in present_totals}
started = time.time()
with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=6) as fh, concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    future_map = {pool.submit(fetch_race, row): row for row in mobile_rows}
    for idx, fut in enumerate(concurrent.futures.as_completed(future_map), 1):
        row = future_map[fut]
        try:
            result = fut.result()
            fh.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
            success += 1
            for k in present_totals:
                present_totals[k] += result['present'][k]
                expected_totals[k] += result['expected'][k]
        except Exception as e:
            failures.append({'raceId': row['raceId'], 'error': f'{type(e).__name__}:{e}'})
        print(json.dumps({'done': idx, 'success': success, 'failures': len(failures), 'elapsedSec': round(time.time()-started,1)}, ensure_ascii=False), flush=True)

coverage = success / len(mobile_rows) if mobile_rows else 0
meta = {
    'deterministicSelectedRaces': len(chosen),
    'mobileRetryRaces': len(mobile_rows),
    'successRaces': success,
    'failedRaces': len(failures),
    'raceCoveragePct': coverage * 100,
    'expectedTotals': expected_totals,
    'presentTotals': present_totals,
    'combinationCoveragePct': {k: (present_totals[k] / expected_totals[k] * 100 if expected_totals[k] else 0) for k in present_totals},
    'failures': failures,
    'source': 'JRA official mobile historical odds pages',
    'syntheticOddsUsed': False,
    'estimatedOddsUsed': False,
    'outcomesUsedToSelectRetryRaces': False,
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False), flush=True)
if coverage < 1.0:
    raise RuntimeError(f'MOBILE_RETRY_INCOMPLETE:{success}/{len(mobile_rows)}')
