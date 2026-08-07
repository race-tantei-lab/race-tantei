import gzip
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "artifacts" / "completion-search-dataset.pkl.gz"
OUTPUT = ROOT / "analysis-results" / "exploration-catboost-value-portfolios.json"
HOLDOUT_START = "2026-01-01"
SEED = 202608080844
RNG = np.random.default_rng(SEED)

UNORDERED = {"ワイド", "馬連", "3連複"}
COURSES = {
    "ライト": {"budget": 2000, "tickets": 6, "types": ("単勝", "ワイド", "馬連"), "max_share": 0.40},
    "スタンダード": {"budget": 5000, "tickets": 15, "types": ("単勝", "ワイド", "馬連", "馬単", "3連複"), "max_share": 0.30},
    "プレミアム": {"budget": 10000, "tickets": 16, "types": ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"), "max_share": 0.24},
}
COUNT_OPTIONS = {
    "ライト": [(1, 2, 3), (1, 3, 2), (2, 2, 2)],
    "スタンダード": [
        (1, 3, 3, 4, 4), (1, 4, 3, 3, 4), (2, 3, 3, 3, 4),
        (1, 3, 2, 4, 5), (2, 4, 3, 3, 3), (1, 4, 4, 3, 3),
    ],
    "プレミアム": [
        (1, 2, 2, 3, 3, 5), (1, 2, 2, 2, 4, 5), (1, 3, 2, 2, 3, 5),
        (2, 2, 2, 2, 3, 5), (1, 2, 3, 2, 3, 5), (1, 2, 2, 3, 4, 4),
    ],
}
VALUE_STRENGTHS = (0.45, 0.70, 0.90, 1.10, 1.30, 1.50)
MIXES = (0.25, 0.50, 0.75)
POLICY_COUNT = 96
MIN_TRAIN_RACES = 450


def canon(bet_type, horses):
    values = tuple(int(x) for x in horses)
    return tuple(sorted(values)) if bet_type in UNORDERED else values


def payout_key(bet_type, horses):
    return f'{bet_type}:{"-".join(map(str, canon(bet_type, horses)))}'


def quarter(date_text):
    year = int(date_text[:4])
    month = int(date_text[5:7])
    return f"{year}-Q{(month - 1) // 3 + 1}"


def zscore(values):
    arr = np.asarray(values, dtype=np.float64)
    std = float(arr.std())
    return (arr - float(arr.mean())) / std if std > 1e-9 else np.zeros_like(arr)


def ordered_probability(order, weights):
    remaining = float(sum(weights.values()))
    p = 1.0
    used = set()
    for horse in order:
        if horse in used or remaining <= 0:
            return 0.0
        w = float(weights.get(horse, 0.0))
        if w <= 0:
            return 0.0
        p *= w / remaining
        remaining -= w
        used.add(horse)
    return max(0.0, min(1.0, p))


def event_probability(bet_type, horses, win_weights, place_weights):
    h = tuple(horses)
    if bet_type == "単勝":
        return float(win_weights.get(h[0], 0.0))
    if bet_type == "馬連":
        return ordered_probability((h[0], h[1]), win_weights) + ordered_probability((h[1], h[0]), win_weights)
    if bet_type == "馬単":
        return ordered_probability(h[:2], win_weights)
    if bet_type == "3連単":
        return ordered_probability(h[:3], win_weights)
    if bet_type == "3連複":
        total = 0.0
        import itertools
        for order in itertools.permutations(h[:3]):
            total += ordered_probability(order, place_weights)
        return min(1.0, total)
    if bet_type == "ワイド":
        total = 0.0
        import itertools
        for third in place_weights:
            if third in h[:2]:
                continue
            three = (h[0], h[1], third)
            for order in itertools.permutations(three):
                total += ordered_probability(order, place_weights)
        return min(1.0, total)
    return 0.0


def flatten(races):
    x, yw, yp, weights = [], [], [], []
    for race in races:
        f = max(1, len(race["runners"]))
        for runner in race["runners"]:
            feats = np.asarray(runner["features"], dtype=np.float64)
            x.append(feats)
            yw.append(int(runner["finish"] == 1))
            yp.append(int(0 < runner["finish"] <= 3))
            weights.append(1.0 / f)
    return np.asarray(x), np.asarray(yw), np.asarray(yp), np.asarray(weights)


def fit_models(train):
    x, yw, yp, weights = flatten(train)
    common = dict(
        iterations=220,
        depth=6,
        learning_rate=0.045,
        l2_leaf_reg=9.0,
        loss_function="Logloss",
        random_seed=SEED,
        verbose=False,
        thread_count=-1,
        allow_writing_files=False,
    )
    win = CatBoostClassifier(**common)
    place = CatBoostClassifier(**common)
    win.fit(x, yw, sample_weight=weights)
    place.fit(x, yp, sample_weight=weights)
    return win, place


def attach_predictions(race, win_model, place_model):
    runners = race["runners"]
    markets = np.asarray([max(1e-8, float(r.get("market") or 0.0)) for r in runners], dtype=np.float64)
    markets /= markets.sum()
    if win_model is None:
        win_raw = markets.copy()
        place_raw = np.power(markets, 0.72)
    else:
        x = np.asarray([r["features"] for r in runners], dtype=np.float64)
        win_raw = np.maximum(1e-9, win_model.predict_proba(x)[:, 1])
        place_raw = np.maximum(1e-9, place_model.predict_proba(x)[:, 1])
    win_prob = win_raw / win_raw.sum()
    place_prob = place_raw / place_raw.sum()
    log_market = np.log(np.maximum(markets, 1e-10))
    log_win = np.log(np.maximum(win_prob, 1e-10))
    log_place = np.log(np.maximum(place_prob, 1e-10))
    zw = zscore(log_win)
    zp = zscore(log_place)
    zm = zscore(log_market)
    by_horse = {}
    for i, runner in enumerate(runners):
        h = int(runner["horseNo"])
        odds = max(1.01, float(runner.get("winOdds") or 99.0))
        by_horse[h] = {
            "win": float(win_prob[i]),
            "place": float(place_prob[i]),
            "market": float(markets[i]),
            "odds": odds,
            "zw": float(zw[i]),
            "zp": float(zp[i]),
            "zm": float(zm[i]),
            "finish": int(runner["finish"]),
        }
    return by_horse


def ranking_variants(by_horse):
    result = {}
    horses = list(by_horse)
    for value_strength in VALUE_STRENGTHS:
        for mix in MIXES:
            name = f"v{value_strength:.2f}_m{mix:.2f}"
            score = {
                h: mix * by_horse[h]["zw"] + (1.0 - mix) * by_horse[h]["zp"] - value_strength * by_horse[h]["zm"]
                for h in horses
            }
            result[name] = sorted(horses, key=lambda h: score[h], reverse=True)
    result["skill_win"] = sorted(horses, key=lambda h: by_horse[h]["win"], reverse=True)
    result["skill_place"] = sorted(horses, key=lambda h: by_horse[h]["place"], reverse=True)
    return result


def make_policies(course):
    types = COURSES[course]["types"]
    counts = COUNT_OPTIONS[course]
    variants = [f"v{v:.2f}_m{m:.2f}" for v in VALUE_STRENGTHS for m in MIXES] + ["skill_win", "skill_place"]
    policies = []
    for _ in range(POLICY_COUNT):
        count_tuple = counts[int(RNG.integers(0, len(counts)))]
        policies.append({
            "counts": dict(zip(types, count_tuple)),
            "anchor_variant": variants[int(RNG.integers(0, len(variants)))],
            "opponent_variant": variants[int(RNG.integers(0, len(variants)))],
            "pool": int(RNG.choice([5, 6, 7, 8, 9])),
            "prob_weight": float(RNG.choice([0.35, 0.55, 0.75, 1.0])),
            "value_weight": float(RNG.choice([0.55, 0.85, 1.15, 1.45, 1.8])),
            "longshot_weight": float(RNG.choice([0.0, 0.10, 0.20, 0.32, 0.45])),
            "race_value_weight": float(RNG.choice([0.6, 1.0, 1.4, 1.8])),
            "race_disagreement_weight": float(RNG.choice([0.0, 0.35, 0.7, 1.0])),
            "allocation_power": float(RNG.choice([0.5, 0.8, 1.1, 1.4])),
        })
    return policies


def ticket_candidates(bet_type, anchor_order, opponent_order, pool):
    import itertools
    a = anchor_order[: min(pool, len(anchor_order))]
    o = opponent_order[: min(pool, len(opponent_order))]
    universe = []
    seen = set()
    def add(horses):
        key = canon(bet_type, horses)
        if len(set(key)) != len(key) or key in seen:
            return
        seen.add(key)
        universe.append(key)
    if bet_type == "単勝":
        for h in a:
            add((h,))
        for h in o:
            add((h,))
    elif bet_type in {"ワイド", "馬連"}:
        for x in a[:3]:
            for y in o:
                if x != y:
                    add((x, y))
        for x, y in itertools.combinations(o[:6], 2):
            add((x, y))
    elif bet_type == "馬単":
        for x in a[:3]:
            for y in o:
                if x != y:
                    add((x, y))
                    add((y, x))
    elif bet_type == "3連複":
        merged = list(dict.fromkeys(a[:3] + o[:7]))
        for combo in itertools.combinations(merged, 3):
            add(combo)
    elif bet_type == "3連単":
        merged = list(dict.fromkeys(a[:3] + o[:7]))
        for x in a[:3]:
            for y in merged:
                if y == x:
                    continue
                for z in merged:
                    if z in {x, y}:
                        continue
                    add((x, y, z))
    return universe


def score_ticket(bet_type, horses, by_horse, policy):
    win_weights = {h: by_horse[h]["win"] for h in by_horse}
    place_weights = {h: by_horse[h]["place"] for h in by_horse}
    p = max(1e-10, event_probability(bet_type, horses, win_weights, place_weights))
    values = []
    odds = []
    for h in horses:
        row = by_horse[h]
        model_mix = 0.55 * row["win"] + 0.45 * row["place"]
        market = max(1e-9, row["market"])
        values.append(max(0.05, min(20.0, model_mix / market)))
        odds.append(max(1.01, row["odds"]))
    value_term = float(np.mean(np.log(values)))
    longshot_term = float(np.mean(np.log(odds)))
    return (
        policy["prob_weight"] * math.log(p)
        + policy["value_weight"] * value_term
        + policy["longshot_weight"] * longshot_term
    )


def build_portfolio(race, by_horse, variants, course, policy):
    spec = COURSES[course]
    anchor_order = variants[policy["anchor_variant"]]
    opponent_order = variants[policy["opponent_variant"]]
    selected = []
    selected_scores = []
    used = set()
    for bet_type in spec["types"]:
        candidates = ticket_candidates(bet_type, anchor_order, opponent_order, policy["pool"])
        scored = sorted(((score_ticket(bet_type, h, by_horse, policy), h) for h in candidates), reverse=True)
        need = policy["counts"][bet_type]
        for score, horses in scored:
            sig = (bet_type, canon(bet_type, horses))
            if sig in used:
                continue
            used.add(sig)
            selected.append(sig)
            selected_scores.append(float(score))
            need -= 1
            if need == 0:
                break
        if need:
            return None
    if len(selected) != spec["tickets"]:
        return None

    total_units = spec["budget"] // 100
    units = np.ones(len(selected), dtype=np.int16)
    remaining = total_units - len(selected)
    max_units = max(1, int(math.floor(total_units * spec["max_share"])))
    desirability = np.exp(np.asarray(selected_scores) - max(selected_scores))
    desirability = np.power(np.maximum(desirability, 1e-5), policy["allocation_power"])
    while remaining > 0:
        eligible = np.where(units < max_units)[0]
        if not len(eligible):
            eligible = np.arange(len(units))
        j = int(eligible[np.argmax(desirability[eligible] / np.maximum(1.0, units[eligible] ** 0.75))])
        units[j] += 1
        remaining -= 1

    payout_map = race.get("payouts") or {}
    refunds = set(int(x) for x in (race.get("refunds") or set()))
    returned = 0.0
    for (bet_type, horses), unit in zip(selected, units):
        if refunds and any(h in refunds for h in horses):
            payout = 100.0
        else:
            payout = float(payout_map.get(payout_key(bet_type, horses), 0.0) or 0.0)
        returned += payout * int(unit)

    horse_values = []
    for h in set(x for _, horses in selected for x in horses):
        row = by_horse[h]
        horse_values.append((0.55 * row["win"] + 0.45 * row["place"]) / max(1e-9, row["market"]))
    market = np.asarray([r["market"] for r in race["runners"]], dtype=np.float64)
    entropy = -float(np.sum(market * np.log(np.maximum(market, 1e-12))))
    disagreement = float(max(horse_values)) if horse_values else 1.0
    avg_ticket = float(np.mean(selected_scores))
    race_score = avg_ticket + policy["race_value_weight"] * math.log(max(0.05, disagreement)) + policy["race_disagreement_weight"] * entropy
    return returned, race_score


def summarize(returns, budget):
    arr = np.asarray(returns, dtype=np.float64)
    stake = len(arr) * budget
    if not len(arr):
        return {"races": 0, "stakeYen": 0, "returnYen": 0, "roiPct": None, "roiWithoutMaxPct": None, "roiWithoutTop1Pct": None}
    total = float(arr.sum())
    k = max(1, int(math.ceil(len(arr) * 0.01)))
    return {
        "races": len(arr), "stakeYen": stake, "returnYen": int(round(total)),
        "roiPct": total / stake * 100.0,
        "roiWithoutMaxPct": (total - float(arr.max())) / stake * 100.0,
        "roiWithoutTop1Pct": (total - float(np.sort(arr)[-k:].sum())) / stake * 100.0,
        "hitRatePct": float(np.mean(arr > 0) * 100.0), "maxRaceReturnYen": int(round(float(arr.max()))),
    }


def robust_policy_score(history_returns, budget):
    if not history_returns:
        return -1e9
    arr = np.asarray(history_returns, dtype=np.float64)
    stake = len(arr) * budget
    roi = arr.sum() / stake * 100.0
    capped = np.minimum(arr, budget * 12).sum() / stake * 100.0
    k = max(1, int(math.ceil(len(arr) * 0.01)))
    trimmed = (arr.sum() - np.sort(arr)[-k:].sum()) / stake * 100.0
    return 0.30 * min(roi, 350.0) + 0.35 * capped + 0.35 * trimmed


def main():
    with gzip.open(DATASET, "rb") as handle:
        payload = pickle.load(handle)
    races = list(payload["races"])
    races.sort(key=lambda r: (r["raceDate"], r["venue"], int(r["raceNo"])))
    quarters = sorted(set(quarter(r["raceDate"]) for r in races))
    policies = {course: make_policies(course) for course in COURSES}
    policy_history = {course: [[] for _ in policies[course]] for course in COURSES}
    final_records = {course: [] for course in COURSES}
    audit = []

    for q in quarters:
        target_indices = [i for i, race in enumerate(races) if quarter(race["raceDate"]) == q]
        if not target_indices:
            continue
        start_date = min(races[i]["raceDate"] for i in target_indices)
        train = [race for race in races if race["raceDate"] < start_date]
        if len(train) >= MIN_TRAIN_RACES:
            win_model, place_model = fit_models(train)
            model_mode = "catboost"
        else:
            win_model = place_model = None
            model_mode = "market_cold_start"

        race_data = {}
        for i in target_indices:
            by_horse = attach_predictions(races[i], win_model, place_model)
            race_data[i] = (by_horse, ranking_variants(by_horse))

        groups = defaultdict(list)
        for i in target_indices:
            race = races[i]
            groups[(race["raceDate"], race["venue"])].append(i)

        q_audit = {"quarter": q, "trainRaces": len(train), "targetRaces": len(target_indices), "modelMode": model_mode, "courses": {}}
        for course, spec in COURSES.items():
            n_policy = len(policies[course])
            policy_q_returns = [[] for _ in range(n_policy)]
            policy_q_selected = [[] for _ in range(n_policy)]
            for day_key, idxs in groups.items():
                if len(idxs) < 5:
                    raise RuntimeError(f"VENUE_DAY_LT5:{day_key}:{len(idxs)}")
                score_matrix = np.full((n_policy, len(idxs)), -1e12, dtype=np.float64)
                return_matrix = np.zeros((n_policy, len(idxs)), dtype=np.float64)
                for pidx, policy in enumerate(policies[course]):
                    for local, i in enumerate(idxs):
                        by_horse, variants = race_data[i]
                        built = build_portfolio(races[i], by_horse, variants, course, policy)
                        if built is not None:
                            returned, score = built
                            score_matrix[pidx, local] = score
                            return_matrix[pidx, local] = returned
                for pidx in range(n_policy):
                    valid = np.where(score_matrix[pidx] > -1e11)[0]
                    if len(valid) < 5:
                        continue
                    chosen_local = valid[np.argsort(-score_matrix[pidx, valid])[:5]]
                    for local in chosen_local:
                        policy_q_returns[pidx].append(float(return_matrix[pidx, local]))
                        policy_q_selected[pidx].append(idxs[int(local)])

            if any(policy_history[course][pidx] for pidx in range(n_policy)):
                scores = [robust_policy_score(policy_history[course][pidx], spec["budget"]) for pidx in range(n_policy)]
                chosen_policy = int(np.argmax(scores))
            else:
                chosen_policy = 0
            chosen_returns = policy_q_returns[chosen_policy]
            chosen_indices = policy_q_selected[chosen_policy]
            if len(chosen_returns) != 5 * len(groups):
                raise RuntimeError(f"COVERAGE_FAIL:{q}:{course}:{len(chosen_returns)}:{5*len(groups)}")
            for i, returned in zip(chosen_indices, chosen_returns):
                final_records[course].append({"date": races[i]["raceDate"], "returnYen": returned})
            for pidx in range(n_policy):
                policy_history[course][pidx].extend(policy_q_returns[pidx])
            q_audit["courses"][course] = {"chosenPolicy": chosen_policy, "quarter": summarize(chosen_returns, spec["budget"])}
        audit.append(q_audit)

    results = {}
    completion = True
    reasons = []
    for course, spec in COURSES.items():
        full_returns = [r["returnYen"] for r in final_records[course]]
        hold_returns = [r["returnYen"] for r in final_records[course] if r["date"] >= HOLDOUT_START]
        full = summarize(full_returns, spec["budget"])
        hold = summarize(hold_returns, spec["budget"])
        checks = {
            "fullRoi200": full["roiPct"] is not None and full["roiPct"] >= 200.0,
            "holdoutRoi200": hold["roiPct"] is not None and hold["roiPct"] >= 200.0,
            "holdout100Races": hold["races"] >= 100,
            "top1Trim100": full["roiWithoutTop1Pct"] is not None and full["roiWithoutTop1Pct"] >= 100.0,
            "maxTrim100": full["roiWithoutMaxPct"] is not None and full["roiWithoutMaxPct"] >= 100.0,
        }
        if not all(checks.values()):
            completion = False
            reasons.append({"course": course, "failed": [k for k, v in checks.items() if not v]})
        results[course] = {"full": full, "holdout": hold, "checks": checks}

    out = {
        "schema": 1,
        "explorationId": "catboost-market-residual-portfolios-20260808",
        "modelVersion": None,
        "source": {"races": len(races), "start": races[0]["raceDate"], "end": races[-1]["raceDate"], "newRaceIngestion": False, "oldVersionResultsUsed": False, "actualJraPayoutsOnly": True, "currentResultLeakage": False},
        "algorithm": {"runnerModels": "quarterly walk-forward CatBoost win/top3", "combinationOddsEstimated": False, "marketInput": "JRA official win odds/normalized win market only", "policiesPerCourse": POLICY_COUNT, "minimumRacesPerVenueDay": 5},
        "quarterlyAudit": audit,
        "courses": results,
        "completionPassed": completion,
        "promotionEligible": completion,
        "failureReasons": reasons,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"completionPassed": completion, "courses": {c: {"fullRoi": r["full"]["roiPct"], "holdoutRoi": r["holdout"]["roiPct"], "trimTop1": r["full"]["roiWithoutTop1Pct"], "races": r["full"]["races"]} for c, r in results.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
