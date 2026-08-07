import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "scripts" / "analyze-expanded-context-search.py"
OUTPUT = ROOT / "analysis-results" / "exploration-regime-online.json"

EXPLORATION_ID = "regime-online-context"
FINAL_START = "2026-05-01"
NEUTRAL_RETURN_PRIOR = 0.75

RANK_MODES = ("market", "balanced_form", "form_heavy")
PROFILE_CONFIGS = {
    "stable": {
        "shrink": 180.0,
        "probPower": 0.20,
        "tailBias": 0.00,
        "weights": {"global": 0.35, "surfaceDistance": 0.20, "venue": 0.10, "marketShape": 0.20, "form": 0.15},
    },
    "context": {
        "shrink": 80.0,
        "probPower": 0.25,
        "tailBias": 0.05,
        "weights": {"global": 0.20, "surfaceDistance": 0.20, "venue": 0.12, "marketShape": 0.20, "form": 0.16, "mixed": 0.12},
    },
    "form": {
        "shrink": 65.0,
        "probPower": 0.30,
        "tailBias": 0.08,
        "weights": {"global": 0.18, "surfaceDistance": 0.16, "venue": 0.08, "marketShape": 0.16, "form": 0.28, "mixed": 0.14},
    },
    "tail": {
        "shrink": 110.0,
        "probPower": 0.12,
        "tailBias": 0.18,
        "weights": {"global": 0.28, "surfaceDistance": 0.18, "venue": 0.10, "marketShape": 0.20, "form": 0.12, "mixed": 0.12},
    },
}

ALLOCATION_POWERS = (1.5, 3.0, 6.0, 10.0)
RACE_COUNTS = (5, 7, 9, 12)
RACE_SCORE_MODES = ("minimum", "lower_mean", "mean")
MAX_TICKET_SHARE = {"ライト": 0.45, "スタンダード": 0.40, "プレミアム": 0.35}
ROBUSTNESS_PERIODS = (
    ("2024-05-01", "2024-11-01"),
    ("2024-11-01", "2025-05-01"),
    ("2025-05-01", "2025-11-01"),
    ("2025-11-01", "2026-05-01"),
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ctx = load_module("regime_context", CONTEXT_PATH)
if not hasattr(ctx.base_analysis.v7, "month_sequence"):
    ctx.base_analysis.v7.month_sequence = ctx.base_analysis.v7.v7.month_sequence


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def feature(runner, index, default=0.0):
    values = runner.get("features") or []
    return number(values[index], default) if index < len(values) else default


def form_signal(runner):
    return (
        1.45 * feature(runner, 3)
        + 1.10 * feature(runner, 4)
        + 0.70 * feature(runner, 5)
        + 0.80 * feature(runner, 7)
        + 1.10 * feature(runner, 8)
        + 0.55 * feature(runner, 9)
        + 1.15 * feature(runner, 17)
        + 0.90 * feature(runner, 18)
        + 0.65 * feature(runner, 61)
        + 0.45 * feature(runner, 63)
        + 0.80 * feature(runner, 64)
        + 0.45 * feature(runner, 66)
        + 0.65 * feature(runner, 67)
        + 0.35 * feature(runner, 69)
        + 0.55 * feature(runner, 70)
        + 0.30 * feature(runner, 72)
        + 0.55 * feature(runner, 73)
        + 0.40 * feature(runner, 74)
    )


def softmax(values, temperature=1.0):
    if not values:
        return []
    raw = np.asarray(values, dtype=float) / max(1e-6, temperature)
    raw -= float(np.max(raw))
    exp = np.exp(np.clip(raw, -30.0, 30.0))
    total = float(exp.sum())
    return list(exp / max(1e-12, total))


def rerank_race(race, mode):
    item = dict(race)
    runners = [dict(row) for row in race.get("runners", [])]
    if not runners:
        item["runners"] = []
        return item
    market = np.asarray([max(1e-9, number(row.get("market"))) for row in runners], dtype=float)
    market /= max(1e-12, float(market.sum()))
    forms = np.asarray([form_signal(row) for row in runners], dtype=float)
    if len(forms) > 1 and float(np.std(forms)) > 1e-9:
        forms = (forms - float(np.mean(forms))) / float(np.std(forms))
    else:
        forms = np.zeros_like(forms)
    form_probs = np.asarray(softmax(list(forms), temperature=1.35), dtype=float)
    if mode == "market":
        blend = market
    elif mode == "balanced_form":
        blend = np.power(market, 0.60) * np.power(np.maximum(form_probs, 1e-9), 0.40)
    else:
        blend = np.power(market, 0.35) * np.power(np.maximum(form_probs, 1e-9), 0.65)
    blend /= max(1e-12, float(blend.sum()))
    for runner, probability, form_value in zip(runners, blend, forms):
        runner["probability"] = float(probability)
        runner["edge"] = float(probability / max(1e-9, number(runner.get("market"))))
        runner["regimeFormSignal"] = float(form_value)
    runners.sort(key=lambda row: (-number(row.get("probability")), int(number(row.get("horseNo")))))
    item["runners"] = runners
    return item


def ordered_probability(order, weights):
    remaining = sum(weights.values())
    result = 1.0
    used = set()
    for horse_no in order:
        if horse_no in used or remaining <= 0:
            return 0.0
        value = weights.get(horse_no, 0.0)
        if value <= 0:
            return 0.0
        result *= value / remaining
        remaining -= value
        used.add(horse_no)
    return clamp(result, 0.0, 1.0)


def unordered_top_two(a, b, weights):
    return clamp(ordered_probability((a, b), weights) + ordered_probability((b, a), weights), 0.0, 1.0)


def unordered_top_three(horses, weights):
    if len(set(horses)) != 3:
        return 0.0
    return clamp(sum(ordered_probability(order, weights) for order in itertools.permutations(horses)), 0.0, 1.0)


def wide_probability(a, b, weights):
    return clamp(sum(
        unordered_top_three((a, b, third), weights)
        for third in weights
        if third not in {a, b}
    ), 0.0, 1.0)


def event_probability(race, primitive):
    _, bet_type, ranks = primitive
    runners = race.get("runners", [])
    selected = [runners[rank - 1] for rank in ranks if 0 < rank <= len(runners)]
    if len(selected) != len(ranks):
        return 0.0
    weights = {int(row["horseNo"]): max(1e-12, number(row.get("probability"))) for row in runners}
    total = sum(weights.values())
    weights = {key: value / max(1e-12, total) for key, value in weights.items()}
    horses = tuple(int(row["horseNo"]) for row in selected)
    if bet_type == "単勝":
        return weights.get(horses[0], 0.0)
    if bet_type == "ワイド":
        return wide_probability(horses[0], horses[1], weights)
    if bet_type == "馬連":
        return unordered_top_two(horses[0], horses[1], weights)
    if bet_type == "馬単":
        return ordered_probability(horses[:2], weights)
    if bet_type == "3連複":
        return unordered_top_three(horses[:3], weights)
    return ordered_probability(horses[:3], weights)


@dataclass
class OnlineStats:
    count: int = 0
    return_sum: float = 0.0
    hit_count: int = 0
    hit_return_sum: float = 0.0
    probability_sum: float = 0.0

    def update(self, returned, probability):
        self.count += 1
        self.return_sum += returned
        self.probability_sum += probability
        if returned > 0:
            self.hit_count += 1
            self.hit_return_sum += returned


def bucket(value, cuts):
    for index, cut in enumerate(cuts):
        if value < cut:
            return index
    return len(cuts)


def distance_band(distance):
    value = int(number(distance))
    if value < 1400:
        return "sprint"
    if value < 1800:
        return "mile"
    if value < 2200:
        return "middle"
    return "long"


def field_bucket(count):
    return bucket(count, (9, 12, 15))


def regime_keys(race):
    runners = race.get("runners", [])
    probabilities = [number(row.get("probability")) for row in runners]
    top = probabilities[0] if probabilities else 0.0
    second = probabilities[1] if len(probabilities) > 1 else 0.0
    entropy = -sum(value * math.log(max(1e-12, value)) for value in probabilities if value > 0)
    top_runner = runners[0] if runners else {}
    top_form = number(top_runner.get("regimeFormSignal"))
    course_place = feature(top_runner, 18)
    recent_speed = feature(top_runner, 64)
    surface = str(race.get("surface") or "unknown")
    distance = distance_band(race.get("distanceM"))
    venue = str(race.get("venue") or "")
    market_shape = (
        bucket(top, (0.10, 0.15, 0.22, 0.32)),
        bucket(top - second, (0.015, 0.04, 0.08, 0.15)),
        bucket(entropy, (1.8, 2.2, 2.6)),
    )
    form_key = (
        bucket(top_form, (-0.8, -0.2, 0.3, 0.9)),
        bucket(course_place, (0.15, 0.25, 0.40)),
        bucket(recent_speed, (-0.5, 0.0, 0.5)),
    )
    return {
        "global": ("global",),
        "surfaceDistance": ("surfaceDistance", surface, distance),
        "venue": ("venue", venue),
        "marketShape": ("marketShape", *market_shape),
        "form": ("form", *form_key),
        "mixed": ("mixed", surface, distance, field_bucket(len(runners)), market_shape[0], form_key[0]),
    }


def stats_mean(stats, shrink):
    return (stats.return_sum + NEUTRAL_RETURN_PRIOR * shrink) / (stats.count + shrink)


def stats_tail(stats):
    return stats.hit_return_sum / stats.hit_count if stats.hit_count else 1.0


def predicted_return(store, primitive, keys, probability, profile):
    config = PROFILE_CONFIGS[profile]
    shrink = config["shrink"]
    values = []
    weights = []
    avg_probability = []
    tails = []
    for name, weight in config["weights"].items():
        key = (primitive[0], *keys[name])
        stats = store.get(key)
        if stats is None:
            mean = NEUTRAL_RETURN_PRIOR
            average_prob = probability
            tail = 1.0
        else:
            mean = stats_mean(stats, shrink)
            average_prob = stats.probability_sum / stats.count if stats.count else probability
            tail = stats_tail(stats)
        values.append(mean)
        weights.append(weight)
        avg_probability.append(max(1e-9, average_prob))
        tails.append(max(1.0, tail))
    weight_sum = sum(weights)
    base_return = sum(value * weight for value, weight in zip(values, weights)) / max(1e-12, weight_sum)
    reference_probability = sum(value * weight for value, weight in zip(avg_probability, weights)) / max(1e-12, weight_sum)
    probability_adjustment = clamp(
        probability / max(1e-9, reference_probability),
        0.45,
        2.25,
    ) ** config["probPower"]
    tail_level = sum(value * weight for value, weight in zip(tails, weights)) / max(1e-12, weight_sum)
    tail_adjustment = clamp(tail_level / 8.0, 0.65, 2.50) ** config["tailBias"]
    return max(1e-6, base_return * probability_adjustment * tail_adjustment)


def update_store(store, primitive, keys, returned, probability):
    for key in keys.values():
        full_key = (primitive[0], *key)
        if full_key not in store:
            store[full_key] = OnlineStats()
        store[full_key].update(returned, probability)


def primitive_return_multiple(race, primitive):
    return min(250.0, max(0.0, ctx.base_analysis.base.primitive_payout(race, primitive) / 100.0))


def candidate_summary(race, store):
    keys = regime_keys(race)
    summary = {profile: defaultdict(list) for profile in PROFILE_CONFIGS}
    for primitive in ctx.PRIMITIVES:
        probability = event_probability(race, primitive)
        if probability <= 0:
            continue
        for profile in PROFILE_CONFIGS:
            score = predicted_return(store, primitive, keys, probability, profile)
            summary[profile][primitive[1]].append((primitive, score, probability))
    for profile in PROFILE_CONFIGS:
        for bet_type in summary[profile]:
            summary[profile][bet_type].sort(key=lambda row: (row[1], row[2], -sum(row[0][2])), reverse=True)
    return keys, summary


def race_signal_record(race, summary):
    record = {
        "race": race,
        "profiles": {},
    }
    for profile in PROFILE_CONFIGS:
        course_rows = {}
        for course, counts in ctx.TYPE_COUNTS.items():
            chosen = []
            for bet_type, count in counts.items():
                chosen.extend(summary[profile][bet_type][:count])
            course_rows[course] = chosen
        record["profiles"][profile] = course_rows
    return record


def simulate_development(enriched_races, rank_mode):
    store = {}
    records = []
    for race in enriched_races:
        if race["raceDate"] >= FINAL_START:
            break
        ranked = rerank_race(race, rank_mode)
        keys, summary = candidate_summary(ranked, store)
        records.append(race_signal_record(ranked, summary))
        for primitive in ctx.PRIMITIVES:
            probability = event_probability(ranked, primitive)
            returned = primitive_return_multiple(ranked, primitive)
            update_store(store, primitive, keys, returned, probability)
    return records, store


def allocate(chosen, budget, power, max_share):
    total_units = budget // 100
    units = [1] * len(chosen)
    max_units = max(1, int(math.floor(total_units * max_share)))
    remaining = total_units - len(chosen)
    raw = np.asarray([max(1e-8, row[1]) ** power for row in chosen], dtype=float)
    while remaining > 0:
        eligible = [index for index in range(len(units)) if units[index] < max_units]
        if not eligible:
            eligible = list(range(len(units)))
        index = max(eligible, key=lambda item: raw[item] / (units[item] ** 0.72))
        units[index] += 1
        remaining -= 1
    return units


def planned_races(records, profile, allocation_power, constraints):
    planned = []
    for record in records:
        race = dict(record["race"])
        race["coursePlans"] = {}
        for course, chosen in record["profiles"][profile].items():
            budget = int(constraints["courses"][course]["budgetYen"])
            units = allocate(chosen, budget, allocation_power, MAX_TICKET_SHARE[course])
            tickets = []
            expected = 0.0
            utility = 0.0
            for (primitive, score, probability), unit in zip(chosen, units):
                stake = unit * 100
                tickets.append({
                    "code": primitive[0],
                    "betType": primitive[1],
                    "predictedRanks": list(primitive[2]),
                    "stakeYen": stake,
                    "predictedHitProbability": probability,
                    "predictedReturnMultiple": score,
                    "selectionUtility": score,
                })
                expected += score * stake
                utility += score * stake
            race["coursePlans"][course] = {
                "budgetYen": budget,
                "predictedRoiPct": expected / budget * 100.0,
                "selectionScorePct": utility / budget * 100.0,
                "tickets": tickets,
            }
        planned.append(race)
    return planned


def race_score(race, mode):
    values = [race["coursePlans"][course]["selectionScorePct"] for course in ctx.TYPE_COUNTS]
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
        group.sort(key=lambda row: (-race_score(row, mode), int(number(row.get("raceNo")))))
        picked = group[:take]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    return selected, coverage


def settle_race(race, plan):
    total = 0.0
    hit = False
    by_code = {row[0]: row for row in ctx.PRIMITIVES}
    for ticket in plan["tickets"]:
        payout = ctx.base_analysis.base.primitive_payout(race, by_code[ticket["code"]])
        if payout > 0:
            hit = True
            total += payout * (ticket["stakeYen"] // 100)
    return total, hit


def summarize(selected, constraints):
    result = {}
    for course, spec in constraints["courses"].items():
        returns = []
        hits = []
        for race in selected:
            returned, hit = settle_race(race, race["coursePlans"][course])
            returns.append(returned)
            hits.append(hit)
        result[course] = ctx.summarize(returns, hits, spec["budgetYen"])
    return result


def robustness(selected, constraints):
    rows = []
    rois = []
    for start, end in ROBUSTNESS_PERIODS:
        subset = [race for race in selected if start <= race["raceDate"] < end]
        if not subset:
            continue
        metrics = summarize(subset, constraints)
        rows.append({"period": f"{start}..{end}", "courses": metrics})
        rois.extend(row["roiPct"] for row in metrics.values())
    return rows, {
        "minimumPeriodCourseRoiPct": min(rois) if rois else 0.0,
        "q25PeriodCourseRoiPct": float(np.quantile(rois, 0.25)) if rois else 0.0,
    }


def expected_groups(races):
    grouped = defaultdict(int)
    for race in races:
        grouped[(race["raceDate"], race["venue"])] += 1
    return sum(count >= 5 for count in grouped.values())


def search_rank_mode(enriched_races, rank_mode, constraints):
    records, frozen_store = simulate_development(enriched_races, rank_mode)
    candidates = []
    for profile in PROFILE_CONFIGS:
        for allocation_power in ALLOCATION_POWERS:
            planned = planned_races(records, profile, allocation_power, constraints)
            for race_count in RACE_COUNTS:
                for race_mode in RACE_SCORE_MODES:
                    selected, coverage = select_races(planned, race_count, race_mode)
                    metrics = summarize(selected, constraints)
                    robust_rows, robust_score = robustness(selected, constraints)
                    rois = [row["roiPct"] for row in metrics.values()]
                    trimmed = [row["roiWithoutTop1Pct"] for row in metrics.values()]
                    candidates.append({
                        "rankMode": rank_mode,
                        "profile": profile,
                        "allocationPower": allocation_power,
                        "racesPerVenueDay": race_count,
                        "raceScoreMode": race_mode,
                        "developmentCourses": metrics,
                        "robustnessPeriods": robust_rows,
                        "objective": {
                            "minimumDevelopmentCourseRoiPct": min(rois),
                            "meanDevelopmentCourseRoiPct": float(np.mean(rois)),
                            "minimumDevelopmentRoiWithoutTop1Pct": min(trimmed),
                            **robust_score,
                        },
                        "coverage": {
                            "groups": len(coverage),
                            "expectedEligibleGroups": expected_groups([record["race"] for record in records]),
                            "minimumSelectedRaces": min(row["selected"] for row in coverage),
                            "maximumSelectedRaces": max(row["selected"] for row in coverage),
                        },
                    })
    return records, frozen_store, candidates


def final_records(enriched_races, rank_mode, frozen_store):
    records = []
    for race in enriched_races:
        if race["raceDate"] < FINAL_START:
            continue
        ranked = rerank_race(race, rank_mode)
        _, summary = candidate_summary(ranked, frozen_store)
        records.append(race_signal_record(ranked, summary))
    return records


def combine(first, second, start, end):
    races = int(first["races"]) + int(second["races"])
    hits = int(first["hits"]) + int(second["hits"])
    stake = int(first["stakeYen"]) + int(second["stakeYen"])
    returned = int(first["returnYen"]) + int(second["returnYen"])
    top = max(int(first.get("topReturnYen", 0)), int(second.get("topReturnYen", 0)))
    return {
        "periodStart": start,
        "periodEnd": end,
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


def representative_policy(selected):
    if not selected:
        return {course: [] for course in ctx.TYPE_COUNTS}
    race = selected[0]
    return {
        course: [ctx.clean_ticket(ticket) for ticket in race["coursePlans"][course]["tickets"]]
        for course in ctx.TYPE_COUNTS
    }


def main():
    constraints = ctx.load_constraints()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows, payouts = ctx.base_analysis.v4.load_data()
    base_races = ctx.base_analysis.v4.build_dataset(rows, payouts)
    extra_rows = ctx.base_analysis.v7.load_extra_rows()
    enriched_races = ctx.base_analysis.v7.enrich_races(base_races, extra_rows)
    enriched_races.sort(key=lambda race: (race["raceDate"], race["venue"], int(number(race.get("raceNo")))))
    archive_start = min(race["raceDate"] for race in enriched_races)
    archive_end = max(race["raceDate"] for race in enriched_races)

    all_candidates = []
    caches = {}
    for rank_mode in RANK_MODES:
        records, frozen_store, candidates = search_rank_mode(enriched_races, rank_mode, constraints)
        caches[rank_mode] = (records, frozen_store)
        all_candidates.extend(candidates)

    all_candidates.sort(key=lambda row: (
        row["objective"]["minimumDevelopmentCourseRoiPct"],
        row["objective"]["q25PeriodCourseRoiPct"],
        row["objective"]["minimumDevelopmentRoiWithoutTop1Pct"],
        row["objective"]["meanDevelopmentCourseRoiPct"],
    ), reverse=True)
    best = all_candidates[0]
    target = float(constraints["promotionRules"]["completionRoiPct"])
    development_passed = best["objective"]["minimumDevelopmentCourseRoiPct"] >= target

    courses = {}
    metric_completion = False
    final_evaluated = False
    if development_passed:
        _, frozen_store = caches[best["rankMode"]]
        records = final_records(enriched_races, best["rankMode"], frozen_store)
        planned = planned_races(records, best["profile"], best["allocationPower"], constraints)
        selected, final_coverage = select_races(planned, best["racesPerVenueDay"], best["raceScoreMode"])
        final_metrics = summarize(selected, constraints)
        final_evaluated = True
        representative = representative_policy(selected)
        full_ok = True
        final_ok = True
        all_groups_covered = (
            int(best["coverage"]["groups"]) == int(best["coverage"]["expectedEligibleGroups"])
            and len(final_coverage) == expected_groups([record["race"] for record in records])
        )
        for course in ctx.TYPE_COUNTS:
            full = combine(best["developmentCourses"][course], final_metrics[course], archive_start, archive_end)
            final = final_metrics[course]
            courses[course] = {
                "fullHistorical": full,
                "finalHoldout": final,
                "coverage": {
                    "minimumSelectedRaces": min(
                        int(best["coverage"]["minimumSelectedRaces"]),
                        min(int(row["selected"]) for row in final_coverage),
                    ),
                    "allEligibleVenueDaysCovered": all_groups_covered,
                    "developmentGroups": int(best["coverage"]["groups"]),
                    "finalGroups": len(final_coverage),
                },
                "policy": {
                    "representativeTickets": representative[course],
                    "ticketCount": int(constraints["courses"][course]["ticketCount"]),
                    "requiredBetTypes": constraints["courses"][course]["allowedBetTypes"],
                },
            }
            full_ok = full_ok and full["roiPct"] >= float(constraints["promotionRules"]["requireFullHistoricalRoiPct"])
            final_ok = final_ok and (
                final["races"] >= int(constraints["promotionRules"]["minimumFinalHoldoutRacesPerCourse"])
                and final["roiPct"] >= float(constraints["promotionRules"]["requireFinalHoldoutRoiPct"])
                and final["roiWithoutTop1Pct"] >= float(constraints["promotionRules"]["requireRoiWithoutTop1Pct"])
                and all_groups_covered
            )
        metric_completion = full_ok and final_ok

    report = {
        "generatedAt": "2026-08-07",
        "explorationId": EXPLORATION_ID,
        "productionChanged": False,
        "promotionEligible": metric_completion,
        "metricCompletionPassed": metric_completion,
        "developmentPassedCompletionRoi": development_passed,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "liveBetGenerationRequiresOfficialCombinationOdds": True,
        "fullAvailablePeriodEvaluated": final_evaluated,
        "coldStartIncluded": True,
        "searchObjective": {
            "primary": "hierarchical past-only return learning by venue, surface, distance, field size, market shape and chronological form regimes",
            "completionRoiPct": target,
            "minimumRacesPerVenueDay": 5,
            "allCourseBetTypesRequired": True,
            "finalHoldoutFrozen": True,
        },
        "period": {
            "archiveStart": archive_start,
            "archiveEnd": archive_end,
            "archiveFinishedRaces": len(enriched_races),
            "fullHistoricalStart": archive_start if final_evaluated else None,
            "fullHistoricalEnd": archive_end if final_evaluated else None,
            "developmentStart": archive_start,
            "developmentEndExclusive": FINAL_START,
            "finalHoldoutStart": FINAL_START,
        },
        "modelAudit": {
            "rankModes": list(RANK_MODES),
            "profiles": PROFILE_CONFIGS,
            "candidateConfigurations": len(all_candidates),
            "regimes": ["venue", "surfaceDistance", "fieldSize", "marketShape", "chronologicalForm", "mixed"],
            "historicalReturnPrior": NEUTRAL_RETURN_PRIOR,
            "currentRaceCombinationOddsUsedInBacktest": False,
        },
        "selectedConfiguration": best,
        "topConfigurations": all_candidates[:20],
        "finalHoldoutEvaluated": final_evaluated,
        "courses": courses,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "explorationId": EXPLORATION_ID,
        "archiveStart": archive_start,
        "archiveEnd": archive_end,
        "archiveFinishedRaces": len(enriched_races),
        "candidateConfigurations": len(all_candidates),
        "developmentGatePassed": development_passed,
        "metricCompletionPassed": metric_completion,
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
