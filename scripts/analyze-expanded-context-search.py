import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "analyze-v14-historical-roi200.py"
CONSTRAINTS_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
OUTPUT = ROOT / "analysis-results" / "exploration-expanded-context.json"

EXPLORATION_ID = "expanded-context-longshot"
ROLLING_START_MONTH = "2024-11"
DEV_FOLDS = (
    ("2025-05-01", "2025-08-01"),
    ("2025-08-01", "2025-11-01"),
    ("2025-11-01", "2026-02-01"),
    ("2026-02-01", "2026-05-01"),
)
FINAL_START = "2026-05-01"
RANDOM_SEED = 2026080711
TARGET_CAP_MULTIPLE = 250.0
MAX_TRAIN_ROWS_PER_TYPE = 180_000
PAYOUT_REGRESSOR_MAX_ROWS = 80_000
PRIOR_SHRINK_ROWS = 120.0

BET_TYPES = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")
MODEL_WEIGHTS = (0.90, 1.00)
PAYOUT_BIASES = (0.0, 0.35, 0.70)
HIT_BIASES = (-0.15, 0.0)
ALLOCATION_POWERS = (2.0, 4.0, 8.0)
RACE_COUNTS = (5, 7, 9)
RACE_SCORE_MODES = ("minimum", "lower_mean", "mean")
MAX_TICKET_SHARE = {"ライト": 0.45, "スタンダード": 0.40, "プレミアム": 0.35}

TYPE_COUNTS = {
    "ライト": {"単勝": 1, "ワイド": 3, "馬連": 2},
    "スタンダード": {"単勝": 1, "ワイド": 4, "馬連": 2, "馬単": 5, "3連複": 3},
    "プレミアム": {"単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 3, "3連複": 3, "3連単": 5},
}

# Original chronological runner features plus the enriched form block added by
# analyze-v7-enriched-ranking.py. These values exist before the target race result.
RUNNER_FEATURE_INDICES = (
    3, 4, 5, 7, 8, 17, 18, 25, 27, 28,
    51, 52, 58, 61, 63, 64, 66, 67, 70, 72,
    73, 74, 82, 83,
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_analysis = load_module("expanded_context_base", BASE_PATH)


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def load_constraints():
    constraints = json.loads(CONSTRAINTS_PATH.read_text(encoding="utf-8"))
    rules = constraints["immutableProjectRules"]
    promotion = constraints["promotionRules"]
    if int(rules["minimumRacesPerVenueDay"]) != 5 or rules["mayDecreaseBelowMinimum"]:
        raise RuntimeError("MINIMUM_RACE_RULE_CHANGED")
    if rules["syntheticOddsForbidden"] is not True or rules["postResultLeakageForbidden"] is not True:
        raise RuntimeError("ODDS_OR_LEAKAGE_RULE_CHANGED")
    if float(promotion["completionRoiPct"]) != 200.0:
        raise RuntimeError("COMPLETION_ROI_CHANGED")
    if str(promotion["approvedModelVersion"]) != "v16":
        raise RuntimeError("APPROVED_VERSION_CHANGED")
    for course, counts in TYPE_COUNTS.items():
        spec = constraints["courses"][course]
        if sum(counts.values()) != int(spec["ticketCount"]):
            raise RuntimeError(f"TICKET_COUNT_CHANGED:{course}")
        if set(counts) != set(spec["allowedBetTypes"]):
            raise RuntimeError(f"BET_TYPES_CHANGED:{course}")
    return constraints


def expanded_primitive_catalog():
    rows = []
    for rank in range(1, 13):
        rows.append((f"S{rank}", "単勝", (rank,)))
    for first, second in itertools.combinations(range(1, 9), 2):
        rows.append((f"W{first}{second}", "ワイド", (first, second)))
        rows.append((f"Q{first}{second}", "馬連", (first, second)))
    for first, second in itertools.permutations(range(1, 7), 2):
        rows.append((f"E{first}{second}", "馬単", (first, second)))
    for ranks in itertools.combinations(range(1, 8), 3):
        rows.append(("T" + "".join(map(str, ranks)), "3連複", ranks))
    for ranks in itertools.permutations(range(1, 7), 3):
        rows.append(("X" + "".join(map(str, ranks)), "3連単", ranks))
    return rows


PRIMITIVES = expanded_primitive_catalog()
PRIMITIVES_BY_TYPE = {
    bet_type: [primitive for primitive in PRIMITIVES if primitive[1] == bet_type]
    for bet_type in BET_TYPES
}
base_analysis.base.PRIMITIVES = PRIMITIVES
base_analysis.base.PRIMITIVE_INDEX = {row[0]: index for index, row in enumerate(PRIMITIVES)}
base_analysis.base.TYPE_BY_INDEX = {index: row[1] for index, row in enumerate(PRIMITIVES)}


def compact_runner_features(runner):
    raw = list(runner.get("features") or [])
    selected = [number(raw[index]) if index < len(raw) else 0.0 for index in RUNNER_FEATURE_INDICES]
    return [
        number(runner.get("probability")),
        number(runner.get("market")),
        number(runner.get("edge")),
        number(runner.get("popularity"), 18.0) / 18.0,
        *selected,
    ]


def primitive_features(race, primitive):
    _, bet_type, ranks = primitive
    runners = list(race.get("runners") or [])
    selected = [runners[rank - 1] if 0 < rank <= len(runners) else {} for rank in ranks]
    probs = [max(1e-9, number(row.get("probability"))) for row in selected]
    markets = [max(1e-9, number(row.get("market"))) for row in selected]
    edges = [p / max(1e-9, m) for p, m in zip(probs, markets)]
    padded_ranks = list(ranks) + [0] * (3 - len(ranks))
    padded_probs = probs + [0.0] * (3 - len(probs))
    padded_markets = markets + [0.0] * (3 - len(markets))
    padded_edges = edges + [0.0] * (3 - len(edges))
    type_one_hot = [int(bet_type == value) for value in BET_TYPES]
    ordered = int(bet_type in {"馬単", "3連単"})

    feature_width = 4 + len(RUNNER_FEATURE_INDICES)
    selected_context = []
    for row in selected[:3]:
        selected_context.extend(compact_runner_features(row))
    while len(selected_context) < feature_width * 3:
        selected_context.extend([0.0] * feature_width)
    selected_context = selected_context[: feature_width * 3]

    return base_analysis.race_base_features(race) + type_one_hot + [
        len(ranks) / 3.0,
        padded_ranks[0] / 12.0,
        padded_ranks[1] / 12.0,
        padded_ranks[2] / 12.0,
        sum(ranks) / 30.0,
        max(ranks) / 12.0,
        ordered,
        float(np.prod(probs)) if probs else 0.0,
        sum(probs),
        max(probs) if probs else 0.0,
        min(probs) if probs else 0.0,
        float(np.prod(markets)) if markets else 0.0,
        sum(markets),
        float(np.prod(edges)) if edges else 0.0,
        sum(edges) / max(1, len(edges)),
        *padded_probs,
        *padded_markets,
        *padded_edges,
        *selected_context,
    ]


class TwoStageContextModel:
    def __init__(self, classifier, payout_model, probability_scale, payout_fallback):
        self.classifier = classifier
        self.payout_model = payout_model
        self.probability_scale = probability_scale
        self.payout_fallback = payout_fallback

    def predict_components(self, x):
        hit_probability = self.classifier.predict_proba(x)[:, 1]
        hit_probability = np.clip(hit_probability * self.probability_scale, 0.000001, 1.0)
        if self.payout_model is None:
            conditional_payout = np.full(len(x), self.payout_fallback, dtype=float)
        else:
            conditional_payout = np.expm1(self.payout_model.predict(x))
            conditional_payout = np.clip(conditional_payout, 1.0, TARGET_CAP_MULTIPLE)
        expected_return = hit_probability * conditional_payout
        return hit_probability, conditional_payout, expected_return


def flat_target(races, primitives, flat_index):
    primitive_count = len(primitives)
    race_index = int(flat_index) // primitive_count
    primitive_index = int(flat_index) % primitive_count
    race = races[race_index]
    primitive = primitives[primitive_index]
    payout = base_analysis.base.primitive_payout(race, primitive) / 100.0
    return race_index, primitive_index, min(TARGET_CAP_MULTIPLE, max(0.0, payout))


def fit_two_stage_models(races, seed):
    rng = np.random.default_rng(seed)
    models = {}
    priors = {}
    audit = {}

    for type_index, bet_type in enumerate(BET_TYPES):
        primitives = PRIMITIVES_BY_TYPE[bet_type]
        primitive_count = len(primitives)
        total_pairs = len(races) * primitive_count
        if total_pairs <= 0:
            raise RuntimeError(f"NO_TRAINING_PAIRS:{bet_type}")

        primitive_totals = np.zeros(primitive_count, dtype=np.float64)
        positive_payouts = {}
        for race_index, race in enumerate(races):
            for primitive_index, primitive in enumerate(primitives):
                payout = base_analysis.base.primitive_payout(race, primitive) / 100.0
                capped = min(TARGET_CAP_MULTIPLE, max(0.0, payout))
                primitive_totals[primitive_index] += capped
                if capped > 0:
                    positive_payouts[race_index * primitive_count + primitive_index] = capped

        positive_indices = np.fromiter(positive_payouts.keys(), dtype=np.int64)
        positive_set = set(int(value) for value in positive_indices)
        max_rows = min(MAX_TRAIN_ROWS_PER_TYPE, total_pairs)
        if len(positive_indices) >= max_rows:
            selected_positive = rng.choice(positive_indices, max_rows // 2, replace=False)
        else:
            selected_positive = positive_indices
        negative_needed = max(0, max_rows - len(selected_positive))
        negative_indices = []
        selected_negative = set()
        while len(negative_indices) < negative_needed:
            remaining = negative_needed - len(negative_indices)
            draw_size = min(total_pairs, max(remaining * 2, 5000))
            drawn = rng.choice(total_pairs, draw_size, replace=False)
            for value in drawn:
                index = int(value)
                if index in positive_set or index in selected_negative:
                    continue
                selected_negative.add(index)
                negative_indices.append(index)
                if len(negative_indices) >= negative_needed:
                    break
            if len(selected_negative) >= total_pairs - len(positive_set):
                break

        selected_indices = np.concatenate([
            np.asarray(selected_positive, dtype=np.int64),
            np.asarray(negative_indices, dtype=np.int64),
        ])
        rng.shuffle(selected_indices)

        x_rows = []
        y_hit = []
        y_payout = []
        positive_feature_rows = []
        positive_feature_payouts = []
        for flat_index in selected_indices:
            race_index, primitive_index, capped = flat_target(races, primitives, int(flat_index))
            features = primitive_features(races[race_index], primitives[primitive_index])
            x_rows.append(features)
            is_hit = int(capped > 0)
            y_hit.append(is_hit)
            y_payout.append(capped)
            if is_hit:
                positive_feature_rows.append(features)
                positive_feature_payouts.append(capped)

        x = np.asarray(x_rows, dtype=np.float32)
        y = np.asarray(y_hit, dtype=np.int8)
        if len(np.unique(y)) < 2:
            raise RuntimeError(f"CLASSIFIER_SINGLE_CLASS:{bet_type}")

        classifier = HistGradientBoostingClassifier(
            loss="log_loss",
            max_leaf_nodes=31,
            learning_rate=0.035,
            max_iter=200,
            l2_regularization=18.0,
            min_samples_leaf=60,
            max_bins=63,
            random_state=seed + type_index,
        )
        classifier.fit(x, y)
        raw_probability = classifier.predict_proba(x)[:, 1]
        true_rate = len(positive_payouts) / total_pairs
        probability_scale = float(np.clip(true_rate / max(1e-9, float(np.mean(raw_probability))), 0.02, 2.0))

        payout_model = None
        payout_fallback = float(np.median(list(positive_payouts.values()))) if positive_payouts else 1.0
        if len(positive_feature_rows) >= 160:
            positive_x = np.asarray(positive_feature_rows, dtype=np.float32)
            positive_y = np.asarray(positive_feature_payouts, dtype=np.float32)
            if len(positive_y) > PAYOUT_REGRESSOR_MAX_ROWS:
                keep = rng.choice(len(positive_y), PAYOUT_REGRESSOR_MAX_ROWS, replace=False)
                positive_x = positive_x[keep]
                positive_y = positive_y[keep]
            payout_model = HistGradientBoostingRegressor(
                loss="squared_error",
                max_leaf_nodes=31,
                learning_rate=0.03,
                max_iter=180,
                l2_regularization=22.0,
                min_samples_leaf=max(30, min(90, len(positive_y) // 18)),
                max_bins=63,
                random_state=seed + 100 + type_index,
            )
            payout_model.fit(positive_x, np.log1p(positive_y))

        overall_return = float(primitive_totals.sum() / total_pairs)
        priors[bet_type] = {}
        for primitive_index, primitive in enumerate(primitives):
            prior = (
                primitive_totals[primitive_index] + overall_return * PRIOR_SHRINK_ROWS
            ) / (len(races) + PRIOR_SHRINK_ROWS)
            priors[bet_type][primitive[0]] = float(prior)

        models[bet_type] = TwoStageContextModel(
            classifier,
            payout_model,
            probability_scale,
            payout_fallback,
        )
        audit[bet_type] = {
            "allPairs": total_pairs,
            "trainingRows": len(y),
            "positivePairs": len(positive_payouts),
            "trueHitRatePct": true_rate * 100.0,
            "probabilityScale": probability_scale,
            "medianHitPayoutMultiple": payout_fallback,
            "payoutRegressorUsed": payout_model is not None,
            "runnerContextFeatureCount": len(RUNNER_FEATURE_INDICES),
        }

    return models, priors, audit


def predict_components(races, models, priors):
    output = []
    for race in races:
        components = {}
        for bet_type in BET_TYPES:
            primitives = PRIMITIVES_BY_TYPE[bet_type]
            x = np.asarray([primitive_features(race, primitive) for primitive in primitives], dtype=np.float32)
            hit, payout, expected = models[bet_type].predict_components(x)
            for primitive, hit_value, payout_value, expected_value in zip(primitives, hit, payout, expected):
                components[primitive[0]] = {
                    "hit": float(hit_value),
                    "payout": float(payout_value),
                    "expected": float(expected_value),
                    "prior": float(priors[bet_type][primitive[0]]),
                }
        item = dict(race)
        item["primitiveComponents"] = components
        output.append(item)
    return output


def primitive_utility(component, model_weight, payout_bias, hit_bias):
    blended = model_weight * component["expected"] + (1.0 - model_weight) * component["prior"]
    payout_term = max(1.0, component["payout"]) ** payout_bias
    hit_term = max(0.001, component["hit"]) ** hit_bias
    return max(1e-8, blended * payout_term * hit_term)


def allocate_units(selected, budget, power, max_share):
    total_units = int(budget) // 100
    units = [1] * len(selected)
    max_units = max(1, int(math.floor(total_units * max_share)))
    remaining = total_units - len(units)
    raw = np.asarray([max(1e-8, row[1]) ** power for row in selected], dtype=float)
    while remaining > 0:
        candidates = [index for index in range(len(units)) if units[index] < max_units]
        if not candidates:
            candidates = list(range(len(units)))
        index = max(candidates, key=lambda item: raw[item] / (units[item] ** 0.70))
        units[index] += 1
        remaining -= 1
    return units


def build_course_plan(race, course, constraints, score_config, allocation_power):
    model_weight, payout_bias, hit_bias = score_config
    components = race["primitiveComponents"]
    selected = []
    for bet_type, count in TYPE_COUNTS[course].items():
        pool = []
        for primitive in PRIMITIVES_BY_TYPE[bet_type]:
            component = components[primitive[0]]
            utility = primitive_utility(component, model_weight, payout_bias, hit_bias)
            pool.append((primitive, utility, component))
        pool.sort(key=lambda row: (row[1], row[2]["expected"], -sum(row[0][2])), reverse=True)
        selected.extend(pool[:count])

    budget = int(constraints["courses"][course]["budgetYen"])
    allocation_source = [(row[0], row[1]) for row in selected]
    units = allocate_units(allocation_source, budget, allocation_power, MAX_TICKET_SHARE[course])
    tickets = []
    expected_total = 0.0
    utility_total = 0.0
    for (primitive, utility, component), unit in zip(selected, units):
        stake = int(unit * 100)
        tickets.append({
            "code": primitive[0],
            "betType": primitive[1],
            "predictedRanks": list(primitive[2]),
            "stakeYen": stake,
            "predictedHitProbability": component["hit"],
            "predictedConditionalPayoutMultiple": component["payout"],
            "predictedReturnMultiple": component["expected"],
            "selectionUtility": utility,
        })
        expected_total += component["expected"] * stake
        utility_total += utility * stake
    return {
        "budgetYen": budget,
        "predictedRoiPct": expected_total / budget * 100.0,
        "selectionScorePct": utility_total / budget * 100.0,
        "tickets": tickets,
    }


def attach_plans(races, constraints, score_config, allocation_power):
    output = []
    for race in races:
        item = dict(race)
        item["coursePlans"] = {
            course: build_course_plan(race, course, constraints, score_config, allocation_power)
            for course in constraints["courses"]
        }
        output.append(item)
    return output


def race_score(race, mode):
    values = [
        race["coursePlans"][course]["selectionScorePct"]
        for course in ("ライト", "スタンダード", "プレミアム")
    ]
    if mode == "minimum":
        return min(values)
    if mode == "lower_mean":
        return 0.65 * min(values) + 0.35 * float(np.mean(values))
    return float(np.mean(values))


def select_races(races, count, mode):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    coverage = []
    for key, group in sorted(grouped.items()):
        if len(group) < 5:
            continue
        take = min(len(group), max(5, int(count)))
        group.sort(key=lambda race: (-race_score(race, mode), int(number(race.get("raceNo")))))
        picked = group[:take]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    if not coverage or min(row["selected"] for row in coverage) < 5:
        raise RuntimeError("SELECTED_BELOW_FIVE")
    return selected, coverage


def settle_race(race, plan):
    total = 0.0
    hit = False
    for ticket in plan["tickets"]:
        primitive = next(row for row in PRIMITIVES if row[0] == ticket["code"])
        payout = base_analysis.base.primitive_payout(race, primitive)
        units = ticket["stakeYen"] // 100
        if payout > 0:
            hit = True
            total += payout * units
    return total, hit


def summarize(returns, hits, budget):
    values = np.asarray(returns, dtype=float)
    stake = len(values) * int(budget)
    total = float(values.sum())
    top = float(values.max()) if len(values) else 0.0
    return {
        "races": len(values),
        "hits": int(sum(hits)),
        "stakeYen": int(stake),
        "returnYen": int(round(total)),
        "profitYen": int(round(total - stake)),
        "roiPct": total / stake * 100.0 if stake else 0.0,
        "roiWithoutTop1Pct": max(0.0, total - top) / stake * 100.0 if stake else 0.0,
        "hitRatePct": sum(hits) / len(hits) * 100.0 if hits else 0.0,
        "topReturnYen": int(round(top)),
    }


def evaluate_selected(selected, constraints):
    result = {}
    for course, spec in constraints["courses"].items():
        returns = []
        hits = []
        for race in selected:
            returned, hit = settle_race(race, race["coursePlans"][course])
            returns.append(returned)
            hits.append(hit)
        result[course] = summarize(returns, hits, spec["budgetYen"])
    return result


def combine_metrics(rows):
    races = sum(int(row["races"]) for row in rows)
    hits = sum(int(row["hits"]) for row in rows)
    stake = sum(int(row["stakeYen"]) for row in rows)
    returned = sum(int(row["returnYen"]) for row in rows)
    top = max((int(row.get("topReturnYen", 0)) for row in rows), default=0)
    return {
        "races": races,
        "hits": hits,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100.0 if stake else 0.0,
        "roiWithoutTop1Pct": max(0, returned - top) / stake * 100.0 if stake else 0.0,
        "hitRatePct": hits / races * 100.0 if races else 0.0,
        "topReturnYen": top,
    }


def development_objective(fold_results):
    aggregate = {}
    for course in TYPE_COUNTS:
        aggregate[course] = combine_metrics([fold["courses"][course] for fold in fold_results])
    fold_rois = [row["roiPct"] for fold in fold_results for row in fold["courses"].values()]
    aggregate_rois = [row["roiPct"] for row in aggregate.values()]
    return {
        "minimumAggregateCourseRoiPct": min(aggregate_rois),
        "meanAggregateCourseRoiPct": float(np.mean(aggregate_rois)),
        "q25FoldCourseRoiPct": float(np.quantile(fold_rois, 0.25)),
        "minimumFoldCourseRoiPct": min(fold_rois),
        "aggregateCourses": aggregate,
    }


def fold_races(predictions, start, end):
    return [race for race in predictions if start <= race["raceDate"] < end]


def clean_ticket(ticket):
    return {
        "code": ticket["code"],
        "betType": ticket["betType"],
        "predictedRanks": ticket["predictedRanks"],
        "stakeYen": ticket["stakeYen"],
    }


def representative_policy(selected):
    if not selected:
        return {course: [] for course in TYPE_COUNTS}
    race = selected[0]
    return {
        course: [clean_ticket(ticket) for ticket in race["coursePlans"][course]["tickets"]]
        for course in TYPE_COUNTS
    }


def main():
    constraints = load_constraints()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    rows, payouts = base_analysis.v4.load_data()
    base_races = base_analysis.v4.build_dataset(rows, payouts)
    extra_rows = base_analysis.v7.load_extra_rows()
    enriched_races = base_analysis.v7.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in enriched_races)
    months = base_analysis.v7.month_sequence(ROLLING_START_MONTH, last_month)
    rolling, ranking_audit = base_analysis.v7.rolling_predictions(enriched_races, months)
    predicted_by_month = rolling["ensemble"]
    all_predicted = [race for month in months for race in predicted_by_month[month]]

    fold_components = []
    training_audit = []
    for fold_index, (start, end) in enumerate(DEV_FOLDS):
        training = [race for race in all_predicted if race["raceDate"] < start]
        target = fold_races(all_predicted, start, end)
        models, priors, audit = fit_two_stage_models(training, RANDOM_SEED + fold_index * 1000)
        components = predict_components(target, models, priors)
        fold_components.append({"start": start, "end": end, "races": components})
        training_audit.append({
            "fold": f"{start}..{end}",
            "trainingRaces": len(training),
            "targetRaces": len(target),
            "models": audit,
        })

    candidates = []
    for model_weight in MODEL_WEIGHTS:
        for payout_bias in PAYOUT_BIASES:
            for hit_bias in HIT_BIASES:
                score_config = (model_weight, payout_bias, hit_bias)
                for allocation_power in ALLOCATION_POWERS:
                    planned_folds = [
                        attach_plans(fold["races"], constraints, score_config, allocation_power)
                        for fold in fold_components
                    ]
                    for race_count in RACE_COUNTS:
                        for race_mode in RACE_SCORE_MODES:
                            fold_results = []
                            coverage = []
                            for fold, planned in zip(fold_components, planned_folds):
                                selected, fold_coverage = select_races(planned, race_count, race_mode)
                                fold_results.append({
                                    "period": f'{fold["start"]}..{fold["end"]}',
                                    "courses": evaluate_selected(selected, constraints),
                                })
                                coverage.extend(fold_coverage)
                            objective = development_objective(fold_results)
                            candidates.append({
                                "modelWeight": model_weight,
                                "payoutBias": payout_bias,
                                "hitBias": hit_bias,
                                "allocationPower": allocation_power,
                                "racesPerVenueDay": race_count,
                                "raceScoreMode": race_mode,
                                "objective": objective,
                                "coverage": {
                                    "groups": len(coverage),
                                    "minimumSelectedRaces": min(row["selected"] for row in coverage),
                                    "maximumSelectedRaces": max(row["selected"] for row in coverage),
                                },
                                "folds": fold_results,
                            })

    candidates.sort(key=lambda row: (
        row["objective"]["minimumAggregateCourseRoiPct"],
        row["objective"]["q25FoldCourseRoiPct"],
        row["objective"]["meanAggregateCourseRoiPct"],
        row["objective"]["minimumFoldCourseRoiPct"],
    ), reverse=True)
    best = candidates[0]
    development_passed = best["objective"]["minimumAggregateCourseRoiPct"] >= float(
        constraints["promotionRules"]["completionRoiPct"]
    )

    final_result = None
    final_selected = []
    final_coverage = []
    if development_passed:
        training = [race for race in all_predicted if race["raceDate"] < FINAL_START]
        target = [race for race in all_predicted if race["raceDate"] >= FINAL_START]
        models, priors, audit = fit_two_stage_models(training, RANDOM_SEED + 9000)
        components = predict_components(target, models, priors)
        score_config = (best["modelWeight"], best["payoutBias"], best["hitBias"])
        planned = attach_plans(components, constraints, score_config, best["allocationPower"])
        final_selected, final_coverage = select_races(planned, best["racesPerVenueDay"], best["raceScoreMode"])
        final_result = {
            "coverage": final_coverage,
            "courses": evaluate_selected(final_selected, constraints),
            "modelAudit": audit,
        }

    course_summary = {}
    completion_passed = False
    if final_result is not None:
        full_pass = True
        final_pass = True
        representative = representative_policy(final_selected)
        for course in TYPE_COUNTS:
            development_rows = [fold["courses"][course] for fold in best["folds"]]
            full = combine_metrics([*development_rows, final_result["courses"][course]])
            final = final_result["courses"][course]
            minimum_coverage = min(
                int(best["coverage"]["minimumSelectedRaces"]),
                min(int(row["selected"]) for row in final_coverage),
            )
            course_summary[course] = {
                "fullHistorical": full,
                "finalHoldout": final,
                "coverage": {
                    "minimumSelectedRaces": minimum_coverage,
                    "developmentGroups": int(best["coverage"]["groups"]),
                    "finalGroups": len(final_coverage),
                },
                "policy": {
                    "representativeTickets": representative[course],
                    "ticketCount": int(constraints["courses"][course]["ticketCount"]),
                    "requiredBetTypes": constraints["courses"][course]["allowedBetTypes"],
                },
            }
            full_pass = full_pass and full["roiPct"] >= float(constraints["promotionRules"]["requireFullHistoricalRoiPct"])
            final_pass = final_pass and (
                final["races"] >= int(constraints["promotionRules"]["minimumFinalHoldoutRacesPerCourse"])
                and final["roiPct"] >= float(constraints["promotionRules"]["requireFinalHoldoutRoiPct"])
                and final["roiWithoutTop1Pct"] >= float(constraints["promotionRules"]["requireRoiWithoutTop1Pct"])
            )
        completion_passed = full_pass and final_pass

    report = {
        "generatedAt": "2026-08-07",
        "explorationId": EXPLORATION_ID,
        "productionChanged": False,
        "promotionEligible": completion_passed,
        "developmentPassedCompletionRoi": development_passed,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "liveBetGenerationRequiresOfficialCombinationOdds": True,
        "searchObjective": {
            "primary": "use chronological runner context to predict ticket hit probability and conditional payout, then maximize the minimum aggregate development ROI across all three courses",
            "completionRoiPct": 200.0,
            "minimumRacesPerVenueDay": 5,
            "singleOnlyPortfolioForbidden": True,
            "allCourseBetTypesRequired": True,
            "finalHoldoutUntouchedUntilDevelopmentPasses": True,
        },
        "period": {
            "archiveStart": min(race["raceDate"] for race in enriched_races),
            "archiveEnd": max(race["raceDate"] for race in enriched_races),
            "archiveFinishedRaces": len(enriched_races),
            "rollingPredictionStart": ROLLING_START_MONTH,
            "developmentFolds": [f"{start}..{end}" for start, end in DEV_FOLDS],
            "finalHoldout": f"{FINAL_START}..end",
        },
        "modelAudit": {
            "ranking": ranking_audit,
            "ticketModels": training_audit,
            "primitiveCount": len(PRIMITIVES),
            "candidateConfigurations": len(candidates),
            "runnerContextFeatureIndices": list(RUNNER_FEATURE_INDICES),
            "maximumTrainingRowsPerBetType": MAX_TRAIN_ROWS_PER_TYPE,
        },
        "selectedConfiguration": best,
        "topConfigurations": candidates[:20],
        "finalHoldoutEvaluated": final_result is not None,
        "courses": course_summary,
    }

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "explorationId": EXPLORATION_ID,
        "candidateConfigurations": len(candidates),
        "developmentGatePassed": development_passed,
        "completionPassed": completion_passed,
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
