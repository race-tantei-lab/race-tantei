import calendar
import importlib.util
import json
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
base = load_module("v6_course_policy", ROOT / "scripts" / "analyze-v6-course-policy.py")

COURSES = tuple(base.COURSE_BUDGETS)
DEV_MONTHS = tuple(f"2026-{month:02d}" for month in range(1, 8))
RACE_MODES = tuple(base.RACE_MODES)
POLICY_COUNT = 3000
REQUIRED_HIT = 36.8

MAX_TICKET_SHARE = {"ライト": 0.50, "スタンダード": 0.40, "プレミアム": 0.35}
MINIMUM_TYPES = {"ライト": 1, "スタンダード": 2, "プレミアム": 3}
CAP_MULTIPLE = {"ライト": 5.0, "スタンダード": 7.0, "プレミアム": 10.0}

MODEL_CONFIG = base.MODEL_CONFIG
BLEND = base.BLEND
TEMPERATURE = base.TEMPERATURE


def month_bounds(month):
    year, value = map(int, month.split("-"))
    last_day = calendar.monthrange(year, value)[1]
    return f"{year:04d}-{value:02d}-01", f"{year:04d}-{value:02d}-{last_day:02d}"


def in_range(race_date, start, end):
    return start <= race_date <= end


def type_count(units):
    return len({base.TYPE_BY_INDEX[index] for index, value in enumerate(units) if value > 0})


def generate_policies(course):
    source = base.generate_policies(course, count=POLICY_COUNT * 2)
    total_units = base.COURSE_BUDGETS[course] // 100
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
        if type_count(units) < MINIMUM_TYPES[course]:
            continue
        kept.append(units)
        if len(kept) >= POLICY_COUNT:
            break
    if not kept:
        raise RuntimeError(f"V6_4_NO_POLICIES:{course}")
    return np.asarray(kept, dtype=np.int16)


def policy_tables(races, policies):
    matrix, months = base.payout_matrix(races)
    returns = matrix @ policies.T.astype(np.float64)
    hits = ((matrix > 0).astype(np.int16) @ (policies > 0).T.astype(np.int16)) > 0
    return matrix, months, returns, hits


def choose_robust_policy(course, races, policies):
    budget = base.COURSE_BUDGETS[course]
    _, months, returns, hits = policy_tables(races, policies)
    if len(races) == 0:
        raise RuntimeError(f"V6_4_EMPTY_RACES:{course}")

    cap_yen = budget * CAP_MULTIPLE[course]
    capped_returns = np.minimum(returns, cap_yen)
    month_raw_rois = []
    month_capped_rois = []
    month_hits = []
    for month in DEV_MONTHS:
        mask = months == month
        count = int(mask.sum())
        if count == 0:
            continue
        stake = budget * count
        month_raw_rois.append(returns[mask].sum(axis=0) / stake * 100)
        month_capped_rois.append(capped_returns[mask].sum(axis=0) / stake * 100)
        month_hits.append(hits[mask].mean(axis=0) * 100)

    raw_stack = np.vstack(month_raw_rois)
    capped_stack = np.vstack(month_capped_rois)
    hit_stack = np.vstack(month_hits)
    total_stake = budget * len(races)
    total_raw_roi = returns.sum(axis=0) / total_stake * 100
    total_capped_roi = capped_returns.sum(axis=0) / total_stake * 100
    total_hit = hits.mean(axis=0) * 100
    winning_months = np.sum(raw_stack >= 100.0, axis=0)
    median_raw = np.median(raw_stack, axis=0)
    median_capped = np.median(capped_stack, axis=0)
    q25_capped = np.quantile(capped_stack, 0.25, axis=0)
    minimum_hit = np.min(hit_stack, axis=0)
    max_single_share = np.max(returns, axis=0) / np.maximum(1.0, returns.sum(axis=0))

    score = (
        q25_capped * 0.34
        + median_capped * 0.20
        + total_capped_roi * 0.16
        + median_raw * 0.10
        + total_hit * 0.15
        + minimum_hit * 0.05
        - np.maximum(0.0, REQUIRED_HIT - total_hit) * 4.0
        - np.maximum(0.0, 4.0 - winning_months) * 22.0
        - np.maximum(0.0, max_single_share - 0.28) * 300.0
    )
    eligible = (
        (total_hit >= REQUIRED_HIT)
        & (winning_months >= 4)
        & (q25_capped >= 70.0)
        & (max_single_share <= 0.40)
    )
    eligible_indices = np.flatnonzero(eligible)
    if len(eligible_indices):
        best = int(eligible_indices[np.argmax(score[eligible_indices])])
    else:
        best = int(np.argmax(score))

    month_details = {}
    for row_index, month in enumerate([month for month in DEV_MONTHS if np.any(months == month)]):
        month_details[month] = {
            "rawRoiPct": float(raw_stack[row_index, best]),
            "cappedRoiPct": float(capped_stack[row_index, best]),
            "hitRatePct": float(hit_stack[row_index, best]),
        }
    return {
        "policyIndex": best,
        "units": policies[best].copy(),
        "score": float(score[best]),
        "eligible": bool(eligible[best]),
        "eligiblePolicyCount": int(eligible.sum()),
        "totalRawRoiPct": float(total_raw_roi[best]),
        "totalCappedRoiPct": float(total_capped_roi[best]),
        "totalHitRatePct": float(total_hit[best]),
        "winningMonths": int(winning_months[best]),
        "medianRawRoiPct": float(median_raw[best]),
        "q25CappedRoiPct": float(q25_capped[best]),
        "maxSingleReturnShare": float(max_single_share[best]),
        "months": month_details,
    }


def evaluate_policy(course, races, units):
    budget = base.COURSE_BUDGETS[course]
    matrix, months = base.payout_matrix(races)
    returns = matrix @ units.astype(np.float64)
    hits = np.any((matrix > 0) & (units[np.newaxis, :] > 0), axis=1)
    stake = budget * len(races)
    returned = float(returns.sum())
    by_day = {}
    dates = np.asarray([race["raceDate"] for race in races], dtype=object)
    for race_date in sorted(set(dates.tolist())):
        mask = dates == race_date
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
        "races": len(races),
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": float(hits.mean() * 100) if len(races) else 0.0,
        "byDay": by_day,
    }


def rolling_predictions(races):
    predictions = {}
    for month in DEV_MONTHS:
        start, end = month_bounds(month)
        train = [race for race in races if race["raceDate"] < start]
        target = [race for race in races if in_range(race["raceDate"], start, end)]
        if not train or not target:
            raise RuntimeError(f"V6_4_EMPTY_MONTH:{month}:{len(train)}:{len(target)}")
        model = base.v6.fit_pairwise(train, MODEL_CONFIG)
        predictions[month] = base.v6.attach_pairwise(model, target, BLEND, TEMPERATURE)
    return predictions


def main():
    rows, payouts = base.v6.v4.load_data()
    races = base.v6.v4.build_dataset(rows, payouts)
    dev_predictions = rolling_predictions(races)
    august_raw = [race for race in races if in_range(race["raceDate"], "2026-08-01", "2026-08-02")]
    august_train = [race for race in races if race["raceDate"] < "2026-08-01"]
    august_model = base.v6.fit_pairwise(august_train, MODEL_CONFIG)
    august_predictions = base.v6.attach_pairwise(august_model, august_raw, BLEND, TEMPERATURE)

    policies = {course: generate_policies(course) for course in COURSES}
    mode_results = {}
    for mode in RACE_MODES:
        selected_dev = []
        for month in DEV_MONTHS:
            selected_dev.extend(base.v6.select_five(dev_predictions[month], mode))
        course_rows = {}
        for course in COURSES:
            chosen = choose_robust_policy(course, selected_dev, policies[course])
            course_rows[course] = {
                "score": chosen["score"],
                "eligible": chosen["eligible"],
                "eligiblePolicyCount": chosen["eligiblePolicyCount"],
                "totalRawRoiPct": chosen["totalRawRoiPct"],
                "totalCappedRoiPct": chosen["totalCappedRoiPct"],
                "totalHitRatePct": chosen["totalHitRatePct"],
                "winningMonths": chosen["winningMonths"],
                "medianRawRoiPct": chosen["medianRawRoiPct"],
                "q25CappedRoiPct": chosen["q25CappedRoiPct"],
                "maxSingleReturnShare": chosen["maxSingleReturnShare"],
                "months": chosen["months"],
                "policy": base.describe_policy(chosen["units"]),
                "units": chosen["units"].tolist(),
            }
        mode_results[mode] = {
            "selectedDevRaces": len(selected_dev),
            "courses": course_rows,
            "floorScore": min(row["score"] for row in course_rows.values()),
            "floorCappedRoiPct": min(row["totalCappedRoiPct"] for row in course_rows.values()),
        }

    global_mode = max(
        RACE_MODES,
        key=lambda mode: (mode_results[mode]["floorScore"], mode_results[mode]["floorCappedRoiPct"]),
    )
    independent_modes = {
        course: max(RACE_MODES, key=lambda mode: mode_results[mode]["courses"][course]["score"])
        for course in COURSES
    }

    global_august_races = base.v6.select_five(august_predictions, global_mode)
    global_courses = {}
    for course in COURSES:
        units = np.asarray(mode_results[global_mode]["courses"][course]["units"], dtype=np.int16)
        global_courses[course] = evaluate_policy(course, global_august_races, units)

    independent_courses = {}
    for course in COURSES:
        mode = independent_modes[course]
        selected = base.v6.select_five(august_predictions, mode)
        units = np.asarray(mode_results[mode]["courses"][course]["units"], dtype=np.int16)
        independent_courses[course] = {
            "mode": mode,
            "result": evaluate_policy(course, selected, units),
        }

    global_pass_100 = all(
        row["roiPct"] >= 100.0 and row["hitRatePct"] >= REQUIRED_HIT
        for row in global_courses.values()
    )
    independent_pass_100 = all(
        row["result"]["roiPct"] >= 100.0 and row["result"]["hitRatePct"] >= REQUIRED_HIT
        for row in independent_courses.values()
    )
    global_pass_200 = all(
        row["roiPct"] >= 200.0 and row["hitRatePct"] >= REQUIRED_HIT
        for row in global_courses.values()
    )
    independent_pass_200 = all(
        row["result"]["roiPct"] >= 200.0 and row["result"]["hitRatePct"] >= REQUIRED_HIT
        for row in independent_courses.values()
    )

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.4-shadow-rolling-oos",
        "productionChanged": False,
        "method": "For each month from January through July 2026, train only on earlier races, select five races per venue/day, and optimize course portfolios using capped returns and seven monthly out-of-sample results. August 1-2 is evaluated only after the policy is frozen.",
        "developmentMonths": list(DEV_MONTHS),
        "modeResults": mode_results,
        "globalCandidate": {
            "mode": global_mode,
            "august": global_courses,
            "promotionEligible100": global_pass_100,
            "promotionEligible200": global_pass_200,
        },
        "independentCandidate": {
            "modes": independent_modes,
            "august": independent_courses,
            "promotionEligible100": independent_pass_100,
            "promotionEligible200": independent_pass_200,
        },
    }
    Path("v6-rolling-oos-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "globalMode": global_mode,
        "globalAugust": global_courses,
        "independentModes": independent_modes,
        "independentAugust": independent_courses,
        "globalPass100": global_pass_100,
        "independentPass100": independent_pass_100,
        "globalPass200": global_pass_200,
        "independentPass200": independent_pass_200,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
