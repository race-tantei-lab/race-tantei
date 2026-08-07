import importlib.util
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-regime-online-search.py"
OUTPUT = ROOT / "analysis-results" / "exploration-course-specific-regime.json"

EXPLORATION_ID = "course-specific-regime"
FINAL_START = "2026-05-01"
RACE_COUNTS = (5, 7, 9, 12)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("course_specific_regime_base", SOURCE)


def number(value, default=0.0):
    return base.number(value, default)


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
            key=lambda race: (
                -number(race["coursePlans"][course]["selectionScorePct"]),
                int(number(race.get("raceNo"))),
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
        returned, hit = base.settle_race(race, race["coursePlans"][course])
        returns.append(returned)
        hits.append(hit)
    return base.ctx.summarize(returns, hits, constraints["courses"][course]["budgetYen"])


def robustness_for_course(selected, course, constraints):
    rows = []
    rois = []
    for start, end in base.ROBUSTNESS_PERIODS:
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


def expected_groups(races):
    grouped = defaultdict(int)
    for race in races:
        grouped[(race["raceDate"], race["venue"])] += 1
    return sum(count >= 5 for count in grouped.values())


def precompute_course_choices(planned, constraints):
    result = {}
    for course in base.ctx.TYPE_COUNTS:
        result[course] = {}
        for count in RACE_COUNTS:
            selected, coverage = select_for_course(planned, course, count)
            metrics = settle_course(selected, course, constraints)
            robust_rows, robust = robustness_for_course(selected, course, constraints)
            result[course][count] = {
                "selected": selected,
                "coverage": coverage,
                "metrics": metrics,
                "robustnessPeriods": robust_rows,
                "robustness": robust,
            }
    return result


def candidate_key(candidate):
    course_rows = candidate["developmentCourses"]
    rois = [row["roiPct"] for row in course_rows.values()]
    trimmed = [row["roiWithoutTop1Pct"] for row in course_rows.values()]
    robust_min = [
        candidate["robustness"][course]["minimumPeriodRoiPct"]
        for course in base.ctx.TYPE_COUNTS
    ]
    robust_q25 = [
        candidate["robustness"][course]["q25PeriodRoiPct"]
        for course in base.ctx.TYPE_COUNTS
    ]
    return (
        min(rois),
        min(robust_q25),
        min(trimmed),
        min(robust_min),
        float(np.mean(rois)),
    )


def clean_candidate(candidate):
    return {
        "rankMode": candidate["rankMode"],
        "profile": candidate["profile"],
        "allocationPower": candidate["allocationPower"],
        "raceCounts": candidate["raceCounts"],
        "developmentCourses": candidate["developmentCourses"],
        "robustness": candidate["robustness"],
        "coverage": candidate["coverage"],
        "objective": candidate["objective"],
    }


def evaluate_rank_profile(enriched_races, rank_mode, profile, allocation_power, constraints):
    records, frozen_store = base.simulate_development(enriched_races, rank_mode)
    planned = base.planned_races(records, profile, allocation_power, constraints)
    choices = precompute_course_choices(planned, constraints)
    expected = expected_groups([record["race"] for record in records])
    candidates = []
    for light_count, standard_count, premium_count in itertools.product(RACE_COUNTS, repeat=3):
        counts = {
            "ライト": light_count,
            "スタンダード": standard_count,
            "プレミアム": premium_count,
        }
        development = {
            course: choices[course][counts[course]]["metrics"]
            for course in base.ctx.TYPE_COUNTS
        }
        robustness = {
            course: choices[course][counts[course]]["robustness"]
            for course in base.ctx.TYPE_COUNTS
        }
        coverage = {
            course: {
                "groups": len(choices[course][counts[course]]["coverage"]),
                "expectedEligibleGroups": expected,
                "minimumSelectedRaces": min(
                    row["selected"] for row in choices[course][counts[course]]["coverage"]
                ),
                "maximumSelectedRaces": max(
                    row["selected"] for row in choices[course][counts[course]]["coverage"]
                ),
            }
            for course in base.ctx.TYPE_COUNTS
        }
        rois = [row["roiPct"] for row in development.values()]
        candidate = {
            "rankMode": rank_mode,
            "profile": profile,
            "allocationPower": allocation_power,
            "raceCounts": counts,
            "developmentCourses": development,
            "robustness": robustness,
            "coverage": coverage,
            "objective": {
                "minimumDevelopmentCourseRoiPct": min(rois),
                "meanDevelopmentCourseRoiPct": float(np.mean(rois)),
                "minimumDevelopmentRoiWithoutTop1Pct": min(
                    row["roiWithoutTop1Pct"] for row in development.values()
                ),
                "minimumRobustnessQ25RoiPct": min(
                    row["q25PeriodRoiPct"] for row in robustness.values()
                ),
                "minimumRobustnessPeriodRoiPct": min(
                    row["minimumPeriodRoiPct"] for row in robustness.values()
                ),
            },
        }
        candidates.append(candidate)
    return candidates, frozen_store


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


def main():
    constraints = base.ctx.load_constraints()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows, payouts = base.ctx.base_analysis.v4.load_data()
    base_races = base.ctx.base_analysis.v4.build_dataset(rows, payouts)
    extra_rows = base.ctx.base_analysis.v7.load_extra_rows()
    enriched_races = base.ctx.base_analysis.v7.enrich_races(base_races, extra_rows)
    enriched_races.sort(
        key=lambda race: (race["raceDate"], race["venue"], int(number(race.get("raceNo"))))
    )
    archive_start = min(race["raceDate"] for race in enriched_races)
    archive_end = max(race["raceDate"] for race in enriched_races)

    all_candidates = []
    frozen_stores = {}
    for rank_mode in base.RANK_MODES:
        records, frozen_store = base.simulate_development(enriched_races, rank_mode)
        frozen_stores[rank_mode] = frozen_store
        for profile in base.PROFILE_CONFIGS:
            for allocation_power in base.ALLOCATION_POWERS:
                planned = base.planned_races(records, profile, allocation_power, constraints)
                choices = precompute_course_choices(planned, constraints)
                expected = expected_groups([record["race"] for record in records])
                for counts_tuple in itertools.product(RACE_COUNTS, repeat=3):
                    counts = dict(zip(base.ctx.TYPE_COUNTS, counts_tuple))
                    development = {
                        course: choices[course][counts[course]]["metrics"]
                        for course in base.ctx.TYPE_COUNTS
                    }
                    robustness = {
                        course: choices[course][counts[course]]["robustness"]
                        for course in base.ctx.TYPE_COUNTS
                    }
                    coverage = {
                        course: {
                            "groups": len(choices[course][counts[course]]["coverage"]),
                            "expectedEligibleGroups": expected,
                            "minimumSelectedRaces": min(
                                row["selected"] for row in choices[course][counts[course]]["coverage"]
                            ),
                            "maximumSelectedRaces": max(
                                row["selected"] for row in choices[course][counts[course]]["coverage"]
                            ),
                        }
                        for course in base.ctx.TYPE_COUNTS
                    }
                    rois = [row["roiPct"] for row in development.values()]
                    all_candidates.append({
                        "rankMode": rank_mode,
                        "profile": profile,
                        "allocationPower": allocation_power,
                        "raceCounts": counts,
                        "developmentCourses": development,
                        "robustness": robustness,
                        "coverage": coverage,
                        "objective": {
                            "minimumDevelopmentCourseRoiPct": min(rois),
                            "meanDevelopmentCourseRoiPct": float(np.mean(rois)),
                            "minimumDevelopmentRoiWithoutTop1Pct": min(
                                row["roiWithoutTop1Pct"] for row in development.values()
                            ),
                            "minimumRobustnessQ25RoiPct": min(
                                row["q25PeriodRoiPct"] for row in robustness.values()
                            ),
                            "minimumRobustnessPeriodRoiPct": min(
                                row["minimumPeriodRoiPct"] for row in robustness.values()
                            ),
                        },
                    })

    all_candidates.sort(key=candidate_key, reverse=True)
    best = all_candidates[0]
    completion_target = float(constraints["promotionRules"]["completionRoiPct"])
    development_passed = best["objective"]["minimumDevelopmentCourseRoiPct"] >= completion_target

    courses = {}
    final_evaluated = False
    metric_completion = False
    if development_passed:
        rank_mode = best["rankMode"]
        frozen_store = frozen_stores[rank_mode]
        records = base.final_records(enriched_races, rank_mode, frozen_store)
        planned = base.planned_races(
            records,
            best["profile"],
            best["allocationPower"],
            constraints,
        )
        expected_final_groups = expected_groups([record["race"] for record in records])
        full_ok = True
        final_ok = True
        for course in base.ctx.TYPE_COUNTS:
            selected, coverage = select_for_course(planned, course, best["raceCounts"][course])
            final = settle_course(selected, course, constraints)
            full = combine(best["developmentCourses"][course], final, archive_start, archive_end)
            all_groups_covered = (
                int(best["coverage"][course]["groups"])
                == int(best["coverage"][course]["expectedEligibleGroups"])
                and len(coverage) == expected_final_groups
            )
            representative = [
                base.ctx.clean_ticket(ticket)
                for ticket in selected[0]["coursePlans"][course]["tickets"]
            ] if selected else []
            courses[course] = {
                "fullHistorical": full,
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
            full_ok = full_ok and full["roiPct"] >= float(
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
            "primary": "select each course's minimum five venue-day races independently using only past contextual return evidence",
            "completionRoiPct": completion_target,
            "minimumRacesPerVenueDayPerCourse": 5,
            "allCourseBetTypesRequired": True,
            "courseRaceSetsMayDiffer": True,
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
            "rankModes": list(base.RANK_MODES),
            "profiles": base.PROFILE_CONFIGS,
            "candidateConfigurations": len(all_candidates),
            "courseSpecificRaceSelection": True,
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
