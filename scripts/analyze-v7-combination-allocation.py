import importlib.util
import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v72 = load_module("v72_enriched", ROOT / "scripts" / "analyze-v7-enriched-ranking.py")
v7 = v72.v7
base = v72.base
v4 = v72.v4

ROLLING_START_MONTH = "2024-11"
EVALUATION_START_MONTH = "2025-05"
FINAL_HOLDOUT_START_MONTH = "2026-05"
COURSES = tuple(v72.COURSES)
COURSE_BUDGETS = dict(v72.COURSE_BUDGETS)
SAFE_VARIANTS = ("point", "pair", "ensemble")
SAFE_MODES = ("confidence", "concentration", "entropy")
REQUIRED_HIT = 36.8

TICKET_COUNTS = {
    "ライト": (3, 5, 6),
    "スタンダード": (6, 9, 12),
    "プレミアム": (10, 14, 18),
}
EXPONENTS = (0.8, 1.6, 3.0)
CALIBRATION_PRIOR = 30.0
PAYOUT_PRIOR_HITS = 15.0
REGIME_MIN_HITS = 12


@dataclass
class PrimitiveStat:
    predicted_sum: float = 0.0
    hits: int = 0
    payout_sum: float = 0.0

    def update(self, predicted, payout):
        self.predicted_sum += float(predicted)
        if payout > 0:
            self.hits += 1
            self.payout_sum += float(payout)


def field_band(count):
    if count <= 9:
        return "small"
    if count <= 13:
        return "medium"
    return "large"


def regime_key(race):
    return "|".join((
        str(race.get("surface") or "unknown"),
        v72.distance_band(race.get("distanceM")),
        field_band(len(race["runners"])),
    ))


def ordered_two(probabilities, first, second):
    p1 = probabilities[first]
    remaining = max(1e-12, 1.0 - p1)
    return p1 * probabilities[second] / remaining


def ordered_three(probabilities, first, second, third):
    p1 = probabilities[first]
    p2 = probabilities[second]
    denominator_second = max(1e-12, 1.0 - p1)
    denominator_third = max(1e-12, 1.0 - p1 - p2)
    return p1 * (p2 / denominator_second) * (probabilities[third] / denominator_third)


def primitive_probabilities(race):
    probabilities = np.asarray([runner["probability"] for runner in race["runners"]], dtype=np.float64)
    probabilities = probabilities / max(1e-12, probabilities.sum())
    count = len(probabilities)
    top_limit = min(5, count)
    wide = {}
    trio = {}
    ordered3 = {}

    for first, second, third in itertools.permutations(range(min(4, count)), 3):
        ordered3[(first, second, third)] = ordered_three(probabilities, first, second, third)
    for combination in itertools.combinations(range(top_limit), 3):
        trio[combination] = sum(
            ordered_three(probabilities, *order)
            for order in itertools.permutations(combination, 3)
        )
    for left, right in itertools.combinations(range(top_limit), 2):
        value = 0.0
        for third in range(count):
            if third in {left, right}:
                continue
            for order in itertools.permutations((left, right, third), 3):
                value += ordered_three(probabilities, *order)
        wide[(left, right)] = value

    result = np.zeros(len(base.PRIMITIVES), dtype=np.float64)
    for index, (_, bet_type, ranks) in enumerate(base.PRIMITIVES):
        positions = tuple(rank - 1 for rank in ranks)
        if any(position >= count for position in positions):
            continue
        if bet_type == "単勝":
            result[index] = probabilities[positions[0]]
        elif bet_type == "馬単":
            result[index] = ordered_two(probabilities, positions[0], positions[1])
        elif bet_type == "馬連":
            first, second = positions
            result[index] = ordered_two(probabilities, first, second) + ordered_two(probabilities, second, first)
        elif bet_type == "3連単":
            result[index] = ordered3.get(positions, ordered_three(probabilities, *positions))
        elif bet_type == "3連複":
            result[index] = trio.get(tuple(sorted(positions)), 0.0)
        elif bet_type == "ワイド":
            result[index] = wide.get(tuple(sorted(positions)), 0.0)
    return np.clip(result, 0.0, 1.0)


def type_payout_priors(races):
    values = defaultdict(list)
    for race in races:
        for key, payout in race.get("payouts", {}).items():
            bet_type = key.split(":", 1)[0]
            if payout > 0:
                values[bet_type].append(float(payout))
    defaults = {
        "単勝": 700.0,
        "ワイド": 900.0,
        "馬連": 3500.0,
        "馬単": 7500.0,
        "3連複": 9000.0,
        "3連単": 45000.0,
    }
    return {
        bet_type: float(np.median(rows)) if rows else defaults[bet_type]
        for bet_type, rows in ((name, values.get(name, [])) for name in defaults)
    }


def estimate_return(index, probability, global_stats, regime_stats, priors, regime):
    bet_type = base.TYPE_BY_INDEX[index]
    global_stat = global_stats[index]
    regime_stat = regime_stats[regime][index]

    global_calibration = (global_stat.hits + CALIBRATION_PRIOR) / max(
        1e-12, global_stat.predicted_sum + CALIBRATION_PRIOR
    )
    global_payout = (
        global_stat.payout_sum + priors[bet_type] * PAYOUT_PRIOR_HITS
    ) / (global_stat.hits + PAYOUT_PRIOR_HITS)

    if regime_stat.hits >= REGIME_MIN_HITS and regime_stat.predicted_sum > 0:
        regime_calibration = (regime_stat.hits + CALIBRATION_PRIOR * 0.5) / (
            regime_stat.predicted_sum + CALIBRATION_PRIOR * 0.5
        )
        regime_payout = (
            regime_stat.payout_sum + global_payout * PAYOUT_PRIOR_HITS * 0.5
        ) / (regime_stat.hits + PAYOUT_PRIOR_HITS * 0.5)
        calibration = 0.55 * global_calibration + 0.45 * regime_calibration
        payout = 0.55 * global_payout + 0.45 * regime_payout
    else:
        calibration = global_calibration
        payout = global_payout

    calibrated_probability = probability * max(0.35, min(2.5, calibration))
    return calibrated_probability * payout


def select_indices(course, expected_returns, ticket_count):
    allowed = [
        index for index in range(len(base.PRIMITIVES))
        if base.TYPE_BY_INDEX[index] in base.COURSE_ALLOWED_TYPES[course]
        and expected_returns[index] > 0
    ]
    allowed.sort(key=lambda index: expected_returns[index], reverse=True)
    selected = allowed[:ticket_count]

    minimum_types = {"ライト": 1, "スタンダード": 2, "プレミアム": 3}[course]
    present = {base.TYPE_BY_INDEX[index] for index in selected}
    if len(present) < minimum_types:
        best_by_type = {}
        for index in allowed:
            bet_type = base.TYPE_BY_INDEX[index]
            if bet_type not in best_by_type:
                best_by_type[bet_type] = index
        missing = [
            index for bet_type, index in sorted(
                best_by_type.items(),
                key=lambda item: expected_returns[item[1]],
                reverse=True,
            )
            if bet_type not in present
        ]
        for replacement in missing:
            if len(present) >= minimum_types:
                break
            if replacement in selected:
                continue
            removable = sorted(
                selected,
                key=lambda index: expected_returns[index],
            )
            for old in removable:
                old_type = base.TYPE_BY_INDEX[old]
                if sum(base.TYPE_BY_INDEX[index] == old_type for index in selected) > 1:
                    selected.remove(old)
                    selected.append(replacement)
                    present = {base.TYPE_BY_INDEX[index] for index in selected}
                    break
    return selected


def allocate_race(course, race, probabilities, global_stats, regime_stats, priors, ticket_count, exponent):
    regime = regime_key(race)
    expected = np.zeros(len(base.PRIMITIVES), dtype=np.float64)
    for index, probability in enumerate(probabilities):
        if probability <= 0:
            continue
        expected[index] = estimate_return(index, probability, global_stats, regime_stats, priors, regime)
    selected = select_indices(course, expected, ticket_count)
    if not selected:
        raise RuntimeError(f"V7_3_NO_TICKETS:{course}:{race['raceId']}")
    floor = max(1.0, float(np.median([expected[index] for index in selected])))
    raw_weights = [max(0.05, expected[index] / floor) ** exponent for index in selected]
    units = base.allocate_units(COURSE_BUDGETS[course], selected, raw_weights)
    if units is None or int(units.sum()) * 100 != COURSE_BUDGETS[course]:
        raise RuntimeError(f"V7_3_BAD_ALLOCATION:{course}:{race['raceId']}")
    return units, expected


def update_estimator(race, probabilities, payouts, global_stats, regime_stats):
    regime = regime_key(race)
    for index in range(len(base.PRIMITIVES)):
        global_stats[index].update(probabilities[index], payouts[index])
        regime_stats[regime][index].update(probabilities[index], payouts[index])


def month_result(course, races, probability_rows, payout_matrix, global_stats, regime_stats,
                 priors, ticket_count, exponent):
    stake = 0
    returned = 0.0
    hits = 0
    max_return = 0.0
    tickets = 0
    for race_index, race in enumerate(races):
        units, _ = allocate_race(
            course, race, probability_rows[race_index], global_stats, regime_stats,
            priors, ticket_count, exponent,
        )
        race_return = float(np.dot(payout_matrix[race_index], units.astype(np.float64)))
        race_hit = bool(np.any((payout_matrix[race_index] > 0) & (units > 0)))
        stake += int(units.sum() * 100)
        returned += race_return
        hits += int(race_hit)
        max_return = max(max_return, race_return)
        tickets += int(np.sum(units > 0))
    return {
        "races": len(races),
        "tickets": tickets,
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": hits / len(races) * 100 if races else 0.0,
        "maxSingleReturnYen": int(round(max_return)),
    }


def aggregate(rows):
    stake = sum(row["stakeYen"] for row in rows)
    returned = sum(row["returnYen"] for row in rows)
    races = sum(row["races"] for row in rows)
    weighted_hits = sum(row["hitRatePct"] * row["races"] for row in rows)
    rois = [row["roiPct"] for row in rows]
    max_single = max((row["maxSingleReturnYen"] for row in rows), default=0)
    winning = sum(value >= 100.0 for value in rois)
    return {
        "months": len(rows),
        "races": races,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": weighted_hits / races if races else 0.0,
        "winningMonths": winning,
        "winningMonthPct": winning / len(rows) * 100 if rows else 0.0,
        "minimumMonthlyRoiPct": min(rois) if rows else 0.0,
        "medianMonthlyRoiPct": float(np.median(rois)) if rows else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(rois, 0.25)) if rows else 0.0,
        "maxSingleReturnShare": max_single / max(1, returned),
    }


def candidate_history_score(rows):
    metrics = aggregate(rows)
    return (
        metrics["q25MonthlyRoiPct"] * 0.30
        + metrics["medianMonthlyRoiPct"] * 0.18
        + min(metrics["roiPct"], 350.0) * 0.16
        + metrics["hitRatePct"] * 0.16
        + metrics["winningMonthPct"] * 0.20
        - max(0.0, REQUIRED_HIT - metrics["hitRatePct"]) * 4.0
        - max(0.0, metrics["maxSingleReturnShare"] - 0.20) * 300.0
    )


def build_candidate_months(course, key, selected_by_month, months, priors):
    configurations = [
        (ticket_count, exponent)
        for ticket_count in TICKET_COUNTS[course]
        for exponent in EXPONENTS
    ]
    rows = {configuration: [] for configuration in configurations}
    global_stats = [PrimitiveStat() for _ in base.PRIMITIVES]
    regime_stats = defaultdict(lambda: [PrimitiveStat() for _ in base.PRIMITIVES])

    for month in months:
        races = selected_by_month[month]
        payout_matrix, _ = base.payout_matrix(races)
        probability_rows = np.vstack([primitive_probabilities(race) for race in races])
        for configuration in configurations:
            ticket_count, exponent = configuration
            result = month_result(
                course, races, probability_rows, payout_matrix,
                global_stats, regime_stats, priors, ticket_count, exponent,
            )
            result["month"] = month
            result["key"] = key
            result["ticketCount"] = ticket_count
            result["exponent"] = exponent
            rows[configuration].append(result)
        for race_index, race in enumerate(races):
            update_estimator(
                race,
                probability_rows[race_index],
                payout_matrix[race_index],
                global_stats,
                regime_stats,
            )
    return rows


def main():
    raw_rows, payouts = v4.load_data()
    base_races = v4.build_dataset(raw_rows, payouts)
    extra_rows = v72.load_extra_rows()
    races = v72.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(ROLLING_START_MONTH, last_month)
    evaluation_months = [month for month in months if month >= EVALUATION_START_MONTH]
    predictions, model_audit = v72.rolling_predictions(races, months)

    selected = {}
    coverage = {}
    for variant in SAFE_VARIANTS:
        for mode in SAFE_MODES:
            key = f"{variant}:{mode}"
            selected[key] = {}
            coverage[key] = {}
            for month in months:
                target = predictions[variant][month]
                picked = v7.select_five_strict(target, mode)
                selected[key][month] = picked
                coverage[key][month] = {
                    "sourceRaces": len(target),
                    "selectedRaces": len(picked),
                    "expectedSelectedRaces": v7.expected_selected_count(target),
                }

    prior_races = [race for race in races if race["raceDate"] < f"{ROLLING_START_MONTH}-01"]
    priors = type_payout_priors(prior_races)
    course_reports = {}
    for course in COURSES:
        candidates = {}
        for key in selected:
            key_rows = build_candidate_months(course, key, selected[key], months, priors)
            for configuration, rows in key_rows.items():
                ticket_count, exponent = configuration
                candidate_id = f"{key}|tickets={ticket_count}|exp={exponent}"
                candidates[candidate_id] = rows

        nested = []
        for month in evaluation_months:
            target_index = months.index(month)
            ranked = []
            for candidate_id, rows in candidates.items():
                history = rows[:target_index]
                ranked.append((candidate_history_score(history), candidate_id))
            ranked.sort(reverse=True)
            _, chosen_id = ranked[0]
            target = dict(candidates[chosen_id][target_index])
            target["candidateId"] = chosen_id
            target["historyScore"] = ranked[0][0]
            nested.append(target)

        development = [row for row in nested if row["month"] < FINAL_HOLDOUT_START_MONTH]
        holdout = [row for row in nested if row["month"] >= FINAL_HOLDOUT_START_MONTH]
        course_reports[course] = {
            "development": aggregate(development),
            "finalHoldout": aggregate(holdout),
            "full": aggregate(nested),
            "monthly": nested,
        }

    promotion = all(
        course_reports[course]["finalHoldout"]["roiPct"] >= 200.0
        and course_reports[course]["finalHoldout"]["hitRatePct"] >= REQUIRED_HIT
        and course_reports[course]["finalHoldout"]["maxSingleReturnShare"] <= 0.20
        for course in COURSES
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v7.3-shadow-combination-allocation",
        "productionChanged": False,
        "promotionEligible": promotion,
        "method": (
            "Use enriched market-free monthly rankings. Convert horse win probabilities to Plackett-Luce win, exacta, quinella, "
            "wide, trio and trifecta probabilities. At the start of each month, calibrate each primitive and estimate conditional "
            "winning payout from earlier OOS months only, freeze those estimates for the whole target month, and spend the full "
            "course budget on every one of five selected races per venue/day."
        ),
        "guardrails": {
            "selectedRacesPerVenueDay": 5,
            "noEmptyRaceSelection": True,
            "fullBudgetEverySelectedRace": True,
            "monthlyEstimatorFreeze": True,
            "currentRaceFinalOddsUsed": False,
            "finalHoldoutStart": FINAL_HOLDOUT_START_MONTH,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
            "rollingMonths": months,
            "evaluationMonths": evaluation_months,
        },
        "typePayoutPriors": priors,
        "modelAudit": model_audit,
        "coverage": coverage,
        "courses": course_reports,
    }
    Path("v7-combination-allocation-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "courses": {
            course: {
                "development": course_reports[course]["development"],
                "finalHoldout": course_reports[course]["finalHoldout"],
                "full": course_reports[course]["full"],
            }
            for course in COURSES
        },
        "promotionEligible": promotion,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
