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

TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '3c6d1826b573b2e68cb13ec37e9e8ade')
DATABASE = os.environ.get('CLOUDFLARE_D1_DATABASE_ID', '949b5e8b-d1a4-4c4e-80d1-d031afdc03de')
ENDPOINT = f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query'
ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / 'analysis-results' / 'fixed-oos-five-races-per-venue-day.json'
OUT = ROOT / 'artifacts' / 'selected-historical-official-odds.jsonl.gz'
META = ROOT / 'artifacts' / 'selected-historical-official-odds-meta.json'
WORKERS = 20
START = '2024-05-04'
END_EXCLUSIVE = '2026-08-03'

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
        time.sleep(min(10, 0.5 * (2 ** attempt)) + random.random() * 0.3)
    raise last or RuntimeError('fetch failed')


def post_odds(opener, cname, referer):
    data = urllib.parse.urlencode({'cname': cname}).encode('ascii')
    req = urllib.request.Request(
        'https://www.jra.go.jp/JRADB/accessO.html', data=data,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.0; +https://www.jra.go.jp/)',
            'Accept-Language': 'ja', 'Referer': referer,
            'Content-Type': 'application/x-www-form-urlencoded',
        }, method='POST')
    raw, final = open_retry(opener, req)
    return raw.decode('cp932', 'replace'), final


def odds_float(text):
    s = str(text or '').strip().replace(',', '')
    if not s or s in {'---', '取消', '除外'}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_win(soup):
    tables = soup.find_all('table', class_=lambda x: x and 'basic' in x)
    for t in tables:
        rows = t.find_all('tr')
        if not rows:
            continue
        head = [' '.join(x.stripped_strings) for x in rows[0].find_all(['th', 'td'])]
        if '馬番' not in head or '単勝' not in head:
            continue
        out = {}
        for tr in rows[1:]:
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            # frame cell may disappear because of rowspan; use numeric positions from right-safe layout.
            nums = [i for i, c in enumerate(cells[:3]) if c.isdigit()]
            if not nums:
                continue
            idx = nums[-1]
            horse = int(cells[idx])
            # horse number is followed by horse name then win odds.
            win_idx = idx + 2
            if win_idx < len(cells):
                o = odds_float(cells[win_idx])
                if o is not None:
                    out[horse] = o
        return out
    return {}


def parse_pair_page(soup, cls, wide=False, ordered=False):
    out = {}
    for t in soup.find_all('table'):
        classes = t.get('class') or []
        if cls not in classes:
            continue
        li = t.find_parent('li')
        text = ' '.join(li.stripped_strings) if li else ''
        m = re.match(r'\s*(\d+)\b', text)
        if not m:
            continue
        first = int(m.group(1))
        for tr in t.find_all('tr'):
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            second = int(cells[0])
            if first == second:
                continue
            if wide:
                mm = re.match(r'\s*([0-9,.]+)\s*-\s*([0-9,.]+)\s*$', cells[1])
                if not mm:
                    continue
                val = [odds_float(mm.group(1)), odds_float(mm.group(2))]
            else:
                val = odds_float(cells[1])
            if val is None or (wide and None in val):
                continue
            key = (first, second) if ordered else tuple(sorted((first, second)))
            out[key] = val
    return out


def parse_trio(soup):
    out = {}
    for t in soup.find_all('table'):
        if 'fuku3' not in (t.get('class') or []):
            continue
        li = t.find_parent('li')
        text = ' '.join(li.stripped_strings) if li else ''
        m = re.match(r'\s*(\d+)\s*-\s*(\d+)\b', text)
        if not m:
            continue
        a, b = map(int, m.groups())
        for tr in t.find_all('tr'):
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0]); val = odds_float(cells[1])
            if val is not None and len({a, b, c}) == 3:
                out[tuple(sorted((a, b, c)))] = val
    return out


def parse_trifecta(soup):
    out = {}
    for t in soup.find_all('table'):
        if 'tan3' not in (t.get('class') or []):
            continue
        li = t.find_parent('li')
        text = ' '.join(li.stripped_strings) if li else ''
        m = re.search(r'1着\s*(\d+)\s*2着\s*(\d+)\s*3着', text)
        if not m:
            continue
        a, b = map(int, m.groups())
        for tr in t.find_all('tr'):
            cells = [' '.join(x.stripped_strings) for x in tr.find_all(['th', 'td'])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            c = int(cells[0]); val = odds_float(cells[1])
            if val is not None and len({a, b, c}) == 3:
                out[(a, b, c)] = val
    return out


def vectorize(horses, win, umaren, wide, umatan, trio, trifecta):
    pairs = list(itertools.combinations(horses, 2))
    exactas = [(a, b) for a in horses for b in horses if a != b]
    trios = list(itertools.combinations(horses, 3))
    trifectas = [(a, b, c) for a in horses for b in horses for c in horses if len({a, b, c}) == 3]
    return {
        'horses': horses,
        'win': [win.get(h) for h in horses],
        'umaren': [umaren.get(tuple(sorted(x))) for x in pairs],
        'wide': [wide.get(tuple(sorted(x))) for x in pairs],
        'umatan': [umatan.get(x) for x in exactas],
        'trio': [trio.get(tuple(sorted(x))) for x in trios],
        'trifecta': [trifecta.get(x) for x in trifectas],
    }


def fetch_race(row):
    race_id = row['raceId']; result_url = row['resultUrl']
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    hdr = {'User-Agent': 'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.0; +https://www.jra.go.jp/)', 'Accept-Language': 'ja'}
    raw, final = open_retry(opener, urllib.request.Request(result_url, headers=hdr))
    html = raw.decode('cp932', 'replace')

    rm = re.search(r'pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})', urllib.parse.unquote(result_url))
    if not rm:
        raise RuntimeError('RESULT_ID_PARSE_MISS')
    venue, year, meeting, day, race_no, ymd = rm.groups()
    marker = f'10{venue}{year}{meeting}{day}{race_no}{ymd}'
    first_match = re.search(r"doAction\('/JRADB/accessO\.html'\s*,\s*'(pw151ou" + re.escape(marker) + r"[^']+)'\)", html)
    if not first_match:
        raise RuntimeError('FIRST_ODDS_CNAME_MISS')

    first_cname = first_match.group(1)
    html151, url151 = post_odds(opener, first_cname, result_url)
    soup151 = BeautifulSoup(html151, 'html.parser')
    tab = {'151': first_cname}
    for tag in soup151.find_all(onclick=True):
        m = re.search(r"doAction\('/JRADB/accessO\.html'\s*,\s*'(pw15([4-8])ou[^']+)'\)", tag.get('onclick', ''))
        if m and marker in m.group(1):
            tab[m.group(2)] = m.group(1)
    if any(k not in tab for k in ['154', '155', '156', '157', '158']):
        raise RuntimeError('REQUIRED_TAB_CNAME_MISS:' + ','.join(sorted(tab)))

    win = parse_win(soup151)
    pages = {}
    for k in ['154', '155', '156', '157', '158']:
        h, _ = post_odds(opener, tab[k], url151)
        pages[k] = BeautifulSoup(h, 'html.parser')

    umaren = parse_pair_page(pages['154'], 'umaren')
    wide = parse_pair_page(pages['155'], 'wide', wide=True)
    umatan = parse_pair_page(pages['156'], 'umatan', ordered=True)
    trio = parse_trio(pages['157'])
    trifecta = parse_trifecta(pages['158'])

    horses = sorted(win)
    vec = vectorize(horses, win, umaren, wide, umatan, trio, trifecta)
    expected = {
        'win': len(horses),
        'umaren': len(list(itertools.combinations(horses, 2))),
        'wide': len(list(itertools.combinations(horses, 2))),
        'umatan': len(horses) * max(0, len(horses) - 1),
        'trio': len(list(itertools.combinations(horses, 3))),
        'trifecta': len(horses) * max(0, len(horses) - 1) * max(0, len(horses) - 2),
    }
    present = {
        'win': sum(v is not None for v in vec['win']),
        'umaren': sum(v is not None for v in vec['umaren']),
        'wide': sum(v is not None for v in vec['wide']),
        'umatan': sum(v is not None for v in vec['umatan']),
        'trio': sum(v is not None for v in vec['trio']),
        'trifecta': sum(v is not None for v in vec['trifecta']),
    }
    return {
        'raceId': race_id, 'raceDate': row['raceDate'], 'venue': row['venue'], 'raceNo': int(row['raceNo']),
        **vec, 'expected': expected, 'present': present, 'source': 'jra_historical_official_odds'
    }


selection = json.loads(SELECTION.read_text(encoding='utf-8'))['races']
selected = set(selection)
rows = d1(
    "SELECT race_id raceId, race_date raceDate, venue, race_no raceNo, result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",
    [START, END_EXCLUSIVE]
)
rows = [r for r in rows if r['raceId'] in selected]
if len(rows) != len(selected):
    missing = sorted(selected - {r['raceId'] for r in rows})
    raise RuntimeError(f'SELECTION_RACE_MISMATCH:{len(rows)} vs {len(selected)} missing={missing[:20]}')

OUT.parent.mkdir(parents=True, exist_ok=True)
success = 0; failures = []
present_totals = {k: 0 for k in ['win','umaren','wide','umatan','trio','trifecta']}
expected_totals = {k: 0 for k in present_totals}
started = time.time()
with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=6) as f, concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    future_map = {pool.submit(fetch_race, row): row for row in rows}
    for idx, fut in enumerate(concurrent.futures.as_completed(future_map), 1):
        row = future_map[fut]
        try:
            result = fut.result()
            f.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
            success += 1
            for k in present_totals:
                present_totals[k] += result['present'][k]
                expected_totals[k] += result['expected'][k]
        except Exception as e:
            failures.append({'raceId': row['raceId'], 'error': f'{type(e).__name__}:{e}'})
        if idx % 50 == 0:
            print(json.dumps({'done': idx, 'success': success, 'failures': len(failures), 'elapsedSec': round(time.time()-started,1)}, ensure_ascii=False), flush=True)

coverage = success / len(rows) if rows else 0
combo_coverage = {k: (present_totals[k] / expected_totals[k] if expected_totals[k] else 0) for k in present_totals}
meta = {
    'selectedRaces': len(rows), 'successRaces': success, 'failedRaces': len(failures), 'raceCoveragePct': coverage*100,
    'expectedTotals': expected_totals, 'presentTotals': present_totals,
    'combinationCoveragePct': {k: v*100 for k,v in combo_coverage.items()},
    'failures': failures[:200], 'source': 'JRA official historical odds pages',
    'syntheticOddsUsed': False, 'estimatedOddsUsed': False, 'workers': WORKERS,
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False), flush=True)
if coverage < 0.95:
    raise RuntimeError(f'HISTORICAL_ODDS_RACE_COVERAGE_TOO_LOW:{coverage:.6f}')
