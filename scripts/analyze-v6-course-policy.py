import importlib.util
import itertools
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v6 = load_module("v6_shadow", ROOT / "scripts" / "analyze-v6-shadow.py")

# Hyperparameters are frozen from the completed v6 May-June selection.
MODEL_CONFIG = {
    "max_leaf_nodes": 31,
    "learning_rate": 0.02,
    "max_iter": 260,
    "l2_regularization": 8.0,
}
BLEND = 0.60
TEMPERATURE = 1.30
RACE_MODES = ["confidence", "edge", "disagreement", "concentration", "entropy", "balanced"]
COURSE_BUDGETS = {"ライト": 1600, "スタンダード": 4200, "プレミアム": 8800}
REQUIRED_OVERALL_HIT = 36.8
MINIMUM_MONTH_HIT = 20.0
RANDOM_SEED = 2026080617


def in_range(race_date, start, end):
    return start <= race_date <= end


def primitive_catalog():
    rows = []
    for rank in range(1, 5):
        rows.append((f"S{rank}", "単勝", (rank,)))
    for first, second in itertools.combinations(range(1, 6), 2):
        rows.append((f"W{first}{second}", "ワイド", (first, second)))
        rows.append((f"Q{first}{second}", "馬連", (first, second)))
    for first, second in itertools.permutations(range(1, 5), 2):
        rows.append((f"E{first}{second}", "馬単", (first, second)))
    for ranks in itertools.combinations(range(1, 6), 3):
        rows.append(("T" + "".join(map(str, ranks)), "3連複", ranks))
    for ranks in itertools.permutations(range(1, 5), 3):
        rows.append(("X" + "".join(map(str, ranks)), "3連単", ranks))
    return rows


PRIMITIVES = primitive_catalog()
PRIMITIVE_INDEX = {row[0]: index for index, row in enumerate(PRIMITIVES)}
TYPE_BY_INDEX = {index: row[1] for index, row in enumerate(PRIMITIVES)}

COURSE_ALLOWED_TYPES = {
    "ライト": {"単勝", "ワイド", "馬連"},
    "スタンダード": {"単勝", "ワイド", "馬連", "馬単", "3連複"},
    "プレミアム": {"単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"},
}
COURSE_COUNTS = {
    "ライト": (2, 6),
    "スタンダード": (5, 12),
    "プレミアム": (8, 18),
}
TYPE_DRAW_WEIGHTS = {
    "ライト": {"単勝": 1.2, "ワイド": 3.0, "馬連": 1.8},
    "スタンダード": {"単勝": 1.2, "ワイド": 2.4, "馬連": 1.7, "馬単": 1.3, "3連複": 1.6},
    "プレミアム": {"単勝": 0.6, "ワイド": 1.2, "馬連": 1.1, "馬単": 1.6, "3連複": 2.0, "3連単": 2.4},
}


def canonical_key(bet_type, horses):
    values = list(horses)
    if bet_type in {"ワイド", "馬連", "3連複"}:
        values.sort()
    return f'{bet_type}:{"-".join(map(str, values))}'


def primitive_payout(race, primitive):
    _, bet_type, ranks = primitive
    runners = race["runners"]
    if any(rank > len(runners) for rank in ranks):
        return 0.0
    horses = tuple(int(runners[rank - 1]["horseNo"]) for rank in ranks)
    if any(horse in race.get("refunds", set()) for horse in horses):
        return 100.0
    return float(race.get("payouts", {}).get(canonical_key(bet_type, horses), 0.0))


def payout_matrix(races):
    matrix = np.zeros((len(races), len(PRIMITIVES)), dtype=np.float64)
    months = []
    for race_index, race in enumerate(races):
        months.append(race["raceDate"][:7])
        for primitive_index, primitive in enumerate(PRIMITIVES):
            matrix[race_index, primitive_index] = primitive_payout(race, primitive)
    return matrix, np.asarray(months, dtype=object)


def allocate_units(budget, indices, raw_weights):
    total_units = budget // 100
    if len(indices) > total_units:
        return None
    units = np.zeros(len(PRIMITIVES), dtype=np.int16)
    for index in indices:
        units[index] = 1
    remaining = total_units - len(indices)
    if remaining <= 0:
        return units
    weights = np.asarray(raw_weights, dtype=np.float64)
    weights = np.maximum(weights, 0.001)
    weights = weights / weights.sum()
    exact = weights * remaining
    additions = np.floor(exact).astype(int)
    for index, amount in zip(indices, additions):
        units[index] += int(amount)
    leftover = remaining - int(additions.sum())
    order = np.argsort(-(exact - additions))
    for position in order[:leftover]:
        units[indices[int(position)]] += 1
    return units


def weighted_sample_without_replacement(rng, pool, count, course):
    keys = []
    for index in pool:
        bet_type = TYPE_BY_INDEX[index]
        weight = TYPE_DRAW_WEIGHTS[course][bet_type]
        key = rng.random() ** (1.0 / max(0.001, weight))
        keys.append((key, index))
    keys.sort(reverse=True)
    return [index for _, index in keys[:count]]


def seed_policies(course):
    named = {
        "ライト": [
            ["W12", "W13"],
            ["W12", "W13", "W23"],
            ["S1", "W12", "W13"],
            ["W13", "W14", "W24"],
            ["W12", "W13", "Q12", "Q13"],
        ],
        "スタンダード": [
            ["S1", "W12", "W13", "Q12", "Q13", "E12", "T123"],
            ["W12", "W13", "W23", "Q12", "E12", "E13", "T123", "T124"],
            ["S1", "S2", "W12", "W13", "Q12", "Q13", "E12", "E21", "T123"],
        ],
        "プレミアム": [
            ["W12", "W13", "Q12", "E12", "E13", "T123", "T124", "T134", "X123", "X132"],
            ["S1", "W12", "W13", "W23", "E12", "E13", "E21", "T123", "T124", "X123", "X132", "X213"],
            ["W12", "W13", "Q12", "Q13", "E12", "E13", "E21", "T123", "T124", "T134", "X123", "X132", "X213", "X231"],
        ],
    }
    result = []
    budget = COURSE_BUDGETS[course]
    for names in named[course]:
        indices = [PRIMITIVE_INDEX[name] for name in names]
        for power in [0.7, 1.0, 1.4, 2.0]:
            raw = [1.0 / ((position + 1) ** power) for position in range(len(indices))]
            units = allocate_units(budget, indices, raw)
            if units is not None:
                result.append(units)
    return result


def generate_policies(course, count=3000):
    rng = random.Random(RANDOM_SEED + sum(ord(ch) for ch in course))
    allowed = [index for index in range(len(PRIMITIVES)) if TYPE_BY_INDEX[index] in COURSE_ALLOWED_TYPES[course]]
    low, high = COURSE_COUNTS[course]
    policies = seed_policies(course)
    seen = {tuple(policy.tolist()) for policy in policies}
    while len(policies) < count:
        ticket_count = rng.randint(low, high)
        indices = weighted_sample_without_replacement(rng, allowed, ticket_count, course)
        concentration = rng.choice([0.35, 0.55, 0.8, 1.0, 1.4, 2.0, 3.0])
        raw = [rng.gammavariate(concentration, 1.0) for _ in indices]
        units = allocate_units(COURSE_BUDGETS[course], indices, raw)
        if units is None:
            continue
        signature = tuple(units.tolist())
        if signature in seen:
            continue
        seen.add(signature)
        policies.append(units)
    return np.asarray(policies, dtype=np.int16)


def period_metrics(matrix, months, units):
    stake_per_race = int(units.sum() * 100)
    returns = matrix @ units.astype(np.float64)
    hits = np.any((matrix > 0) & (units[np.newaxis, :] > 0), axis=1)
    result = {}
    for month in sorted(set(months.tolist())):
        mask = months == month
        races = int(mask.sum())
        stake = stake_per_race * races
        returned = float(returns[mask].sum())
        result[month] = {
            "races": races,
            "stakeYen": stake,
            "returnYen": int(round(returned)),
            "roiPct": returned / stake * 100 if stake else 0.0,
            "hitRatePct": float(hits[mask].mean() * 100) if races else 0.0,
        }
    total_races = len(matrix)
    total_stake = stake_per_race * total_races
    total_return = float(returns.sum())
    result["TOTAL"] = {
        "races": total_races,
        "stakeYen": total_stake,
        "returnYen": int(round(total_return)),
        "roiPct": total_return / total_stake * 100 if total_stake else 0.0,
        "hitRatePct": float(hits.mean() * 100) if total_races else 0.0,
    }
    return result


def policy_score(metrics):
    months = [row for key, row in metrics.items() if key != "TOTAL"]
    minimum_roi = min(row["roiPct"] for row in months)
    mean_roi = sum(row["roiPct"] for row in months) / len(months)
    minimum_hit = min(row["hitRatePct"] for row in months)
    total_hit = metrics["TOTAL"]["hitRatePct"]
    penalty = max(0.0, REQUIRED_OVERALL_HIT - total_hit) * 7.0
    penalty += max(0.0, MINIMUM_MONTH_HIT - minimum_hit) * 4.0
    return minimum_roi * 0.58 + mean_roi * 0.22 + minimum_hit * 0.10 + total_hit * 0.10 - penalty


def clean_metrics(metrics):
    return {
        key: {
            "races": int(row["races"]),
            "stakeYen": int(row["stakeYen"]),
            "returnYen": int(row["returnYen"]),
            "profitYen": int(row["returnYen"] - row["stakeYen"]),
            "roiPct": round(float(row["roiPct"]), 4),
            "hitRatePct": round(float(row["hitRatePct"]), 4),
        }
        for key, row in metrics.items()
    }


def describe_policy(units):
    rows = []
    for index, unit in enumerate(units):
        if unit <= 0:
            continue
        name, bet_type, ranks = PRIMITIVES[index]
        rows.append({
            "code": name,
            "betType": bet_type,
            "predictedRanks": list(ranks),
            "stakeYen": int(unit * 100),
        })
    return rows


def optimize_course(course, policies, matrices):
    best = None
    for units in policies:
        combined_matrix = np.concatenate([matrices["validation"][0], matrices["july"][0]], axis=0)
        combined_months = np.concatenate([matrices["validation"][1], matrices["july"][1]], axis=0)
        metrics = period_metrics(combined_matrix, combined_months, units)
        score = policy_score(metrics)
        row = {"units": units.copy(), "metrics": metrics, "score": score}
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def main():
    rows, payouts = v6.v4.load_data()
    races = v6.v4.build_dataset(rows, payouts)

    train = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-04-30")]
    validation_raw = [race for race in races if in_range(race["raceDate"], "2026-05-01", "2026-06-30")]
    through_june = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-06-30")]
    july_raw = [race for race in races if in_range(race["raceDate"], "2026-07-01", "2026-07-31")]
    through_july = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-07-31")]
    august_raw = [race for race in races if in_range(race["raceDate"], "2026-08-01", "2026-08-02")]

    validation_model = v6.fit_pairwise(train, MODEL_CONFIG)
    validation = v6.attach_pairwise(validation_model, validation_raw, BLEND, TEMPERATURE)
    july_model = v6.fit_pairwise(through_june, MODEL_CONFIG)
    july = v6.attach_pairwise(july_model, july_raw, BLEND, TEMPERATURE)
    august_model = v6.fit_pairwise(through_july, MODEL_CONFIG)
    august = v6.attach_pairwise(august_model, august_raw, BLEND, TEMPERATURE)

    policy_sets = {course: generate_policies(course) for course in COURSE_BUDGETS}
    mode_results = []
    for mode in RACE_MODES:
        selected_validation = v6.select_five(validation, mode)
        selected_july = v6.select_five(july, mode)
        selected_august = v6.select_five(august, mode)
        matrices = {
            "validation": payout_matrix(selected_validation),
            "july": payout_matrix(selected_july),
            "august": payout_matrix(selected_august),
        }
        courses = {}
        for course, policies in policy_sets.items():
            optimized = optimize_course(course, policies, matrices)
            august_metrics = period_metrics(matrices["august"][0], matrices["august"][1], optimized["units"])
            courses[course] = {
                "policy": describe_policy(optimized["units"]),
                "development": clean_metrics(optimized["metrics"]),
                "developmentScore": round(float(optimized["score"]), 4),
                "august": clean_metrics(august_metrics),
            }
        development_floor = min(row["developmentScore"] for row in courses.values())
        development_roi_floor = min(
            min(value["roiPct"] for key, value in row["development"].items() if key != "TOTAL")
            for row in courses.values()
        )
        mode_results.append({
            "mode": mode,
            "selected": {
                "validation": len(selected_validation),
                "july": len(selected_july),
                "august": len(selected_august),
            },
            "courses": courses,
            "developmentFloor": round(float(development_floor), 4),
            "developmentRoiFloor": round(float(development_roi_floor), 4),
        })

    mode_results.sort(key=lambda row: (row["developmentRoiFloor"], row["developmentFloor"]), reverse=True)
    winner = mode_results[0]
    promotion = all(
        row["august"]["TOTAL"]["roiPct"] > 100
        and row["august"]["TOTAL"]["hitRatePct"] >= REQUIRED_OVERALL_HIT
        for row in winner["courses"].values()
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.1-shadow-course-policy",
        "productionChanged": False,
        "selectionRule": "Rank model fixed from v6; race mode and course-specific ticket portfolios selected using May, June and July only. August 1-2 is evaluation only.",
        "ranking": {
            "config": MODEL_CONFIG,
            "blend": BLEND,
            "temperature": TEMPERATURE,
        },
        "winner": winner,
        "promotionEligible": promotion,
        "allModes": mode_results,
    }
    Path("v6-course-policy-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "mode": winner["mode"],
        "promotionEligible": promotion,
        "august": {
            course: row["august"]["TOTAL"]
            for course, row in winner["courses"].items()
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
