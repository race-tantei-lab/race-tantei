import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FULL_PATH = ROOT / "scripts" / "analyze-full-period-online-search.py"
REGIME_PATH = ROOT / "scripts" / "analyze-regime-online-search.py"
OUTPUT = ROOT / "analysis-results" / "exploration-independent-edge-regime.json"

EXPLORATION_ID = "independent-edge-regime"
FINAL_START = "2026-05-01"
RACE_COUNTS = (5, 7, 9, 12)
RANDOM_SEED = 2026080721


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


full = load_module("independent_edge_full", FULL_PATH)
regime = load_module("independent_edge_regime", REGIME_PATH)
ctx = regime.ctx

EDGE_PROFILES = {
    "edge-balanced": {
        "shrink": 75.0,
        "probPower": 0.24,
        "tailBias": 0.06,
        "weights": {
            "global": 0.12,
            "surfaceDistance": 0.12,
            "venue": 0.06,
            "marketShape": 0.13,
            "form": 0.13,
            "mixed": 0.08,
            "edge": 0.22,
            "edgeContext": 0.14,
        },
    },
    "edge-strong": {
        "shrink": 60.0,
        "probPower": 0.30,
        "tailBias": 0.08,
        "weights": {
            "global": 0.08,
            "surfaceDistance": 0.10,
            "venue": 0.05,
            "marketShape": 0.10,
            "form": 0.12,
            "mixed": 0.08,
            "edge": 0.29,
            "edgeContext": 0.18,
        },
    },
    "edge-tail": {
        "shrink": 95.0,
        "probPower": 0.18,
        "tailBias": 0.20,
        "weights": {
            "global": 0.15,
            "surfaceDistance": 0.11,
            "venue": 0.06,
            "marketShape": 0.13,
            "form": 0.11,
            "mixed": 0.08,
            "edge": 0.22,
            "edgeContext": 0.14,
        },
    },
}

ALLOCATION_POWERS = (1.5, 3.0, 6.0, 10.0)


def number(value, default=0.0):
    return regime.number(value, default)


def edge_bucket(value):
    return regime.bucket(value, (0.75, 0.95, 1.10, 1.30, 1.65, 2.20))


def disagreement_bucket(value):
    return regime.bucket(value, (0.15, 0.30, 0.50, 0.80, 1.20))


def enrich_edge_context(race):
    item = dict(race)
    runners = []
    for runner in race.get("runners", []):
        copied = dict(runner)
        copied["regimeFormSignal"] = regime.form_signal(copied)
        runners.append(copied)
    item["runners"] = runners
    return item


def edge_regime_keys(race):
    keys = regime.regime_keys(race)
    runners = race.get("runners", [])
    top = runners[0] if runners else {}
    top_edge = number(top.get("edge"), 1.0)
    max_edge = max((number(row.get("edge"), 1.0) for row in runners[:8]), default=1.0)
    market_rank = int(number(top.get("popularity"), 18.0))
    disagreement = sum(
        abs(number(row.get("probability")) - number(row.get("market")))
        for row in runners
    )
    surface = str(race.get("surface") or "unknown")
    distance = regime.distance_band(race.get("distanceM"))
    keys["edge"] = (
        "edge",
        edge_bucket(top_edge),
        edge_bucket(max_edge),
        disagreement_bucket(disagreement),
        regime.bucket(market_rank, (2, 4, 7, 11)),
    )
    keys["edgeContext"] = (
        "edgeContext",
        surface,
        distance,
        edge_bucket(max_edge),
        regime.bucket(market_rank, (2, 4, 7, 11)),
    )
    return keys


regime.regime_keys = edge_regime_keys
regime.PROFILE_CONFIGS = EDGE_PROFILES


def process_segment(predicted, store):
    records = []
    for race in sorted(
        predicted,
        key=lambda row: (row["raceDate"], row["venue"], int(number(row.get("raceNo")))),
    ):
        prepared = enrich_edge_context(race)
        keys, summary = regime.candidate_summary(prepared, store)
        records.append(regime.race_signal_record(prepared, summary))
        for primitive in ctx.PRIMITIVES:
            probability = regime.event_probability(prepared, primitive)
            returned = regime.primitive_return_multiple(prepared, primitive)
            regime.update_store(store, primitive, keys, returned, probability)
    return records


def build_development(enriched_races, archive_start):
    store = {}
    records = []
    audit = []
    segments = full.development_segments(archive_start, FINAL_START)
    for index, (start, end) in enumerate(segments):
        training = [race for race in enriched_races if race["raceDate"] < start]
        target = [race for race in enriched_races if start <= race["raceDate"] < end]
        if not target:
            continue
        predicted, ranking_mode = full.ranking_predictions(training, target)
        segment_records = process_segment(predicted, store)
        records.extend(segment_records)
        audit.append({
            "period": f"{start}..{end}",
            "rankingMode": ranking_mode,
            "rankingTrainingRaces": len(training),
            "targetRaces": len(target),
            "historicalReturnStoreFrozenBeforeEachRace": True,
        })
    return records, store, audit


def build_final(enriched_races, frozen_store):
    training = [race for race in enriched_races if race["raceDate"] < FINAL_START]
    target = [race for race in enriched_races if race["raceDate"] >= FINAL_START]
    predicted, ranking_mode = full.ranking_predictions(training, target)
    records = []
    for race in sorted(
        predicted,
        key=lambda row: (row["raceDate"], row["venue"], int(number(row.get("raceNo")))),
    ):
        prepared = enrich_edge_context(race)
        _, summary = regime.candidate_summary(prepared, frozen_store)
        records.append(regime.race_signal_record(prepared, summary))
    return records, {
        "rankingMode": ranking_mode,
        "rankingTrainingRaces": len(training),
        "targetRaces": len(target),
        "historicalReturnStoreFrozenThroughoutHoldout": True,
    }


def select_for_course(races, course, count):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    coverage = []
    for key, group in sorted(grouped.items()):
        if len(group) < 5:
            continue
        take = min(len(group), max(5, int(count)))
        ranked = sorted(
            group,
            key=lambda row: (
                -number(row["coursePlans"][course]["selectionScorePct"]),
                -number(row.get("maxEdge")),
                int(number(row.get("raceNo"))),
            ),
        )
        picked = ranked[:take]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    if not coverage or min(row["selected"] for row in coverage) < 5:
        raise RuntimeError(f"COURSE_SELECTION_BELOW_FIVE:{course}")
    return selected, coverage


def settle_course(selected, course, constraints):
    returns = []
    hits = []
    for race in selected:
        returned, hit = regime.settle_race(race, race["coursePlans"][course])
        returns.append(returned)
        hits.append(hit)
    return ctx.summarize(returns, hits, constraints["courses"][course]["budgetYen"])


def robustness(selected, course, constraints):
    rows = []
    rois = []
    for start, end in regime.ROBUSTNESS_PERIODS:
        subset = [race for race in selected if start <= race["raceDate"] < end]
        if not subset:
            continue
        metrics = settle_course(subset, course, constraints)
        rows.append({"period": f"{start}..{end}", "metrics": metrics})
        rois.append(metrics["roiPct"])
    return rows, {
        "minimumPeriodRoiPct": min(rois) if rois else 0.0,
        "q25PeriodRoiPct": float(np.quantile(rois, 0.25)) if rois else 0.0,
    }


def expected_groups(records):
    grouped = defaultdict(int)
    for record in records:
        race = record["race"] if "race" in record else record
        grouped[(race["raceDate"], race["venue"])] += 1
    return sum(count >= 5 for count in grouped.values())


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


def candidate_key(row):
    development = row["developmentCourses"]
    rois = [value["roiPct"] for value in development.values()]
    trimmed = [value["roiWithoutTop1Pct"] for value in development.values()]
    robust_q25 = [row["robustness"][course]["q25PeriodRoiPct"] for course in ctx.TYPE_COUNTS]
    robust_min = [row["robustness"][course]["minimumPeriodRoiPct"] for course in ctx.TYPE_COUNTS]
    return (
        min(rois),
        min(robust_q25),
        min(trimmed),
        min(robust_min),
        float(np.mean(rois)),
    )


def clean_candidate(row):
    return {
        key: row[key]
        for key in (
            "profile",
            "allocationPower",
            "raceCounts",
            "developmentCourses",
            "robustness",
            "coverage",
            "objective",
        )
    }


def main():
    constraints = ctx.load_constraints()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    rows, payouts = ctx.base_analysis.v4.load_data()
    base_races = ctx.base_analysis.v4.build_dataset(rows, payouts)
    extra_rows = ctx.base_analysis.v7.load_extra_rows()
    enriched_races = ctx.base_analysis.v7.enrich_races(base_races, extra_rows)
    enriched_races.sort(
        key=lambda race: (race["raceDate"], race["venue"], int(number(race.get("raceNo"))))
    )
    archive_start = min(race["raceDate"] for race in enriched_races)
    archive_end = max(race["raceDate"] for race in enriched_races)

    records, frozen_store, ranking_audit = build_development(enriched_races, archive_start)
    expected_development_groups = expected_groups(records)
    all_candidates = []

    for profile in EDGE_PROFILES:
        for allocation_power in ALLOCATION_POWERS:
            planned = regime.planned_races(records, profile, allocation_power, constraints)
            choices = {}
            for course in ctx.TYPE_COUNTS:
                choices[course] = {}
                for count in RACE_COUNTS:
                    selected, coverage = select_for_course(planned, course, count)
                    metrics = settle_course(selected, course, constraints)
                    robust_rows, robust = robustness(selected, course, constraints)
                    choices[course][count] = {
                        "metrics": metrics,
                        "coverage": coverage,
                        "robustnessPeriods": robust_rows,
                        "robustness": robust,
                    }
            for counts_tuple in itertools.product(RACE_COUNTS, repeat=3):
                counts = dict(zip(ctx.TYPE_COUNTS, counts_tuple))
                development = {
                    course: choices[course][counts[course]]["metrics"]
                    for course in ctx.TYPE_COUNTS
                }
                robust = {
                    course: choices[course][counts[course]]["robustness"]
                    for course in ctx.TYPE_COUNTS
                }
                coverage = {
                    course: {
                        "groups": len(choices[course][counts[course]]["coverage"]),
                        "expectedEligibleGroups": expected_development_groups,
                        "minimumSelectedRaces": min(
                            row["selected"] for row in choices[course][counts[course]]["coverage"]
                        ),
                        "maximumSelectedRaces": max(
                            row["selected"] for row in choices[course][counts[course]]["coverage"]
                        ),
                    }
                    for course in ctx.TYPE_COUNTS
                }
                rois = [row["roiPct"] for row in development.values()]
                all_candidates.append({
                    "profile": profile,
                    "allocationPower": allocation_power,
                    "raceCounts": counts,
                    "developmentCourses": development,
                    "robustness": robust,
                    "coverage": coverage,
                    "objective": {
                        "minimumDevelopmentCourseRoiPct": min(rois),
                        "meanDevelopmentCourseRoiPct": float(np.mean(rois)),
                        "minimumDevelopmentRoiWithoutTop1Pct": min(
                            row["roiWithoutTop1Pct"] for row in development.values()
                        ),
                        "minimumRobustnessQ25RoiPct": min(
                            row["q25PeriodRoiPct"] for row in robust.values()
                        ),
                        "minimumRobustnessPeriodRoiPct": min(
                            row["minimumPeriodRoiPct"] for row in robust.values()
                        ),
                    },
                })

    all_candidates.sort(key=candidate_key, reverse=True)
    best = all_candidates[0]
    completion_target = float(constraints["promotionRules"]["completionRoiPct"])
    development_passed = best["objective"]["minimumDevelopmentCourseRoiPct"] >= completion_target

    courses = {}
    final_audit = None
    final_evaluated = False
    metric_completion = False
    if development_passed:
        final_records, final_audit = build_final(enriched_races, frozen_store)
        planned = regime.planned_races(
            final_records,
            best["profile"],
            best["allocationPower"],
            constraints,
        )
        expected_final_groups = expected_groups(final_records)
        full_ok = True
        final_ok = True
        for course in ctx.TYPE_COUNTS:
            selected, coverage = select_for_course(planned, course, best["raceCounts"][course])
            final = settle_course(selected, course, constraints)
            full_metric = combine(best["developmentCourses"][course], final, archive_start, archive_end)
            all_groups_covered = (
                int(best["coverage"][course]["groups"])
                == int(best["coverage"][course]["expectedEligibleGroups"])
                and len(coverage) == expected_final_groups
            )
            representative = [
                ctx.clean_ticket(ticket)
                for ticket in selected[0]["coursePlans"][course]["tickets"]
            ] if selected else []
            courses[course] = {
                "fullHistorical": full_metric,
                "finalHoldout": final,
                "coverage": {
                    "minimumSelectedRaces": min(
                        int(best["coverage"][course]["minimumSelectedRaces"]),
                        min(int(row["selected"]) for row in coverage),
                    ),
                    "allEligibleVenueDaysCovered": all_groups_covered,
                    "developmentGroups": int(best["coverage"][course]["groups"]),
                    "finalGroups": len(coverage),
                    "selectedRacesPerVenueDay": int(best["raceCounts"][course]),
                },
                "policy": {
                    "representativeTickets": representative,
                    "ticketCount": int(constraints["courses"][course]["ticketCount"]),
                    "requiredBetTypes": constraints["courses"][course]["allowedBetTypes"],
                },
            }
            full_ok = full_ok and full_metric["roiPct"] >= float(
                constraints["promotionRules"]["requireFullHistoricalRoiPct"]
            )
            final_ok = final_ok and (
                final["races"] >= int(constraints["promotionRules"]["minimumFinalHoldoutRacesPerCourse"])
                and final["roiPct"] >= float(constraints["promotionRules"]["requireFinalHoldoutRoiPct"])
                and final["roiWithoutTop1Pct"] >= float(constraints["promotionRules"]["requireRoiWithoutTop1Pct"])
                and all_groups_covered
            )
        final_evaluated = True
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
            "primary": "combine market-independent chronological horse ranking, explicit model-vs-market edge regimes, past-only realized returns, and course-specific minimum-five race selection",
            "completionRoiPct": completion_target,
            "minimumRacesPerVenueDayPerCourse": 5,
            "marketFeaturesExcludedFromRankingModel": True,
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
            "ranking": ranking_audit,
            "finalRanking": final_audit,
            "profiles": EDGE_PROFILES,
            "candidateConfigurations": len(all_candidates),
            "edgeFeatures": ["topEdge", "maxEdgeTop8", "modelMarketDisagreement", "marketPopularityRank"],
            "currentRaceCombinationOddsUsedInBacktest": False,
        },
        "selectedConfiguration": clean_candidate(best),
        "topConfigurations": [clean_candidate(row) for row in all_candidates[:20]],
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
