import importlib.util
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
rolling = load_module("v6_rolling", ROOT / "scripts" / "analyze-v6-rolling-oos.py")
base = rolling.base

COURSES = tuple(base.COURSE_BUDGETS)
TRAIN_MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04")
DEVELOPMENT_MONTHS = ("2026-05", "2026-06", "2026-07")
REQUIRED_HIT = 36.8
BET_TYPES = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")
BET_TYPE_INDEX = {name: index for index, name in enumerate(BET_TYPES)}
PAYOUT_RATIO = {"単勝": 1.00, "ワイド": 0.77, "馬連": 0.77, "馬単": 0.75, "3連複": 0.75, "3連単": 0.72}
RELIABILITY = {"単勝": 1.00, "ワイド": 0.98, "馬連": 0.96, "馬単": 0.93, "3連複": 0.91, "3連単": 0.87}

ALPHAS = (0.25, 0.50, 0.75)
MIN_EVS = (100.0, 120.0, 150.0, 200.0)
TICKET_LIMITS = (1, 2, 3, 5)
MAX_ODDS = (20.0, 80.0, 300.0, 2500.0)
MIN_SPEND_FRACTIONS = (0.25, 0.50)
EDGE_SCALES = (0.50, 1.50)
ALLOCATION_POWERS = (0.70, 1.50)


def in_month(race, month):
    return race["raceDate"].startswith(month)


def ordered_probability(ranks, weights):
    remaining = float(np.sum(weights))
    probability = 1.0
    used = set()
    for rank in ranks:
        index = rank - 1
        if index < 0 or index >= len(weights) or index in used or remaining <= 0:
            return 0.0
        value = float(weights[index])
        if value <= 0:
            return 0.0
        probability *= value / remaining
        remaining -= value
        used.add(index)
    return max(0.0, min(1.0, probability))


def unordered_two(ranks, weights):
    first, second = ranks
    return min(1.0, ordered_probability((first, second), weights) + ordered_probability((second, first), weights))


def unordered_three(ranks, weights):
    return min(1.0, sum(ordered_probability(order, weights) for order in itertools.permutations(ranks)))


def wide_probability(ranks, weights):
    first, second = ranks
    total = 0.0
    for third in range(1, len(weights) + 1):
        if third in ranks:
            continue
        total += unordered_three((first, second, third), weights)
    return min(1.0, total)


def event_probability(bet_type, ranks, weights):
    if bet_type == "単勝":
        return float(weights[ranks[0] - 1]) if ranks[0] <= len(weights) else 0.0
    if bet_type == "ワイド":
        return wide_probability(ranks, weights)
    if bet_type == "馬連":
        return unordered_two(ranks, weights)
    if bet_type == "馬単":
        return ordered_probability(ranks, weights)
    if bet_type == "3連複":
        return unordered_three(ranks, weights)
    return ordered_probability(ranks, weights)


def primitive_feature(race, primitive):
    _, bet_type, ranks = primitive
    if any(rank > len(race["runners"]) for rank in ranks):
        return None
    model_weights = np.asarray([runner["probability"] for runner in race["runners"]], dtype=np.float64)
    market_weights = np.asarray([runner["market"] for runner in race["runners"]], dtype=np.float64)
    model_probability = event_probability(bet_type, ranks, model_weights)
    market_probability = event_probability(bet_type, ranks, market_weights)
    if model_probability <= 0 or market_probability <= 0:
        return None

    if bet_type == "単勝":
        assumed_odds = float(race["runners"][ranks[0] - 1].get("winOdds") or 0.0)
        if assumed_odds <= 1.0:
            return None
    else:
        assumed_odds = PAYOUT_RATIO[bet_type] / market_probability
    assumed_odds = max(1.1, min(2500.0, math.floor(assumed_odds * 10.0) / 10.0))

    rank_values = list(ranks) + [0, 0, 0]
    involved = [race["runners"][rank - 1] for rank in ranks]
    involved_model = [float(runner["probability"]) for runner in involved]
    involved_market = [float(runner["market"]) for runner in involved]
    involved_edge = [float(runner.get("edge") or 0.0) for runner in involved]
    type_flags = [1.0 if bet_type == name else 0.0 for name in BET_TYPES]
    features = [
        math.log(max(1e-9, model_probability)),
        math.log(max(1e-9, market_probability)),
        math.log(max(1.1, assumed_odds)),
        math.log(max(1e-6, model_probability / market_probability)),
        model_probability,
        market_probability,
        float(race["topProbability"]),
        float(race["probabilityGap"]),
        float(race["top3Concentration"]),
        math.log(max(1.0, float(race["maxEdge"]))),
        float(race["disagreement"]),
        float(race["entropy"]),
        len(race["runners"]) / 18.0,
        rank_values[0] / 5.0,
        rank_values[1] / 5.0,
        rank_values[2] / 5.0,
        sum(ranks) / 15.0,
        float(1 in ranks),
        float(np.mean(involved_model)),
        float(np.min(involved_model)),
        float(np.mean(involved_market)),
        float(np.min(involved_market)),
        float(np.mean(involved_edge)),
        float(np.max(involved_edge)),
        *type_flags,
    ]
    return {
        "features": features,
        "betType": bet_type,
        "ranks": tuple(ranks),
        "modelProbability": model_probability,
        "marketProbability": market_probability,
        "assumedOdds": assumed_odds,
        "payoutYen": float(base.primitive_payout(race, primitive)),
    }


def build_ticket_rows(races):
    rows = []
    for race_index, race in enumerate(races):
        for primitive_index, primitive in enumerate(base.PRIMITIVES):
            built = primitive_feature(race, primitive)
            if built is None:
                continue
            built["raceIndex"] = race_index
            built["primitiveIndex"] = primitive_index
            rows.append(built)
    return rows


def fit_ticket_model(training_races):
    rows = build_ticket_rows(training_races)
    if not rows:
        raise RuntimeError("V6_6_EMPTY_TICKET_TRAINING")
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray([int(row["payoutYen"] > 0) for row in rows], dtype=np.int8)
    sample_weight = np.asarray([
        1.0 / max(1, sum(1 for candidate in rows if candidate["raceIndex"] == row["raceIndex"]))
        for row in rows
    ], dtype=np.float64)
    positive_rate = float(y.mean())
    positive_boost = min(4.0, max(1.0, (1.0 - positive_rate) / max(0.01, positive_rate) * 0.15))
    sample_weight[y == 1] *= positive_boost
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=31,
        learning_rate=0.035,
        max_iter=220,
        l2_regularization=5.0,
        min_samples_leaf=70,
        random_state=2026080620,
    )
    model.fit(x, y, sample_weight=sample_weight)
    return model, {"ticketRows": len(rows), "positiveRatePct": positive_rate * 100, "positiveBoost": positive_boost}


def scored_races(model, races, alpha):
    result = []
    for race in races:
        candidates = []
        for primitive in base.PRIMITIVES:
            row = primitive_feature(race, primitive)
            if row is None:
                continue
            learned = float(model.predict_proba(np.asarray([row["features"]], dtype=np.float64))[0, 1])
            probability = (1.0 - alpha) * row["modelProbability"] + alpha * learned
            probability = max(0.000001, min(0.999999, probability))
            expected_value = probability * row["assumedOdds"] * 100.0 * RELIABILITY[row["betType"]]
            item = dict(row)
            item["learnedProbability"] = learned
            item["hitProbability"] = probability
            item["expectedValuePct"] = expected_value
            candidates.append(item)
        copied = dict(race)
        copied["ticketCandidates"] = candidates
        result.append(copied)
    return result


def allocate_units(candidates, total_units, power):
    if not candidates or total_units < len(candidates):
        return []
    stakes = [1 for _ in candidates]
    remaining = total_units - len(candidates)
    raw = np.asarray([
        max(0.01, candidate["expectedValuePct"] - 100.0) ** power
        * max(0.05, candidate["hitProbability"]) ** 0.25
        for candidate in candidates
    ], dtype=np.float64)
    raw /= raw.sum()
    exact = raw * remaining
    extra = np.floor(exact).astype(int)
    stakes = [value + int(addition) for value, addition in zip(stakes, extra)]
    leftover = remaining - int(extra.sum())
    order = np.argsort(-(exact - extra))
    for position in order[:leftover]:
        stakes[int(position)] += 1
    return stakes


def evaluate_config(races, course, config):
    allowed_types = base.COURSE_ALLOWED_TYPES[course]
    grouped = defaultdict(list)
    for race in races:
        eligible = [
            candidate for candidate in race["ticketCandidates"]
            if candidate["betType"] in allowed_types
            and candidate["assumedOdds"] <= config["maxOdds"]
            and candidate["expectedValuePct"] >= config["minEv"]
        ]
        eligible.sort(key=lambda row: (row["expectedValuePct"], row["hitProbability"]), reverse=True)
        if eligible:
            top = eligible[: config["ticketLimit"]]
            race_score = max(row["expectedValuePct"] for row in top) + np.mean([row["expectedValuePct"] for row in top]) * 0.35
            copied = dict(race)
            copied["eligibleTickets"] = top
            copied["selectionScore"] = float(race_score)
            grouped[(race["raceDate"], race["venue"])].append(copied)

    selected = []
    for group in grouped.values():
        if len(group) < 5:
            return None
        group.sort(key=lambda race: (-race["selectionScore"], race["raceNo"]))
        selected.extend(group[:5])
    expected_groups = len({(race["raceDate"], race["venue"]) for race in races if len([r for r in races if r["raceDate"] == race["raceDate"] and r["venue"] == race["venue"]]) >= 5})
    if len(selected) != expected_groups * 5:
        return None

    budget_units = base.COURSE_BUDGETS[course] // 100
    stake = returned = hit_races = 0
    single_returns = []
    monthly = defaultdict(lambda: {"races": 0, "stake": 0, "return": 0, "hits": 0})
    by_day = defaultdict(lambda: {"races": 0, "stake": 0, "return": 0, "hits": 0})
    for race in selected:
        tickets = race["eligibleTickets"][: config["ticketLimit"]]
        maximum_ev = max(ticket["expectedValuePct"] for ticket in tickets)
        edge_strength = max(0.0, maximum_ev / 100.0 - 1.0)
        fraction = min(1.0, max(config["minSpendFraction"], config["minSpendFraction"] + edge_strength / config["edgeScale"]))
        total_units = max(len(tickets), int(round(budget_units * fraction)))
        total_units = min(budget_units, total_units)
        units = allocate_units(tickets, total_units, config["allocationPower"])
        race_return = 0.0
        race_stake = total_units * 100
        for ticket, ticket_units in zip(tickets, units):
            value = ticket["payoutYen"] * ticket_units
            race_return += value
            single_returns.append(value)
        race_hit = int(race_return > 0)
        stake += race_stake
        returned += race_return
        hit_races += race_hit
        month = race["raceDate"][:7]
        monthly[month]["races"] += 1
        monthly[month]["stake"] += race_stake
        monthly[month]["return"] += race_return
        monthly[month]["hits"] += race_hit
        day = race["raceDate"]
        by_day[day]["races"] += 1
        by_day[day]["stake"] += race_stake
        by_day[day]["return"] += race_return
        by_day[day]["hits"] += race_hit

    monthly_metrics = {}
    for month, row in sorted(monthly.items()):
        monthly_metrics[month] = {
            "races": row["races"],
            "stakeYen": int(row["stake"]),
            "returnYen": int(round(row["return"])),
            "roiPct": row["return"] / row["stake"] * 100 if row["stake"] else 0.0,
            "hitRatePct": row["hits"] / row["races"] * 100 if row["races"] else 0.0,
        }
    by_day_metrics = {}
    for day, row in sorted(by_day.items()):
        by_day_metrics[day] = {
            "races": row["races"],
            "stakeYen": int(row["stake"]),
            "returnYen": int(round(row["return"])),
            "roiPct": row["return"] / row["stake"] * 100 if row["stake"] else 0.0,
            "hitRatePct": row["hits"] / row["races"] * 100 if row["races"] else 0.0,
        }
    rois = [row["roiPct"] for row in monthly_metrics.values()]
    hits = [row["hitRatePct"] for row in monthly_metrics.values()]
    total_roi = returned / stake * 100 if stake else 0.0
    total_hit = hit_races / len(selected) * 100 if selected else 0.0
    q25_roi = float(np.quantile(rois, 0.25)) if rois else 0.0
    median_roi = float(np.median(rois)) if rois else 0.0
    minimum_roi = min(rois) if rois else 0.0
    minimum_hit = min(hits) if hits else 0.0
    max_single_share = max(single_returns) / returned if returned > 0 and single_returns else 1.0
    winning_months = sum(value >= 100.0 for value in rois)
    score = (
        q25_roi * 0.38
        + median_roi * 0.22
        + total_roi * 0.18
        + total_hit * 0.17
        + minimum_hit * 0.05
        - max(0.0, REQUIRED_HIT - total_hit) * 4.5
        - max(0.0, 2.0 - winning_months) * 30.0
        - max(0.0, max_single_share - 0.35) * 250.0
        - max(0.0, 65.0 - minimum_roi) * 1.5
    )
    return {
        "selectedRaces": len(selected),
        "stakeYen": int(stake),
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": total_roi,
        "hitRatePct": total_hit,
        "q25MonthlyRoiPct": q25_roi,
        "medianMonthlyRoiPct": median_roi,
        "minimumMonthlyRoiPct": minimum_roi,
        "minimumMonthlyHitRatePct": minimum_hit,
        "winningMonths": winning_months,
        "maxSingleReturnShare": max_single_share,
        "monthly": monthly_metrics,
        "byDay": by_day_metrics,
        "score": score,
    }


def search_course(model, development_races, course):
    best = None
    for alpha in ALPHAS:
        scored = scored_races(model, development_races, alpha)
        for min_ev in MIN_EVS:
            for ticket_limit in TICKET_LIMITS:
                for max_odds in MAX_ODDS:
                    for min_fraction in MIN_SPEND_FRACTIONS:
                        for edge_scale in EDGE_SCALES:
                            for power in ALLOCATION_POWERS:
                                config = {
                                    "alpha": alpha,
                                    "minEv": min_ev,
                                    "ticketLimit": ticket_limit,
                                    "maxOdds": max_odds,
                                    "minSpendFraction": min_fraction,
                                    "edgeScale": edge_scale,
                                    "allocationPower": power,
                                }
                                result = evaluate_config(scored, course, config)
                                if result is None:
                                    continue
                                row = {"config": config, "development": result}
                                if best is None or result["score"] > best["development"]["score"]:
                                    best = row
    if best is None:
        raise RuntimeError(f"V6_6_NO_CONFIG:{course}")
    return best


def clean_result(row):
    cleaned = dict(row)
    for key in ("roiPct", "hitRatePct", "q25MonthlyRoiPct", "medianMonthlyRoiPct", "minimumMonthlyRoiPct", "minimumMonthlyHitRatePct", "maxSingleReturnShare", "score"):
        if key in cleaned:
            cleaned[key] = round(float(cleaned[key]), 4)
    return cleaned


def main():
    rows, payouts = base.v6.v4.load_data()
    races = base.v6.v4.build_dataset(rows, payouts)
    predictions = rolling.rolling_predictions(races)
    training_races = [race for month in TRAIN_MONTHS for race in predictions[month]]
    development_races = [race for month in DEVELOPMENT_MONTHS for race in predictions[month]]
    model, training_summary = fit_ticket_model(training_races)

    august_raw = [race for race in races if "2026-08-01" <= race["raceDate"] <= "2026-08-02"]
    august_train = [race for race in races if race["raceDate"] < "2026-08-01"]
    august_rank_model = base.v6.fit_pairwise(august_train, rolling.MODEL_CONFIG)
    august_races = base.v6.attach_pairwise(august_rank_model, august_raw, rolling.BLEND, rolling.TEMPERATURE)

    courses = {}
    for course in COURSES:
        winner = search_course(model, development_races, course)
        august_scored = scored_races(model, august_races, winner["config"]["alpha"])
        august_result = evaluate_config(august_scored, course, winner["config"])
        if august_result is None:
            raise RuntimeError(f"V6_6_AUGUST_CONFIG_INVALID:{course}")
        courses[course] = {
            "config": winner["config"],
            "development": clean_result(winner["development"]),
            "august": clean_result(august_result),
        }

    pass_100 = all(row["august"]["roiPct"] >= 100.0 and row["august"]["hitRatePct"] >= REQUIRED_HIT for row in courses.values())
    pass_200 = all(row["august"]["roiPct"] >= 200.0 and row["august"]["hitRatePct"] >= REQUIRED_HIT for row in courses.values())
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.6-shadow-ticket-ev",
        "productionChanged": False,
        "method": "Train a ticket-level hit model from January-April rolling out-of-sample horse predictions, select course-specific EV thresholds and stake rules on May-July only, then evaluate August 1-2 after every choice is frozen.",
        "ticketTraining": training_summary,
        "courses": courses,
        "promotionEligible100": pass_100,
        "promotionEligible200": pass_200,
    }
    Path("v6-ticket-ev-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "ticketTraining": training_summary,
        "august": {course: row["august"] for course, row in courses.items()},
        "promotionEligible100": pass_100,
        "promotionEligible200": pass_200,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
