import calendar
import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "scripts" / "analyze-expanded-context-search.py"
CONSTRAINTS_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
OUTPUT = ROOT / "analysis-results" / "exploration-full-period-online.json"

EXPLORATION_ID = "full-period-online-context"
FINAL_START = "2026-05-01"
RANDOM_SEED = 2026080715
MIN_RANKING_TRAIN_RACES = 250
MIN_TICKET_TRAIN_RACES = 250

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


ctx = load_module("full_period_context", CONTEXT_PATH)
if not hasattr(ctx.base_analysis.v7, "month_sequence"):
    ctx.base_analysis.v7.month_sequence = ctx.base_analysis.v7.v7.month_sequence


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def next_month(value):
    year, month = map(int, value[:7].split("-"))
    if month == 12:
        return f"{year + 1:04d}-01-01"
    return f"{year:04d}-{month + 1:02d}-01"


def month_end_exclusive(value):
    return next_month(value[:7] + "-01")


def quarter_start(value):
    year, month = map(int, value[:7].split("-"))
    start_month = ((month - 1) // 3) * 3 + 1
    return f"{year:04d}-{start_month:02d}-01"


def next_quarter(value):
    year, month = map(int, value[:7].split("-"))
    start_month = ((month - 1) // 3) * 3 + 1
    if start_month == 10:
        return f"{year + 1:04d}-01-01"
    return f"{year:04d}-{start_month + 3:02d}-01"


def development_segments(archive_start, development_end):
    segments = []
    cursor = archive_start[:7] + "-01"
    while cursor < development_end:
        q_end = next_quarter(cursor)
        end = min(q_end, development_end)
        start = max(cursor, archive_start)
        if start < end:
            segments.append((start, end))
        cursor = end
    return segments


def market_only_predictions(races):
    output = []
    for race in races:
        item = dict(race)
        runners = []
        total = sum(max(0.0, number(row.get("market"))) for row in race.get("runners", []))
        for runner in race.get("runners", []):
            copied = dict(runner)
            probability = max(0.0, number(runner.get("market"))) / max(1e-12, total)
            copied["probability"] = probability
            copied["edge"] = 1.0
            runners.append(copied)
        runners.sort(key=lambda row: (-number(row.get("probability")), int(number(row.get("horseNo")))))
        item["runners"] = runners
        if runners:
            item["topProbability"] = number(runners[0].get("probability"))
            item["probabilityGap"] = (
                number(runners[0].get("probability")) - number(runners[1].get("probability"))
                if len(runners) > 1 else number(runners[0].get("probability"))
            )
            item["top3Concentration"] = sum(number(row.get("probability")) for row in runners[:3])
            item["maxEdge"] = 1.0
            item["disagreement"] = 0.0
            item["entropy"] = -sum(
                number(row.get("probability")) * math.log(max(1e-12, number(row.get("probability"))))
                for row in runners
            )
        output.append(item)
    return output


def ranking_predictions(training, target):
    if len(training) < MIN_RANKING_TRAIN_RACES:
        return market_only_predictions(target), "market-only-cold-start"
    point_model = ctx.base_analysis.v7.fit_pointwise(training)
    pair_model = ctx.base_analysis.v7.v6.fit_pairwise(training, ctx.base_analysis.v7.PAIR_CONFIG)
    return ctx.base_analysis.v7.attach_variant(target, point_model, pair_model, "ensemble"), "form-ensemble"


def ordered_probability(order, weights):
    remaining = sum(weights.values())
    probability = 1.0
    used = set()
    for horse_no in order:
        if horse_no in used or remaining <= 0:
            return 0.0
        weight = weights.get(horse_no, 0.0)
        if weight <= 0:
            return 0.0
        probability *= weight / remaining
        remaining -= weight
        used.add(horse_no)
    return max(0.0, min(1.0, probability))


def unordered_top_two(a, b, weights):
    return ordered_probability((a, b), weights) + ordered_probability((b, a), weights)


def unordered_top_three(horses, weights):
    if len(set(horses)) != 3:
        return 0.0
    return sum(ordered_probability(order, weights) for order in itertools.permutations(horses))


def wide_probability(a, b, weights):
    if a == b or len(weights) < 3:
        return 0.0
    return sum(
        unordered_top_three((a, b, third), weights)
        for third in weights
        if third not in {a, b}
    )


def primitive_hit_probability(race, primitive):
    _, bet_type, ranks = primitive
    runners = list(race.get("runners") or [])
    selected = [runners[rank - 1] for rank in ranks if 0 < rank <= len(runners)]
    if len(selected) != len(ranks):
        return 0.0
    weights = {
        int(row["horseNo"]): max(1e-12, number(row.get("probability")))
        for row in runners
    }
    total = sum(weights.values())
    weights = {key: value / max(1e-12, total) for key, value in weights.items()}
    horses = tuple(int(row["horseNo"]) for row in selected)
    if bet_type == "単勝":
        return weights.get(horses[0], 0.0)
    if bet_type == "ワイド":
        return max(0.0, min(1.0, wide_probability(horses[0], horses[1], weights)))
    if bet_type == "馬連":
        return max(0.0, min(1.0, unordered_top_two(horses[0], horses[1], weights)))
    if bet_type == "馬単":
        return max(0.0, min(1.0, ordered_probability(horses[:2], weights)))
    if bet_type == "3連複":
        return max(0.0, min(1.0, unordered_top_three(horses[:3], weights)))
    return max(0.0, min(1.0, ordered_probability(horses[:3], weights)))


def cold_start_components(races):
    output = []
    for race in races:
        components = {}
        for primitive in ctx.PRIMITIVES:
            hit = primitive_hit_probability(race, primitive)
            components[primitive[0]] = {
                "hit": hit,
                "payout": 1.0,
                "expected": hit,
                "prior": hit,
            }
        item = dict(race)
        item["primitiveComponents"] = components
        output.append(item)
    return output


def ticket_components(training_predictions, target_predictions, seed):
    if len(training_predictions) < MIN_TICKET_TRAIN_RACES:
        return cold_start_components(target_predictions), {
            "mode": "probability-only-cold-start",
            "trainingRaces": len(training_predictions),
        }
    models, priors, audit = ctx.fit_two_stage_models(training_predictions, seed)
    return ctx.predict_components(target_predictions, models, priors), {
        "mode": "two-stage-hit-payout",
        "trainingRaces": len(training_predictions),
        "models": audit,
    }


def build_online_development(enriched_races, archive_start):
    segments = development_segments(archive_start, FINAL_START)
    prior_predictions = []
    component_races = []
    audit = []
    for index, (start, end) in enumerate(segments):
        ranking_training = [race for race in enriched_races if race["raceDate"] < start]
        target = [race for race in enriched_races if start <= race["raceDate"] < end]
        if not target:
            continue
        predicted, ranking_mode = ranking_predictions(ranking_training, target)
        components, ticket_audit = ticket_components(
            prior_predictions,
            predicted,
            RANDOM_SEED + index * 1000,
        )
        component_races.extend(components)
        prior_predictions.extend(predicted)
        audit.append({
            "period": f"{start}..{end}",
            "rankingMode": ranking_mode,
            "rankingTrainingRaces": len(ranking_training),
            "targetRaces": len(target),
            "ticketModel": ticket_audit,
        })
    return component_races, prior_predictions, audit


def build_frozen_final(enriched_races, development_predictions):
    ranking_training = [race for race in enriched_races if race["raceDate"] < FINAL_START]
    target = [race for race in enriched_races if race["raceDate"] >= FINAL_START]
    predicted, ranking_mode = ranking_predictions(ranking_training, target)
    components, ticket_audit = ticket_components(
        development_predictions,
        predicted,
        RANDOM_SEED + 90_000,
    )
    return components, {
        "period": f"{FINAL_START}..end",
        "rankingMode": ranking_mode,
        "rankingTrainingRaces": len(ranking_training),
        "targetRaces": len(target),
        "ticketModel": ticket_audit,
        "frozenThroughoutHoldout": True,
    }


def filter_selected(selected, start, end):
    return [race for race in selected if start <= race["raceDate"] < end]


def robustness_metrics(selected, constraints):
    rows = []
    for start, end in ROBUSTNESS_PERIODS:
        subset = filter_selected(selected, start, end)
        if subset:
            rows.append({
                "period": f"{start}..{end}",
                "courses": ctx.evaluate_selected(subset, constraints),
            })
    rois = [metrics["roiPct"] for row in rows for metrics in row["courses"].values()]
    return rows, {
        "minimumPeriodCourseRoiPct": min(rois) if rois else 0.0,
        "q25PeriodCourseRoiPct": float(np.quantile(rois, 0.25)) if rois else 0.0,
    }


def development_objective(selected, constraints):
    courses = ctx.evaluate_selected(selected, constraints)
    robustness, robust_score = robustness_metrics(selected, constraints)
    rois = [row["roiPct"] for row in courses.values()]
    trimmed = [row["roiWithoutTop1Pct"] for row in courses.values()]
    return courses, robustness, {
        "minimumDevelopmentCourseRoiPct": min(rois),
        "meanDevelopmentCourseRoiPct": float(np.mean(rois)),
        "minimumDevelopmentRoiWithoutTop1Pct": min(trimmed),
        **robust_score,
    }


def expected_eligible_groups(races):
    grouped = defaultdict(int)
    for race in races:
        grouped[(race["raceDate"], race["venue"])] += 1
    return sum(1 for count in grouped.values() if count >= 5)


def combine_two_metrics(first, second, period_start, period_end):
    races = int(first["races"]) + int(second["races"])
    hits = int(first["hits"]) + int(second["hits"])
    stake = int(first["stakeYen"]) + int(second["stakeYen"])
    returned = int(first["returnYen"]) + int(second["returnYen"])
    top = max(int(first.get("topReturnYen", 0)), int(second.get("topReturnYen", 0)))
    return {
        "periodStart": period_start,
        "periodEnd": period_end,
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


def clean_representative_policy(selected):
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

    development_components, development_predictions, online_audit = build_online_development(
        enriched_races,
        archive_start,
    )

    candidates = []
    for model_weight in ctx.MODEL_WEIGHTS:
        for payout_bias in ctx.PAYOUT_BIASES:
            for hit_bias in ctx.HIT_BIASES:
                score_config = (model_weight, payout_bias, hit_bias)
                for allocation_power in ctx.ALLOCATION_POWERS:
                    planned = ctx.attach_plans(
                        development_components,
                        constraints,
                        score_config,
                        allocation_power,
                    )
                    for race_count in ctx.RACE_COUNTS:
                        for race_mode in ctx.RACE_SCORE_MODES:
                            selected, coverage = ctx.select_races(planned, race_count, race_mode)
                            course_metrics, robustness, objective = development_objective(selected, constraints)
                            candidates.append({
                                "modelWeight": model_weight,
                                "payoutBias": payout_bias,
                                "hitBias": hit_bias,
                                "allocationPower": allocation_power,
                                "racesPerVenueDay": race_count,
                                "raceScoreMode": race_mode,
                                "objective": objective,
                                "developmentCourses": course_metrics,
                                "robustnessPeriods": robustness,
                                "coverage": {
                                    "groups": len(coverage),
                                    "expectedEligibleGroups": expected_eligible_groups(development_components),
                                    "minimumSelectedRaces": min(row["selected"] for row in coverage),
                                    "maximumSelectedRaces": max(row["selected"] for row in coverage),
                                },
                            })

    candidates.sort(key=lambda row: (
        row["objective"]["minimumDevelopmentCourseRoiPct"],
        row["objective"]["q25PeriodCourseRoiPct"],
        row["objective"]["minimumDevelopmentRoiWithoutTop1Pct"],
        row["objective"]["meanDevelopmentCourseRoiPct"],
    ), reverse=True)
    best = candidates[0]
    completion_roi = float(constraints["promotionRules"]["completionRoiPct"])
    development_passed = best["objective"]["minimumDevelopmentCourseRoiPct"] >= completion_roi

    final_result = None
    final_selected = []
    final_coverage = []
    final_audit = None
    if development_passed:
        final_components, final_audit = build_frozen_final(enriched_races, development_predictions)
        score_config = (best["modelWeight"], best["payoutBias"], best["hitBias"])
        final_planned = ctx.attach_plans(
            final_components,
            constraints,
            score_config,
            best["allocationPower"],
        )
        final_selected, final_coverage = ctx.select_races(
            final_planned,
            best["racesPerVenueDay"],
            best["raceScoreMode"],
        )
        final_result = ctx.evaluate_selected(final_selected, constraints)

    courses = {}
    metric_completion_passed = False
    if final_result is not None:
        representative = clean_representative_policy(final_selected)
        full_ok = True
        final_ok = True
        development_groups = int(best["coverage"]["groups"])
        expected_development_groups = int(best["coverage"]["expectedEligibleGroups"])
        expected_final_groups = expected_eligible_groups([
            race for race in enriched_races if race["raceDate"] >= FINAL_START
        ])
        for course in ctx.TYPE_COUNTS:
            development = best["developmentCourses"][course]
            final = final_result[course]
            full = combine_two_metrics(development, final, archive_start, archive_end)
            minimum_coverage = min(
                int(best["coverage"]["minimumSelectedRaces"]),
                min(int(row["selected"]) for row in final_coverage),
            )
            all_groups_covered = (
                development_groups == expected_development_groups
                and len(final_coverage) == expected_final_groups
            )
            courses[course] = {
                "fullHistorical": full,
                "finalHoldout": final,
                "coverage": {
                    "minimumSelectedRaces": minimum_coverage,
                    "allEligibleVenueDaysCovered": all_groups_covered,
                    "developmentGroups": development_groups,
                    "finalGroups": len(final_coverage),
                    "expectedDevelopmentGroups": expected_development_groups,
                    "expectedFinalGroups": expected_final_groups,
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
        metric_completion_passed = full_ok and final_ok

    report = {
        "generatedAt": "2026-08-07",
        "explorationId": EXPLORATION_ID,
        "productionChanged": False,
        "promotionEligible": metric_completion_passed,
        "metricCompletionPassed": metric_completion_passed,
        "developmentPassedCompletionRoi": development_passed,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "liveBetGenerationRequiresOfficialCombinationOdds": True,
        "fullAvailablePeriodEvaluated": final_result is not None,
        "coldStartIncluded": True,
        "searchObjective": {
            "primary": "online chronological full-period validation with a fixed market-only cold start, past-only model updates, and a frozen final holdout",
            "completionRoiPct": completion_roi,
            "minimumRacesPerVenueDay": 5,
            "singleOnlyPortfolioForbidden": True,
            "allCourseBetTypesRequired": True,
            "developmentUsesFullAvailablePreHoldoutPeriod": True,
            "finalHoldoutUntouchedUntilDevelopmentPasses": True,
        },
        "period": {
            "archiveStart": archive_start,
            "archiveEnd": archive_end,
            "archiveFinishedRaces": len(enriched_races),
            "fullHistoricalStart": archive_start if final_result is not None else None,
            "fullHistoricalEnd": archive_end if final_result is not None else None,
            "developmentStart": archive_start,
            "developmentEndExclusive": FINAL_START,
            "finalHoldoutStart": FINAL_START,
        },
        "modelAudit": {
            "onlineDevelopment": online_audit,
            "finalFrozen": final_audit,
            "primitiveCount": len(ctx.PRIMITIVES),
            "candidateConfigurations": len(candidates),
            "coldStartRanking": "JRA official win-market probabilities only; no synthetic combination odds",
            "coldStartTickets": "probability-only ranking inside each required bet type; settlement uses actual JRA payouts",
        },
        "selectedConfiguration": best,
        "topConfigurations": candidates[:20],
        "finalHoldoutEvaluated": final_result is not None,
        "courses": courses,
    }

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "explorationId": EXPLORATION_ID,
        "archiveStart": archive_start,
        "archiveEnd": archive_end,
        "archiveFinishedRaces": len(enriched_races),
        "candidateConfigurations": len(candidates),
        "developmentGatePassed": development_passed,
        "metricCompletionPassed": metric_completion_passed,
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
