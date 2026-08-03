#!/usr/bin/env python3
"""Apply the immutable production-promotion gate to a walk-forward result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

COURSE_TARGETS = {"ライト": 1600, "スタンダード": 4200, "プレミアム": 8800}
MINIMUM_IMPROVEMENT_PCT = 5.0
MINIMUM_ABSOLUTE_ROI_PCT = 100.0
MINIMUM_HIT_RATE_PCT = 20.0
MAXIMUM_POSITIVE_DAY_SHARE = 0.40


def selected_race_metrics(data: dict[str, Any], split: str, course: str) -> dict[str, Any]:
    target = COURSE_TARGETS[course]
    prefix = f"{course}｜"
    selected: list[dict[str, Any]] = []
    counts_by_venue: dict[str, int] = {}
    fixed_stake_violations = 0
    daily_profit: dict[str, int] = {}

    for race in data.get("races", []):
        if race.get("split") != split:
            continue
        bets = [row for row in race.get("baselineBets", []) if str(row.get("betType", "")).startswith(prefix)]
        if not bets:
            continue
        stake = sum(int(row.get("stakeYen", 0)) for row in bets)
        returns = sum(int(row.get("returnYen", 0)) for row in bets)
        if stake != target:
            fixed_stake_violations += 1
        selected.append({
            "raceId": str(race.get("raceId")),
            "raceDate": str(race.get("raceDate")),
            "venue": str(race.get("venue")),
            "stakeYen": stake,
            "returnYen": returns,
        })
        venue_key = f"{race.get('raceDate')}:{race.get('venue')}"
        counts_by_venue[venue_key] = counts_by_venue.get(venue_key, 0) + 1
        date = str(race.get("raceDate"))
        daily_profit[date] = daily_profit.get(date, 0) + returns - stake

    stake = sum(row["stakeYen"] for row in selected)
    returns = sum(row["returnYen"] for row in selected)
    hits = sum(1 for row in selected if row["returnYen"] > 0)
    positives = [max(0, value) for value in daily_profit.values()]
    positive_total = sum(positives)
    concentration = max(positives, default=0) / positive_total if positive_total > 0 else 1.0
    return {
        "selectedRaces": len(selected),
        "selectedRaceIds": sorted(row["raceId"] for row in selected),
        "selectedByVenue": counts_by_venue,
        "fivePerVenue": bool(counts_by_venue) and all(value == 5 for value in counts_by_venue.values()),
        "fixedStakeViolations": fixed_stake_violations,
        "stakeYen": stake,
        "returnYen": returns,
        "profitYen": returns - stake,
        "roiPct": returns / stake * 100.0 if stake else 0.0,
        "hitRatePct": hits / len(selected) * 100.0 if selected else 0.0,
        "averageStakeYen": stake / len(selected) if selected else 0.0,
        "maximumPositiveDayShare": concentration,
    }


def baseline_metrics(data: dict[str, Any], split: str) -> dict[str, Any]:
    courses = {course: selected_race_metrics(data, split, course) for course in COURSE_TARGETS}
    race_sets = [set(row["selectedRaceIds"]) for row in courses.values()]
    same_races = len(race_sets) == 3 and race_sets[0] == race_sets[1] == race_sets[2]
    valid = same_races and all(
        row["selectedRaces"] > 0
        and row["fivePerVenue"]
        and row["fixedStakeViolations"] == 0
        and abs(row["averageStakeYen"] - COURSE_TARGETS[course]) < 0.01
        for course, row in courses.items()
    )
    return {
        "policyVersion": "roi-policy-v1",
        "split": split,
        "valid": valid,
        "sameSelectedRacesAcrossCourses": same_races,
        "courses": courses,
    }


def apply_gate(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    validation_baseline = baseline_metrics(data, "validation")
    holdout_baseline = baseline_metrics(data, "holdout")
    holdout = result.get("holdout", {})
    learned_courses = holdout.get("courses", {})
    thresholds = {
        course: max(MINIMUM_ABSOLUTE_ROI_PCT, holdout_baseline["courses"][course]["roiPct"] + MINIMUM_IMPROVEMENT_PCT)
        for course in COURSE_TARGETS
    }
    checks: dict[str, dict[str, Any]] = {}
    for course in COURSE_TARGETS:
        learned = learned_courses.get(course, {})
        roi = float(learned.get("roiPct", 0.0))
        hit_rate = float(learned.get("hitRatePct", 0.0))
        concentration = float(learned.get("maximumPositiveDayShare", 1.0))
        checks[course] = {
            "requiredRoiPct": thresholds[course],
            "learnedRoiPct": roi,
            "baselineRoiPct": holdout_baseline["courses"][course]["roiPct"],
            "roiImprovementPct": roi - holdout_baseline["courses"][course]["roiPct"],
            "roiPassed": roi >= thresholds[course],
            "hitRatePassed": hit_rate >= MINIMUM_HIT_RATE_PCT,
            "concentrationPassed": concentration <= MAXIMUM_POSITIVE_DAY_SHARE,
        }
    promotion_ready = (
        validation_baseline["valid"]
        and holdout_baseline["valid"]
        and holdout.get("fivePerVenue") is True
        and all(
            row["roiPassed"] and row["hitRatePassed"] and row["concentrationPassed"]
            for row in checks.values()
        )
    )
    output = dict(result)
    output["baseline"] = {
        "validation": validation_baseline,
        "holdout": holdout_baseline,
    }
    output["promotionChecks"] = checks
    output["promotionReady"] = promotion_ready
    output["promotionRule"] = {
        "mustBeatAuditedV1ByPctPoints": MINIMUM_IMPROVEMENT_PCT,
        "allHoldoutCoursesRoiAtLeastPct": MINIMUM_ABSOLUTE_ROI_PCT,
        "maximumPositiveDayShareAtMost": MAXIMUM_POSITIVE_DAY_SHARE,
        "allHoldoutCoursesHitRateAtLeastPct": MINIMUM_HIT_RATE_PCT,
        "fiveRacesPerVenue": True,
        "sameSelectedRacesAcrossCourses": True,
        "fixedStakeViolations": 0,
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("result")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    gated = apply_gate(data, result)
    output = Path(args.output or args.result)
    output.write_text(json.dumps(gated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "promotionReady": gated["promotionReady"],
        "promotionChecks": gated["promotionChecks"],
        "baselineValid": gated["baseline"]["holdout"]["valid"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
