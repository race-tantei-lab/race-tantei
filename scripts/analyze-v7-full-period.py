import calendar
import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
base = load_module("v6_course_policy", ROOT / "scripts" / "analyze-v6-course-policy.py")
v6 = base.v6
v4 = v6.v4

# Always load the complete available archive. Historical features are materialized
# chronologically and each history store is updated only after the race is built.
v4.HOLDOUT_END = "2026-08-31"

DATA_START = "2024-05-01"
ROLLING_START_MONTH = "2024-11"
NESTED_EVALUATION_START_MONTH = "2025-05"
MIN_POLICY_HISTORY_MONTHS = 6
MODEL_CONFIG = base.MODEL_CONFIG
TEMPERATURE = base.TEMPERATURE
REQUIRED_HIT = 36.8
POLICY_COUNT = 1600
RANDOM_SEED = 2026080630

COURSES = tuple(base.COURSE_BUDGETS)
COURSE_BUDGETS = dict(base.COURSE_BUDGETS)
CAP_MULTIPLE = {"ライト": 5.0, "スタンダード": 7.0, "プレミアム": 10.0}
MAX_TICKET_SHARE = {"ライト": 0.50, "スタンダード": 0.40, "プレミアム": 0.35}
MINIMUM_TYPES = {"ライト": 1, "スタンダード": 2, "プレミアム": 3}

# The pairwise model is trained without current-race market features. The two variants
# below therefore measure the incremental value and replay risk of blending final odds.
VARIANTS = {
    "form_only": {
        "blend": 1.0,
        "modes": ("confidence", "concentration", "entropy"),
        "productionSafe": True,
    },
    "market_blend_audit": {
        "blend": 0.60,
        "modes": tuple(base.RACE_MODES),
        "productionSafe": False,
    },
}

MARKET_FEATURE_INDICES = (0, 1, 2)


def month_bounds(month):
    year, value = map(int, month.split("-"))
    last_day = calendar.monthrange(year, value)[1]
    return f"{year:04d}-{value:02d}-01", f"{year:04d}-{value:02d}-{last_day:02d}"


def month_sequence(start_month, end_month):
    year, month = map(int, start_month.split("-"))
    end_year, end_value = map(int, end_month.split("-"))
    result = []
    while (year, month) <= (end_year, end_value):
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def in_range(race_date, start, end):
    return start <= race_date <= end


def strip_market_features(races):
    stripped = []
    for race in races:
        item = dict(race)
        runners = []
        for runner in race["runners"]:
            copied = dict(runner)
            features = list(copied["features"])
            for index in MARKET_FEATURE_INDICES:
                if index < len(features):
                    features[index] = 0.0
            copied["features"] = features
            runners.append(copied)
        item["runners"] = runners
        stripped.append(item)
    return stripped


def expected_selected_count(races):
    grouped = defaultdict(int)
    for race in races:
        grouped[(race["raceDate"], race["venue"])] += 1
    return sum(5 for count in grouped.values() if count >= 5)


def select_five_strict(races, mode):
    selected = v6.select_five(list(races), mode)
    expected = expected_selected_count(races)
    if len(selected) != expected:
        raise RuntimeError(f"V7_SELECTION_COVERAGE:{mode}:{len(selected)}:{expected}")
    return selected


def type_count(units):
    return len({base.TYPE_BY_INDEX[index] for index, value in enumerate(units) if value > 0})


def generate_policies(course):
    source = base.generate_policies(course, count=POLICY_COUNT * 3)
    total_units = COURSE_BUDGETS[course] // 100
    max_units = max(1, int(total_units * MAX_TICKET_SHARE[course]))
    kept = []
    seen = set()
    for units in source:
        signature = tuple(int(value) for value in units)
        if signature in seen:
            continue
        seen.add(signature)
        if int(units.max()) > max_units:
            continue
        if int(units.sum()) != total_units:
            continue
        if type_count(units) < MINIMUM_TYPES[course]:
            continue
        kept.append(units.astype(np.int16))
        if len(kept) >= POLICY_COUNT:
            break
    if len(kept) < max(300, POLICY_COUNT // 2):
        raise RuntimeError(f"V7_INSUFFICIENT_POLICIES:{course}:{len(kept)}")
    return np.asarray(kept, dtype=np.int16)


def rolling_predictions(races, months):
    predictions = {variant: {} for variant in VARIANTS}
    model_audit = {}
    for month in months:
        start, end = month_bounds(month)
        train_raw = [race for race in races if DATA_START <= race["raceDate"] < start]
        target_raw = [race for race in races if in_range(race["raceDate"], start, end)]
        if not train_raw or not target_raw:
            raise RuntimeError(f"V7_EMPTY_MONTH:{month}:{len(train_raw)}:{len(target_raw)}")

        train = strip_market_features(train_raw)
        target = strip_market_features(target_raw)
        model = v6.fit_pairwise(train, MODEL_CONFIG)
        for variant, config in VARIANTS.items():
            predictions[variant][month] = v6.attach_pairwise(
                model,
                target,
                config["blend"],
                TEMPERATURE,
            )
        model_audit[month] = {
            "trainRaces": len(train),
            "targetRaces": len(target),
            "targetStart": start,
            "targetEnd": end,
        }
    return predictions, model_audit


def summarize_policy(units):
    return base.describe_policy(units)


def precompute_candidate(course, policies, selected_by_month, months):
    budget = COURSE_BUDGETS[course]
    cap_yen = budget * CAP_MULTIPLE[course]
    policy_active = policies > 0
    rows = []
    for month in months:
        races = selected_by_month[month]
        matrix, _ = base.payout_matrix(races)
        returns = matrix @ policies.T.astype(np.float64)
        hits = ((matrix > 0).astype(np.int16) @ policy_active.T.astype(np.int16)) > 0
        capped = np.minimum(returns, cap_yen)
        stake = budget * len(races)
        rows.append({
            "month": month,
            "races": len(races),
            "stake": stake,
            "rawRoi": returns.sum(axis=0) / max(1, stake) * 100.0,
            "cappedRoi": capped.sum(axis=0) / max(1, stake) * 100.0,
            "hitRate": hits.mean(axis=0) * 100.0 if len(races) else np.zeros(len(policies)),
            "totalReturn": returns.sum(axis=0),
            "maxSingleReturn": returns.max(axis=0) if len(races) else np.zeros(len(policies)),
            "targetReturns": returns,
            "targetHits": hits,
            "dates": np.asarray([race["raceDate"] for race in races], dtype=object),
        })
    return rows


def history_policy_score(rows, history_count):
    history = rows[:history_count]
    raw = np.vstack([row["rawRoi"] for row in history])
    capped = np.vstack([row["cappedRoi"] for row in history])
    hits = np.vstack([row["hitRate"] for row in history])
    total_stake = sum(row["stake"] for row in history)
    total_return = np.sum([row["totalReturn"] for row in history], axis=0)
    maximum_return = np.maximum.reduce([row["maxSingleReturn"] for row in history])
    total_raw = total_return / max(1, total_stake) * 100.0
    weights = np.asarray([row["stake"] for row in history], dtype=np.float64)
    total_capped = np.average(capped, axis=0, weights=weights)
    total_hit = np.average(hits, axis=0, weights=np.asarray([row["races"] for row in history], dtype=np.float64))
    winning_months = np.sum(raw >= 100.0, axis=0)
    q25_capped = np.quantile(capped, 0.25, axis=0)
    median_capped = np.median(capped, axis=0)
    minimum_capped = np.min(capped, axis=0)
    minimum_hit = np.min(hits, axis=0)
    max_single_share = maximum_return / np.maximum(1.0, total_return)
    required_winning = max(2, math.ceil(history_count * 0.50))

    score = (
        q25_capped * 0.28
        + median_capped * 0.18
        + total_capped * 0.14
        + np.minimum(total_raw, 400.0) * 0.10
        + total_hit * 0.16
        + minimum_hit * 0.06
        + minimum_capped * 0.08
        - np.maximum(0.0, REQUIRED_HIT - total_hit) * 5.0
        - np.maximum(0.0, required_winning - winning_months) * 18.0
        - np.maximum(0.0, max_single_share - 0.20) * 350.0
    )
    eligible = (
        (total_hit >= REQUIRED_HIT)
        & (winning_months >= required_winning)
        & (q25_capped >= 70.0)
        & (max_single_share <= 0.30)
    )
    eligible_indices = np.flatnonzero(eligible)
    if len(eligible_indices):
        best = int(eligible_indices[np.argmax(score[eligible_indices])])
    else:
        best = int(np.argmax(score))
    return {
        "index": best,
        "score": float(score[best]),
        "eligible": bool(eligible[best]),
        "eligibleCount": int(eligible.sum()),
        "historyRawRoiPct": float(total_raw[best]),
        "historyCappedRoiPct": float(total_capped[best]),
        "historyHitRatePct": float(total_hit[best]),
        "historyWinningMonths": int(winning_months[best]),
        "historyQ25CappedRoiPct": float(q25_capped[best]),
        "historyMinimumCappedRoiPct": float(minimum_capped[best]),
        "historyMaxSingleReturnShare": float(max_single_share[best]),
    }


def target_month_result(course, row, policy_index):
    budget = COURSE_BUDGETS[course]
    cap_yen = budget * CAP_MULTIPLE[course]
    returns = row["targetReturns"][:, policy_index]
    hits = row["targetHits"][:, policy_index]
    stake = budget * row["races"]
    returned = float(returns.sum())
    capped_returned = float(np.minimum(returns, cap_yen).sum())
    by_day = {}
    for race_date in sorted(set(row["dates"].tolist())):
        mask = row["dates"] == race_date
        day_stake = budget * int(mask.sum())
        day_return = float(returns[mask].sum())
        by_day[race_date] = {
            "races": int(mask.sum()),
            "stakeYen": day_stake,
            "returnYen": int(round(day_return)),
            "roiPct": day_return / day_stake * 100 if day_stake else 0.0,
            "hitRatePct": float(hits[mask].mean() * 100) if np.any(mask) else 0.0,
        }
    return {
        "races": row["races"],
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "cappedReturnYen": int(round(capped_returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped_returned / stake * 100 if stake else 0.0,
        "hitRatePct": float(hits.mean() * 100) if len(hits) else 0.0,
        "maxSingleReturnYen": int(round(float(returns.max()))) if len(returns) else 0,
        "byDay": by_day,
    }


def aggregate_nested(course, monthly_rows):
    stake = sum(row["result"]["stakeYen"] for row in monthly_rows)
    returned = sum(row["result"]["returnYen"] for row in monthly_rows)
    capped_returned = sum(row["result"]["cappedReturnYen"] for row in monthly_rows)
    races = sum(row["result"]["races"] for row in monthly_rows)
    weighted_hits = sum(row["result"]["hitRatePct"] * row["result"]["races"] for row in monthly_rows)
    monthly_rois = [row["result"]["roiPct"] for row in monthly_rows]
    winning_months = sum(value >= 100.0 for value in monthly_rois)
    maximum_single = max((row["result"]["maxSingleReturnYen"] for row in monthly_rows), default=0)
    return {
        "months": len(monthly_rows),
        "races": races,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped_returned / stake * 100 if stake else 0.0,
        "hitRatePct": weighted_hits / races if races else 0.0,
        "winningMonths": winning_months,
        "winningMonthPct": winning_months / len(monthly_rows) * 100 if monthly_rows else 0.0,
        "minimumMonthlyRoiPct": min(monthly_rois) if monthly_rois else 0.0,
        "medianMonthlyRoiPct": float(np.median(monthly_rois)) if monthly_rois else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(monthly_rois, 0.25)) if monthly_rois else 0.0,
        "maxSingleReturnShare": maximum_single / max(1, returned),
    }


def policy_type_stakes(policy_rows):
    totals = Counter()
    for month_row in policy_rows:
        for ticket in month_row["policy"]:
            totals[ticket["betType"]] += int(ticket["stakeYen"])
    return dict(sorted(totals.items()))


def main():
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    if not races:
        raise RuntimeError("V7_NO_RACES")
    last_month = max(race["raceDate"][:7] for race in races)
    months = month_sequence(ROLLING_START_MONTH, last_month)
    evaluation_months = [month for month in months if month >= NESTED_EVALUATION_START_MONTH]
    if len(months) - len(evaluation_months) < MIN_POLICY_HISTORY_MONTHS:
        raise RuntimeError("V7_POLICY_HISTORY_TOO_SHORT")

    predictions, model_audit = rolling_predictions(races, months)
    policies = {course: generate_policies(course) for course in COURSES}

    selected = {}
    coverage = {}
    for variant, config in VARIANTS.items():
        for mode in config["modes"]:
            key = f"{variant}:{mode}"
            selected[key] = {}
            coverage[key] = {}
            for month in months:
                target = predictions[variant][month]
                picked = select_five_strict(target, mode)
                selected[key][month] = picked
                coverage[key][month] = {
                    "sourceRaces": len(target),
                    "selectedRaces": len(picked),
                    "expectedSelectedRaces": expected_selected_count(target),
                    "venueDays": len(picked) // 5,
                }

    candidate_tables = {course: {} for course in COURSES}
    for course in COURSES:
        for key, selected_by_month in selected.items():
            candidate_tables[course][key] = precompute_candidate(
                course,
                policies[course],
                selected_by_month,
                months,
            )

    nested = {course: [] for course in COURSES}
    for month in evaluation_months:
        target_index = months.index(month)
        if target_index < MIN_POLICY_HISTORY_MONTHS:
            continue
        for course in COURSES:
            choices = []
            for key, table in candidate_tables[course].items():
                choice = history_policy_score(table, target_index)
                choice["key"] = key
                choices.append(choice)
            choices.sort(
                key=lambda row: (
                    row["eligible"],
                    row["score"],
                    row["historyQ25CappedRoiPct"],
                    row["historyHitRatePct"],
                ),
                reverse=True,
            )
            chosen = choices[0]
            variant, mode = chosen["key"].split(":", 1)
            table = candidate_tables[course][chosen["key"]]
            result = target_month_result(course, table[target_index], chosen["index"])
            nested[course].append({
                "month": month,
                "variant": variant,
                "productionSafe": bool(VARIANTS[variant]["productionSafe"]),
                "mode": mode,
                "history": {key: value for key, value in chosen.items() if key not in {"index", "key"}},
                "policy": summarize_policy(policies[course][chosen["index"]]),
                "result": result,
            })

    aggregate = {course: aggregate_nested(course, nested[course]) for course in COURSES}
    selection_audit = {}
    for course in COURSES:
        variant_counts = Counter(row["variant"] for row in nested[course])
        mode_counts = Counter(row["mode"] for row in nested[course])
        selection_audit[course] = {
            "variantMonths": dict(sorted(variant_counts.items())),
            "modeMonths": dict(sorted(mode_counts.items())),
            "ticketTypeStakeAcrossMonthlyPolicies": policy_type_stakes(nested[course]),
            "allMonthsHadTickets": all(bool(row["policy"]) for row in nested[course]),
            "allMonthsHadSelectedRaces": all(row["result"]["races"] > 0 for row in nested[course]),
        }

    promotion_eligible = all(
        aggregate[course]["roiPct"] >= 200.0
        and aggregate[course]["cappedRoiPct"] >= 110.0
        and aggregate[course]["hitRatePct"] >= REQUIRED_HIT
        and aggregate[course]["winningMonthPct"] >= 60.0
        and aggregate[course]["maxSingleReturnShare"] <= 0.20
        for course in COURSES
    ) and all(
        all(row["productionSafe"] for row in nested[course])
        for course in COURSES
    )

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v7.0-shadow-full-period-nested-oos",
        "productionChanged": False,
        "promotionEligible": promotion_eligible,
        "targetRoiPct": 200.0,
        "method": (
            "Use all available finished races from May 2024 onward. Train a market-feature-stripped "
            "pairwise horse model before each target month, force five selected races per venue/day, "
            "choose the next month's course-specific race mode and non-empty fixed-budget ticket policy "
            "only from earlier rolling out-of-sample months, and settle every selected race against official payouts."
        ),
        "guardrails": {
            "noEmptyRaceSelection": True,
            "selectedRacesPerVenueDay": 5,
            "everySelectedRaceSpendsFullCourseBudget": True,
            "marketFeatureIndicesRemovedFromModel": list(MARKET_FEATURE_INDICES),
            "marketBlendAuditCannotPromote": True,
            "minimumPolicyHistoryMonths": MIN_POLICY_HISTORY_MONTHS,
            "policyCountPerCourse": {course: len(policies[course]) for course in COURSES},
            "requiredHitRatePct": REQUIRED_HIT,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "allFinishedRaces": len(races),
            "rollingPredictionMonths": months,
            "nestedEvaluationMonths": evaluation_months,
        },
        "modelAudit": model_audit,
        "coverage": coverage,
        "aggregate": aggregate,
        "selectionAudit": selection_audit,
        "monthly": nested,
    }
    Path("v7-full-period-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "period": report["period"],
        "aggregate": aggregate,
        "selectionAudit": selection_audit,
        "promotionEligible": promotion_eligible,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
