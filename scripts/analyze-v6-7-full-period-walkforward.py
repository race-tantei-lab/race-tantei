import calendar
import importlib.util
import json
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

START_MONTH = "2024-08"
END_MONTH = "2026-08"
MIN_PRIOR_OOS_MONTHS = 3
COURSES = tuple(base.COURSE_BUDGETS)
RACE_MODES = tuple(base.RACE_MODES)
MODEL_CONFIG = {
    "max_leaf_nodes": 15,
    "learning_rate": 0.03,
    "max_iter": 160,
    "l2_regularization": 8.0,
}
BLEND = 0.60
TEMPERATURE = 1.30
MAX_SINGLE_SHARE = {"ライト": 0.35, "スタンダード": 0.30, "プレミアム": 0.25}
CAP_MULTIPLE = {"ライト": 5.0, "スタンダード": 7.0, "プレミアム": 10.0}


def month_list(start, end):
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def month_bounds(month):
    year, value = map(int, month.split("-"))
    return f"{month}-01", f"{month}-{calendar.monthrange(year, value)[1]:02d}"


def in_range(race_date, start, end):
    return start <= race_date <= end


def select_required(races, mode):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    for group in grouped.values():
        group.sort(key=lambda race: (-base.v6.race_score(race, mode), race["raceNo"]))
        selected.extend(group[: min(5, len(group))])
    return selected


def policy_set(course):
    source = rolling.generate_policies(course)
    if len(source) > 1800:
        indices = np.linspace(0, len(source) - 1, 1800, dtype=int)
        source = source[indices]
    return source


def policy_metrics(course, races, policies):
    budget = base.COURSE_BUDGETS[course]
    matrix, months = base.payout_matrix(races)
    returns = matrix @ policies.T.astype(np.float64)
    hits = ((matrix > 0).astype(np.int16) @ (policies > 0).T.astype(np.int16)) > 0
    capped = np.minimum(returns, budget * CAP_MULTIPLE[course])

    month_raw = []
    month_capped = []
    month_hits = []
    for month in sorted(set(months.tolist())):
        mask = months == month
        count = int(mask.sum())
        stake = budget * count
        month_raw.append(returns[mask].sum(axis=0) / stake * 100)
        month_capped.append(capped[mask].sum(axis=0) / stake * 100)
        month_hits.append(hits[mask].mean(axis=0) * 100)

    raw_stack = np.vstack(month_raw)
    capped_stack = np.vstack(month_capped)
    hit_stack = np.vstack(month_hits)
    total_stake = budget * len(races)
    total_raw = returns.sum(axis=0) / total_stake * 100
    total_capped = capped.sum(axis=0) / total_stake * 100
    total_hit = hits.mean(axis=0) * 100
    q25 = np.quantile(capped_stack, 0.25, axis=0)
    median = np.median(capped_stack, axis=0)
    minimum = np.min(capped_stack, axis=0)
    winning_share = np.mean(raw_stack >= 100.0, axis=0)
    max_single_share = np.max(returns, axis=0) / np.maximum(1.0, returns.sum(axis=0))

    score = (
        q25 * 0.30
        + median * 0.20
        + minimum * 0.10
        + total_capped * 0.15
        + np.minimum(total_raw, 400.0) * 0.10
        + total_hit * 0.10
        + winning_share * 100.0 * 0.05
        - np.maximum(0.0, max_single_share - MAX_SINGLE_SHARE[course]) * 500.0
    )
    best = int(np.argmax(score))
    return {
        "index": best,
        "units": policies[best].copy(),
        "score": float(score[best]),
        "totalRawRoiPct": float(total_raw[best]),
        "totalCappedRoiPct": float(total_capped[best]),
        "q25CappedRoiPct": float(q25[best]),
        "medianCappedRoiPct": float(median[best]),
        "minimumCappedRoiPct": float(minimum[best]),
        "hitRatePct": float(total_hit[best]),
        "winningMonthSharePct": float(winning_share[best] * 100),
        "maxSingleReturnShare": float(max_single_share[best]),
    }


def choose_configuration(history, policies):
    candidates = []
    for mode in RACE_MODES:
        prior_races = []
        for month in sorted(history):
            prior_races.extend(history[month][mode])
        course_rows = {
            course: policy_metrics(course, prior_races, policies[course])
            for course in COURSES
        }
        floor_score = min(row["score"] for row in course_rows.values())
        floor_roi = min(row["totalRawRoiPct"] for row in course_rows.values())
        floor_q25 = min(row["q25CappedRoiPct"] for row in course_rows.values())
        candidates.append({
            "mode": mode,
            "courses": course_rows,
            "score": floor_score + min(floor_roi, 300.0) * 0.08 + floor_q25 * 0.12,
        })
    return max(candidates, key=lambda row: row["score"])


def evaluate_month(month, selected, chosen):
    result = {}
    for course in COURSES:
        row = rolling.evaluate_policy(course, selected, chosen["courses"][course]["units"])
        result[course] = row
    return {
        "month": month,
        "mode": chosen["mode"],
        "selectedRaces": len(selected),
        "courses": result,
    }


def aggregate(monthly):
    result = {}
    for course in COURSES:
        stake = sum(row["courses"][course]["stakeYen"] for row in monthly)
        returned = sum(row["courses"][course]["returnYen"] for row in monthly)
        races = sum(row["courses"][course]["races"] for row in monthly)
        hit_races = sum(
            round(row["courses"][course]["hitRatePct"] / 100 * row["courses"][course]["races"])
            for row in monthly
        )
        result[course] = {
            "races": races,
            "stakeYen": stake,
            "returnYen": returned,
            "profitYen": returned - stake,
            "roiPct": returned / stake * 100 if stake else 0.0,
            "hitRatePct": hit_races / races * 100 if races else 0.0,
            "monthsOver100": sum(row["courses"][course]["roiPct"] >= 100.0 for row in monthly),
            "monthsOver200": sum(row["courses"][course]["roiPct"] >= 200.0 for row in monthly),
        }
    return result


def main():
    rows, payouts = base.v6.v4.load_data()
    races = base.v6.v4.build_dataset(rows, payouts)
    months = month_list(START_MONTH, END_MONTH)
    policies = {course: policy_set(course) for course in COURSES}
    baseline = {
        "mode": "balanced",
        "courses": {
            course: {
                "units": policies[course][0].copy(),
                "score": 0.0,
                "totalRawRoiPct": 0.0,
                "q25CappedRoiPct": 0.0,
            }
            for course in COURSES
        },
    }

    history = {}
    monthly = []
    diagnostics = []

    for month in months:
        start, end = month_bounds(month)
        train = [race for race in races if race["raceDate"] < start]
        target_raw = [race for race in races if in_range(race["raceDate"], start, end)]
        if not train or not target_raw:
            diagnostics.append({"month": month, "status": "missing-data", "train": len(train), "target": len(target_raw)})
            continue

        model = base.v6.fit_pairwise(train, MODEL_CONFIG)
        predicted = base.v6.attach_pairwise(model, target_raw, BLEND, TEMPERATURE)
        selections = {mode: select_required(predicted, mode) for mode in RACE_MODES}

        if len(history) >= MIN_PRIOR_OOS_MONTHS:
            chosen = choose_configuration(history, policies)
        else:
            chosen = baseline

        selected = selections[chosen["mode"]]
        monthly.append(evaluate_month(month, selected, chosen))
        history[month] = selections
        diagnostics.append({
            "month": month,
            "status": "evaluated",
            "trainRaces": len(train),
            "targetRaces": len(target_raw),
            "selectedRaces": len(selected),
            "mode": chosen["mode"],
            "priorOosMonths": len(history) - 1,
        })
        print(json.dumps(diagnostics[-1], ensure_ascii=False), flush=True)

    totals = aggregate(monthly)
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.7-full-period-walkforward",
        "productionChanged": False,
        "method": (
            "Expanding monthly walk-forward from 2024-08 through 2026-08. Every target month is predicted "
            "using only earlier races. Five races per venue/day are always selected. Course policies and race mode "
            "are chosen only from earlier out-of-sample months. Evaluation uses actual JRA payouts only."
        ),
        "constraints": {
            "startMonth": START_MONTH,
            "endMonth": END_MONTH,
            "minimumPriorOosMonths": MIN_PRIOR_OOS_MONTHS,
            "courseBudgets": base.COURSE_BUDGETS,
            "targetRacesPerVenueDay": 5,
            "usesAssumedOddsForEvaluation": False,
        },
        "diagnostics": diagnostics,
        "monthly": monthly,
        "totals": totals,
        "allCoursesOver200": all(row["roiPct"] >= 200.0 for row in totals.values()),
        "promotionEligible": all(row["roiPct"] >= 200.0 for row in totals.values()),
    }
    Path("v6-7-full-period-walkforward.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"totals": totals, "allCoursesOver200": report["allCoursesOver200"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
