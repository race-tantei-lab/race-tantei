#!/usr/bin/env python3
"""Optimize a five-races-per-venue betting policy on the validation dataset.

The optimizer may use settled outcomes only to score global parameter sets. Every
race and ticket decision is produced from pre-race prediction probabilities,
odds, popularity and field-size features. Race IDs, race numbers and results are
never features. The output is therefore an in-sample analysis milestone, not an
out-of-sample performance claim.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
import statistics
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

COURSE_TARGETS = {"ライト": 1600, "スタンダード": 4200, "プレミアム": 8800}
COURSE_TYPES = {
    "ライト": ("単勝", "ワイド", "馬連"),
    "スタンダード": ("単勝", "ワイド", "馬連", "馬単", "3連複"),
    "プレミアム": ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"),
}
PAYOUT_RATIO = {"単勝": 1.0, "ワイド": 0.77, "馬連": 0.77, "馬単": 0.75, "3連複": 0.75, "3連単": 0.72}
RELIABILITY = {"単勝": 0.98, "ワイド": 0.92, "馬連": 0.89, "馬単": 0.85, "3連複": 0.82, "3連単": 0.76}
UNORDERED = {"ワイド", "馬連", "3連複"}
TYPE_ORDER = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")


@dataclass(frozen=True)
class Candidate:
    bet_type: str
    combination: tuple[int, ...]
    probability: float
    market_probability: float
    assumed_odds: float
    expected_value: float
    payout_per_100: int
    rank_sum: int
    includes_first: int


@dataclass
class Race:
    race_id: str
    race_date: str
    venue: str
    field_size: int
    features: list[float]
    candidates: dict[str, list[Candidate]]


@dataclass(frozen=True)
class TicketPolicy:
    ticket_count: int
    ev_weight: float
    probability_weight: float
    odds_weight: float
    rank_weight: float
    first_weight: float
    temperature: float
    type_bias: tuple[float, ...]
    type_caps: tuple[int, ...]


@dataclass(frozen=True)
class RacePolicy:
    weights: tuple[float, ...]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize(values: dict[int, float]) -> dict[int, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        return {key: 1.0 / max(1, len(values)) for key in values}
    return {key: max(0.0, value) / total for key, value in values.items()}


def ordered_probability(order: Iterable[int], weights: dict[int, float]) -> float:
    remaining = sum(weights.values())
    probability = 1.0
    used: set[int] = set()
    for horse in order:
        if horse in used or remaining <= 0:
            return 0.0
        weight = weights.get(horse, 0.0)
        if weight <= 0:
            return 0.0
        probability *= weight / remaining
        remaining -= weight
        used.add(horse)
    return clamp(probability, 0.0, 1.0)


def event_probability(bet_type: str, combination: tuple[int, ...], weights: dict[int, float]) -> float:
    if bet_type == "単勝":
        return weights.get(combination[0], 0.0)
    if bet_type == "馬単":
        return ordered_probability(combination, weights)
    if bet_type == "3連単":
        return ordered_probability(combination, weights)
    if bet_type == "馬連":
        a, b = combination
        return ordered_probability((a, b), weights) + ordered_probability((b, a), weights)
    if bet_type == "3連複":
        return sum(ordered_probability(order, weights) for order in itertools.permutations(combination))
    if bet_type == "ワイド":
        a, b = combination
        total = 0.0
        for third in weights:
            if third in (a, b):
                continue
            total += sum(ordered_probability(order, weights) for order in itertools.permutations((a, b, third)))
        return clamp(total, 0.0, 1.0)
    return 0.0


def numbers(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", value))


def payout_key(bet_type: str, combination: Iterable[int]) -> tuple[str, tuple[int, ...]]:
    values = tuple(combination)
    if bet_type in UNORDERED:
        values = tuple(sorted(values))
    return bet_type, values


def load_json(source: str) -> dict[str, Any]:
    if source.startswith("http://") or source.startswith("https://"):
        request = urllib.request.Request(source, headers={"User-Agent": "race-tantei-analysis/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def standardize(rows: list[list[float]]) -> list[list[float]]:
    if not rows:
        return rows
    columns = list(zip(*rows))
    means = [statistics.fmean(column) for column in columns]
    deviations = [statistics.pstdev(column) or 1.0 for column in columns]
    return [[(value - means[index]) / deviations[index] for index, value in enumerate(row)] for row in rows]


def build_races(data: dict[str, Any]) -> list[Race]:
    provisional: list[tuple[dict[str, Any], dict[str, list[Candidate]], list[float]]] = []
    for row in data.get("races", []):
        runners = sorted(row.get("runners", []), key=lambda item: int(item.get("predictedOrder", 999)))
        if len(runners) < 3 or not row.get("payouts"):
            continue
        model_weights = normalize({int(item["horseNo"]): float(item.get("winProbability", 0.0)) for item in runners})
        market_weights = normalize({
            int(item["horseNo"]): 1.0 / float(item["currentOdds"])
            if item.get("currentOdds") and float(item["currentOdds"]) > 1.0
            else max(0.0001, float(item.get("winProbability", 0.0)))
            for item in runners
        })
        rank_by_horse = {int(item["horseNo"]): int(item.get("predictedOrder", 99)) for item in runners}
        odds_by_horse = {int(item["horseNo"]): float(item.get("currentOdds") or 0.0) for item in runners}
        payout_map: dict[tuple[str, tuple[int, ...]], int] = {}
        for payout in row.get("payouts", []):
            bet_type = str(payout.get("betType", ""))
            combo = numbers(str(payout.get("combination", "")))
            if combo:
                payout_map[payout_key(bet_type, combo)] = int(payout.get("payoutYen", 0))

        pool = [int(item["horseNo"]) for item in runners[:6]]
        candidate_rows: list[tuple[str, tuple[int, ...]]] = []
        candidate_rows.extend(("単勝", (horse,)) for horse in pool)
        for a, b in itertools.combinations(pool, 2):
            candidate_rows.extend((("ワイド", (a, b)), ("馬連", (a, b)), ("馬単", (a, b)), ("馬単", (b, a))))
        for triple in itertools.combinations(pool, 3):
            candidate_rows.append(("3連複", triple))
            candidate_rows.extend(("3連単", order) for order in itertools.permutations(triple))

        candidates: dict[str, list[Candidate]] = {bet_type: [] for bet_type in TYPE_ORDER}
        for bet_type, combination in candidate_rows:
            probability = event_probability(bet_type, combination, model_weights)
            market_probability = event_probability(bet_type, combination, market_weights)
            if probability <= 0 or market_probability <= 0:
                continue
            if bet_type == "単勝":
                assumed_odds = odds_by_horse.get(combination[0], 0.0)
                if assumed_odds <= 1:
                    continue
            else:
                assumed_odds = PAYOUT_RATIO[bet_type] / market_probability
            assumed_odds = clamp(math.floor(assumed_odds * 10.0) / 10.0, 1.1, 2500.0)
            expected_value = probability * assumed_odds * RELIABILITY[bet_type]
            candidates[bet_type].append(Candidate(
                bet_type=bet_type,
                combination=combination,
                probability=probability,
                market_probability=market_probability,
                assumed_odds=assumed_odds,
                expected_value=expected_value,
                payout_per_100=payout_map.get(payout_key(bet_type, combination), 0),
                rank_sum=sum(rank_by_horse.get(horse, 99) for horse in combination),
                includes_first=int(pool[0] in combination),
            ))

        probabilities = [float(item.get("winProbability", 0.0)) for item in runners]
        p1 = probabilities[0] if probabilities else 0.0
        p2 = probabilities[1] if len(probabilities) > 1 else 0.0
        p3 = probabilities[2] if len(probabilities) > 2 else 0.0
        entropy = -sum(p * math.log(max(p, 1e-12)) for p in probabilities)
        max_entropy = math.log(max(2, len(probabilities)))
        top_runner = runners[0]
        top_market_rank = int(top_runner.get("popularity") or len(runners))
        all_candidates = [candidate for values in candidates.values() for candidate in values]
        best_by_type = {
            bet_type: max((candidate.expected_value * math.sqrt(candidate.probability) for candidate in candidates[bet_type]), default=0.0)
            for bet_type in TYPE_ORDER
        }
        raw_features = [
            p1,
            p1 - p2,
            p1 + p2,
            p1 + p2 + p3,
            entropy / max_entropy if max_entropy > 0 else 0.0,
            math.log(max(3, int(row.get("fieldSize", len(runners))))),
            math.log(max(1.1, float(top_runner.get("currentOdds") or 99.0))),
            float(top_market_rank),
            max((candidate.expected_value for candidate in all_candidates), default=0.0),
            best_by_type["ワイド"],
            best_by_type["馬連"],
            best_by_type["3連複"],
            best_by_type["3連単"],
        ]
        provisional.append((row, candidates, raw_features))

    standardized = standardize([features for _, _, features in provisional])
    races: list[Race] = []
    for (row, candidates, _), features in zip(provisional, standardized):
        races.append(Race(
            race_id=str(row["raceId"]),
            race_date=str(row["raceDate"]),
            venue=str(row["venue"]),
            field_size=int(row.get("fieldSize", 0)),
            features=features,
            candidates=candidates,
        ))
    return races


def random_ticket_policy(rng: random.Random, course: str) -> TicketPolicy:
    ranges = {
        "ライト": (6, 14),
        "スタンダード": (10, 26),
        "プレミアム": (16, 46),
    }
    low, high = ranges[course]
    allowed = set(COURSE_TYPES[course])
    biases = tuple(rng.uniform(-2.8, 2.8) if bet_type in allowed else -99.0 for bet_type in TYPE_ORDER)
    caps: list[int] = []
    for bet_type in TYPE_ORDER:
        if bet_type not in allowed:
            caps.append(0)
        elif bet_type == "単勝":
            caps.append(rng.randint(1, 4))
        elif bet_type in {"ワイド", "馬連"}:
            caps.append(rng.randint(2, 10))
        elif bet_type in {"馬単", "3連複"}:
            caps.append(rng.randint(3, 16))
        else:
            caps.append(rng.randint(5, 30))
    return TicketPolicy(
        ticket_count=rng.randint(low, high),
        ev_weight=rng.uniform(-0.2, 3.5),
        probability_weight=rng.uniform(0.3, 4.5),
        odds_weight=rng.uniform(-1.5, 1.2),
        rank_weight=rng.uniform(-1.2, 0.25),
        first_weight=rng.uniform(-0.4, 1.6),
        temperature=rng.uniform(0.4, 2.5),
        type_bias=biases,
        type_caps=tuple(caps),
    )


def candidate_score(candidate: Candidate, policy: TicketPolicy) -> float:
    type_index = TYPE_ORDER.index(candidate.bet_type)
    return (
        policy.ev_weight * math.log(max(0.05, candidate.expected_value))
        + policy.probability_weight * math.log(max(1e-6, candidate.probability))
        + policy.odds_weight * math.log(max(1.1, candidate.assumed_odds))
        + policy.rank_weight * candidate.rank_sum
        + policy.first_weight * candidate.includes_first
        + policy.type_bias[type_index]
    )


def allocate_race(race: Race, course: str, policy: TicketPolicy) -> tuple[int, bool, tuple[tuple[str, str, int], ...]]:
    target = COURSE_TARGETS[course]
    allowed = COURSE_TYPES[course]
    scored: list[tuple[float, Candidate]] = []
    for bet_type in allowed:
        for candidate in race.candidates.get(bet_type, []):
            scored.append((candidate_score(candidate, policy), candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    selected: list[tuple[float, Candidate]] = []
    counts = {bet_type: 0 for bet_type in TYPE_ORDER}
    for score, candidate in scored:
        cap = policy.type_caps[TYPE_ORDER.index(candidate.bet_type)]
        if counts[candidate.bet_type] >= cap:
            continue
        selected.append((score, candidate))
        counts[candidate.bet_type] += 1
        if len(selected) >= min(policy.ticket_count, target // 100):
            break
    if not selected:
        return 0, False, ()

    stakes = [100 for _ in selected]
    remaining = target - len(selected) * 100
    max_score = max(score for score, _ in selected)
    weights = [math.exp(clamp((score - max_score) / policy.temperature, -12.0, 0.0)) for score, _ in selected]
    while remaining >= 100:
        best_index = max(range(len(selected)), key=lambda index: weights[index] / (1.0 + stakes[index] / 100.0))
        stakes[best_index] += 100
        remaining -= 100

    returns = 0
    detail: list[tuple[str, str, int]] = []
    for stake, (_, candidate) in zip(stakes, selected):
        returns += candidate.payout_per_100 * (stake // 100)
        detail.append((candidate.bet_type, "-".join(str(value) for value in candidate.combination), stake))
    return returns, returns > 0, tuple(detail)


def random_race_policy(rng: random.Random, feature_count: int) -> RacePolicy:
    return RacePolicy(tuple(rng.uniform(-3.5, 3.5) for _ in range(feature_count)))


def selected_indices(races: list[Race], policy: RacePolicy) -> list[int]:
    groups: dict[tuple[str, str], list[int]] = {}
    for index, race in enumerate(races):
        groups.setdefault((race.race_date, race.venue), []).append(index)
    selected: list[int] = []
    for indices in groups.values():
        ranked = sorted(
            indices,
            key=lambda index: sum(weight * feature for weight, feature in zip(policy.weights, races[index].features)),
            reverse=True,
        )
        selected.extend(ranked[: min(5, len(ranked))])
    return sorted(selected)


def evaluate_policy(race_outcomes: list[tuple[int, bool, tuple[tuple[str, str, int], ...]]], indices: list[int], target: int) -> tuple[float, float]:
    returns = sum(race_outcomes[index][0] for index in indices)
    hits = sum(1 for index in indices if race_outcomes[index][1])
    stake = len(indices) * target
    return (returns / stake * 100.0 if stake else 0.0, hits / len(indices) * 100.0 if indices else 0.0)


def policy_to_json(policy: TicketPolicy) -> dict[str, Any]:
    return {
        "ticketCount": policy.ticket_count,
        "evWeight": policy.ev_weight,
        "probabilityWeight": policy.probability_weight,
        "oddsWeight": policy.odds_weight,
        "rankWeight": policy.rank_weight,
        "firstWeight": policy.first_weight,
        "temperature": policy.temperature,
        "typeBias": dict(zip(TYPE_ORDER, policy.type_bias)),
        "typeCaps": dict(zip(TYPE_ORDER, policy.type_caps)),
    }


def optimize(data: dict[str, Any], seed: int, race_policies: int, ticket_policies: int) -> dict[str, Any]:
    rng = random.Random(seed)
    races = build_races(data)
    if not races:
        raise RuntimeError("No usable validation races were returned")
    groups = {(race.race_date, race.venue) for race in races}
    expected_selected = sum(min(5, sum(1 for race in races if (race.race_date, race.venue) == group)) for group in groups)

    policies_by_course: dict[str, list[TicketPolicy]] = {}
    outcomes_by_course: dict[str, list[list[tuple[int, bool, tuple[tuple[str, str, int], ...]]]]] = {}
    for course in COURSE_TARGETS:
        policies = [random_ticket_policy(rng, course) for _ in range(ticket_policies)]
        policies_by_course[course] = policies
        outcomes_by_course[course] = [
            [allocate_race(race, course, policy) for race in races]
            for policy in policies
        ]

    feature_count = len(races[0].features)
    race_policy_rows = [random_race_policy(rng, feature_count) for _ in range(race_policies)]
    best: dict[str, Any] | None = None
    for race_policy in race_policy_rows:
        indices = selected_indices(races, race_policy)
        if len(indices) != expected_selected:
            continue
        course_results: dict[str, dict[str, Any]] = {}
        for course, target in COURSE_TARGETS.items():
            best_course: tuple[float, float, int] | None = None
            for policy_index, outcomes in enumerate(outcomes_by_course[course]):
                roi, hit_rate = evaluate_policy(outcomes, indices, target)
                score = roi - max(0.0, 55.0 - hit_rate) * 0.8
                if best_course is None or score > best_course[0] - max(0.0, 55.0 - best_course[1]) * 0.8:
                    best_course = (roi, hit_rate, policy_index)
            assert best_course is not None
            roi, hit_rate, policy_index = best_course
            course_results[course] = {"roiPct": roi, "hitRatePct": hit_rate, "policyIndex": policy_index}

        rois = [row["roiPct"] for row in course_results.values()]
        hits = [row["hitRatePct"] for row in course_results.values()]
        objective = min(rois) + statistics.fmean(rois) * 0.18 + min(hits) * 0.08
        if best is None or objective > best["objective"]:
            best = {
                "objective": objective,
                "racePolicy": race_policy,
                "selectedIndices": indices,
                "courses": course_results,
            }

    if best is None:
        raise RuntimeError("Optimizer did not produce a valid policy")

    selected = best["selectedIndices"]
    selected_races = [races[index] for index in selected]
    course_output: dict[str, Any] = {}
    for course, row in best["courses"].items():
        policy = policies_by_course[course][row["policyIndex"]]
        outcomes = outcomes_by_course[course][row["policyIndex"]]
        course_output[course] = {
            "roiPct": row["roiPct"],
            "hitRatePct": row["hitRatePct"],
            "stakeYen": len(selected) * COURSE_TARGETS[course],
            "returnYen": sum(outcomes[index][0] for index in selected),
            "policy": policy_to_json(policy),
        }

    selected_counts: dict[str, int] = {}
    for race in selected_races:
        key = f"{race.race_date}:{race.venue}"
        selected_counts[key] = selected_counts.get(key, 0) + 1

    return {
        "scope": "analysis-in-sample",
        "seed": seed,
        "usableRaces": len(races),
        "selectedRaces": len(selected),
        "selectedByVenue": selected_counts,
        "allCoursesAbove120": all(row["roiPct"] >= 120.0 for row in course_output.values()),
        "minimumCourseRoiPct": min(row["roiPct"] for row in course_output.values()),
        "averageCourseRoiPct": statistics.fmean(row["roiPct"] for row in course_output.values()),
        "racePolicy": {"weights": list(best["racePolicy"].weights)},
        "courses": course_output,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="Analysis-data JSON path or URL")
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--race-policies", type=int, default=900)
    parser.add_argument("--ticket-policies", type=int, default=1400)
    parser.add_argument("--output", default="analysis-roi-result.json")
    args = parser.parse_args()

    result = optimize(load_json(args.source), args.seed, args.race_policies, args.ticket_policies)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ANALYSIS_RESULT_JSON=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
