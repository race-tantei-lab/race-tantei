#!/usr/bin/env python3
"""Train and evaluate a leak-resistant JRA betting policy.

Stages:
1. Fit probability calibration on the 12-month training split.
2. Choose calibration and one of several policy candidates on validation only.
3. Evaluate the frozen winner exactly once on the holdout split.

Every runtime decision uses only probabilities, odds, popularity, field size and
other pre-race derived features. Results and payouts are labels used only inside
the corresponding training/evaluation stage.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimize_validation_roi as legacy  # noqa: E402

SPLITS = ("train", "validation", "holdout")
COURSES = tuple(legacy.COURSE_TARGETS)
FEATURE_ORDER = (
    "top1Probability",
    "top1Top2Gap",
    "top2ProbabilitySum",
    "top3ProbabilitySum",
    "inverseEntropy",
    "inverseFieldSize",
    "inverseTop1Odds",
    "inverseTop1Popularity",
    "bestAnyValueCoverageScore",
    "bestWideValueCoverageScore",
    "bestQuinellaValueCoverageScore",
    "bestTrioValueCoverageScore",
    "bestTrifectaValueCoverageScore",
)


@dataclass(frozen=True)
class FrozenCandidate:
    seed: int
    race_policy: legacy.RacePolicy
    ticket_policies: dict[str, legacy.TicketPolicy]
    training: dict[str, Any]


def load_data(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def split_data(data: dict[str, Any], split: str) -> dict[str, Any]:
    result = {key: value for key, value in data.items() if key != "races"}
    result["races"] = [row for row in data.get("races", []) if row.get("split") == split]
    result["activeSplit"] = split
    return result


def normalize(values: dict[int, float]) -> dict[int, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        return {key: 1.0 / max(1, len(values)) for key in values}
    return {key: max(0.0, value) / total for key, value in values.items()}


def market_probabilities(runners: list[dict[str, Any]]) -> dict[int, float]:
    values: dict[int, float] = {}
    for runner in runners:
        horse = int(runner["horseNo"])
        odds = runner.get("currentOdds")
        popularity = runner.get("popularity")
        if odds and float(odds) > 1.0:
            values[horse] = 1.0 / float(odds)
        elif popularity and int(popularity) > 0:
            values[horse] = 1.0 / math.pow(float(popularity) + 0.5, 1.25)
        else:
            values[horse] = max(1e-6, float(runner.get("winProbability", 0.0)))
    return normalize(values)


def calibrated_copy(data: dict[str, Any], model_weight: float, temperature: float) -> dict[str, Any]:
    result = copy.deepcopy(data)
    for race in result.get("races", []):
        runners = race.get("runners", [])
        if not runners:
            continue
        base = normalize({int(row["horseNo"]): float(row.get("winProbability", 0.0)) for row in runners})
        market = market_probabilities(runners)
        scores: dict[int, float] = {}
        for row in runners:
            horse = int(row["horseNo"])
            base_p = max(1e-9, base.get(horse, 0.0))
            market_p = max(1e-9, market.get(horse, 0.0))
            scores[horse] = (
                model_weight * math.log(base_p)
                + (1.0 - model_weight) * math.log(market_p)
            ) / temperature
        maximum = max(scores.values())
        exp = {horse: math.exp(max(-40.0, score - maximum)) for horse, score in scores.items()}
        probabilities = normalize(exp)
        ranked = sorted(runners, key=lambda row: probabilities[int(row["horseNo"])], reverse=True)
        rank = {int(row["horseNo"]): index + 1 for index, row in enumerate(ranked)}
        for row in runners:
            horse = int(row["horseNo"])
            probability = probabilities[horse]
            row["winProbability"] = probability
            row["placeProbability"] = min(0.96, max(probability, 1.0 - math.pow(1.0 - probability, 3)))
            row["fairOdds"] = 1.0 / max(1e-9, probability)
            row["predictedOrder"] = rank[horse]
            odds = row.get("currentOdds")
            row["expectedValuePct"] = probability * float(odds) * 100.0 if odds else None
    return result


def winner_number(race: dict[str, Any]) -> int | None:
    for row in race.get("results", []):
        if int(row.get("finishPosition") or 0) == 1:
            return int(row["horseNo"])
    return None


def log_loss(data: dict[str, Any]) -> float:
    losses: list[float] = []
    for race in data.get("races", []):
        winner = winner_number(race)
        if winner is None:
            continue
        probabilities = {int(row["horseNo"]): float(row.get("winProbability", 0.0)) for row in race.get("runners", [])}
        losses.append(-math.log(max(1e-12, probabilities.get(winner, 0.0))))
    return statistics.fmean(losses) if losses else float("inf")


def choose_calibration(train: dict[str, Any], validation: dict[str, Any]) -> dict[str, float]:
    candidates: list[dict[str, float]] = []
    for model_weight in [index / 10.0 for index in range(0, 16)]:
        for temperature in (0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.30, 1.45):
            transformed = calibrated_copy(train, model_weight, temperature)
            candidates.append({
                "modelWeight": model_weight,
                "temperature": temperature,
                "trainLogLoss": log_loss(transformed),
            })
    finalists = sorted(candidates, key=lambda row: row["trainLogLoss"])[:16]
    for row in finalists:
        transformed = calibrated_copy(validation, row["modelWeight"], row["temperature"])
        row["validationLogLoss"] = log_loss(transformed)
    return min(finalists, key=lambda row: row["validationLogLoss"])


def raw_race_features(race: legacy.Race) -> list[float]:
    all_candidates = [candidate for values in race.candidates.values() for candidate in values]
    probabilities = sorted(
        [candidate.probability for candidate in race.candidates.get("単勝", [])],
        reverse=True,
    )
    if not probabilities:
        probabilities = [0.0, 0.0, 0.0]
    p1 = probabilities[0] if probabilities else 0.0
    p2 = probabilities[1] if len(probabilities) > 1 else 0.0
    p3 = probabilities[2] if len(probabilities) > 2 else 0.0
    singles = sorted(race.candidates.get("単勝", []), key=lambda row: row.probability, reverse=True)
    top_odds = singles[0].assumed_odds if singles else 99.0
    entropy = -sum(value * math.log(max(1e-12, value)) for value in probabilities if value > 0)
    max_entropy = math.log(max(2, race.field_size))

    def best(bet_type: str | None = None) -> float:
        values = all_candidates if bet_type is None else race.candidates.get(bet_type, [])
        return max((candidate.expected_value * math.sqrt(candidate.probability) for candidate in values), default=0.0)

    top_popularity = 1.0
    if singles and singles[0].market_probability > 0:
        top_popularity = singles[0].market_probability
    return [
        p1,
        p1 - p2,
        p1 + p2,
        p1 + p2 + p3,
        1.0 - (entropy / max_entropy if max_entropy > 0 else 0.0),
        1.0 / max(3.0, float(race.field_size)),
        1.0 / max(1.1, top_odds),
        top_popularity,
        best(None),
        best("ワイド"),
        best("馬連"),
        best("3連複"),
        best("3連単"),
    ]


def percentile(values: list[float], value: float) -> float:
    if len(values) <= 1:
        return 0.5
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return (below + max(0, equal - 1) / 2.0) / (len(values) - 1)


def build_transferable_races(data: dict[str, Any]) -> list[legacy.Race]:
    races = legacy.build_races(data)
    raw = {race.race_id: raw_race_features(race) for race in races}
    groups: dict[tuple[str, str], list[legacy.Race]] = {}
    for race in races:
        groups.setdefault((race.race_date, race.venue), []).append(race)
    for group in groups.values():
        columns = list(zip(*(raw[race.race_id] for race in group)))
        for race in group:
            values = raw[race.race_id]
            race.features = [
                percentile(list(columns[index]), value) - 0.5
                for index, value in enumerate(values)
            ]
    return races


def outcome_grid(
    races: list[legacy.Race],
    course: str,
    policies: list[legacy.TicketPolicy],
) -> list[list[tuple[int, bool]]]:
    return [
        [legacy.allocate_race(race, course, policy)[:2] for race in races]
        for policy in policies
    ]


def evaluate_outcomes(
    outcomes: list[tuple[int, bool]],
    indices: list[int],
    target: int,
    races: list[legacy.Race],
) -> dict[str, Any]:
    returns = sum(outcomes[index][0] for index in indices)
    hits = sum(1 for index in indices if outcomes[index][1])
    stake = len(indices) * target
    daily: dict[str, int] = {}
    for index in indices:
        profit = outcomes[index][0] - target
        daily[races[index].race_date] = daily.get(races[index].race_date, 0) + profit
    positive = [max(0, value) for value in daily.values()]
    total_positive = sum(positive)
    concentration = max(positive, default=0) / total_positive if total_positive > 0 else 1.0
    return {
        "selectedRaces": len(indices),
        "stakeYen": stake,
        "returnYen": returns,
        "profitYen": returns - stake,
        "roiPct": returns / stake * 100.0 if stake else 0.0,
        "hitRatePct": hits / len(indices) * 100.0 if indices else 0.0,
        "maximumPositiveDayShare": concentration,
    }


def policy_objective(rows: dict[str, dict[str, Any]]) -> float:
    rois = [row["roiPct"] for row in rows.values()]
    hits = [row["hitRatePct"] for row in rows.values()]
    concentration = max(row["maximumPositiveDayShare"] for row in rows.values())
    downside = sum(max(0.0, 100.0 - roi) for roi in rois)
    return min(rois) + statistics.fmean(rois) * 0.18 + min(hits) * 0.06 - downside * 0.7 - concentration * 18.0


def train_candidate(
    races: list[legacy.Race],
    seed: int,
    race_policy_count: int,
    ticket_policy_count: int,
) -> FrozenCandidate:
    rng = random.Random(seed)
    policies_by_course: dict[str, list[legacy.TicketPolicy]] = {}
    outcomes_by_course: dict[str, list[list[tuple[int, bool]]]] = {}
    for course in COURSES:
        policies = [legacy.random_ticket_policy(rng, course) for _ in range(ticket_policy_count)]
        policies_by_course[course] = policies
        outcomes_by_course[course] = outcome_grid(races, course, policies)

    best: tuple[float, legacy.RacePolicy, dict[str, int], dict[str, dict[str, Any]]] | None = None
    for _ in range(race_policy_count):
        race_policy = legacy.random_race_policy(rng, len(FEATURE_ORDER))
        indices = legacy.selected_indices(races, race_policy)
        selected_policies: dict[str, int] = {}
        summaries: dict[str, dict[str, Any]] = {}
        for course, target in legacy.COURSE_TARGETS.items():
            best_course: tuple[float, int, dict[str, Any]] | None = None
            for policy_index, outcomes in enumerate(outcomes_by_course[course]):
                summary = evaluate_outcomes(outcomes, indices, target, races)
                score = summary["roiPct"] - max(0.0, 45.0 - summary["hitRatePct"]) * 0.5 - summary["maximumPositiveDayShare"] * 10.0
                if best_course is None or score > best_course[0]:
                    best_course = (score, policy_index, summary)
            assert best_course is not None
            selected_policies[course] = best_course[1]
            summaries[course] = best_course[2]
        score = policy_objective(summaries)
        if best is None or score > best[0]:
            best = (score, race_policy, selected_policies, summaries)

    if best is None:
        raise RuntimeError("No walk-forward policy candidate was produced")
    _, race_policy, selected_policies, summaries = best
    return FrozenCandidate(
        seed=seed,
        race_policy=race_policy,
        ticket_policies={course: policies_by_course[course][selected_policies[course]] for course in COURSES},
        training=summaries,
    )


def selected_by_venue(races: list[legacy.Race], indices: list[int]) -> dict[str, int]:
    values: dict[str, int] = {}
    for index in indices:
        race = races[index]
        key = f"{race.race_date}:{race.venue}"
        values[key] = values.get(key, 0) + 1
    return values


def evaluate_candidate(candidate: FrozenCandidate, races: list[legacy.Race]) -> dict[str, Any]:
    indices = legacy.selected_indices(races, candidate.race_policy)
    courses: dict[str, dict[str, Any]] = {}
    for course, target in legacy.COURSE_TARGETS.items():
        outcomes = [legacy.allocate_race(race, course, candidate.ticket_policies[course])[:2] for race in races]
        courses[course] = evaluate_outcomes(outcomes, indices, target, races)
    counts = selected_by_venue(races, indices)
    return {
        "usableRaces": len(races),
        "selectedRaces": len(indices),
        "selectedByVenue": counts,
        "fivePerVenue": all(value == 5 for value in counts.values()),
        "courses": courses,
        "objective": policy_objective(courses),
    }


def ticket_policy_json(policy: legacy.TicketPolicy) -> dict[str, Any]:
    return legacy.policy_to_json(policy)


def candidate_json(candidate: FrozenCandidate) -> dict[str, Any]:
    return {
        "seed": candidate.seed,
        "featureOrder": list(FEATURE_ORDER),
        "racePolicy": {"weights": list(candidate.race_policy.weights)},
        "ticketPolicies": {course: ticket_policy_json(policy) for course, policy in candidate.ticket_policies.items()},
        "training": candidate.training,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", default="walk-forward-roi-result.json")
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--race-policies", type=int, default=90)
    parser.add_argument("--ticket-policies", type=int, default=140)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    data = load_data(args.source)
    if data.get("complete") is not True:
        raise RuntimeError("Walk-forward dataset is not complete")
    split_counts = data.get("splitCounts", {})
    if int(split_counts.get("train", 0)) < 1800:
        raise RuntimeError(f"Training sample is too small: {split_counts}")
    if int(split_counts.get("validation", 0)) < 300 or int(split_counts.get("holdout", 0)) < 150:
        raise RuntimeError(f"Validation or holdout sample is too small: {split_counts}")

    train_raw = split_data(data, "train")
    validation_raw = split_data(data, "validation")
    holdout_raw = split_data(data, "holdout")
    calibration = choose_calibration(train_raw, validation_raw)

    train = calibrated_copy(train_raw, calibration["modelWeight"], calibration["temperature"])
    validation = calibrated_copy(validation_raw, calibration["modelWeight"], calibration["temperature"])
    holdout = calibrated_copy(holdout_raw, calibration["modelWeight"], calibration["temperature"])
    train_races = build_transferable_races(train)
    validation_races = build_transferable_races(validation)
    holdout_races = build_transferable_races(holdout)

    candidates = [
        train_candidate(
            train_races,
            args.seed + index * 9973,
            args.race_policies,
            args.ticket_policies,
        )
        for index in range(args.candidates)
    ]
    validation_rows = [evaluate_candidate(candidate, validation_races) for candidate in candidates]
    winner_index = max(range(len(candidates)), key=lambda index: validation_rows[index]["objective"])
    winner = candidates[winner_index]
    holdout_result = evaluate_candidate(winner, holdout_races)

    holdout_courses = holdout_result["courses"]
    promotion_ready = (
        holdout_result["fivePerVenue"]
        and all(row["roiPct"] >= 100.0 for row in holdout_courses.values())
        and all(row["maximumPositiveDayShare"] <= 0.40 for row in holdout_courses.values())
        and all(row["hitRatePct"] >= 20.0 for row in holdout_courses.values())
    )

    result = {
        "scope": data.get("scope"),
        "method": "12-month-train-validation-holdout",
        "splitCounts": split_counts,
        "calibration": calibration,
        "candidateCount": len(candidates),
        "selectedCandidate": candidate_json(winner),
        "validation": validation_rows[winner_index],
        "holdout": holdout_result,
        "promotionReady": promotion_ready,
        "promotionRule": {
            "allHoldoutCoursesRoiAtLeastPct": 100,
            "maximumPositiveDayShareAtMost": 0.40,
            "allHoldoutCoursesHitRateAtLeastPct": 20,
            "fiveRacesPerVenue": True,
        },
        "warning": "The holdout result is evaluated once. Do not retune against it; roll the window forward for the next experiment.",
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
