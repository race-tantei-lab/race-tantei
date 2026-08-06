import calendar
import importlib.util
import json
import math
from collections import defaultdict
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
v6 = base.v6
v4 = v6.v4

# Always load every finished race currently available in the 2024-05 onward D1 history.
v4.HOLDOUT_END = "2026-08-31"

START_MONTH = "2024-05"
END_MONTH = "2026-08"
COURSE_BUDGETS = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
COURSES = tuple(COURSE_BUDGETS)
RACE_MODES = tuple(v6.RACE_MODES)

MODEL_CONFIG = {
    "max_leaf_nodes": 15,
    "learning_rate": 0.04,
    "max_iter": 160,
    "l2_regularization": 6.0,
}
MIN_TRAIN_RACES = 500

LOOKBACKS = (3, 6, 12, 24)
DECAYS = (0.85, 0.95)
SHRINK_MONTHS = (2.0, 6.0)
RISK_AVERSIONS = (0.0, 0.8, 1.6)
ALLOCATION_POWERS = (0.8, 1.5)
TICKET_COUNTS = {
    "ライト": (3, 5, 7),
    "スタンダード": (7, 11, 15),
    "プレミアム": (12, 18, 24),
}
MAX_TICKET_SHARE = {"ライト": 0.45, "スタンダード": 0.35, "プレミアム": 0.28}
MINIMUM_TYPES = {"ライト": 2, "スタンダード": 3, "プレミアム": 4}
ALLOWED_TYPES = {
    "ライト": {"単勝", "ワイド", "馬連"},
    "スタンダード": {"単勝", "ワイド", "馬連", "馬単", "3連複"},
    "プレミアム": {"単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"},
}
TYPE_CAPS = {
    "ライト": {"単勝": 2, "ワイド": 5, "馬連": 4},
    "スタンダード": {"単勝": 2, "ワイド": 5, "馬連": 4, "馬単": 7, "3連複": 7},
    "プレミアム": {"単勝": 2, "ワイド": 5, "馬連": 5, "馬単": 8, "3連複": 9, "3連単": 12},
}
PAYOUT_CAP_PER_100 = {"ライト": 5000.0, "スタンダード": 20000.0, "プレミアム": 100000.0}
TYPE_PRIOR_ROI = {"単勝": 80.0, "ワイド": 77.0, "馬連": 77.0, "馬単": 75.0, "3連複": 75.0, "3連単": 72.0}

PRIMITIVES = tuple(base.PRIMITIVES)
PRIMITIVE_COUNT = len(PRIMITIVES)
TYPE_BY_INDEX = {index: primitive[1] for index, primitive in enumerate(PRIMITIVES)}
RANKS_BY_INDEX = {index: primitive[2] for index, primitive in enumerate(PRIMITIVES)}
CODE_BY_INDEX = {index: primitive[0] for index, primitive in enumerate(PRIMITIVES)}


def month_sequence(start_month, end_month):
    year, month = map(int, start_month.split("-"))
    end_year, end_value = map(int, end_month.split("-"))
    result = []
    while (year, month) <= (end_year, end_value):
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def month_bounds(month):
    year, value = map(int, month.split("-"))
    last_day = calendar.monthrange(year, value)[1]
    return f"{year:04d}-{value:02d}-01", f"{year:04d}-{value:02d}-{last_day:02d}"


def quarter_key(month):
    year, value = map(int, month.split("-"))
    return f"{year:04d}-Q{((value - 1) // 3) + 1}"


def attach_market_only(races):
    attached = []
    for race in races:
        runners = []
        for runner in race["runners"]:
            item = dict(runner)
            item["probability"] = float(runner["market"])
            item["edge"] = 1.0
            runners.append(item)
        runners.sort(key=lambda row: row["probability"], reverse=True)
        item = dict(race)
        item["runners"] = runners
        item["topProbability"] = float(runners[0]["probability"])
        item["probabilityGap"] = float(runners[0]["probability"] - runners[1]["probability"])
        item["top3Concentration"] = float(sum(row["probability"] for row in runners[:3]))
        item["maxEdge"] = 1.0
        item["disagreement"] = 0.0
        item["entropy"] = float(
            -sum(row["probability"] * math.log(max(1e-12, row["probability"])) for row in runners)
        )
        attached.append(item)
    return attached


def select_five_complete(races, mode):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    coverage = []
    for (race_date, venue), group in sorted(grouped.items()):
        group.sort(key=lambda race: (-v6.race_score(race, mode), race["raceNo"]))
        take = min(5, len(group))
        chosen = group[:take]
        selected.extend(chosen)
        coverage.append(
            {
                "raceDate": race_date,
                "venue": venue,
                "availableRaces": len(group),
                "selectedRaces": take,
            }
        )
    return selected, coverage


def rolling_predictions(races, months):
    predictions = {}
    model_cache = {}
    model_training = {}
    for month in months:
        start, end = month_bounds(month)
        target = [race for race in races if start <= race["raceDate"] <= end]
        if not target:
            continue
        train = [race for race in races if race["raceDate"] < start]
        key = quarter_key(month)
        if len(train) >= MIN_TRAIN_RACES:
            if key not in model_cache:
                model_cache[key] = v6.fit_pairwise(train, MODEL_CONFIG)
                model_training[key] = {
                    "trainThrough": max(race["raceDate"] for race in train),
                    "trainRaces": len(train),
                }
            predictions[month] = v6.attach_pairwise(model_cache[key], target, 0.60, 1.30)
        else:
            predictions[month] = attach_market_only(target)
            model_training[key] = {
                "trainThrough": max((race["raceDate"] for race in train), default=None),
                "trainRaces": len(train),
                "fallback": "market-only",
            }
    return predictions, model_training


def config_grid(course):
    rows = []
    for mode in RACE_MODES:
        for lookback in LOOKBACKS:
            for decay in DECAYS:
                for shrink in SHRINK_MONTHS:
                    for risk in RISK_AVERSIONS:
                        for ticket_count in TICKET_COUNTS[course]:
                            for allocation_power in ALLOCATION_POWERS:
                                rows.append(
                                    {
                                        "mode": mode,
                                        "lookback": lookback,
                                        "decay": decay,
                                        "shrinkMonths": shrink,
                                        "riskAversion": risk,
                                        "ticketCount": ticket_count,
                                        "allocationPower": allocation_power,
                                    }
                                )
    return rows


def default_config_index(configs, course):
    target_count = TICKET_COUNTS[course][1]
    for index, config in enumerate(configs):
        if (
            config["mode"] == "balanced"
            and config["lookback"] == 6
            and config["decay"] == 0.95
            and config["shrinkMonths"] == 6.0
            and config["riskAversion"] == 0.8
            and config["ticketCount"] == target_count
            and config["allocationPower"] == 0.8
        ):
            return index
    return 0


def monthly_primitive_tables(month_rows):
    if not month_rows:
        empty = np.empty((0, PRIMITIVE_COUNT), dtype=np.float64)
        return empty, empty.copy(), empty.copy()
    return (
        np.asarray([row["raw"] for row in month_rows], dtype=np.float64),
        np.asarray([row["capped"] for row in month_rows], dtype=np.float64),
        np.asarray([row["hits"] for row in month_rows], dtype=np.float64),
    )


def primitive_scores(history_rows, course, config, current_min_field):
    lookback = int(config["lookback"])
    source = history_rows[-lookback:] if lookback > 0 else history_rows
    raw, capped, hits = monthly_primitive_tables(source)

    allowed = np.asarray(
        [
            TYPE_BY_INDEX[index] in ALLOWED_TYPES[course]
            and max(RANKS_BY_INDEX[index]) <= current_min_field
            for index in range(PRIMITIVE_COUNT)
        ],
        dtype=bool,
    )
    scores = np.full(PRIMITIVE_COUNT, -1e9, dtype=np.float64)
    if not np.any(allowed):
        return scores

    base_prior = np.asarray(
        [
            TYPE_PRIOR_ROI[TYPE_BY_INDEX[index]]
            - max(0, sum(RANKS_BY_INDEX[index]) - len(RANKS_BY_INDEX[index]) * 2) * 1.5
            for index in range(PRIMITIVE_COUNT)
        ],
        dtype=np.float64,
    )
    if len(capped) == 0:
        scores[allowed] = base_prior[allowed]
        return scores

    weights = np.asarray(
        [config["decay"] ** power for power in range(len(capped) - 1, -1, -1)],
        dtype=np.float64,
    )
    weights /= max(1e-12, weights.sum())
    weighted_capped = np.sum(capped * weights[:, None], axis=0)
    weighted_raw = np.sum(raw * weights[:, None], axis=0)
    weighted_hit = np.sum(hits * weights[:, None], axis=0)
    q25 = np.quantile(capped, 0.25, axis=0)
    recent = np.mean(capped[-min(3, len(capped)):], axis=0)
    volatility = np.std(capped, axis=0)
    effective_months = 1.0 / max(1e-12, float(np.sum(weights**2)))

    type_prior = base_prior.copy()
    for bet_type in ALLOWED_TYPES[course]:
        indices = [
            index
            for index in range(PRIMITIVE_COUNT)
            if allowed[index] and TYPE_BY_INDEX[index] == bet_type
        ]
        if indices:
            values = weighted_capped[indices]
            type_value = float(np.median(values))
            for index in indices:
                type_prior[index] = 0.65 * type_value + 0.35 * base_prior[index]

    shrink = float(config["shrinkMonths"])
    shrunk = (
        weighted_capped * effective_months + type_prior * shrink
    ) / (effective_months + shrink)
    standard_error = volatility / math.sqrt(max(1.0, effective_months))
    lower = shrunk - float(config["riskAversion"]) * standard_error
    dry_penalty = np.maximum(0.0, 12.0 - weighted_hit) * 1.25
    score = (
        lower * 0.40
        + weighted_capped * 0.18
        + q25 * 0.16
        + recent * 0.12
        + weighted_raw * 0.08
        + weighted_hit * 0.18
        - dry_penalty
    )
    scores[allowed] = score[allowed]
    return scores


def choose_indices(course, scores, ticket_count):
    candidates = [
        index
        for index in np.argsort(-scores)
        if scores[index] > -1e8 and TYPE_BY_INDEX[index] in ALLOWED_TYPES[course]
    ]
    if not candidates:
        raise RuntimeError(f"V6_7_NO_ALLOWED_PRIMITIVES:{course}")

    selected = []
    type_counts = defaultdict(int)
    best_by_type = {}
    for index in candidates:
        bet_type = TYPE_BY_INDEX[index]
        best_by_type.setdefault(bet_type, index)

    distinct_types = sorted(
        best_by_type,
        key=lambda bet_type: scores[best_by_type[bet_type]],
        reverse=True,
    )
    for bet_type in distinct_types[: MINIMUM_TYPES[course]]:
        index = best_by_type[bet_type]
        selected.append(index)
        type_counts[bet_type] += 1

    for index in candidates:
        if len(selected) >= ticket_count:
            break
        if index in selected:
            continue
        bet_type = TYPE_BY_INDEX[index]
        if type_counts[bet_type] >= TYPE_CAPS[course].get(bet_type, 0):
            continue
        selected.append(index)
        type_counts[bet_type] += 1

    if not selected:
        selected = [candidates[0]]
    return selected[:ticket_count]


def allocate_units(course, selected, scores, power):
    total_units = COURSE_BUDGETS[course] // 100
    units = np.zeros(PRIMITIVE_COUNT, dtype=np.int16)
    for index in selected:
        units[index] = 1
    remaining = total_units - len(selected)
    if remaining < 0:
        raise RuntimeError(f"V6_7_TOO_MANY_TICKETS:{course}:{len(selected)}:{total_units}")

    selected_scores = np.asarray([scores[index] for index in selected], dtype=np.float64)
    selected_scores -= float(np.min(selected_scores))
    weights = np.power(np.maximum(1.0, selected_scores + 1.0), float(power))
    weights /= max(1e-12, float(weights.sum()))
    max_units = max(1, int(total_units * MAX_TICKET_SHARE[course]))

    while remaining > 0:
        eligible = [
            position
            for position, index in enumerate(selected)
            if units[index] < max_units
        ]
        if not eligible:
            eligible = list(range(len(selected)))
        position = max(
            eligible,
            key=lambda value: weights[value] / (1.0 + float(units[selected[value]])),
        )
        units[selected[position]] += 1
        remaining -= 1

    if int(units.sum()) != total_units:
        raise RuntimeError(f"V6_7_BUDGET_MISMATCH:{course}:{int(units.sum())}:{total_units}")
    return units


def build_policy(history_rows, course, config, current_min_field):
    scores = primitive_scores(history_rows, course, config, current_min_field)
    selected = choose_indices(course, scores, int(config["ticketCount"]))
    units = allocate_units(
        course,
        selected,
        scores,
        float(config["allocationPower"]),
    )
    return units, scores


def meta_score(rois):
    if not rois:
        return -1e9
    values = np.asarray(rois[-12:], dtype=np.float64)
    capped = np.minimum(values, 400.0)
    q25 = float(np.quantile(capped, 0.25))
    median = float(np.median(capped))
    mean = float(np.mean(capped))
    recent = float(np.mean(capped[-min(3, len(capped)):]))
    minimum = float(np.min(capped))
    volatility = float(np.std(capped))
    downside = float(np.mean(np.maximum(0.0, 100.0 - capped)))
    winning = float(np.mean(capped >= 100.0) * 100.0)
    return (
        q25 * 0.30
        + median * 0.22
        + recent * 0.18
        + mean * 0.10
        + minimum * 0.08
        + winning * 0.20
        - downside * 0.18
        - volatility * 0.06
    )


def describe_policy(units):
    rows = []
    for index, value in enumerate(units):
        if value <= 0:
            continue
        rows.append(
            {
                "code": CODE_BY_INDEX[index],
                "betType": TYPE_BY_INDEX[index],
                "predictedRanks": list(RANKS_BY_INDEX[index]),
                "stakeYen": int(value * 100),
            }
        )
    return rows


def summarize_course(course, monthly_rows):
    stake = sum(row["stakeYen"] for row in monthly_rows)
    returned = sum(row["returnYen"] for row in monthly_rows)
    races = sum(row["selectedRaces"] for row in monthly_rows)
    hit_races = sum(row["hitRaces"] for row in monthly_rows)
    single_returns = [
        value
        for row in monthly_rows
        for value in row["raceReturnsYen"]
    ]
    max_share = max(single_returns, default=0) / max(1, returned)
    return {
        "selectedRaces": races,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRaces": hit_races,
        "hitRatePct": hit_races / races * 100 if races else 0.0,
        "winningMonths": sum(row["roiPct"] >= 100.0 for row in monthly_rows),
        "monthsAtOrAbove200": sum(row["roiPct"] >= 200.0 for row in monthly_rows),
        "minimumMonthlyRoiPct": min((row["roiPct"] for row in monthly_rows), default=0.0),
        "medianMonthlyRoiPct": float(
            np.median([row["roiPct"] for row in monthly_rows])
        ) if monthly_rows else 0.0,
        "maxSingleRaceReturnShare": max_share,
        "monthly": {
            row["month"]: {
                key: value
                for key, value in row.items()
                if key not in {"raceReturnsYen"}
            }
            for row in monthly_rows
        },
    }


def main():
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    months = [
        month
        for month in month_sequence(START_MONTH, END_MONTH)
        if any(race["raceDate"].startswith(month) for race in races)
    ]
    predictions, model_training = rolling_predictions(races, months)

    month_mode_data = {}
    coverage_rows = []
    for month in months:
        if month not in predictions:
            continue
        mode_rows = {}
        for mode in RACE_MODES:
            selected, coverage = select_five_complete(predictions[month], mode)
            matrix, _ = base.payout_matrix(selected)
            mode_rows[mode] = {
                "races": selected,
                "matrix": matrix,
                "minimumField": min(
                    (len(race["runners"]) for race in selected),
                    default=1,
                ),
                "coverage": coverage,
            }
        month_mode_data[month] = mode_rows
        coverage_rows.extend(mode_rows["balanced"]["coverage"])

    report_courses = {}
    for course in COURSES:
        configs = config_grid(course)
        histories = [[] for _ in configs]
        default_index = default_config_index(configs, course)
        primitive_history = {mode: [] for mode in RACE_MODES}
        monthly_rows = []
        chosen_indices = []

        for month_index, month in enumerate(months):
            if month not in month_mode_data:
                continue

            if month_index < 3:
                chosen_index = default_index
            else:
                prior_scores = np.asarray(
                    [meta_score(history) for history in histories],
                    dtype=np.float64,
                )
                chosen_index = int(np.argmax(prior_scores))
            chosen_indices.append(chosen_index)

            policies = []
            score_cache = {}
            for config in configs:
                mode = config["mode"]
                current = month_mode_data[month][mode]
                score_key = (
                    mode,
                    config["lookback"],
                    config["decay"],
                    config["shrinkMonths"],
                    config["riskAversion"],
                    current["minimumField"],
                )
                if score_key not in score_cache:
                    score_cache[score_key] = primitive_scores(
                        primitive_history[mode],
                        course,
                        config,
                        current["minimumField"],
                    )
                scores = score_cache[score_key]
                selected = choose_indices(course, scores, int(config["ticketCount"]))
                units = allocate_units(
                    course,
                    selected,
                    scores,
                    float(config["allocationPower"]),
                )
                policies.append(units)
            policy_matrix = np.asarray(policies, dtype=np.int16)

            current_rois = np.zeros(len(configs), dtype=np.float64)
            for mode in RACE_MODES:
                config_indices = [
                    index
                    for index, config in enumerate(configs)
                    if config["mode"] == mode
                ]
                if not config_indices:
                    continue
                matrix = month_mode_data[month][mode]["matrix"]
                aggregate_payout = matrix.sum(axis=0)
                returns = aggregate_payout @ policy_matrix[config_indices].T.astype(np.float64)
                stake = COURSE_BUDGETS[course] * len(matrix)
                values = returns / stake * 100.0 if stake else np.zeros(len(config_indices))
                current_rois[np.asarray(config_indices, dtype=int)] = values

            chosen_config = configs[chosen_index]
            chosen_mode = chosen_config["mode"]
            chosen_data = month_mode_data[month][chosen_mode]
            chosen_units = policy_matrix[chosen_index]
            race_returns = chosen_data["matrix"] @ chosen_units.astype(np.float64)
            stake = COURSE_BUDGETS[course] * len(chosen_data["matrix"])
            returned = int(round(float(race_returns.sum())))
            hit_races = int(np.sum(race_returns > 0))
            monthly_rows.append(
                {
                    "month": month,
                    "mode": chosen_mode,
                    "configIndex": chosen_index,
                    "config": chosen_config,
                    "policy": describe_policy(chosen_units),
                    "selectedRaces": len(chosen_data["matrix"]),
                    "stakeYen": stake,
                    "returnYen": returned,
                    "profitYen": returned - stake,
                    "roiPct": returned / stake * 100 if stake else 0.0,
                    "hitRaces": hit_races,
                    "hitRatePct": hit_races / len(chosen_data["matrix"]) * 100
                    if len(chosen_data["matrix"])
                    else 0.0,
                    "raceReturnsYen": [int(round(value)) for value in race_returns.tolist()],
                }
            )

            for index, roi in enumerate(current_rois.tolist()):
                histories[index].append(float(roi))
            for mode in RACE_MODES:
                matrix = month_mode_data[month][mode]["matrix"]
                cap = PAYOUT_CAP_PER_100[course]
                primitive_history[mode].append(
                    {
                        "raw": matrix.mean(axis=0),
                        "capped": np.minimum(matrix, cap).mean(axis=0),
                        "hits": (matrix > 0).mean(axis=0) * 100.0,
                    }
                )

        final_leaderboard = sorted(
            [
                {
                    "configIndex": index,
                    "config": config,
                    "walkForwardRoiScore": meta_score(histories[index]),
                    "meanMonthlyRoiPct": float(np.mean(histories[index])) if histories[index] else 0.0,
                    "medianMonthlyRoiPct": float(np.median(histories[index])) if histories[index] else 0.0,
                    "winningMonths": int(np.sum(np.asarray(histories[index]) >= 100.0)),
                }
                for index, config in enumerate(configs)
            ],
            key=lambda row: row["walkForwardRoiScore"],
            reverse=True,
        )[:20]

        summary = summarize_course(course, monthly_rows)
        summary["configurationCount"] = len(configs)
        summary["chosenConfigIndices"] = chosen_indices
        summary["leaderboardForNextMonthOnly"] = final_leaderboard
        summary["passesAllPeriod200"] = summary["roiPct"] >= 200.0
        report_courses[course] = summary

    total_selected = sum(row["selectedRaces"] for row in coverage_rows)
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.7-shadow-full-period-online",
        "productionChanged": False,
        "method": (
            "Use every finished race from May 2024 onward. At each month, build horse probabilities "
            "only from prior races, select up to five races for every venue-day, score thousands of "
            "course-specific primitive portfolios from prior monthly payouts only, choose the live "
            "configuration using prior configuration results only, and settle the current month with "
            "actual JRA payouts. No current-month result is used to choose its races or tickets."
        ),
        "requirements": {
            "fullAvailablePeriod": True,
            "noCurrentMonthLeakage": True,
            "noAssumedExoticOdds": True,
            "noEmptyTargetByRoiThreshold": True,
            "budgetPerSelectedRace": COURSE_BUDGETS,
            "targetRacesPerVenueDay": 5,
        },
        "data": {
            "firstRaceDate": min(race["raceDate"] for race in races),
            "lastRaceDate": max(race["raceDate"] for race in races),
            "races": len(races),
            "months": months,
            "modelTraining": model_training,
        },
        "coverage": {
            "venueDays": len(coverage_rows),
            "selectedRaces": total_selected,
            "zeroSelectedVenueDays": sum(row["selectedRaces"] == 0 for row in coverage_rows),
            "shortVenueDays": [
                row for row in coverage_rows if row["selectedRaces"] < 5
            ],
        },
        "factorGrid": {
            "raceModes": list(RACE_MODES),
            "lookbacks": list(LOOKBACKS),
            "decays": list(DECAYS),
            "shrinkMonths": list(SHRINK_MONTHS),
            "riskAversions": list(RISK_AVERSIONS),
            "allocationPowers": list(ALLOCATION_POWERS),
            "ticketCounts": TICKET_COUNTS,
            "configurationCountPerCourse": {
                course: len(config_grid(course)) for course in COURSES
            },
        },
        "courses": report_courses,
        "allCoursesOver200": all(
            row["roiPct"] >= 200.0 for row in report_courses.values()
        ),
    }
    Path("v6-7-full-period-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "modelVersion": report["modelVersion"],
                "period": [report["data"]["firstRaceDate"], report["data"]["lastRaceDate"]],
                "coverage": report["coverage"],
                "courses": {
                    course: {
                        "selectedRaces": row["selectedRaces"],
                        "roiPct": round(row["roiPct"], 4),
                        "hitRatePct": round(row["hitRatePct"], 4),
                        "winningMonths": row["winningMonths"],
                        "passesAllPeriod200": row["passesAllPeriod200"],
                    }
                    for course, row in report_courses.items()
                },
                "allCoursesOver200": report["allCoursesOver200"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
