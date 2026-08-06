import hashlib
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT = Path(__file__).resolve().parents[1]
V7_PATH = ROOT / "scripts" / "analyze-v7-enriched-ranking.py"
BASE_POLICY_PATH = ROOT / "scripts" / "analyze-v6-course-policy.py"
CONSTRAINTS_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
OUTPUT = ROOT / "v13-constrained-roi-200-search.json"
V14_OUTPUT = ROOT / "v14-historical-roi200-search.json"
UPCOMING_OUTPUT = ROOT / "v14-upcoming-predictions.json"

MODEL_VERSION = "v14-historical-payout-value-roi200"
DATA_START_MONTH = "2024-11"
DEV_FOLDS = (
    ("2025-05-01", "2025-08-01"),
    ("2025-08-01", "2025-11-01"),
    ("2025-11-01", "2026-02-01"),
    ("2026-02-01", "2026-05-01"),
)
FINAL_START = "2026-05-01"
TARGET_CAP_MULTIPLE = 250.0
MAX_TRAIN_ROWS_PER_TYPE = 140_000
RANDOM_SEED = 2026080708
RACE_COUNTS = (5, 7, 9, 12)
ALLOCATION_POWERS = (0.7, 1.0, 1.4, 2.0, 3.0)
MODEL_PRIOR_WEIGHTS = (0.55, 0.70, 0.85)
RACE_SCORE_MODES = ("minimum", "light", "mean", "lower_mean")
MAX_TICKET_SHARE = {"ライト": 0.50, "スタンダード": 0.40, "プレミアム": 0.35}
TYPE_COUNTS = {
    "ライト": {"単勝": 1, "ワイド": 3, "馬連": 2},
    "スタンダード": {"単勝": 1, "ワイド": 4, "馬連": 2, "馬単": 5, "3連複": 3},
    "プレミアム": {"単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 3, "3連複": 3, "3連単": 5},
}
BET_TYPES = tuple({bet_type for counts in TYPE_COUNTS.values() for bet_type in counts})
VENUES = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v7 = load_module("v14_enriched", V7_PATH)
base = load_module("v14_course_base", BASE_POLICY_PATH)
v4 = v7.v4


def num(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def verify_constraints():
    constraints = json.loads(CONSTRAINTS_PATH.read_text(encoding="utf-8"))
    rules = constraints["immutableProjectRules"]
    promotion = constraints["promotionRules"]
    if int(rules["minimumRacesPerVenueDay"]) != 5 or rules["mayDecreaseBelowMinimum"]:
        raise RuntimeError("V14_MINIMUM_RACE_RULE_CHANGED")
    if not rules["singleOnlyPortfolioForbidden"] or rules["syntheticOddsForbidden"] is not True:
        raise RuntimeError("V14_BET_OR_ODDS_RULE_CHANGED")
    if float(promotion["targetRoiPct"]) != 200.0:
        raise RuntimeError("V14_TARGET_ROI_CHANGED")
    for course, counts in TYPE_COUNTS.items():
        spec = constraints["courses"][course]
        if sum(counts.values()) != int(spec["ticketCount"]):
            raise RuntimeError(f"V14_TICKET_COUNT_CHANGED:{course}")
        if set(counts) != set(spec["allowedBetTypes"]):
            raise RuntimeError(f"V14_BET_TYPES_CHANGED:{course}")
    return constraints


def distance_band(value):
    distance = int(num(value))
    if distance < 1400:
        return 0
    if distance < 1800:
        return 1
    if distance < 2200:
        return 2
    return 3


def race_base_features(race):
    runners = list(race.get("runners") or [])
    probabilities = np.asarray([max(1e-9, num(row.get("probability"))) for row in runners], dtype=float)
    if probabilities.size:
        probabilities /= probabilities.sum()
    markets = np.asarray([max(1e-9, num(row.get("market"))) for row in runners], dtype=float)
    if markets.size:
        markets /= markets.sum()
    top_probs = list(probabilities[:8]) + [0.0] * max(0, 8 - len(probabilities))
    top_markets = list(markets[:8]) + [0.0] * max(0, 8 - len(markets))
    venue = str(race.get("venue") or "")
    surface = str(race.get("surface") or "")
    class_level = num(race.get("classLevel"))
    probability_gap = top_probs[0] - top_probs[1] if len(top_probs) >= 2 else 0.0
    entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12)))) if probabilities.size else 0.0
    market_entropy = -float(np.sum(markets * np.log(np.maximum(markets, 1e-12)))) if markets.size else 0.0
    features = [
        len(runners) / 18.0,
        num(race.get("raceNo")) / 12.0,
        num(race.get("distanceM")) / 3600.0,
        distance_band(race.get("distanceM")) / 3.0,
        class_level / 7.0,
        int(surface == "芝"),
        int(surface == "ダート"),
        int("重" in str(race.get("trackCondition") or "")),
        int("不" in str(race.get("trackCondition") or "")),
        top_probs[0],
        probability_gap,
        sum(top_probs[:3]),
        entropy / max(1e-9, math.log(max(2, len(runners)))),
        top_markets[0],
        sum(top_markets[:3]),
        market_entropy / max(1e-9, math.log(max(2, len(runners)))),
        sum(abs(a - b) for a, b in zip(top_probs, top_markets)),
        max((a / max(1e-9, b) for a, b in zip(top_probs[:6], top_markets[:6])), default=1.0) / 8.0,
    ]
    features.extend(top_probs)
    features.extend(top_markets)
    features.extend(int(venue == value) for value in VENUES)
    return features


def primitive_features(race, primitive):
    code, bet_type, ranks = primitive
    runners = list(race.get("runners") or [])
    selected = [runners[rank - 1] if 0 < rank <= len(runners) else {} for rank in ranks]
    probs = [max(1e-9, num(row.get("probability"))) for row in selected]
    markets = [max(1e-9, num(row.get("market"))) for row in selected]
    edges = [p / max(1e-9, m) for p, m in zip(probs, markets)]
    padded_ranks = list(ranks) + [0] * (3 - len(ranks))
    padded_probs = probs + [0.0] * (3 - len(probs))
    padded_markets = markets + [0.0] * (3 - len(markets))
    padded_edges = edges + [0.0] * (3 - len(edges))
    type_one_hot = [int(bet_type == value) for value in BET_TYPES]
    ordered = int(bet_type in {"馬単", "3連単"})
    return race_base_features(race) + type_one_hot + [
        len(ranks) / 3.0,
        padded_ranks[0] / 6.0,
        padded_ranks[1] / 6.0,
        padded_ranks[2] / 6.0,
        sum(ranks) / 15.0,
        max(ranks) / 6.0,
        ordered,
        float(np.prod(probs)) if probs else 0.0,
        sum(probs),
        max(probs) if probs else 0.0,
        min(probs) if probs else 0.0,
        float(np.prod(markets)) if markets else 0.0,
        sum(markets),
        float(np.prod(edges)) if edges else 0.0,
        sum(edges) / max(1, len(edges)),
    ] + padded_probs + padded_markets + padded_edges


def make_training_rows(races, primitives_by_type, rng):
    output = {}
    priors = {}
    for bet_type, primitives in primitives_by_type.items():
        x = []
        y = []
        code_totals = defaultdict(float)
        code_counts = defaultdict(int)
        for race in races:
            for primitive in primitives:
                payout = base.primitive_payout(race, primitive) / 100.0
                target = min(TARGET_CAP_MULTIPLE, max(0.0, payout))
                x.append(primitive_features(race, primitive))
                y.append(target)
                code_totals[primitive[0]] += target
                code_counts[primitive[0]] += 1
        if len(y) > MAX_TRAIN_ROWS_PER_TYPE:
            indexes = np.asarray(rng.choice(len(y), MAX_TRAIN_ROWS_PER_TYPE, replace=False), dtype=int)
            x_array = np.asarray(x, dtype=np.float32)[indexes]
            y_array = np.asarray(y, dtype=np.float32)[indexes]
        else:
            x_array = np.asarray(x, dtype=np.float32)
            y_array = np.asarray(y, dtype=np.float32)
        output[bet_type] = (x_array, y_array)
        overall = float(np.mean(y_array)) if len(y_array) else 0.0
        priors[bet_type] = {
            primitive[0]: (code_totals[primitive[0]] + overall * 80.0) / (code_counts[primitive[0]] + 80.0)
            for primitive in primitives
        }
    return output, priors


def fit_value_models(races, primitives_by_type, seed):
    rng = np.random.default_rng(seed)
    training, priors = make_training_rows(races, primitives_by_type, rng)
    models = {}
    audit = {}
    for index, bet_type in enumerate(BET_TYPES):
        x, y = training[bet_type]
        if len(y) < 500:
            raise RuntimeError(f"V14_TRAINING_TOO_SMALL:{bet_type}:{len(y)}")
        model = HistGradientBoostingRegressor(
            loss="poisson",
            max_leaf_nodes=31,
            learning_rate=0.045,
            max_iter=120,
            l2_regularization=12.0,
            min_samples_leaf=80,
            max_bins=63,
            random_state=seed + index,
        )
        model.fit(x, y)
        models[bet_type] = model
        audit[bet_type] = {
            "rows": len(y),
            "positiveRows": int(np.sum(y > 0)),
            "meanCappedReturnMultiple": float(np.mean(y)),
        }
    return models, priors, audit


def predict_scores(races, models, priors, primitives_by_type, model_weight):
    rows = []
    for race in races:
        scores = {}
        for bet_type, primitives in primitives_by_type.items():
            x = np.asarray([primitive_features(race, primitive) for primitive in primitives], dtype=np.float32)
            predicted = np.maximum(0.0, models[bet_type].predict(x))
            for primitive, value in zip(primitives, predicted):
                prior = priors[bet_type][primitive[0]]
                score = model_weight * float(value) + (1.0 - model_weight) * float(prior)
                scores[primitive[0]] = max(0.0, score)
        item = dict(race)
        item["primitiveScores"] = scores
        rows.append(item)
    return rows


def allocate_units(selected, budget, power, max_share):
    total_units = int(budget) // 100
    units = [1] * len(selected)
    max_units = max(1, int(math.floor(total_units * max_share)))
    remaining = total_units - len(units)
    raw = np.asarray([max(1e-6, score) ** power for _, score in selected], dtype=float)
    while remaining > 0:
        candidates = [i for i in range(len(units)) if units[i] < max_units]
        if not candidates:
            candidates = list(range(len(units)))
        index = max(candidates, key=lambda i: raw[i] / (units[i] ** 0.65))
        units[index] += 1
        remaining -= 1
    return units


def build_course_plan(race, course, constraints, power):
    scores = race["primitiveScores"]
    selected = []
    for bet_type, count in TYPE_COUNTS[course].items():
        pool = [primitive for primitive in base.PRIMITIVES if primitive[1] == bet_type and primitive[0] in scores]
        pool.sort(key=lambda primitive: (scores[primitive[0]], -sum(primitive[2])), reverse=True)
        selected.extend((primitive, scores[primitive[0]]) for primitive in pool[:count])
    budget = int(constraints["courses"][course]["budgetYen"])
    units = allocate_units(selected, budget, power, MAX_TICKET_SHARE[course])
    tickets = []
    predicted_return = 0.0
    for (primitive, score), unit in zip(selected, units):
        tickets.append({
            "code": primitive[0],
            "betType": primitive[1],
            "predictedRanks": list(primitive[2]),
            "stakeYen": int(unit * 100),
            "predictedReturnMultiple": float(score),
        })
        predicted_return += score * unit * 100.0
    return {
        "budgetYen": budget,
        "predictedRoiPct": predicted_return / budget * 100.0,
        "tickets": tickets,
    }


def attach_plans(races, constraints, power):
    output = []
    for race in races:
        item = dict(race)
        plans = {course: build_course_plan(race, course, constraints, power) for course in constraints["courses"]}
        item["coursePlans"] = plans
        output.append(item)
    return output


def race_score(race, mode):
    values = [race["coursePlans"][course]["predictedRoiPct"] for course in ("ライト", "スタンダード", "プレミアム")]
    if mode == "minimum":
        return min(values)
    if mode == "light":
        return values[0]
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
        group.sort(key=lambda race: (-race_score(race, mode), int(num(race.get("raceNo")))))
        picked = group[:take]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    if not coverage or min(row["selected"] for row in coverage) < 5:
        raise RuntimeError("V14_SELECTED_BELOW_FIVE")
    return selected, coverage


def settle_race(race, plan):
    total = 0.0
    hit = False
    for ticket in plan["tickets"]:
        primitive = next(row for row in base.PRIMITIVES if row[0] == ticket["code"])
        payout = base.primitive_payout(race, primitive)
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
        "stakeYen": stake,
        "returnYen": int(round(total)),
        "profitYen": int(round(total - stake)),
        "roiPct": total / stake * 100.0 if stake else 0.0,
        "roiWithoutTop1Pct": max(0.0, total - top) / stake * 100.0 if stake else 0.0,
        "hitRatePct": sum(hits) / len(hits) * 100.0 if hits else 0.0,
        "maxSingleReturnShare": top / total if total > 0 else 1.0,
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


def fold_races(predictions, start, end):
    return [race for race in predictions if start <= race["raceDate"] < end]


def score_config(folds):
    all_rows = [metrics for fold in folds for metrics in fold["courses"].values()]
    minimum = min(row["roiPct"] for row in all_rows)
    trimmed = min(row["roiWithoutTop1Pct"] for row in all_rows)
    mean = float(np.mean([row["roiPct"] for row in all_rows]))
    hit = min(row["hitRatePct"] for row in all_rows)
    return (minimum, trimmed, mean, hit)


def clean_plan(plan):
    return {
        "budgetYen": plan["budgetYen"],
        "predictedRoiPct": round(plan["predictedRoiPct"], 4),
        "tickets": [
            {
                "code": row["code"],
                "betType": row["betType"],
                "predictedRanks": row["predictedRanks"],
                "stakeYen": row["stakeYen"],
                "predictedReturnMultiple": round(row["predictedReturnMultiple"], 6),
            }
            for row in plan["tickets"]
        ],
    }


def rank_to_horses(race, ticket):
    runners = race.get("runners") or []
    horses = []
    for rank in ticket["predictedRanks"]:
        if 0 < rank <= len(runners):
            runner = runners[rank - 1]
            horses.append({
                "horseNo": int(num(runner.get("horseNo"))),
                "horseName": str(runner.get("horseName") or ""),
                "predictedRank": rank,
            })
    return horses


def future_predictions(best, constraints, models, priors):
    try:
        from production_base_loader import load_production_base
        production = load_production_base("v14_future_base", ROOT / "scripts" / "publish-nonlinear-v4-production.py")
        finished_rows = production.load_finished_rows()
        training_races, stores = production.build_training(finished_rows)
        ranking_model = production.fit_model(training_races)
        future_rows = production.load_future_rows()
        future_races = production.build_future(future_rows, stores)
        predicted = production.attach_predictions(ranking_model, future_races)
    except Exception as error:
        return {"generated": False, "error": f"{type(error).__name__}:{error}", "races": []}
    scored = predict_scores(predicted, models, priors, {t: [p for p in base.PRIMITIVES if p[1] == t] for t in BET_TYPES}, best["modelWeight"])
    planned = attach_plans(scored, constraints, best["allocationPower"])
    selected, coverage = select_races(planned, best["racesPerVenueDay"], best["raceScoreMode"])
    rows = []
    for race in selected:
        courses = {}
        for course, plan in race["coursePlans"].items():
            clean = clean_plan(plan)
            for ticket in clean["tickets"]:
                ticket["horses"] = rank_to_horses(race, ticket)
            courses[course] = clean
        rows.append({
            "raceId": race.get("raceId"),
            "raceDate": race.get("raceDate"),
            "venue": race.get("venue"),
            "raceNo": race.get("raceNo"),
            "raceName": race.get("raceName"),
            "startTimeUtc": race.get("startTimeUtc"),
            "courses": courses,
        })
    return {"generated": True, "trainingRaces": len(training_races), "futureRaces": len(predicted), "selectedRaces": len(rows), "coverage": coverage, "races": rows}


def main():
    constraints = verify_constraints()
    rows, payouts = v4.load_data()
    base_races = v4.build_dataset(rows, payouts)
    extra_rows = v7.load_extra_rows()
    enriched_races = v7.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in enriched_races)
    months = v7.month_sequence(DATA_START_MONTH, last_month)
    rolling, ranking_audit = v7.rolling_predictions(enriched_races, months)
    predicted_by_month = rolling["ensemble"]
    all_predicted = [race for month in months for race in predicted_by_month[month]]
    primitives_by_type = {bet_type: [primitive for primitive in base.PRIMITIVES if primitive[1] == bet_type] for bet_type in BET_TYPES}

    fold_predictions = []
    training_audit = []
    for fold_index, (start, end) in enumerate(DEV_FOLDS):
        training = [race for race in all_predicted if race["raceDate"] < start]
        target = fold_races(all_predicted, start, end)
        models, priors, audit = fit_value_models(training, primitives_by_type, RANDOM_SEED + fold_index * 1000)
        by_weight = {
            weight: predict_scores(target, models, priors, primitives_by_type, weight)
            for weight in MODEL_PRIOR_WEIGHTS
        }
        fold_predictions.append({"start": start, "end": end, "targets": by_weight})
        training_audit.append({"fold": f"{start}..{end}", "trainingRaces": len(training), "targetRaces": len(target), "models": audit})

    candidates = []
    for model_weight in MODEL_PRIOR_WEIGHTS:
        for power in ALLOCATION_POWERS:
            fold_plans = [attach_plans(fold["targets"][model_weight], constraints, power) for fold in fold_predictions]
            for count in RACE_COUNTS:
                for mode in RACE_SCORE_MODES:
                    fold_results = []
                    coverage = []
                    for fold, planned in zip(fold_predictions, fold_plans):
                        selected, fold_coverage = select_races(planned, count, mode)
                        fold_results.append({"period": f'{fold["start"]}..{fold["end"]}', "courses": evaluate_selected(selected, constraints)})
                        coverage.extend(fold_coverage)
                    objective = score_config(fold_results)
                    candidates.append({
                        "modelWeight": model_weight,
                        "allocationPower": power,
                        "racesPerVenueDay": count,
                        "raceScoreMode": mode,
                        "objective": {
                            "minimumFoldCourseRoiPct": objective[0],
                            "minimumFoldCourseRoiWithoutTop1Pct": objective[1],
                            "meanFoldCourseRoiPct": objective[2],
                            "minimumFoldCourseHitRatePct": objective[3],
                        },
                        "coverage": {
                            "groups": len(coverage),
                            "minimumSelectedRaces": min(row["selected"] for row in coverage),
                            "maximumSelectedRaces": max(row["selected"] for row in coverage),
                        },
                        "folds": fold_results,
                    })
    candidates.sort(key=lambda row: (
        row["objective"]["minimumFoldCourseRoiPct"],
        row["objective"]["minimumFoldCourseRoiWithoutTop1Pct"],
        row["objective"]["meanFoldCourseRoiPct"],
    ), reverse=True)
    best = candidates[0]
    development_passed = best["objective"]["minimumFoldCourseRoiPct"] >= 200.0

    final_result = None
    if development_passed:
        training = [race for race in all_predicted if race["raceDate"] < FINAL_START]
        target = [race for race in all_predicted if race["raceDate"] >= FINAL_START]
        final_models, final_priors, final_audit = fit_value_models(training, primitives_by_type, RANDOM_SEED + 9000)
        scored = predict_scores(target, final_models, final_priors, primitives_by_type, best["modelWeight"])
        planned = attach_plans(scored, constraints, best["allocationPower"])
        selected, final_coverage = select_races(planned, best["racesPerVenueDay"], best["raceScoreMode"])
        metrics = evaluate_selected(selected, constraints)
        final_result = {"coverage": final_coverage, "courses": metrics, "modelAudit": final_audit}

    current_training = list(all_predicted)
    current_models, current_priors, current_audit = fit_value_models(current_training, primitives_by_type, RANDOM_SEED + 12000)
    upcoming = future_predictions(best, constraints, current_models, current_priors)
    UPCOMING_OUTPUT.write_text(json.dumps({
        "modelVersion": MODEL_VERSION,
        "historicalGatePassed": development_passed,
        "bestHistoricalObjective": best["objective"],
        **upcoming,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    final_passed = bool(final_result) and all(
        row["roiPct"] >= 200.0 and row["roiWithoutTop1Pct"] >= 100.0 and row["races"] >= 100
        for row in final_result["courses"].values()
    )
    report = {
        "generatedAt": "2026-08-07",
        "modelVersion": MODEL_VERSION,
        "productionChanged": False,
        "promotionEligible": final_passed,
        "developmentPassedRoi200Objective": development_passed,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "finalHoldoutEvaluated": final_result is not None,
        "searchObjective": {
            "primary": "predict capped payout value from past races and maximize the minimum ROI across every development fold and course",
            "targetRoiPct": 200.0,
            "minimumRacesPerVenueDay": 5,
            "singleOnlyPortfolioForbidden": True,
            "allCourseBetTypesRequired": True,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in enriched_races),
            "dataEnd": max(race["raceDate"] for race in enriched_races),
            "finishedRaces": len(enriched_races),
            "developmentFolds": [f"{a}..{b}" for a, b in DEV_FOLDS],
            "finalHoldout": f"{FINAL_START}..end",
        },
        "modelAudit": {
            "ranking": ranking_audit,
            "valueModels": training_audit,
            "current": current_audit,
            "targetCapMultiple": TARGET_CAP_MULTIPLE,
            "candidateConfigurations": len(candidates),
        },
        "selectedConfiguration": best,
        "topConfigurations": candidates[:10],
        "finalHoldout": final_result,
        "upcomingPredictions": {
            "generated": upcoming.get("generated", False),
            "futureRaces": upcoming.get("futureRaces", 0),
            "selectedRaces": upcoming.get("selectedRaces", 0),
            "file": "v14-upcoming-predictions.json",
        },
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    OUTPUT.write_text(encoded, encoding="utf-8")
    V14_OUTPUT.write_text(encoded, encoding="utf-8")
    print(json.dumps({
        "modelVersion": MODEL_VERSION,
        "finishedRaces": len(enriched_races),
        "candidateConfigurations": len(candidates),
        "bestMinimumDevelopmentRoiPct": best["objective"]["minimumFoldCourseRoiPct"],
        "developmentPassed": development_passed,
        "finalPassed": final_passed,
        "upcomingGenerated": upcoming.get("generated", False),
        "upcomingSelectedRaces": upcoming.get("selectedRaces", 0),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
