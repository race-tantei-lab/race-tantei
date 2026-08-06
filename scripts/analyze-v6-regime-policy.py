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
RACE_MODES = tuple(base.RACE_MODES)
QUANTILE_PAIRS = ((0.25, 0.75), (0.33, 0.67), (0.40, 0.70))
REQUIRED_HIT = 36.8
POLICY_COUNT = 2600

MAX_TICKET_SHARE = {"ライト": 0.55, "スタンダード": 0.45, "プレミアム": 0.40}
MINIMUM_TYPES = {"ライト": 1, "スタンダード": 2, "プレミアム": 3}

MODEL_CONFIG = base.MODEL_CONFIG
BLEND = base.BLEND
TEMPERATURE = base.TEMPERATURE


def in_range(race_date, start, end):
    return start <= race_date <= end


def feature_value(race, name):
    runners = race["runners"]
    if name == "topProbability":
        return float(race["topProbability"])
    if name == "probabilityGap":
        return float(race["probabilityGap"])
    if name == "top3Concentration":
        return float(race["top3Concentration"])
    if name == "maxEdge":
        return float(race["maxEdge"])
    if name == "disagreement":
        return float(race["disagreement"])
    if name == "entropy":
        return float(race["entropy"])
    if name == "fieldSize":
        return float(len(runners))
    if name == "favoriteOdds":
        return float(runners[0].get("winOdds") or 99.0)
    if name == "topEdge":
        return float(runners[0].get("edge") or 0.0)
    raise KeyError(name)


FEATURE_NAMES = (
    "topProbability",
    "probabilityGap",
    "top3Concentration",
    "maxEdge",
    "disagreement",
    "entropy",
    "fieldSize",
    "favoriteOdds",
    "topEdge",
)


def type_count(units):
    return len({base.TYPE_BY_INDEX[index] for index, value in enumerate(units) if value > 0})


def generate_course_policies(course):
    candidates = base.generate_policies(course, count=POLICY_COUNT * 2)
    total_units = base.COURSE_BUDGETS[course] // 100
    maximum_units = max(1, int(total_units * MAX_TICKET_SHARE[course]))
    kept = []
    seen = set()
    for units in candidates:
        signature = tuple(int(value) for value in units)
        if signature in seen:
            continue
        seen.add(signature)
        if int(units.max()) > maximum_units:
            continue
        if type_count(units) < MINIMUM_TYPES[course]:
            continue
        kept.append(units)
        if len(kept) >= POLICY_COUNT:
            break
    if not kept:
        raise RuntimeError(f"V6_3_NO_POLICIES:{course}")
    return np.asarray(kept, dtype=np.int16)


def policy_tables(races, policies):
    matrix, months = base.payout_matrix(races)
    returns = matrix @ policies.T.astype(np.float64)
    hits = ((matrix > 0).astype(np.int16) @ (policies > 0).T.astype(np.int16)) > 0
    return {
        "matrix": matrix,
        "months": months,
        "returns": returns,
        "hits": hits,
    }


def choose_policy(table, mask, budget):
    indices = np.flatnonzero(mask)
    if len(indices) < 10:
        return None
    returns = table["returns"][indices]
    hits = table["hits"][indices]
    months = table["months"][indices]
    total_stake = budget * len(indices)
    total_roi = returns.sum(axis=0) / total_stake * 100
    total_hit = hits.mean(axis=0) * 100

    month_rois = []
    month_hits = []
    for month in sorted(set(months.tolist())):
        month_mask = months == month
        month_stake = budget * int(month_mask.sum())
        month_rois.append(returns[month_mask].sum(axis=0) / month_stake * 100)
        month_hits.append(hits[month_mask].mean(axis=0) * 100)
    minimum_roi = np.min(np.vstack(month_rois), axis=0)
    minimum_hit = np.min(np.vstack(month_hits), axis=0)

    score = (
        minimum_roi * 0.48
        + total_roi * 0.32
        + minimum_hit * 0.08
        + total_hit * 0.12
        - np.maximum(0.0, 100.0 - minimum_roi) * 1.6
        - np.maximum(0.0, REQUIRED_HIT - total_hit) * 3.0
    )
    best = int(np.argmax(score))
    return {
        "policyIndex": best,
        "score": float(score[best]),
        "minimumRoiPct": float(minimum_roi[best]),
        "totalRoiPct": float(total_roi[best]),
        "minimumHitRatePct": float(minimum_hit[best]),
        "totalHitRatePct": float(total_hit[best]),
    }


def regime_ids(races, feature, thresholds):
    values = np.asarray([feature_value(race, feature) for race in races], dtype=np.float64)
    return np.digitize(values, thresholds, right=False), values


def aggregate_with_regimes(table, regime_values, chosen, budget):
    total_return = 0.0
    total_hits = 0
    races = len(regime_values)
    by_regime = {}
    for regime in range(3):
        mask = regime_values == regime
        count = int(mask.sum())
        if count == 0:
            by_regime[str(regime)] = {
                "races": 0,
                "roiPct": 0.0,
                "hitRatePct": 0.0,
            }
            continue
        policy_index = chosen[regime]["policyIndex"]
        returned = float(table["returns"][mask, policy_index].sum())
        hits = int(table["hits"][mask, policy_index].sum())
        total_return += returned
        total_hits += hits
        by_regime[str(regime)] = {
            "races": count,
            "returnYen": int(round(returned)),
            "roiPct": returned / (budget * count) * 100,
            "hitRatePct": hits / count * 100,
        }
    stake = budget * races
    return {
        "races": races,
        "stakeYen": stake,
        "returnYen": int(round(total_return)),
        "profitYen": int(round(total_return - stake)),
        "roiPct": total_return / stake * 100 if stake else 0.0,
        "hitRatePct": total_hits / races * 100 if races else 0.0,
        "byRegime": by_regime,
    }


def describe_policy(units):
    return base.describe_policy(units)


def candidate_score(course_metrics):
    rois = [row["roiPct"] for row in course_metrics.values()]
    hits = [row["hitRatePct"] for row in course_metrics.values()]
    floor_roi = min(rois)
    mean_roi = sum(rois) / len(rois)
    floor_hit = min(hits)
    return (
        floor_roi * 0.62
        + mean_roi * 0.28
        + floor_hit * 0.10
        - max(0.0, 100.0 - floor_roi) * 2.5
        - max(0.0, REQUIRED_HIT - floor_hit) * 2.0
    )


def build_periods():
    rows, payouts = base.v6.v4.load_data()
    races = base.v6.v4.build_dataset(rows, payouts)

    train = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-04-30")]
    validation_raw = [race for race in races if in_range(race["raceDate"], "2026-05-01", "2026-06-30")]
    through_june = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-06-30")]
    july_raw = [race for race in races if in_range(race["raceDate"], "2026-07-01", "2026-07-31")]
    through_july = [race for race in races if in_range(race["raceDate"], "2025-05-01", "2026-07-31")]
    august_raw = [race for race in races if in_range(race["raceDate"], "2026-08-01", "2026-08-02")]

    validation_model = base.v6.fit_pairwise(train, MODEL_CONFIG)
    july_model = base.v6.fit_pairwise(through_june, MODEL_CONFIG)
    august_model = base.v6.fit_pairwise(through_july, MODEL_CONFIG)
    return {
        "validation": base.v6.attach_pairwise(validation_model, validation_raw, BLEND, TEMPERATURE),
        "july": base.v6.attach_pairwise(july_model, july_raw, BLEND, TEMPERATURE),
        "august": base.v6.attach_pairwise(august_model, august_raw, BLEND, TEMPERATURE),
    }


def main():
    periods = build_periods()
    policies = {course: generate_course_policies(course) for course in COURSES}
    candidates = []

    for mode in RACE_MODES:
        selected = {
            period: base.v6.select_five(races, mode)
            for period, races in periods.items()
        }
        tables = {
            course: {
                period: policy_tables(selected[period], policies[course])
                for period in selected
            }
            for course in COURSES
        }

        for feature in FEATURE_NAMES:
            validation_values = np.asarray(
                [feature_value(race, feature) for race in selected["validation"]],
                dtype=np.float64,
            )
            for lower_q, upper_q in QUANTILE_PAIRS:
                thresholds = (
                    float(np.quantile(validation_values, lower_q)),
                    float(np.quantile(validation_values, upper_q)),
                )
                validation_regimes, _ = regime_ids(selected["validation"], feature, thresholds)
                july_regimes, _ = regime_ids(selected["july"], feature, thresholds)
                course_rows = {}
                valid = True
                for course in COURSES:
                    chosen = {}
                    for regime in range(3):
                        row = choose_policy(
                            tables[course]["validation"],
                            validation_regimes == regime,
                            base.COURSE_BUDGETS[course],
                        )
                        if row is None:
                            valid = False
                            break
                        chosen[regime] = row
                    if not valid:
                        break
                    july_metrics = aggregate_with_regimes(
                        tables[course]["july"],
                        july_regimes,
                        chosen,
                        base.COURSE_BUDGETS[course],
                    )
                    course_rows[course] = {
                        "chosenOnValidation": chosen,
                        "july": july_metrics,
                    }
                if not valid:
                    continue
                candidates.append({
                    "mode": mode,
                    "feature": feature,
                    "quantiles": [lower_q, upper_q],
                    "thresholds": list(thresholds),
                    "courses": course_rows,
                    "score": candidate_score({course: row["july"] for course, row in course_rows.items()}),
                })

    if not candidates:
        raise RuntimeError("V6_3_NO_CANDIDATES")
    candidates.sort(key=lambda row: row["score"], reverse=True)
    winner = candidates[0]

    selected = {
        period: base.v6.select_five(races, winner["mode"])
        for period, races in periods.items()
    }
    validation_regimes, _ = regime_ids(selected["validation"], winner["feature"], winner["thresholds"])
    july_regimes, _ = regime_ids(selected["july"], winner["feature"], winner["thresholds"])
    august_regimes, _ = regime_ids(selected["august"], winner["feature"], winner["thresholds"])

    final_courses = {}
    for course in COURSES:
        validation_table = policy_tables(selected["validation"], policies[course])
        july_table = policy_tables(selected["july"], policies[course])
        august_table = policy_tables(selected["august"], policies[course])
        combined_table = {
            "returns": np.concatenate([validation_table["returns"], july_table["returns"]], axis=0),
            "hits": np.concatenate([validation_table["hits"], july_table["hits"]], axis=0),
            "months": np.concatenate([validation_table["months"], july_table["months"]], axis=0),
        }
        combined_regimes = np.concatenate([validation_regimes, july_regimes], axis=0)
        chosen = {}
        policy_details = {}
        for regime in range(3):
            row = choose_policy(
                combined_table,
                combined_regimes == regime,
                base.COURSE_BUDGETS[course],
            )
            if row is None:
                raise RuntimeError(f"V6_3_EMPTY_FINAL_REGIME:{course}:{regime}")
            chosen[regime] = row
            policy_details[str(regime)] = describe_policy(policies[course][row["policyIndex"]])
        august_metrics = aggregate_with_regimes(
            august_table,
            august_regimes,
            chosen,
            base.COURSE_BUDGETS[course],
        )
        development_metrics = aggregate_with_regimes(
            combined_table,
            combined_regimes,
            chosen,
            base.COURSE_BUDGETS[course],
        )
        final_courses[course] = {
            "policies": policy_details,
            "development": development_metrics,
            "august": august_metrics,
        }

    promotion_100 = all(
        row["august"]["roiPct"] >= 100.0
        and row["august"]["hitRatePct"] >= REQUIRED_HIT
        for row in final_courses.values()
    )
    promotion_200 = all(
        row["august"]["roiPct"] >= 200.0
        and row["august"]["hitRatePct"] >= REQUIRED_HIT
        for row in final_courses.values()
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.3-shadow-regime-portfolios",
        "productionChanged": False,
        "method": "Choose 5 races per venue/day with the v6 pairwise model, classify selected races into three regimes using May-June thresholds, choose the regime architecture on July, refit course-specific portfolios on May-July, and evaluate August 1-2 only at the end.",
        "winner": {
            "mode": winner["mode"],
            "feature": winner["feature"],
            "quantiles": winner["quantiles"],
            "thresholds": winner["thresholds"],
            "julyScore": winner["score"],
        },
        "selectedRaces": {period: len(races) for period, races in selected.items()},
        "courses": final_courses,
        "promotionEligible100": promotion_100,
        "promotionEligible200": promotion_200,
        "candidateCount": len(candidates),
    }
    Path("v6-regime-policy-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "winner": report["winner"],
        "promotionEligible100": promotion_100,
        "promotionEligible200": promotion_200,
        "august": {
            course: row["august"]
            for course, row in final_courses.items()
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
