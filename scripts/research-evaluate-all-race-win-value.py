#!/usr/bin/env python3
import argparse
import collections
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
from lightgbm import LGBMClassifier, LGBMRegressor

COURSES = {'light': 2000, 'standard': 5000, 'premium': 10000}
UNITS = {'light': (7, 7, 6), 'standard': (17, 17, 16), 'premium': (35, 35, 30)}
GAMMAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)
TEMPLATES = ('pair', 'spread', 'trio', 'ordered')
JP = {'win': '単勝', 'wide': 'ワイド', 'umaren': '馬連', 'trio': '3連複', 'umatan': '馬単', 'trifecta': '3連単'}


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def odds_value(v):
    if isinstance(v, list):
        x = [float(q) for q in v if q is not None]
        return sum(x) / len(x) if x else None
    return float(v) if v is not None else None


def softmax(rows):
    vals = np.asarray([float(r['abilityScore']) for r in rows], dtype=np.float64)
    vals -= vals.max()
    e = np.exp(np.clip(vals, -50, 50))
    e /= e.sum()
    return e


def norm(bt, horses):
    horses = tuple(int(x) for x in horses)
    if bt in ('wide', 'umaren', 'trio'):
        horses = tuple(sorted(horses))
    return '-'.join(map(str, horses))


def tickets(template, top3):
    a, b, c = top3
    if template == 'pair':
        return [('win', (a,)), ('wide', (a, b)), ('umaren', (a, b))]
    if template == 'spread':
        return [('win', (a,)), ('wide', (a, b)), ('wide', (a, c))]
    if template == 'trio':
        return [('win', (a,)), ('wide', (a, b)), ('trio', (a, b, c))]
    return [('win', (a,)), ('umatan', (a, b)), ('trifecta', (a, b, c))]


def payout_index(bundle):
    return {
        (str(p.get('betType') or ''), str(p.get('combination') or '')): int(p['payoutYen'])
        for p in bundle.get('payouts', []) if p.get('payoutYen') is not None
    }


def entropy(p):
    p = np.asarray(p, dtype=np.float64)
    p = p[p > 0]
    return float(-(p * np.log(p)).sum()) if len(p) else 0.0


def race_fold(race_id):
    # Race-level cross-fit: only the target race itself is guaranteed outside training.
    return int(hashlib.sha1(str(race_id).encode()).hexdigest()[:8], 16) % 5


def robust(selected_returns, budget):
    r = np.asarray(selected_returns, dtype=np.float64)
    stake = len(r) * budget
    roi = 100.0 * r.sum() / stake if stake else 0.0
    order = np.argsort(-r)
    keep = order[min(50, len(order)):]
    top50 = 100.0 * r[keep].sum() / (len(keep) * budget) if len(keep) else 0.0
    return {'races': int(len(r)), 'roiPct': round(roi, 4), 'top50ExcludedRoiPct': round(top50, 4)}


def evaluate(scores, returns, groups):
    # scores: races x actions. Choose one action per race, then exactly five races per venue-day where available.
    best_action = np.argmax(scores, axis=1)
    best_score = scores[np.arange(len(scores)), best_action]
    by_group = collections.defaultdict(list)
    for i, g in enumerate(groups):
        by_group[str(g)].append(i)
    selected = []
    for inds in by_group.values():
        ix = np.asarray(inds, dtype=np.int32)
        order = ix[np.argsort(-best_score[ix])]
        selected.extend(order[:min(5, len(order))].tolist())
    selected = np.asarray(selected, dtype=np.int32)
    actions = best_action[selected]
    courses = {}
    for ci, (course, budget) in enumerate(COURSES.items()):
        r = returns[selected, actions, ci]
        courses[course] = robust(r, budget)
    return {
        'selectedRaces': int(len(selected)),
        'venueDays': int(len(by_group)),
        'venueDaysWithFewerThanFiveFinishedRaces': int(sum(len(v) < 5 for v in by_group.values())),
        'courses': courses,
        'minRoiPct': min(v['roiPct'] for v in courses.values()),
        'minTop50ExcludedRoiPct': min(v['top50ExcludedRoiPct'] for v in courses.values()),
        'passesCompletionGate': all(v['roiPct'] >= 200.0 and v['top50ExcludedRoiPct'] >= 150.0 for v in courses.values()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--predictions-dir', required=True)
    ap.add_argument('--win-odds-dir', required=True)
    ap.add_argument('--history', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    preds = collections.defaultdict(list)
    for p in sorted(Path(args.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):
            preds[str(r['raceId'])].append(r)
    odds = {}
    for p in sorted(Path(args.win_odds_dir).glob('all-race-win-odds-20*.jsonl')):
        for r in read_jsonl(p):
            odds[str(r['raceId'])] = r
    hist = {}
    for b in read_jsonl(args.history):
        d = str(b['race']['raceDate'])
        if '2016-08-10' <= d <= '2026-08-09':
            hist[str(b['race']['raceId'])] = b
    if len(preds) != 34566 or len(odds) != 34566 or len(hist) != 34566:
        raise RuntimeError(f'INPUT_COUNTS:{len(preds)}:{len(odds)}:{len(hist)}')

    race_ids = sorted(hist, key=lambda rid: (hist[rid]['race']['raceDate'], hist[rid]['race']['venue'], int(hist[rid]['race']['raceNo'])))
    actions = [(g, t) for g in GAMMAS for t in TEMPLATES]
    n, na = len(race_ids), len(actions)
    # 31 compact continuous/categorical pre-result features per action.
    X = np.zeros((n, na, 31), dtype=np.float32)
    R = np.zeros((n, na, 3), dtype=np.float32)
    folds = np.zeros(n, dtype=np.int8)
    groups = np.empty(n, dtype='U20')
    direct_max_ev = np.full((n, na), -1e30, dtype=np.float32)
    direct_max_edge = np.full((n, na), -1e30, dtype=np.float32)

    for i, rid in enumerate(race_ids):
        bundle = hist[rid]
        race = bundle['race']
        date, venue, race_no = str(race['raceDate']), str(race['venue']), int(race['raceNo'])
        groups[i] = f'{date}|{venue}'
        folds[i] = race_fold(rid)
        win = (odds[rid].get('officialOdds') or {}).get('win') or {}
        active_odds = {int(h): odds_value(v) for h, v in win.items() if odds_value(v) is not None and odds_value(v) > 1.0}
        rows = [r for r in preds[rid] if int(r['horseNo']) in active_odds]
        if len(rows) < 3:
            raise RuntimeError(f'ACTIVE_ROWS_TOO_FEW:{rid}:{len(rows)}')
        ap = softmax(rows)
        horses = np.asarray([int(r['horseNo']) for r in rows], dtype=np.int16)
        wo = np.asarray([float(active_odds[int(h)]) for h in horses], dtype=np.float64)
        inv = 1.0 / wo
        q = inv / inv.sum()
        ev = ap * wo
        edge = ap / np.maximum(q, 1e-12)
        market_rank = np.argsort(np.argsort(wo)) + 1
        ao = np.argsort(-ap)
        global_features = [
            len(rows), race_no, float(wo.min()), float(np.partition(wo, 1)[1]), float(np.median(wo)),
            float(inv.sum()), entropy(q), entropy(ap), float(ap[ao[0]]), float(ap[ao[1]]), float(ap[ao[2]]),
            float(ap[ao[0]] - ap[ao[1]]), float(ap[ao[:3]].sum()), float(ev.max()), float(edge.max())
        ]
        pays = payout_index(bundle)
        for ai, (gamma, template) in enumerate(actions):
            score = np.log(np.maximum(ap, 1e-12)) + gamma * np.log(np.maximum(wo, 1.000001))
            order = np.argsort(-score)
            top_idx = order[:3]
            top = tuple(int(horses[j]) for j in top_idx)
            sf = global_features + [
                gamma, float(TEMPLATES.index(template)),
                *[float(ap[j]) for j in top_idx],
                *[float(q[j]) for j in top_idx],
                *[float(wo[j]) for j in top_idx],
                *[float(ev[j]) for j in top_idx],
                *[float(market_rank[j]) for j in top_idx],
            ]
            X[i, ai] = np.asarray(sf, dtype=np.float32)
            direct_max_ev[i, ai] = float(max(ev[j] for j in top_idx))
            direct_max_edge[i, ai] = float(max(edge[j] for j in top_idx))
            ts = tickets(template, top)
            pvals = [pays.get((JP[bt], norm(bt, hs)), 0) for bt, hs in ts]
            for ci, course in enumerate(COURSES):
                R[i, ai, ci] = float(sum(u * p for u, p in zip(UNITS[course], pvals)))
        if i and i % 5000 == 0:
            print(json.dumps({'builtRaces': i}, ensure_ascii=False), flush=True)

    flatX = X.reshape(n * na, -1)
    flatFold = np.repeat(folds, na)
    standard_ratio = (R[:, :, 1] / 5000.0).reshape(-1)
    configs = {}

    # Direct value baselines use gamma/template actions but no target-trained selector.
    for name, s in [('direct_max_ev', direct_max_ev), ('direct_max_edge', direct_max_edge)]:
        configs[name] = evaluate(s, R, groups)

    model_specs = (
        ('reg_cap3', 'reg', 3.0),
        ('reg_cap5', 'reg', 5.0),
        ('reg_cap10', 'reg', 10.0),
        ('weighted_cap5', 'weighted', 5.0),
        ('weighted_cap10', 'weighted', 10.0),
    )
    oof_by_name = {name: np.zeros((n, na), dtype=np.float32) for name, _, _ in model_specs}
    for fold in range(5):
        tr = flatFold != fold
        va_races = np.flatnonzero(folds == fold)
        va_flat = np.concatenate([np.arange(i * na, (i + 1) * na) for i in va_races])
        for name, kind, cap in model_specs:
            if kind == 'reg':
                y = np.minimum(standard_ratio[tr], cap).astype(np.float32)
                model = LGBMRegressor(
                    objective='regression_l1', n_estimators=180, learning_rate=.035, num_leaves=31,
                    min_child_samples=120, subsample=.9, colsample_bytree=.9, reg_alpha=.6, reg_lambda=7.0,
                    random_state=20260811 + fold, n_jobs=-1, verbosity=-1,
                )
                model.fit(flatX[tr], y)
                p = model.predict(flatX[va_flat])
            else:
                hit = (standard_ratio[tr] > 0).astype(np.int8)
                w = np.where(hit > 0, np.minimum(standard_ratio[tr], cap), 1.0).astype(np.float32)
                model = LGBMClassifier(
                    objective='binary', n_estimators=180, learning_rate=.035, num_leaves=31,
                    min_child_samples=120, subsample=.9, colsample_bytree=.9, reg_alpha=.6, reg_lambda=7.0,
                    random_state=20260911 + fold, n_jobs=-1, verbosity=-1,
                )
                model.fit(flatX[tr], hit, sample_weight=w)
                p = model.predict_proba(flatX[va_flat])[:, 1]
            oof_by_name[name][va_races] = p.reshape(len(va_races), na)
        print(json.dumps({'crossFitFoldComplete': fold}, ensure_ascii=False), flush=True)

    for name, scores in oof_by_name.items():
        configs[name] = evaluate(scores, R, groups)

    # Fixed ensemble: percentile ranks of two stability-oriented OOF models. No target-result fitting of weights.
    a = oof_by_name['reg_cap5']
    b = oof_by_name['weighted_cap5']
    def col_percentile(z):
        out = np.empty_like(z)
        for j in range(z.shape[1]):
            order = np.argsort(z[:, j])
            ranks = np.empty(len(z), dtype=np.float32)
            ranks[order] = np.arange(len(z), dtype=np.float32) / max(1, len(z) - 1)
            out[:, j] = ranks
        return out
    ensemble = (col_percentile(a) + col_percentile(b)) * 0.5
    configs['stable_ensemble'] = evaluate(ensemble, R, groups)

    winner_name = max(configs, key=lambda k: (configs[k]['passesCompletionGate'], configs[k]['minTop50ExcludedRoiPct'], configs[k]['minRoiPct']))
    winner = configs[winner_name]
    summary = {
        'purpose': 'all_2016_2026_price_aware_race_level_crossfit_five_race_selection',
        'period': {'start': '2016-08-10', 'end': '2026-08-09'},
        'allResultRaces': n,
        'officialWinOddsRaces': len(odds),
        'venueDays': len(set(groups)),
        'raceSelectionRule': 'top five predicted-value races per venue-day, or all finished races if fewer than five exist',
        'targetRaceResultUsedForOwnScore': False,
        'crossFitUnit': 'race',
        'historicalFinalWinOddsUsed': True,
        'syntheticOddsUsed': False,
        'productionDatabaseWritten': False,
        'productionModelChanged': False,
        'ticketCountPerRace': 3,
        'minimumBetTypesPerRace': 2,
        'maxTicketBudgetSharePct': 35.0,
        'completionGate': {'allCoursesRoiPctAtLeast': 200.0, 'allCoursesTop50ExcludedRoiPctAtLeast': 150.0},
        'candidateHorseValueParameterGammas': list(GAMMAS),
        'ticketTemplates': list(TEMPLATES),
        'configs': configs,
        'bestCandidate': {'name': winner_name, **winner},
        'completed': bool(winner['passesCompletionGate']),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'completed': summary['completed'], 'bestCandidate': summary['bestCandidate']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
