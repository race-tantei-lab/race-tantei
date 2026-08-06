import importlib.util
import json
import random
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
rolling = load_module("v6_rolling", ROOT / "scripts" / "analyze-v6-rolling-oos.py")
base = rolling.base

COURSES = tuple(base.COURSE_BUDGETS)
RACE_MODES = tuple(base.RACE_MODES)
DEV_MONTHS = rolling.DEV_MONTHS
REQUIRED_HIT = 36.8
POLICY_COUNT = 5200
RANDOM_SEED = 2026080619

UNIT_RANGES = {
    "ライト": (5, 16),
    "スタンダード": (12, 42),
    "プレミアム": (25, 88),
}
TICKET_RANGES = {
    "ライト": (1, 4),
    "スタンダード": (2, 8),
    "プレミアム": (3, 12),
}
MAX_SHARE = {"ライト": 0.70, "スタンダード": 0.58, "プレミアム": 0.48}
MIN_TYPES = {"ライト": 1, "スタンダード": 2, "プレミアム": 3}
CAP_MULTIPLE = {"ライト": 6.0, "スタンダード": 8.0, "プレミアム": 12.0}


def type_count(units):
    return len({base.TYPE_BY_INDEX[index] for index, value in enumerate(units) if value > 0})


def weighted_sample(rng, pool, count, course):
    rows = []
    for index in pool:
        bet_type = base.TYPE_BY_INDEX[index]
        weight = base.TYPE_DRAW_WEIGHTS[course].get(bet_type, 1.0)
        rows.append((rng.random() ** (1.0 / max(0.01, weight)), index))
    rows.sort(reverse=True)
    return [index for _, index in rows[:count]]


def allocate(total_units, indices, raw):
    units = np.zeros(len(base.PRIMITIVES), dtype=np.int16)
    for index in indices:
        units[index] = 1
    remaining = total_units - len(indices)
    if remaining <= 0:
        return units
    weights = np.maximum(np.asarray(raw, dtype=np.float64), 0.001)
    weights /= weights.sum()
    exact = weights * remaining
    additions = np.floor(exact).astype(int)
    for index, amount in zip(indices, additions):
        units[index] += int(amount)
    leftover = remaining - int(additions.sum())
    order = np.argsort(-(exact - additions))
    for position in order[:leftover]:
        units[indices[int(position)]] += 1
    return units


def generate_sparse_policies(course):
    rng = random.Random(RANDOM_SEED + sum(ord(ch) for ch in course))
    allowed = [
        index for index in range(len(base.PRIMITIVES))
        if base.TYPE_BY_INDEX[index] in base.COURSE_ALLOWED_TYPES[course]
    ]
    low_units, high_units = UNIT_RANGES[course]
    low_tickets, high_tickets = TICKET_RANGES[course]
    policies = []
    seen = set()

    for seed in base.seed_policies(course):
        indices = np.flatnonzero(seed > 0).tolist()
        for total_units in sorted(set([
            low_units,
            max(low_units, int((low_units + high_units) * 0.35)),
            max(low_units, int((low_units + high_units) * 0.55)),
            high_units,
        ])):
            if len(indices) > total_units:
                continue
            raw = [float(seed[index]) for index in indices]
            units = allocate(total_units, indices, raw)
            signature = tuple(int(value) for value in units)
            if signature not in seen:
                seen.add(signature)
                policies.append(units)

    while len(policies) < POLICY_COUNT:
        ticket_count = rng.randint(low_tickets, high_tickets)
        total_units = rng.randint(max(low_units, ticket_count), high_units)
        indices = weighted_sample(rng, allowed, ticket_count, course)
        concentration = rng.choice([0.25, 0.4, 0.65, 1.0, 1.5, 2.5])
        raw = [rng.gammavariate(concentration, 1.0) for _ in indices]
        units = allocate(total_units, indices, raw)
        if int(units.max()) / max(1, int(units.sum())) > MAX_SHARE[course]:
            continue
        if type_count(units) < MIN_TYPES[course]:
            continue
        signature = tuple(int(value) for value in units)
        if signature in seen:
            continue
        seen.add(signature)
        policies.append(units)
    return np.asarray(policies, dtype=np.int16)


def policy_tables(races, policies):
    matrix, months = base.payout_matrix(races)
    returns = matrix @ policies.T.astype(np.float64)
    hits = ((matrix > 0).astype(np.int16) @ (policies > 0).T.astype(np.int16)) > 0
    return matrix, months, returns, hits


def select_policy(course, races, policies):
    _, months, returns, hits = policy_tables(races, policies)
    stakes = policies.sum(axis=1).astype(np.float64) * 100
    capped = np.minimum(returns, stakes[np.newaxis, :] * CAP_MULTIPLE[course])

    raw_months = []
    capped_months = []
    hit_months = []
    present_months = []
    for month in DEV_MONTHS:
        mask = months == month
        count = int(mask.sum())
        if count == 0:
            continue
        present_months.append(month)
        denominator = stakes * count
        raw_months.append(returns[mask].sum(axis=0) / denominator * 100)
        capped_months.append(capped[mask].sum(axis=0) / denominator * 100)
        hit_months.append(hits[mask].mean(axis=0) * 100)

    raw_stack = np.vstack(raw_months)
    capped_stack = np.vstack(capped_months)
    hit_stack = np.vstack(hit_months)
    total_denominator = stakes * len(races)
    total_raw = returns.sum(axis=0) / total_denominator * 100
    total_capped = capped.sum(axis=0) / total_denominator * 100
    total_hit = hits.mean(axis=0) * 100
    winning_months = np.sum(raw_stack >= 100.0, axis=0)
    q25_capped = np.quantile(capped_stack, 0.25, axis=0)
    median_capped = np.median(capped_stack, axis=0)
    median_raw = np.median(raw_stack, axis=0)
    minimum_hit = np.min(hit_stack, axis=0)
    maximum_share = np.max(returns, axis=0) / np.maximum(1.0, returns.sum(axis=0))

    score = (
        q25_capped * 0.35
        + median_capped * 0.20
        + total_capped * 0.15
        + median_raw * 0.10
        + total_hit * 0.15
        + minimum_hit * 0.05
        - np.maximum(0.0, REQUIRED_HIT - total_hit) * 4.5
        - np.maximum(0.0, 4.0 - winning_months) * 24.0
        - np.maximum(0.0, maximum_share - 0.30) * 320.0
    )
    eligible = (
        (total_hit >= REQUIRED_HIT)
        & (winning_months >= 4)
        & (q25_capped >= 75.0)
        & (maximum_share <= 0.42)
    )
    pool = np.flatnonzero(eligible)
    best = int(pool[np.argmax(score[pool])]) if len(pool) else int(np.argmax(score))

    month_details = {}
    for row_index, month in enumerate(present_months):
        month_details[month] = {
            "rawRoiPct": float(raw_stack[row_index, best]),
            "cappedRoiPct": float(capped_stack[row_index, best]),
            "hitRatePct": float(hit_stack[row_index, best]),
        }
    return {
        "index": best,
        "units": policies[best].copy(),
        "stakePerRaceYen": int(stakes[best]),
        "score": float(score[best]),
        "eligible": bool(eligible[best]),
        "eligiblePolicyCount": int(eligible.sum()),
        "totalRawRoiPct": float(total_raw[best]),
        "totalCappedRoiPct": float(total_capped[best]),
        "totalHitRatePct": float(total_hit[best]),
        "winningMonths": int(winning_months[best]),
        "q25CappedRoiPct": float(q25_capped[best]),
        "maxSingleReturnShare": float(maximum_share[best]),
        "months": month_details,
    }


def evaluate(course, races, units):
    matrix, _ = base.payout_matrix(races)
    returns = matrix @ units.astype(np.float64)
    hits = np.any((matrix > 0) & (units[np.newaxis, :] > 0), axis=1)
    stake_per_race = int(units.sum() * 100)
    stake = stake_per_race * len(races)
    returned = float(returns.sum())
    dates = np.asarray([race["raceDate"] for race in races], dtype=object)
    by_day = {}
    for race_date in sorted(set(dates.tolist())):
        mask = dates == race_date
        day_stake = stake_per_race * int(mask.sum())
        day_return = float(returns[mask].sum())
        by_day[race_date] = {
            "races": int(mask.sum()),
            "stakeYen": day_stake,
            "returnYen": int(round(day_return)),
            "roiPct": day_return / day_stake * 100 if day_stake else 0.0,
            "hitRatePct": float(hits[mask].mean() * 100),
        }
    return {
        "races": len(races),
        "stakePerRaceYen": stake_per_race,
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": float(hits.mean() * 100) if len(races) else 0.0,
        "byDay": by_day,
    }


def main():
    rows, payouts = base.v6.v4.load_data()
    races = base.v6.v4.build_dataset(rows, payouts)
    dev_predictions = rolling.rolling_predictions(races)
    august_raw = [race for race in races if "2026-08-01" <= race["raceDate"] <= "2026-08-02"]
    august_train = [race for race in races if race["raceDate"] < "2026-08-01"]
    august_model = base.v6.fit_pairwise(august_train, rolling.MODEL_CONFIG)
    august_predictions = base.v6.attach_pairwise(
        august_model, august_raw, rolling.BLEND, rolling.TEMPERATURE
    )

    policies = {course: generate_sparse_policies(course) for course in COURSES}
    candidates = {course: [] for course in COURSES}
    for mode in RACE_MODES:
        selected_dev = []
        for month in DEV_MONTHS:
            selected_dev.extend(base.v6.select_five(dev_predictions[month], mode))
        for course in COURSES:
            chosen = select_policy(course, selected_dev, policies[course])
            candidates[course].append({
                "mode": mode,
                "chosen": chosen,
                "policy": base.describe_policy(chosen["units"]),
            })

    winners = {}
    august = {}
    for course in COURSES:
        candidates[course].sort(key=lambda row: row["chosen"]["score"], reverse=True)
        winner = candidates[course][0]
        selected_august = base.v6.select_five(august_predictions, winner["mode"])
        result = evaluate(course, selected_august, winner["chosen"]["units"])
        winners[course] = {
            "mode": winner["mode"],
            "development": {
                key: value for key, value in winner["chosen"].items()
                if key not in {"units", "index"}
            },
            "policy": winner["policy"],
        }
        august[course] = result

    pass_100 = all(
        row["roiPct"] >= 100.0 and row["hitRatePct"] >= REQUIRED_HIT
        for row in august.values()
    )
    pass_200 = all(
        row["roiPct"] >= 200.0 and row["hitRatePct"] >= REQUIRED_HIT
        for row in august.values()
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.5-shadow-sparse-variable-budget",
        "productionChanged": False,
        "method": "Use seven rolling out-of-sample months, treat each course budget as a ceiling, choose sparse ticket portfolios with variable stake, and evaluate August 1-2 only after mode and portfolio are frozen.",
        "winners": winners,
        "august": august,
        "promotionEligible100": pass_100,
        "promotionEligible200": pass_200,
    }
    Path("v6-sparse-budget-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "winners": {course: {"mode": row["mode"], "development": row["development"]} for course, row in winners.items()},
        "august": august,
        "promotionEligible100": pass_100,
        "promotionEligible200": pass_200,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
