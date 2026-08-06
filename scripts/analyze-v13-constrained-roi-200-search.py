import hashlib
import importlib.util
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v12-multi-course-upset.py"
CONSTRAINTS_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
OUTPUT = ROOT / "v13-constrained-roi-200-search.json"
CANDIDATE_POLICY = ROOT / "candidate-policies" / "v13-constrained-roi-200.py"

ROLLING_START = "2024-11"
DEV_START = "2025-05-01"
FINAL_START = "2026-05-01"
DEV_FOLDS = (
    ("2025-05-01", "2025-08-01"),
    ("2025-08-01", "2025-11-01"),
    ("2025-11-01", "2026-02-01"),
    ("2026-02-01", "2026-05-01"),
)
RACE_COUNTS = (5, 7, 9, 12)
STAGE1_POLICIES = 40
STAGE2_POLICIES = 900
STAGE2_CONFIGS = 6
RANDOM_SEED = 2026080701

TYPE_COUNTS = {
    "ライト": {"単勝": 1, "ワイド": 3, "馬連": 2},
    "スタンダード": {"単勝": 1, "ワイド": 4, "馬連": 2, "馬単": 5, "3連複": 3},
    "プレミアム": {"単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 3, "3連複": 3, "3連単": 5},
}

RANK_PROFILES = (
    {"name": "model", "kind": "linear", "point": 1.00, "market": 0.00},
    {"name": "linear-85-15", "kind": "linear", "point": 0.85, "market": 0.15},
    {"name": "linear-70-30", "kind": "linear", "point": 0.70, "market": 0.30},
    {"name": "linear-50-50", "kind": "linear", "point": 0.50, "market": 0.50},
    {"name": "geometric-75-25", "kind": "geometric", "point": 0.75, "market": 0.25},
    {"name": "geometric-50-50", "kind": "geometric", "point": 0.50, "market": 0.50},
    {"name": "value-025", "kind": "value", "alpha": 0.25},
    {"name": "value-050", "kind": "value", "alpha": 0.50},
)

SELECTION_PROFILES = (
    {"name": "confidence", "confidence": 1.00, "upset": 0.00, "disagreement": 0.00, "edge": 0.00, "concentration": 0.00},
    {"name": "upset", "confidence": 0.00, "upset": 1.00, "disagreement": 0.00, "edge": 0.00, "concentration": 0.00},
    {"name": "disagreement", "confidence": 0.00, "upset": 0.00, "disagreement": 1.00, "edge": 0.00, "concentration": 0.00},
    {"name": "edge", "confidence": 0.00, "upset": 0.00, "disagreement": 0.00, "edge": 1.00, "concentration": 0.00},
    {"name": "balanced", "confidence": 0.30, "upset": 0.30, "disagreement": 0.20, "edge": 0.10, "concentration": 0.10},
    {"name": "value-upset", "confidence": 0.05, "upset": 0.30, "disagreement": 0.25, "edge": 0.40, "concentration": 0.00},
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v12 = load_module("v13_v12_source", SOURCE)
enriched = v12.enriched
v7 = v12.v7
base = v12.base
v4 = v12.v4


def num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def verify_constraints():
    constraints = json.loads(CONSTRAINTS_PATH.read_text(encoding="utf-8"))
    rules = constraints["immutableProjectRules"]
    promotion = constraints["promotionRules"]
    if int(rules["minimumRacesPerVenueDay"]) != 5 or rules["mayDecreaseBelowMinimum"]:
        raise RuntimeError("V13_MINIMUM_RACE_RULE_CHANGED")
    if not rules["singleOnlyPortfolioForbidden"] or not rules["officialOddsOnly"]:
        raise RuntimeError("V13_BET_OR_ODDS_RULE_CHANGED")
    if float(promotion["targetRoiPct"]) != 200.0:
        raise RuntimeError("V13_TARGET_ROI_CHANGED")
    for course, counts in TYPE_COUNTS.items():
        spec = constraints["courses"][course]
        if sum(counts.values()) != int(spec["ticketCount"]):
            raise RuntimeError(f"V13_TICKET_COUNT_CHANGED:{course}")
        if set(counts) != set(spec["allowedBetTypes"]):
            raise RuntimeError(f"V13_BET_TYPES_CHANGED:{course}")
    return constraints


def rank_race(race, profile):
    runners = []
    raw = []
    for original in race["runners"]:
        point = max(1e-12, num(original.get("probability")))
        market = max(1e-12, num(original.get("market")))
        if profile["kind"] == "linear":
            value = profile["point"] * point + profile["market"] * market
        elif profile["kind"] == "geometric":
            value = point ** profile["point"] * market ** profile["market"]
        else:
            value = point / (market ** profile["alpha"])
        raw.append(max(1e-12, value))
    total = sum(raw)
    for original, value in zip(race["runners"], raw):
        copied = dict(original)
        copied["probability"] = value / total
        copied["edge"] = copied["probability"] / max(1e-12, num(original.get("market")))
        runners.append(copied)
    runners.sort(key=lambda row: row["probability"], reverse=True)
    item = dict(race)
    item["runners"] = runners
    point_values = [num(row["probability"]) for row in runners]
    market_values = np.asarray([max(1e-12, num(row.get("market"))) for row in runners], dtype=float)
    market_values /= market_values.sum()
    entropy = -sum(value * math.log(max(1e-12, value)) for value in point_values)
    entropy_norm = entropy / max(1e-12, math.log(max(2, len(runners))))
    market_top3 = float(np.sort(market_values)[::-1][:3].sum())
    item["topProbability"] = point_values[0]
    item["top3Concentration"] = sum(point_values[:3])
    item["entropy"] = entropy
    item["disagreement"] = sum(abs(num(row["probability"]) - num(row.get("market"))) for row in runners)
    item["maxEdge"] = max(num(row.get("edge")) for row in runners[:6])
    item["upsetSignal"] = clamp(
        0.30 * item["disagreement"]
        + 0.30 * entropy_norm
        + 0.20 * (1.0 - market_top3)
        + 0.20 * clamp((item["maxEdge"] - 1.0) / 3.0)
    )
    return item


def scale(values):
    values = np.asarray(values, dtype=float)
    span = float(values.max() - values.min()) if len(values) else 0.0
    return np.zeros_like(values) if span < 1e-12 else (values - values.min()) / span


def select_races(races, profile, count):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    coverage = []
    for key, group in sorted(grouped.items()):
        if len(group) < 5:
            raise RuntimeError(f"V13_SOURCE_BELOW_FIVE:{key}:{len(group)}")
        components = {
            "confidence": scale([num(r.get("topProbability")) for r in group]),
            "upset": scale([num(r.get("upsetSignal")) for r in group]),
            "disagreement": scale([num(r.get("disagreement")) for r in group]),
            "edge": scale([num(r.get("maxEdge")) for r in group]),
            "concentration": scale([num(r.get("top3Concentration")) for r in group]),
        }
        scores = np.zeros(len(group), dtype=float)
        for name, values in components.items():
            scores += num(profile.get(name)) * values
        take = min(len(group), max(5, int(count)))
        order = sorted(range(len(group)), key=lambda index: (-scores[index], group[index]["raceNo"]))
        picked = [group[index] for index in order[:take]]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    if not coverage or min(row["selected"] for row in coverage) < 5:
        raise RuntimeError("V13_SELECTED_BELOW_FIVE")
    return selected, coverage


def primitive_risk(primitive):
    _, bet_type, ranks = primitive
    type_bonus = {"単勝": 0.0, "ワイド": 0.2, "馬連": 0.5, "馬単": 0.9, "3連複": 1.1, "3連単": 1.7}[bet_type]
    return float(np.mean(ranks) + 0.35 * max(ranks) + type_bonus)


def weighted_pick(pool, count, target, spread, rng):
    available = list(pool)
    chosen = []
    while len(chosen) < count:
        weights = [math.exp(-((primitive_risk(item) - target) ** 2) / max(0.1, 2 * spread * spread)) for item in available]
        total = sum(weights)
        point = rng.random() * total
        running = 0.0
        index = len(available) - 1
        for candidate_index, weight in enumerate(weights):
            running += weight
            if running >= point:
                index = candidate_index
                break
        chosen.append(available.pop(index))
    return chosen


def allocate_units(primitives, budget, rng, aggressive):
    units_total = int(budget) // 100
    units = [1] * len(primitives)
    remaining = units_total - len(units)
    risks = np.asarray([primitive_risk(item) for item in primitives], dtype=float)
    center = float(risks.mean())
    logits = (risks - center) * (0.35 if aggressive else -0.20)
    logits += np.asarray([rng.uniform(-0.45, 0.45) for _ in primitives])
    weights = np.exp(logits - logits.max())
    probabilities = weights / weights.sum()
    if remaining > 0:
        extra = np.random.default_rng(rng.randrange(1, 2**31 - 1)).multinomial(remaining, probabilities)
        units = [value + int(add) for value, add in zip(units, extra)]
    if sum(units) * 100 != int(budget):
        raise RuntimeError("V13_BUDGET_MISMATCH")
    return units


def generate_policy(course, primitives_by_type, budget, rng):
    threshold = rng.choice((0.30, 0.40, 0.50, 0.60, 0.70))
    normal = []
    upset = []
    normal_target = rng.uniform(2.0, 4.4)
    upset_target = rng.uniform(3.5, 7.0)
    normal_spread = rng.uniform(0.8, 2.0)
    upset_spread = rng.uniform(1.0, 2.6)
    for bet_type, count in TYPE_COUNTS[course].items():
        pool = primitives_by_type[bet_type]
        normal.extend(weighted_pick(pool, count, normal_target, normal_spread, rng))
        upset.extend(weighted_pick(pool, count, upset_target, upset_spread, rng))
    return {
        "threshold": threshold,
        "normal": normal,
        "upset": upset,
        "normalUnits": allocate_units(normal, budget, rng, False),
        "upsetUnits": allocate_units(upset, budget, rng, True),
    }


def structured_policies(course, primitives_by_type, budget):
    rows = []
    for offset, threshold in enumerate((0.35, 0.45, 0.55, 0.65)):
        normal = []
        upset = []
        for bet_type, count in TYPE_COUNTS[course].items():
            pool = sorted(primitives_by_type[bet_type], key=primitive_risk)
            normal.extend(pool[(offset + index) % len(pool)] for index in range(count))
            reverse = list(reversed(pool))
            upset.extend(reverse[(offset + index) % len(reverse)] for index in range(count))
        rng = random.Random(RANDOM_SEED + offset + len(course))
        rows.append({
            "threshold": threshold,
            "normal": normal,
            "upset": upset,
            "normalUnits": allocate_units(normal, budget, rng, False),
            "upsetUnits": allocate_units(upset, budget, rng, True),
        })
    return rows


def generate_policies(course, primitives_by_type, budget, count, seed):
    rows = structured_policies(course, primitives_by_type, budget)
    rng = random.Random(seed)
    while len(rows) < count:
        rows.append(generate_policy(course, primitives_by_type, budget, rng))
    return rows


def policy_returns(payouts, upset_signal, policies, primitive_index):
    result = np.zeros((len(payouts), len(policies)), dtype=float)
    for column, policy in enumerate(policies):
        normal = np.zeros(len(payouts), dtype=float)
        upset = np.zeros(len(payouts), dtype=float)
        for primitive, units in zip(policy["normal"], policy["normalUnits"]):
            normal += payouts[:, primitive_index[primitive[0]]] * units
        for primitive, units in zip(policy["upset"], policy["upsetUnits"]):
            upset += payouts[:, primitive_index[primitive[0]]] * units
        result[:, column] = np.where(upset_signal >= policy["threshold"], upset, normal)
    return result


def summarize_vector(returns, races, budget):
    values = np.asarray(returns, dtype=float)
    stake = len(values) * int(budget)
    total = float(values.sum())
    top = float(values.max()) if len(values) else 0.0
    hits = int(np.sum(values > 0))
    return {
        "races": len(values),
        "hits": hits,
        "stakeYen": stake,
        "returnYen": int(round(total)),
        "profitYen": int(round(total - stake)),
        "roiPct": total / stake * 100 if stake else 0.0,
        "roiWithoutTop1Pct": max(0.0, total - top) / stake * 100 if stake else 0.0,
        "hitRatePct": hits / len(values) * 100 if len(values) else 0.0,
        "maxSingleReturnShare": top / total if total > 0 else 1.0,
    }


def fold_indices(races):
    return [
        np.asarray([index for index, race in enumerate(races) if start <= race["raceDate"] < end], dtype=int)
        for start, end in DEV_FOLDS
    ]


def evaluate_policy_columns(returns_matrix, races, budget):
    folds = fold_indices(races)
    rows = []
    for column in range(returns_matrix.shape[1]):
        metrics = [summarize_vector(returns_matrix[indexes, column], [races[i] for i in indexes], budget) for indexes in folds]
        min_roi = min(row["roiPct"] for row in metrics)
        min_trimmed = min(row["roiWithoutTop1Pct"] for row in metrics)
        min_hits = min(row["hits"] for row in metrics)
        mean_roi = sum(row["roiPct"] for row in metrics) / len(metrics)
        deficit = sum(max(0.0, 200.0 - row["roiPct"]) ** 2 for row in metrics)
        trimmed_deficit = sum(max(0.0, 100.0 - row["roiWithoutTop1Pct"]) ** 2 for row in metrics)
        score = (
            min_roi * 1_000_000
            + min_trimmed * 10_000
            + mean_roi * 100
            + min_hits
            - deficit * 10
            - trimmed_deficit * 3
        )
        rows.append({
            "column": column,
            "score": score,
            "minimumFoldRoiPct": min_roi,
            "minimumFoldRoiWithoutTop1Pct": min_trimmed,
            "minimumFoldHits": min_hits,
            "meanFoldRoiPct": mean_roi,
            "folds": metrics,
        })
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def policy_description(policy):
    def side(name):
        return [
            {
                "code": primitive[0],
                "betType": primitive[1],
                "predictedRanks": list(primitive[2]),
                "stakeYen": units * 100,
            }
            for primitive, units in zip(policy[name], policy[f"{name}Units"])
        ]
    return {"upsetThreshold": policy["threshold"], "normal": side("normal"), "upset": side("upset")}


def config_key(rank_profile, selection_profile, count):
    return f'{rank_profile["name"]}|{selection_profile["name"]}|{count}'


def rank_predictions(point_predictions, months, profile):
    return {month: [rank_race(race, profile) for race in point_predictions[month]] for month in months}


def select_development(ranked_by_month, months, selection_profile, count):
    selected = []
    coverage = []
    for month in months:
        if month < DEV_START[:7] or month >= FINAL_START[:7]:
            continue
        picked, rows = select_races(ranked_by_month[month], selection_profile, count)
        selected.extend(picked)
        coverage.extend(rows)
    return selected, coverage


def evaluate_config(selected, coverage, policies_by_course, primitives, primitive_index, constraints):
    payouts = np.asarray([[base.primitive_payout(race, primitive) for primitive in primitives] for race in selected], dtype=float)
    signal = np.asarray([num(race.get("upsetSignal")) for race in selected], dtype=float)
    courses = {}
    for course, policies in policies_by_course.items():
        returns = policy_returns(payouts, signal, policies, primitive_index)
        ranked = evaluate_policy_columns(returns, selected, constraints["courses"][course]["budgetYen"])
        best = ranked[0]
        courses[course] = {
            **best,
            "policy": policy_description(policies[best["column"]]),
            "policyObject": policies[best["column"]],
        }
    joint_min_roi = min(row["minimumFoldRoiPct"] for row in courses.values())
    joint_min_trimmed = min(row["minimumFoldRoiWithoutTop1Pct"] for row in courses.values())
    joint_mean = sum(row["meanFoldRoiPct"] for row in courses.values()) / len(courses)
    return {
        "jointMinimumFoldRoiPct": joint_min_roi,
        "jointMinimumFoldRoiWithoutTop1Pct": joint_min_trimmed,
        "jointMeanFoldRoiPct": joint_mean,
        "coverage": {
            "groups": len(coverage),
            "minimumSelectedRaces": min(row["selected"] for row in coverage),
            "maximumSelectedRaces": max(row["selected"] for row in coverage),
        },
        "courses": courses,
    }


def choose_stage1(point_predictions, months, constraints, primitives, primitive_index, primitives_by_type):
    policies_by_course = {
        course: generate_policies(
            course,
            primitives_by_type,
            spec["budgetYen"],
            STAGE1_POLICIES,
            RANDOM_SEED + index * 1000,
        )
        for index, (course, spec) in enumerate(constraints["courses"].items())
    }
    rows = []
    for rank_profile in RANK_PROFILES:
        ranked = rank_predictions(point_predictions, months, rank_profile)
        for selection_profile in SELECTION_PROFILES:
            for count in RACE_COUNTS:
                selected, coverage = select_development(ranked, months, selection_profile, count)
                result = evaluate_config(selected, coverage, policies_by_course, primitives, primitive_index, constraints)
                rows.append({
                    "key": config_key(rank_profile, selection_profile, count),
                    "rankProfile": rank_profile,
                    "selectionProfile": selection_profile,
                    "racesPerVenueDay": count,
                    **result,
                })
    rows.sort(
        key=lambda row: (
            row["jointMinimumFoldRoiPct"],
            row["jointMinimumFoldRoiWithoutTop1Pct"],
            row["jointMeanFoldRoiPct"],
        ),
        reverse=True,
    )
    return rows


def refine_configs(stage1, point_predictions, months, constraints, primitives, primitive_index, primitives_by_type):
    rows = []
    for config_index, config in enumerate(stage1[:STAGE2_CONFIGS]):
        policies_by_course = {
            course: generate_policies(
                course,
                primitives_by_type,
                spec["budgetYen"],
                STAGE2_POLICIES,
                RANDOM_SEED + 100_000 + config_index * 10_000 + course_index * 1_000,
            )
            for course_index, (course, spec) in enumerate(constraints["courses"].items())
        }
        ranked = rank_predictions(point_predictions, months, config["rankProfile"])
        selected, coverage = select_development(
            ranked,
            months,
            config["selectionProfile"],
            config["racesPerVenueDay"],
        )
        result = evaluate_config(selected, coverage, policies_by_course, primitives, primitive_index, constraints)
        rows.append({
            "key": config["key"],
            "rankProfile": config["rankProfile"],
            "selectionProfile": config["selectionProfile"],
            "racesPerVenueDay": config["racesPerVenueDay"],
            **result,
        })
    rows.sort(
        key=lambda row: (
            row["jointMinimumFoldRoiPct"],
            row["jointMinimumFoldRoiWithoutTop1Pct"],
            row["jointMeanFoldRoiPct"],
        ),
        reverse=True,
    )
    return rows


def evaluate_final(best, point_predictions, months, primitives, primitive_index, constraints):
    ranked = rank_predictions(point_predictions, months, best["rankProfile"])
    selected = []
    coverage = []
    for month in months:
        if month < FINAL_START[:7]:
            continue
        picked, rows = select_races(ranked[month], best["selectionProfile"], best["racesPerVenueDay"])
        selected.extend(picked)
        coverage.extend(rows)
    payouts = np.asarray([[base.primitive_payout(race, primitive) for primitive in primitives] for race in selected], dtype=float)
    signal = np.asarray([num(race.get("upsetSignal")) for race in selected], dtype=float)
    results = {}
    for course, row in best["courses"].items():
        policy = row["policyObject"]
        returns = policy_returns(payouts, signal, [policy], primitive_index)[:, 0]
        results[course] = summarize_vector(returns, selected, constraints["courses"][course]["budgetYen"])
    return results, {
        "groups": len(coverage),
        "minimumSelectedRaces": min(row["selected"] for row in coverage),
        "maximumSelectedRaces": max(row["selected"] for row in coverage),
    }


def python_literal(value):
    return repr(value)


def generate_candidate_policy_source(model_version, best):
    course_policies = {
        course: {
            "upsetThreshold": row["policy"]["upsetThreshold"],
            "normal": row["policy"]["normal"],
            "upset": row["policy"]["upset"],
        }
        for course, row in best["courses"].items()
    }
    rank_profile = best["rankProfile"]
    selection_profile = best["selectionProfile"]
    count = best["racesPerVenueDay"]
    return f'''import itertools\nimport math\nfrom collections import defaultdict\n\nMODEL_VERSION = {model_version!r}\nCOURSE_TARGET_STAKES = {{"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}}\nCOURSES = tuple(COURSE_TARGET_STAKES)\nOFFICIAL_ODDS_SOURCE = "jra_official"\nUNORDERED_TYPES = {{"ワイド", "馬連", "3連複"}}\nRANK_PROFILE = {python_literal(rank_profile)}\nSELECTION_PROFILE = {python_literal(selection_profile)}\nRACES_PER_VENUE_DAY = {count}\nCOURSE_POLICIES = {python_literal(course_policies)}\n\ndef clamp(value, low=0.0, high=1.0):\n    return max(low, min(high, value))\n\ndef canonical_horses(bet_type, horses):\n    values = tuple(int(value) for value in horses)\n    return tuple(sorted(values)) if bet_type in UNORDERED_TYPES else values\n\ndef odds_key(bet_type, horses):\n    values = canonical_horses(bet_type, horses)\n    return f'{{bet_type}}:{{"-".join(str(value) for value in values)}}'\n\ndef official_odds_map(race):\n    if race.get("oddsSource") != OFFICIAL_ODDS_SOURCE:\n        return {{}}\n    raw = race.get("officialOdds")\n    if not isinstance(raw, dict):\n        return {{}}\n    result = {{}}\n    for key, value in raw.items():\n        try:\n            odds = float(value)\n        except (TypeError, ValueError):\n            continue\n        if math.isfinite(odds) and odds > 1.0:\n            result[str(key)] = math.floor(odds * 10) / 10\n    return result\n\ndef rank_runners(race):\n    source = race.get("runners", [])\n    raw = []\n    for runner in source:\n        point = max(1e-12, float(runner.get("probability") or 0))\n        market = max(1e-12, float(runner.get("market") or 0))\n        if RANK_PROFILE["kind"] == "linear":\n            value = RANK_PROFILE["point"] * point + RANK_PROFILE["market"] * market\n        elif RANK_PROFILE["kind"] == "geometric":\n            value = point ** RANK_PROFILE["point"] * market ** RANK_PROFILE["market"]\n        else:\n            value = point / (market ** RANK_PROFILE["alpha"])\n        raw.append(max(1e-12, value))\n    total = sum(raw)\n    runners = []\n    for runner, value in zip(source, raw):\n        copied = dict(runner)\n        copied["rankProbability"] = value / max(1e-12, total)\n        copied["rankEdge"] = copied["rankProbability"] / max(1e-12, float(runner.get("market") or 0))\n        runners.append(copied)\n    runners.sort(key=lambda row: row["rankProbability"], reverse=True)\n    return runners\n\ndef race_components(race):\n    runners = rank_runners(race)\n    probabilities = [float(row["rankProbability"]) for row in runners]\n    markets = [max(1e-12, float(row.get("market") or 0)) for row in runners]\n    market_total = sum(markets)\n    markets = [value / market_total for value in markets]\n    entropy = -sum(value * math.log(max(1e-12, value)) for value in probabilities)\n    entropy_norm = entropy / max(1e-12, math.log(max(2, len(runners))))\n    market_top3 = sum(sorted(markets, reverse=True)[:3])\n    disagreement = sum(abs(a - b) for a, b in zip(probabilities, markets))\n    max_edge = max((row["rankEdge"] for row in runners[:6]), default=1.0)\n    upset = clamp(0.30 * disagreement + 0.30 * entropy_norm + 0.20 * (1.0 - market_top3) + 0.20 * clamp((max_edge - 1.0) / 3.0))\n    return {{\n        "confidence": probabilities[0] if probabilities else 0.0,\n        "upset": upset,\n        "disagreement": disagreement,\n        "edge": max_edge,\n        "concentration": sum(probabilities[:3]),\n    }}\n\ndef scale(values):\n    if not values:\n        return []\n    low, high = min(values), max(values)\n    if high - low < 1e-12:\n        return [0.0 for _ in values]\n    return [(value - low) / (high - low) for value in values]\n\ndef selected_race_ids(races):\n    groups = defaultdict(list)\n    for race in races:\n        groups[(race["raceDate"], race["venue"])].append(race)\n    selected = set()\n    for group in groups.values():\n        if len(group) < 5:\n            continue\n        rows = [race_components(race) for race in group]\n        scaled = {{name: scale([row[name] for row in rows]) for name in SELECTION_PROFILE if name != "name"}}\n        scores = []\n        for index in range(len(group)):\n            score = sum(float(SELECTION_PROFILE[name]) * scaled[name][index] for name in scaled)\n            scores.append(score)\n        order = sorted(range(len(group)), key=lambda index: (-scores[index], group[index]["raceNo"]))\n        take = min(len(group), max(5, RACES_PER_VENUE_DAY))\n        selected.update(group[index]["raceId"] for index in order[:take])\n    return selected\n\ndef ordered_probability(order, weights):\n    remaining = sum(weights.values())\n    result = 1.0\n    used = set()\n    for horse in order:\n        if horse in used or remaining <= 0:\n            return 0.0\n        weight = weights.get(horse, 0.0)\n        if weight <= 0:\n            return 0.0\n        result *= weight / remaining\n        remaining -= weight\n        used.add(horse)\n    return clamp(result)\n\ndef unordered_probability(horses, weights):\n    return clamp(sum(ordered_probability(order, weights) for order in itertools.permutations(horses)))\n\ndef wide_probability(first, second, weights):\n    return clamp(sum(unordered_probability((first, second, third), weights) for third in weights if third not in {{first, second}}))\n\ndef event_probability(bet_type, horses, weights):\n    if bet_type == "単勝":\n        return weights.get(horses[0], 0.0)\n    if bet_type == "ワイド":\n        return wide_probability(horses[0], horses[1], weights)\n    if bet_type == "馬連":\n        return unordered_probability(horses[:2], weights)\n    if bet_type == "馬単":\n        return ordered_probability(horses[:2], weights)\n    if bet_type == "3連複":\n        return unordered_probability(horses[:3], weights)\n    return ordered_probability(horses[:3], weights)\n\ndef build_bets(race):\n    official = official_odds_map(race)\n    if not official:\n        return []\n    ranked = rank_runners(race)\n    if len(ranked) < 6:\n        return []\n    weights = {{int(row["horseNo"]): float(row["rankProbability"]) for row in ranked}}\n    upset = race_components(race)["upset"]\n    all_bets = []\n    signatures = {{}}\n    for course, policy in COURSE_POLICIES.items():\n        side = policy["upset"] if upset >= policy["upsetThreshold"] else policy["normal"]\n        bets = []\n        for ticket in side:\n            horses = tuple(int(ranked[int(rank) - 1]["horseNo"]) for rank in ticket["predictedRanks"])\n            horses = canonical_horses(ticket["betType"], horses)\n            odds = official.get(odds_key(ticket["betType"], horses))\n            if odds is None:\n                return []\n            probability = event_probability(ticket["betType"], horses, weights)\n            bets.append({{\n                "betType": f'{{course}}｜{{ticket["betType"]}}',\n                "combination": "-".join(str(value) for value in horses),\n                "stakeYen": int(ticket["stakeYen"]),\n                "assumedOdds": odds,\n                "officialOdds": odds,\n                "oddsSource": OFFICIAL_ODDS_SOURCE,\n                "hitProbability": probability,\n                "expectedValuePct": probability * odds * 100,\n            }})\n        if sum(row["stakeYen"] for row in bets) != COURSE_TARGET_STAKES[course]:\n            raise RuntimeError(f"V13_LIVE_BUDGET_MISMATCH:{{course}}")\n        signatures[course] = tuple((row["betType"], row["combination"], row["stakeYen"]) for row in bets)\n        all_bets.extend(bets)\n    if len(set(signatures.values())) != len(signatures):\n        raise RuntimeError("V13_LIVE_COURSES_NOT_DISTINCT")\n    return all_bets\n'''


def strip_internal(best):
    result = dict(best)
    result["courses"] = {}
    for course, row in best["courses"].items():
        result["courses"][course] = {key: value for key, value in row.items() if key not in {"column", "score", "policyObject"}}
    return result


def main():
    constraints = verify_constraints()
    v12.EXPECTED = constraints
    runner_rows, payouts = v4.load_data()
    races = enriched.enrich_races(v4.build_dataset(runner_rows, payouts), enriched.load_extra_rows())
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(ROLLING_START, last_month)
    predictions, ranking_audit = enriched.rolling_predictions(races, months)
    point_predictions = predictions["point"]

    primitives = list(base.PRIMITIVES)
    primitive_index = {primitive[0]: index for index, primitive in enumerate(primitives)}
    primitives_by_type = defaultdict(list)
    for primitive in primitives:
        primitives_by_type[primitive[1]].append(primitive)

    stage1 = choose_stage1(point_predictions, months, constraints, primitives, primitive_index, primitives_by_type)
    stage2 = refine_configs(stage1, point_predictions, months, constraints, primitives, primitive_index, primitives_by_type)
    best = stage2[0]

    target = float(constraints["promotionRules"]["targetRoiPct"])
    trimmed_target = float(constraints["promotionRules"]["requireRoiWithoutTop1Pct"])
    development_passed = (
        best["jointMinimumFoldRoiPct"] >= target
        and best["jointMinimumFoldRoiWithoutTop1Pct"] >= trimmed_target
        and best["coverage"]["minimumSelectedRaces"] >= int(constraints["immutableProjectRules"]["minimumRacesPerVenueDay"])
    )

    final_results = None
    final_coverage = None
    promotion_eligible = False
    implementation = None
    model_version = "v13-constrained-roi-200-search"

    if development_passed:
        final_results, final_coverage = evaluate_final(best, point_predictions, months, primitives, primitive_index, constraints)
        promotion_eligible = all(
            row["races"] >= int(constraints["promotionRules"]["minimumFinalHoldoutRacesPerCourse"])
            and row["roiPct"] >= target
            and row["roiWithoutTop1Pct"] >= trimmed_target
            for row in final_results.values()
        )
        if promotion_eligible:
            CANDIDATE_POLICY.parent.mkdir(parents=True, exist_ok=True)
            source = generate_candidate_policy_source(model_version, best)
            CANDIDATE_POLICY.write_text(source, encoding="utf-8")
            implementation = {
                "candidatePolicyPath": str(CANDIDATE_POLICY.relative_to(ROOT)),
                "candidatePolicySha256": hashlib.sha256(CANDIDATE_POLICY.read_bytes()).hexdigest(),
                "productionRunnerPath": "scripts/run-final-course-production.py",
            }

    courses = {}
    for course, row in best["courses"].items():
        courses[course] = {
            "development": {
                "minimumFoldRoiPct": row["minimumFoldRoiPct"],
                "minimumFoldRoiWithoutTop1Pct": row["minimumFoldRoiWithoutTop1Pct"],
                "minimumFoldHits": row["minimumFoldHits"],
                "meanFoldRoiPct": row["meanFoldRoiPct"],
                "folds": row["folds"],
            },
            "policy": row["policy"],
            "coverage": best["coverage"],
            "finalHoldout": final_results[course] if final_results else None,
        }

    report = {
        "generatedAt": "2026-08-07",
        "modelVersion": model_version,
        "productionChanged": False,
        "promotionEligible": promotion_eligible,
        "developmentPassedRoi200Objective": development_passed,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "liveBetGenerationRequiresOfficialCombinationOdds": True,
        "officialCombinationOddsRequiredForLiveBets": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "finalHoldoutEvaluated": final_results is not None,
        "searchObjective": {
            "primary": "maximize the minimum ROI across every development fold and every course",
            "targetRoiPct": target,
            "minimumRacesPerVenueDay": constraints["immutableProjectRules"]["minimumRacesPerVenueDay"],
            "singleOnlyPortfolioForbidden": True,
            "allCourseBetTypesRequired": True,
            "finalHoldoutUsedOnlyAfterDevelopmentPass": True,
        },
        "constraints": constraints,
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
            "developmentFolds": [f"{start}..{end}" for start, end in DEV_FOLDS],
            "finalHoldout": f"{FINAL_START}..end",
        },
        "searchAudit": {
            "stage1Configurations": len(stage1),
            "stage1PoliciesPerCourse": STAGE1_POLICIES,
            "stage2Configurations": len(stage2),
            "stage2PoliciesPerCourse": STAGE2_POLICIES,
            "rankingAudit": ranking_audit,
            "stage1Top": [strip_internal(row) for row in stage1[:5]],
            "stage2Top": [strip_internal(row) for row in stage2[:5]],
        },
        "selectedConfiguration": {
            "rankProfile": best["rankProfile"],
            "selectionProfile": best["selectionProfile"],
            "racesPerVenueDay": best["racesPerVenueDay"],
            "jointMinimumFoldRoiPct": best["jointMinimumFoldRoiPct"],
            "jointMinimumFoldRoiWithoutTop1Pct": best["jointMinimumFoldRoiWithoutTop1Pct"],
            "jointMeanFoldRoiPct": best["jointMeanFoldRoiPct"],
            "coverage": best["coverage"],
        },
        "finalCoverage": final_coverage,
        "productionImplementation": implementation,
        "courses": courses,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "developmentPassedRoi200Objective": development_passed,
        "finalHoldoutEvaluated": final_results is not None,
        "promotionEligible": promotion_eligible,
        "selectedConfiguration": report["selectedConfiguration"],
        "courses": {
            course: {
                "minimumDevelopmentFoldRoiPct": row["development"]["minimumFoldRoiPct"],
                "minimumDevelopmentFoldRoiWithoutTop1Pct": row["development"]["minimumFoldRoiWithoutTop1Pct"],
                "finalHoldout": row["finalHoldout"],
            }
            for course, row in courses.items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
