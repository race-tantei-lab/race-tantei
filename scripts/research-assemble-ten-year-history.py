#!/usr/bin/env python3
import argparse, gzip, json, zipfile
from collections import defaultdict
from pathlib import Path

EVAL_START = '2016-08-10'
EVAL_END = '2026-08-09'
D1_START = '2024-05-04'
PATCH_IDS = {
    '2016-08-28-niigata-12',
    '2017-08-26-sapporo-10',
    '2019-06-29-hakodate-11',
}


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def read_gz_jsonl(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def expand_patch(record):
    runners, results = [], []
    for row in record['rows']:
        horse_no, frame_no, name, sex_age, assigned_weight, jockey, horse_weight, weight_change, trainer, popularity, finish, time_text, margin, final3f = row
        runners.append({
            'horseNo': horse_no, 'frameNo': frame_no, 'horseName': name, 'sexAge': sex_age,
            'coatColor': None, 'horseWeight': horse_weight, 'weightChange': weight_change,
            'jockey': jockey, 'assignedWeight': assigned_weight, 'trainer': trainer, 'stable': None,
            'popularity': popularity, 'runnerStatus': 'active', 'winOdds': None,
        })
        results.append({
            'horseNo': horse_no, 'finishPosition': finish, 'resultStatus': 'finished',
            'timeText': time_text, 'marginText': margin, 'final3f': final3f,
        })
    payouts = [
        {'betType': bet, 'combination': combo, 'payoutYen': yen, 'popularity': pop}
        for bet, combo, yen, pop in record['payouts']
    ]
    source = record.get('source', {})
    return {
        'race': record['race'], 'runners': runners, 'results': results, 'payouts': payouts,
        'refundHorseNos': [],
        'provenance': {
            'resultUrl': source.get('url') or record['race'].get('resultUrl'),
            'source': 'jra_official_fixed_recovery',
            'syntheticOddsUsed': False,
            'productionDatabaseWritten': False,
        },
    }


def camel_race(r):
    return {
        'raceId': r['race_id'], 'raceDate': r['race_date'], 'venue': r['venue'],
        'meetingNo': r.get('meeting_no'), 'meetingDay': r.get('meeting_day'), 'raceNo': r['race_no'],
        'raceName': r.get('race_name'), 'conditions': r.get('conditions'), 'surface': r.get('surface'),
        'distanceM': r.get('distance_m'), 'direction': r.get('direction'),
        'startTimeJst': r.get('start_time_jst'), 'startTimeUtc': r.get('start_time_utc'),
        'weather': r.get('weather'), 'trackCondition': r.get('track_condition'),
        'entryUrl': r.get('entry_url'), 'resultUrl': r.get('result_url'), 'status': r.get('status'),
    }


def assemble_d1(d1_dir):
    races = {r['race_id']: r for r in read_gz_jsonl(d1_dir/'races.jsonl.gz') if EVAL_START <= r['race_date'] <= EVAL_END}
    runners, results, payouts = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in read_gz_jsonl(d1_dir/'runners.jsonl.gz'):
        if r['race_id'] in races:
            runners[r['race_id']].append({
                'horseNo': r['horse_no'], 'frameNo': r.get('frame_no'), 'horseName': r['horse_name'],
                'sexAge': r.get('sex_age'), 'coatColor': r.get('coat_color'), 'horseWeight': r.get('horse_weight'),
                'weightChange': r.get('weight_change'), 'jockey': r.get('jockey'),
                'assignedWeight': r.get('assigned_weight'), 'trainer': r.get('trainer'), 'stable': r.get('stable'),
                'popularity': r.get('popularity'), 'runnerStatus': r.get('runner_status'), 'winOdds': r.get('win_odds'),
            })
    for r in read_gz_jsonl(d1_dir/'results.jsonl.gz'):
        if r['race_id'] in races:
            results[r['race_id']].append({
                'horseNo': r['horse_no'], 'finishPosition': r.get('finish_position'),
                'resultStatus': r.get('result_status'), 'timeText': r.get('time_text'),
                'marginText': r.get('margin_text'), 'final3f': r.get('final3f'),
            })
    for p in read_gz_jsonl(d1_dir/'payouts.jsonl.gz'):
        if p['race_id'] in races:
            payouts[p['race_id']].append({
                'betType': p['bet_type'], 'combination': p['combination'],
                'payoutYen': p['payout_yen'], 'popularity': p.get('popularity'),
            })
    out = []
    for race_id, r in races.items():
        try:
            refund = json.loads(r.get('refund_horse_nos_json') or '[]')
        except Exception:
            refund = []
        out.append({
            'race': camel_race(r),
            'runners': sorted(runners[race_id], key=lambda x: x['horseNo']),
            'results': sorted(results[race_id], key=lambda x: (x['finishPosition'] is None, x['finishPosition'] or 999, x['horseNo'])),
            'payouts': payouts[race_id], 'refundHorseNos': refund,
            'provenance': {
                'resultUrl': r.get('result_url'), 'source': 'existing_production_d1_read_only',
                'syntheticOddsUsed': False, 'productionDatabaseWritten': False,
            },
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--legacy-dir', required=True)
    ap.add_argument('--d1-dir', required=True)
    ap.add_argument('--patch', required=True)
    ap.add_argument('--out-corpus', required=True)
    ap.add_argument('--out-eval', required=True)
    ap.add_argument('--meta', required=True)
    args = ap.parse_args()

    legacy_dir = Path(args.legacy_dir)
    d1_dir = Path(args.d1_dir)
    rows = {}
    legacy_files = sorted(legacy_dir.rglob('history-*-metadata.jsonl'))
    if len(legacy_files) != 10:
        raise SystemExit(f'expected 10 legacy metadata shards, found {len(legacy_files)}')

    for path in legacy_files:
        for row in read_jsonl(path):
            date = row.get('race', {}).get('raceDate')
            rid = row.get('race', {}).get('raceId')
            if not date or not rid or date >= D1_START:
                continue
            if rid in rows:
                raise SystemExit(f'duplicate legacy raceId: {rid}')
            rows[rid] = row

    patch_rows = [expand_patch(x) for x in read_jsonl(args.patch)]
    if {x['race']['raceId'] for x in patch_rows} != PATCH_IDS:
        raise SystemExit('official recovery patch ids do not match expected blocked evaluation races')
    for row in patch_rows:
        rows[row['race']['raceId']] = row

    d1_rows = assemble_d1(d1_dir)
    for row in d1_rows:
        rid = row['race']['raceId']
        if rid in rows:
            raise SystemExit(f'legacy/D1 overlap raceId: {rid}')
        rows[rid] = row

    corpus = sorted(rows.values(), key=lambda x: (x['race']['raceDate'], x['race']['venue'], x['race']['raceNo']))
    evaluation = [x for x in corpus if EVAL_START <= x['race']['raceDate'] <= EVAL_END]
    ids = [x['race']['raceId'] for x in corpus]
    eval_ids = [x['race']['raceId'] for x in evaluation]

    incomplete_eval = []
    for row in evaluation:
        race = row['race']
        if not race.get('raceName') or not race.get('conditions') or race.get('surface') not in ('芝','ダート','障害') or not race.get('distanceM'):
            incomplete_eval.append(race['raceId'])
        if len(row.get('runners', [])) < 2 or (race.get('status') != 'cancelled' and not row.get('payouts')):
            incomplete_eval.append(race['raceId'])

    if len(ids) != len(set(ids)) or len(eval_ids) != len(set(eval_ids)):
        raise SystemExit('duplicate race ids after assembly')
    if not evaluation or evaluation[0]['race']['raceDate'] != EVAL_START or evaluation[-1]['race']['raceDate'] != EVAL_END:
        raise SystemExit(f'evaluation boundary mismatch: {evaluation[0]["race"]["raceDate"] if evaluation else None} .. {evaluation[-1]["race"]["raceDate"] if evaluation else None}')
    if not PATCH_IDS.issubset(set(eval_ids)):
        raise SystemExit('one or more official recovery races missing after assembly')
    if incomplete_eval:
        raise SystemExit(f'incomplete evaluation races: {sorted(set(incomplete_eval))[:20]} count={len(set(incomplete_eval))}')

    Path(args.out_corpus).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_corpus).write_text('\n'.join(json.dumps(x, ensure_ascii=False, separators=(',',':')) for x in corpus)+'\n', encoding='utf-8')
    Path(args.out_eval).write_text('\n'.join(json.dumps(x, ensure_ascii=False, separators=(',',':')) for x in evaluation)+'\n', encoding='utf-8')
    meta = {
        'purpose': 'research_only_ten_year_history_assembly',
        'corpusStart': corpus[0]['race']['raceDate'], 'corpusEnd': corpus[-1]['race']['raceDate'],
        'evaluationStart': EVAL_START, 'evaluationEnd': EVAL_END,
        'legacyMetadataShards': len(legacy_files), 'd1Races': len(d1_rows),
        'officialBlockedEvaluationRacesRecovered': sorted(PATCH_IDS),
        'corpusRaceCount': len(corpus), 'evaluationRaceCount': len(evaluation),
        'duplicateRaceIds': 0, 'incompleteEvaluationRaceIds': [],
        'knownWarmupGap': '2015-08-22-niigata-02',
        'syntheticOddsUsed': False, 'productionDatabaseWritten': False,
    }
    Path(args.meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False))

if __name__ == '__main__':
    main()
