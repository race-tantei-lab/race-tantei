import concurrent.futures
import gzip
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / 'scripts' / 'export-mobile-historical-official-odds-retry.py'
LOCK = ROOT / 'analysis-results' / 'all-light-primary-failure-ids.json'
OUT = ROOT / 'artifacts' / 'exact-76-full-mobile-odds.jsonl.gz'
META = ROOT / 'artifacts' / 'exact-76-full-mobile-odds-meta.json'

source = PARSER.read_text(encoding='utf-8')
marker = '# Rebuild exactly the same deterministic 3,210-race selection used by the primary export.'
if marker not in source:
    raise RuntimeError('AUDITED_MOBILE_PARSER_MARKER_MISSING')
namespace = {'__file__': str(PARSER)}
exec(compile(source.split(marker, 1)[0], str(PARSER), 'exec'), namespace)

d1 = namespace['d1']
fetch_race = namespace['fetch_race']
START = namespace['START']
END_EXCLUSIVE = namespace['END_EXCLUSIVE']

cfg = json.loads(LOCK.read_text(encoding='utf-8'))
retry_ids = list(cfg.get('raceIds', []))
if len(retry_ids) != 76 or len(set(retry_ids)) != 76:
    raise RuntimeError(f'EXACT_76_LOCK_INVALID:{len(retry_ids)}:{len(set(retry_ids))}')

all_rows = d1(
    "SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",
    [START, END_EXCLUSIVE],
)
by_id = {row['raceId']: row for row in all_rows}
missing = [race_id for race_id in retry_ids if race_id not in by_id]
if missing:
    raise RuntimeError(f'EXACT_76_NOT_IN_FIXED_ARCHIVE:{missing}')
rows = [by_id[race_id] for race_id in retry_ids]

OUT.parent.mkdir(parents=True, exist_ok=True)
success = 0
failures = []
present_totals = {k: 0 for k in ['win', 'umaren', 'wide', 'umatan', 'trio', 'trifecta']}
expected_totals = {k: 0 for k in present_totals}
started = time.time()

with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=5) as fh, concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    future_map = {pool.submit(fetch_race, row): row for row in rows}
    for index, future in enumerate(concurrent.futures.as_completed(future_map), 1):
        row = future_map[future]
        try:
            result = future.result()
            fh.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
            success += 1
            for key in present_totals:
                present_totals[key] += result['present'][key]
                expected_totals[key] += result['expected'][key]
        except Exception as exc:
            failures.append({'raceId': row['raceId'], 'error': f'{type(exc).__name__}:{exc}'})
        print(json.dumps({'done': index, 'success': success, 'failures': len(failures), 'elapsedSec': round(time.time() - started, 1)}, ensure_ascii=False), flush=True)

meta = {
    'lockedRetryRaces': len(rows),
    'successRaces': success,
    'failedRaces': len(failures),
    'raceCoveragePct': 100 * success / len(rows),
    'expectedTotals': expected_totals,
    'presentTotals': present_totals,
    'combinationCoveragePct': {key: (100 * present_totals[key] / expected_totals[key] if expected_totals[key] else 0) for key in present_totals},
    'failures': failures,
    'source': 'JRA official mobile historical odds pages',
    'outcomesUsedToChooseRetryIds': False,
    'payoutsUsedToChooseRetryIds': False,
    'syntheticOddsUsed': False,
    'estimatedOddsUsed': False,
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False), flush=True)
if success != len(rows):
    raise RuntimeError(f'EXACT_76_FULL_MOBILE_INCOMPLETE:{success}/{len(rows)}')
