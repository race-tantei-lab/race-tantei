#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'scripts' / 'ten-year-production-core.py'
COLLECTOR_PATH = ROOT / 'scripts' / 'collect-jra-official-odds.py'
EXPLANATION_PREFIX = 'worker_selection_explanation:'
EXPLANATION_VERSION = 'canonical-selection-trace-v1'
SOURCE_MODEL = 'ten-year-completed-model'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def same_number(a, b, tol=1e-8):
    return abs(float(a) - float(b)) <= tol


def code_range(axis, value):
    value = int(value)
    if axis in ('bestform', 'bestspeed'):
        labels = ['履歴なし', '30%未満', '30〜50%未満', '50〜70%未満', '70%以上']
        return labels[value] if 0 <= value < len(labels) else f'区分{value}'
    if axis in ('bestj', 'bestt'):
        labels = ['15%未満', '15〜25%未満', '25〜35%未満', '35〜45%未満', '45%以上']
        return labels[value] if 0 <= value < len(labels) else f'区分{value}'
    return str(value)


def axis_value_label(core, axis, value):
    value = int(value)
    if axis == 'venue':
        return f"会場={core.SEL_VENUES[value] if 0 <= value < len(core.SEL_VENUES) else f'区分{value}'}"
    if axis == 'surface':
        labels = ['芝', 'ダート', '障害']
        return f"馬場={labels[value] if 0 <= value < len(labels) else f'区分{value}'}"
    if axis == 'dist':
        labels = ['〜1200m', '1201〜1500m', '1501〜1800m', '1801〜2200m', '2201〜2600m', '2601m〜']
        return f"距離={labels[value] if 0 <= value < len(labels) else f'区分{value}'}"
    if axis == 'field':
        labels = ['8頭以下', '9〜11頭', '12〜13頭', '14〜16頭', '17頭以上']
        return f"頭数={labels[value] if 0 <= value < len(labels) else f'区分{value}'}"
    if axis == 'raceNo':
        labels = ['1〜3R', '4〜6R', '7〜9R', '10〜12R']
        return f"R帯={labels[value] if 0 <= value < len(labels) else f'区分{value}'}"
    if axis == 'rclass':
        labels = ['新馬', '未勝利', '1勝', '2勝', '3勝', 'OP/L', 'G3', 'G2', 'G1', 'その他']
        return f"クラス={labels[value] if 0 <= value < len(labels) else f'区分{value}'}"
    if axis == 'bestform':
        return f'組合せ内・近走着順指数の最高={code_range(axis, value)}'
    if axis == 'bestspeed':
        return f'組合せ内・近走速度指数の最高={code_range(axis, value)}'
    if axis == 'bestj':
        return f'組合せ内・騎手3着内率の最高={code_range(axis, value)}'
    if axis == 'bestt':
        return f'組合せ内・調教師3着内率の最高={code_range(axis, value)}'
    if axis == 'expcnt':
        return f"組合せ内・3走以上経験馬={'3頭以上' if value >= 3 else f'{value}頭'}"
    if axis == 'top3lastsum':
        return f"組合せ馬・直近3走3着内合計={'7回以上' if value >= 7 else f'{value}回'}"
    return f'{axis}={value}'


def component_label(core, axes, vals):
    return ' × '.join(axis_value_label(core, axis, val) for axis, val in zip(axes, vals))


def ticket_evidence(core, state, ticket):
    bt = int(ticket['bt'])
    bn, bret = state['bet_stats'][bt]
    bmean = core.mean_roi(bn, bret, core.BET_PRIOR, core.PRIOR_ROI)
    comps = []
    for key in core.candidate_keys(bt, ticket['vals']):
        n, ret = state['stats'].get(key, (0, 0))
        if n < core.MIN_N:
            continue
        km = core.mean_roi(n, ret, core.KEY_PRIOR, bmean)
        reliability = n / (n + core.KEY_PRIOR)
        complexity = 1.0 if len(key[1]) == 1 else 0.92
        comps.append({
            'axes': list(key[1]),
            'values': list(key[2]),
            'label': component_label(core, key[1], key[2]),
            'sampleN': int(round(n)),
            'smoothedRoi': float(km),
            'reliability': float(reliability),
            'complexity': float(complexity),
            'effectiveWeight': float(reliability * complexity),
        })
    comps.sort(key=lambda x: (x['smoothedRoi'], x['effectiveWeight'], x['sampleN']), reverse=True)
    top = comps[:core.TOP_COMPONENTS]
    weight = sum(x['effectiveWeight'] for x in top)
    local = (sum(x['smoothedRoi'] * x['effectiveWeight'] for x in top) / weight) if weight else None
    final = bmean * 0.95 if local is None else (1.0 - core.LOCAL_WEIGHT) * bmean + core.LOCAL_WEIGHT * local
    if not same_number(final, ticket['score'], 1e-10):
        raise RuntimeError(f"EXPLANATION_TICKET_SCORE_PARITY_FAILED:{ticket['betType']}:{ticket['combo']}:{final}:{ticket['score']}")
    return {
        'betType': str(ticket['betType']),
        'combination': str(ticket['combo']),
        'horses': [int(x) for x in ticket.get('horses', [])],
        'globalSampleN': int(round(bn)),
        'globalSmoothedRoi': float(bmean),
        'eligibleComponentCount': len(comps),
        'localWeightedRoi': None if local is None else float(local),
        'localWeight': float(core.LOCAL_WEIGHT),
        'globalWeight': float(1.0 - core.LOCAL_WEIGHT),
        'finalScore': float(final),
        'usedFallback': local is None,
        'topComponents': top,
    }


def horse_evidence(core, state, bundle):
    race = bundle['race']
    rid = str(race['raceId'])
    runners = [r for r in bundle.get('runners', []) if (r.get('runnerStatus') or 'active') == 'active']
    runners.sort(key=lambda r: int(r.get('horseNo') or 0))
    features = {int(r['horseNo']): core.selection_feature_tuple(state, rid, r) for r in runners}
    ranked = sorted(features, key=lambda h: core.selection_strength(features[h], h), reverse=True)[:core.TOP_HORSES]
    by_no = {int(r['horseNo']): r for r in runners}
    out = []
    for horse_no in ranked:
        feature = features[horse_no]
        runner = by_no[horse_no]
        out.append({
            'horseNo': horse_no,
            'horseName': str(runner.get('horseName') or ''),
            'jockey': str(runner.get('jockey') or ''),
            'trainer': str(runner.get('trainer') or ''),
            'formCode': int(feature[0]),
            'speedCode': int(feature[1]),
            'jockeyCode': int(feature[2]),
            'trainerCode': int(feature[3]),
            'startsCode': int(feature[4]),
            'recentTop3Count': int(feature[5]),
            'strength': [float(x) for x in core.selection_strength(feature, horse_no)],
        })
    return out


def ensure_selection_explanations(collector, date, frozen_payload=None):
    core = load(CORE_PATH, 'ten_year_selection_explanation_core')
    if frozen_payload is None:
        rows = collector.d1_query(
            'SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1',
            [f'final_daily_selection:{date}'],
        )
        if not rows:
            raise RuntimeError(f'EXPLANATION_FROZEN_SELECTION_MISSING:{date}')
        frozen_payload = json.loads(str(rows[0].get('value') or '{}'))
    if frozen_payload.get('sourceModel') != SOURCE_MODEL or frozen_payload.get('resultDataUsedForTargetDay') is not False:
        raise RuntimeError('EXPLANATION_FROZEN_SELECTION_INVALID')
    frozen_selected = frozen_payload.get('selected')
    if not isinstance(frozen_selected, list) or not frozen_selected:
        raise RuntimeError('EXPLANATION_FROZEN_SELECTION_EMPTY')

    state = core.load_selection_state()
    base_through_date = str(state['throughDate'])
    delta = core.delta_bundles(collector, state['throughDate'], date)
    core.advance_selection_state(state, delta)
    targets = core.target_bundles(collector, date)
    if not targets:
        raise RuntimeError(f'EXPLANATION_TARGETS_EMPTY:{date}')

    canonical_selected = core.select_target_races(state, targets, date)
    frozen_by_id = {str(row.get('raceId')): row for row in frozen_selected}
    if len(canonical_selected) != len(frozen_selected):
        raise RuntimeError(f'EXPLANATION_SELECTED_COUNT_MISMATCH:{len(canonical_selected)}:{len(frozen_selected)}')
    for row in canonical_selected:
        frozen = frozen_by_id.get(str(row['raceId']))
        if not frozen or str(frozen.get('venue')) != str(row['venue']) or int(frozen.get('raceNo') or 0) != int(row['raceNo']) or not same_number(frozen.get('raceScore'), row['raceScore']):
            raise RuntimeError(f"EXPLANATION_FROZEN_PARITY_FAILED:{row['raceId']}")

    by_venue = collections.defaultdict(list)
    for bundle in targets:
        rows = core.selection_candidate_rows(state, bundle)
        chosen = core.select_proxy_tickets(rows, state['stats'], state['bet_stats'])
        race_score = round(sum(float(t['score']) for t in chosen) / len(chosen), 8)
        by_venue[str(bundle['race'].get('venue') or '')].append((bundle, race_score, chosen))

    explanations = []
    for venue, rows in by_venue.items():
        rows.sort(key=lambda x: (-x[1], int(x[0]['race'].get('raceNo') or 0)))
        for index, (bundle, race_score, chosen) in enumerate(rows):
            race = bundle['race']
            race_id = str(race['raceId'])
            frozen = frozen_by_id.get(race_id)
            if frozen is None:
                continue
            if not same_number(race_score, frozen.get('raceScore')):
                raise RuntimeError(f"EXPLANATION_SCORE_PARITY_FAILED:{race_id}:{race_score}:{frozen.get('raceScore')}")
            explanations.append({
                'version': EXPLANATION_VERSION,
                'sourceModel': SOURCE_MODEL,
                'raceId': race_id,
                'raceDate': date,
                'venue': venue,
                'raceNo': int(race.get('raceNo') or 0),
                'venueRank': index + 1,
                'raceScore': float(race_score),
                'verifiedAgainstFrozenSelection': True,
                'stateBaseThroughDate': base_through_date,
                'stateAdvancedThroughDate': str(state['throughDate']),
                'topHorses': horse_evidence(core, state, bundle),
                'proxyTickets': [ticket_evidence(core, state, ticket) for ticket in chosen],
                'scoreFormula': {
                    'localWeight': float(core.LOCAL_WEIGHT),
                    'globalWeight': float(1.0 - core.LOCAL_WEIGHT),
                    'topComponents': int(core.TOP_COMPONENTS),
                    'minSampleN': int(core.MIN_N),
                    'keyPriorN': int(core.KEY_PRIOR),
                    'betPriorN': int(core.BET_PRIOR),
                    'priorRoi': float(core.PRIOR_ROI),
                },
            })

    if len(explanations) != len(frozen_selected):
        raise RuntimeError(f'EXPLANATION_OUTPUT_COUNT_MISMATCH:{len(explanations)}:{len(frozen_selected)}')

    for row in explanations:
        collector.d1_query(
            '''INSERT INTO rt_system_state(state_key,state_value,updated_at)
               VALUES(?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP''',
            [f"{EXPLANATION_PREFIX}{date}:{row['raceId']}", json.dumps(row, ensure_ascii=False, separators=(',', ':'))],
        )
    return explanations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True)
    args = ap.parse_args()
    collector = load(COLLECTOR_PATH, 'ten_year_selection_explanation_collector')
    rows = ensure_selection_explanations(collector, args.date)
    print(json.dumps({
        'status': 'ok',
        'date': args.date,
        'sourceModel': SOURCE_MODEL,
        'version': EXPLANATION_VERSION,
        'rows': len(rows),
        'raceIds': [row['raceId'] for row in rows],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
