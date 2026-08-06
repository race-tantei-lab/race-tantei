import importlib.util
import json
import math
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v7 = load_module("v7_full", ROOT / "scripts" / "analyze-v7-full-period.py")
base = v7.base
v4 = v7.v4

POLICY_COUNT = 1200
MIN_REGIME_RACES = 60
MIN_REGIME_MONTHS = 3
DEVELOPMENT_END = "2026-04"
FINAL_HOLDOUT_START = "2026-05"
COURSES = tuple(v7.COURSES)
COURSE_BUDGETS = dict(v7.COURSE_BUDGETS)
CAP_MULTIPLE = dict(v7.CAP_MULTIPLE)

CANDIDATE_KEYS = (
    "form_only:confidence",
    "form_only:concentration",
    "form_only:entropy",
    "market_blend_audit:confidence",
    "market_blend_audit:disagreement",
    "market_blend_audit:entropy",
)
SCHEMES = (
    "global",
    "surface_distance",
    "class_surface",
    "field_race_band",
    "uncertainty",
    "track_context",
)


def class_band(race_name, conditions):
    text = f"{race_name or ''} {conditions or ''}"
    if "障害" in text:
        return "障害"
    for token, name in (
        ("ＧⅠ", "G1"), ("GⅠ", "G1"), ("Ｇ１", "G1"),
        ("ＧⅡ", "G2"), ("GⅡ", "G2"), ("Ｇ２", "G2"),
        ("ＧⅢ", "G3"), ("GⅢ", "G3"), ("Ｇ３", "G3"),
    ):
        if token in text:
            return name
    if any(token in text for token in ("オープン", "ＯＰ", "OP", "リステッド", "Ｌ")):
        return "OPEN"
    if any(token in text for token in ("3勝", "３勝", "1600万")):
        return "3勝"
    if any(token in text for token in ("2勝", "２勝", "1000万")):
        return "2勝"
    if any(token in text for token in ("1勝", "１勝", "500万")):
        return "1勝"
    if "新馬" in text:
        return "新馬"
    if "未勝利" in text:
        return "未勝利"
    return "その他"


def distance_band(value):
    distance = int(value or 0)
    if distance < 1400:
        return "短"
    if distance < 1800:
        return "マイル"
    if distance < 2200:
        return "中"
    return "長"


def field_band(value):
    count = int(value)
    if count <= 9:
        return "少"
    if count <= 13:
        return "中"
    return "多"


def race_no_band(value):
    number = int(value)
    if number <= 4:
        return "前半"
    if number <= 8:
        return "中盤"
    return "後半"


def condition_band(value):
    text = str(value or "")
    if "不" in text:
        return "不良"
    if "重" in text:
        return "重"
    if "稍" in text:
        return "稍重"
    return "良"


def confidence_band(value):
    value = float(value or 0.0)
    if value < 0.13:
        return "低"
    if value < 0.19:
        return "中"
    return "高"


def entropy_band(race):
    count = max(2, len(race["runners"]))
    normalized = float(race.get("entropy") or 0.0) / math.log(count)
    if normalized < 0.88:
        return "集中"
    if normalized < 0.96:
        return "中間"
    return "混戦"


def regime_label(race, scheme):
    surface = str(race.get("surface") or "不明")
    distance = distance_band(race.get("distanceM"))
    field = field_band(len(race["runners"]))
    race_band = race_no_band(race["raceNo"])
    klass = class_band(race.get("raceName"), race.get("conditions"))
    condition = condition_band(race.get("trackCondition"))
    if scheme == "global":
        return "ALL"
    if scheme == "surface_distance":
        return f"{surface}|{distance}"
    if scheme == "class_surface":
        return f"{klass}|{surface}"
    if scheme == "field_race_band":
        return f"{field}|{race_band}"
    if scheme == "uncertainty":
        return f"{confidence_band(race.get('topProbability'))}|{entropy_band(race)}"
    return f"{condition}|{distance}|{field}"


def load_metadata():
    result = {}
    for start, end in v4.month_ranges(v4.CONTEXT_START, v4.HOLDOUT_END):
        rows = v4.sql(
            """
            SELECT race_id raceId,race_name raceName,conditions,surface,distance_m distanceM,
                   direction,weather,track_condition trackCondition,
                   meeting_no meetingNo,meeting_day meetingDay
            FROM rt_races
            WHERE race_date>=? AND race_date<? AND status='finished'
            """,
            [start, end],
        )
        for row in rows:
            result[row["raceId"]] = row
    return result


def enrich(races, metadata):
    enriched = []
    for race in races:
        item = dict(race)
        item.update(metadata.get(race["raceId"], {}))
        enriched.append(item)
    return enriched


def build_stat(returns, hits, mask, budget, cap_yen):
    count = int(mask.sum())
    if count == 0:
        return None
    selected_returns = returns[mask]
    selected_hits = hits[mask]
    return {
        "races": count,
        "stake": budget * count,
        "rawSum": selected_returns.sum(axis=0),
        "cappedSum": np.minimum(selected_returns, cap_yen).sum(axis=0),
        "hitCount": selected_hits.sum(axis=0),
        "maxReturn": selected_returns.max(axis=0),
    }


def month_scheme_stats(returns, hits, races, scheme, budget, cap_yen):
    labels = np.asarray([regime_label(race, scheme) for race in races], dtype=object)
    stats = {}
    for label in sorted(set(labels.tolist())):
        row = build_stat(returns, hits, labels == label, budget, cap_yen)
        if row is not None:
            stats[label] = row
    return labels, stats


def choose_policy(history_stats, label, policy_count):
    records = []
    for month in history_stats:
        row = month.get(label)
        if row is not None:
            records.append(row)
    if not records:
        return None
    total_races = sum(row["races"] for row in records)
    if total_races < MIN_REGIME_RACES or len(records) < MIN_REGIME_MONTHS:
        return None

    raw_months = np.vstack([row["rawSum"] / row["stake"] * 100.0 for row in records])
    capped_months = np.vstack([row["cappedSum"] / row["stake"] * 100.0 for row in records])
    hit_months = np.vstack([row["hitCount"] / row["races"] * 100.0 for row in records])
    total_stake = sum(row["stake"] for row in records)
    total_return = np.sum([row["rawSum"] for row in records], axis=0)
    total_capped = np.sum([row["cappedSum"] for row in records], axis=0)
    total_hits = np.sum([row["hitCount"] for row in records], axis=0)
    maximum_return = np.maximum.reduce([row["maxReturn"] for row in records])

    total_raw_roi = total_return / max(1, total_stake) * 100.0
    total_capped_roi = total_capped / max(1, total_stake) * 100.0
    total_hit = total_hits / max(1, total_races) * 100.0
    q25_capped = np.quantile(capped_months, 0.25, axis=0)
    median_capped = np.median(capped_months, axis=0)
    minimum_capped = np.min(capped_months, axis=0)
    minimum_hit = np.min(hit_months, axis=0)
    winning_months = np.sum(raw_months >= 100.0, axis=0)
    required_winning = max(1, math.ceil(len(records) * 0.45))
    max_single_share = maximum_return / np.maximum(1.0, total_return)

    score = (
        q25_capped * 0.30
        + median_capped * 0.18
        + total_capped_roi * 0.17
        + np.minimum(total_raw_roi, 350.0) * 0.10
        + total_hit * 0.15
        + minimum_hit * 0.04
        + minimum_capped * 0.06
        - np.maximum(0.0, v7.REQUIRED_HIT - total_hit) * 4.0
        - np.maximum(0.0, required_winning - winning_months) * 15.0
        - np.maximum(0.0, max_single_share - 0.25) * 250.0
    )
    if len(score) != policy_count:
        raise RuntimeError(f"V7_1_POLICY_SHAPE:{len(score)}:{policy_count}")
    best = int(np.argmax(score))
    return {
        "index": best,
        "score": float(score[best]),
        "historyRaces": total_races,
        "historyMonths": len(records),
        "historyRawRoiPct": float(total_raw_roi[best]),
        "historyCappedRoiPct": float(total_capped_roi[best]),
        "historyHitRatePct": float(total_hit[best]),
        "historyQ25CappedRoiPct": float(q25_capped[best]),
        "historyWinningMonths": int(winning_months[best]),
        "historyMaxSingleReturnShare": float(max_single_share[best]),
    }


def evaluate_month(month, races, returns, hits, labels, regime_choices, global_choice, budget, cap_yen):
    chosen_indices = np.asarray([
        regime_choices.get(label, global_choice)["index"]
        for label in labels
    ], dtype=np.int64)
    row_indices = np.arange(len(races), dtype=np.int64)
    selected_returns = returns[row_indices, chosen_indices]
    selected_hits = hits[row_indices, chosen_indices]
    stake = budget * len(races)
    returned = float(selected_returns.sum())
    capped_returned = float(np.minimum(selected_returns, cap_yen).sum())
    return {
        "month": month,
        "races": len(races),
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "cappedReturnYen": int(round(capped_returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped_returned / stake * 100 if stake else 0.0,
        "hitRatePct": float(selected_hits.mean() * 100) if len(races) else 0.0,
        "maxSingleReturnYen": int(round(float(selected_returns.max()))) if len(races) else 0,
        "regimePolicies": len(regime_choices),
        "fallbackRaces": int(sum(label not in regime_choices for label in labels)),
    }


def aggregate(rows):
    stake = sum(row["stakeYen"] for row in rows)
    returned = sum(row["returnYen"] for row in rows)
    capped = sum(row["cappedReturnYen"] for row in rows)
    races = sum(row["races"] for row in rows)
    monthly_rois = [row["roiPct"] for row in rows]
    weighted_hits = sum(row["hitRatePct"] * row["races"] for row in rows)
    max_single = max((row["maxSingleReturnYen"] for row in rows), default=0)
    winning = sum(value >= 100.0 for value in monthly_rois)
    return {
        "months": len(rows),
        "races": races,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped / stake * 100 if stake else 0.0,
        "hitRatePct": weighted_hits / races if races else 0.0,
        "winningMonths": winning,
        "winningMonthPct": winning / len(rows) * 100 if rows else 0.0,
        "minimumMonthlyRoiPct": min(monthly_rois) if rows else 0.0,
        "medianMonthlyRoiPct": float(np.median(monthly_rois)) if rows else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(monthly_rois, 0.25)) if rows else 0.0,
        "maxSingleReturnShare": max_single / max(1, returned),
    }


def candidate_score(metrics):
    return (
        metrics["cappedRoiPct"] * 0.28
        + metrics["q25MonthlyRoiPct"] * 0.24
        + metrics["medianMonthlyRoiPct"] * 0.14
        + metrics["hitRatePct"] * 0.14
        + metrics["winningMonthPct"] * 0.20
        - max(0.0, 55.0 - metrics["cappedRoiPct"]) * 2.0
        - max(0.0, metrics["maxSingleReturnShare"] - 0.20) * 250.0
    )


def build_key_month_data(course, races_by_month, policies):
    policy_active = policies > 0
    month_data = {}
    for month in v7.month_sequence(v7.ROLLING_START_MONTH, max(races_by_month)):
        races = races_by_month[month]
        matrix, _ = base.payout_matrix(races)
        returns = matrix @ policies.T.astype(np.float64)
        hits = ((matrix > 0).astype(np.int16) @ policy_active.T.astype(np.int16)) > 0
        month_data[month] = {"races": races, "returns": returns, "hits": hits}
    return month_data


def evaluate_candidate(course, key, scheme, base_month_data, policies):
    budget = COURSE_BUDGETS[course]
    cap_yen = budget * CAP_MULTIPLE[course]
    month_data = {}
    month_stats = []
    for month, base_row in base_month_data.items():
        races = base_row["races"]
        returns = base_row["returns"]
        hits = base_row["hits"]
        labels, stats = month_scheme_stats(returns, hits, races, scheme, budget, cap_yen)
        all_mask = np.ones(len(races), dtype=bool)
        stats["__GLOBAL__"] = build_stat(returns, hits, all_mask, budget, cap_yen)
        month_data[month] = {
            "races": races,
            "returns": returns,
            "hits": hits,
            "labels": labels,
        }
        month_stats.append(stats)

    months = list(month_data)
    evaluation_months = [month for month in months if month >= v7.NESTED_EVALUATION_START_MONTH]
    results = []
    for month in evaluation_months:
        target_index = months.index(month)
        history_stats = month_stats[:target_index]
        global_choice = choose_policy(history_stats, "__GLOBAL__", len(policies))
        if global_choice is None:
            raise RuntimeError(f"V7_1_NO_GLOBAL:{course}:{key}:{scheme}:{month}")
        labels_seen = sorted({
            label
            for stats in history_stats
            for label in stats
            if label != "__GLOBAL__"
        })
        choices = {}
        for label in labels_seen:
            chosen = choose_policy(history_stats, label, len(policies))
            if chosen is not None:
                choices[label] = chosen
        target = month_data[month]
        results.append(evaluate_month(
            month,
            target["races"],
            target["returns"],
            target["hits"],
            target["labels"],
            choices,
            global_choice,
            budget,
            cap_yen,
        ))
    development = aggregate([row for row in results if row["month"] <= DEVELOPMENT_END])
    holdout = aggregate([row for row in results if row["month"] >= FINAL_HOLDOUT_START])
    full = aggregate(results)
    return {
        "course": course,
        "key": key,
        "variant": key.split(":", 1)[0],
        "productionSafe": key.startswith("form_only:"),
        "scheme": scheme,
        "development": development,
        "holdout": holdout,
        "full": full,
        "monthly": results,
        "developmentScore": candidate_score(development),
    }


def main():
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(v7.ROLLING_START_MONTH, last_month)
    predictions, model_audit = v7.rolling_predictions(races, months)
    metadata = load_metadata()

    selected = {}
    coverage = {}
    for key in CANDIDATE_KEYS:
        variant, mode = key.split(":", 1)
        selected[key] = {}
        coverage[key] = {}
        for month in months:
            target = predictions[variant][month]
            picked = enrich(v7.select_five_strict(target, mode), metadata)
            selected[key][month] = picked
            coverage[key][month] = {
                "sourceRaces": len(target),
                "selectedRaces": len(picked),
                "expectedSelectedRaces": v7.expected_selected_count(target),
            }

    v7.POLICY_COUNT = POLICY_COUNT
    chosen = {}
    for course in COURSES:
        policies = v7.generate_policies(course)
        course_results = []
        for key in CANDIDATE_KEYS:
            key_month_data = build_key_month_data(course, selected[key], policies)
            for scheme in SCHEMES:
                course_results.append(evaluate_candidate(course, key, scheme, key_month_data, policies))
        course_results.sort(key=lambda row: row["developmentScore"], reverse=True)
        best_overall = course_results[0]
        safe_results = [row for row in course_results if row["productionSafe"]]
        best_safe = safe_results[0]
        chosen[course] = {
            "bestOverall": best_overall,
            "bestProductionSafe": best_safe,
            "topDevelopmentCandidates": [
                {
                    "key": row["key"],
                    "scheme": row["scheme"],
                    "productionSafe": row["productionSafe"],
                    "developmentScore": row["developmentScore"],
                    "development": row["development"],
                    "holdout": row["holdout"],
                }
                for row in course_results[:8]
            ],
        }

    overall_holdout_pass = all(
        chosen[course]["bestOverall"]["holdout"]["roiPct"] >= 200.0
        and chosen[course]["bestOverall"]["holdout"]["cappedRoiPct"] >= 110.0
        and chosen[course]["bestOverall"]["holdout"]["hitRatePct"] >= v7.REQUIRED_HIT
        for course in COURSES
    )
    safe_holdout_pass = all(
        chosen[course]["bestProductionSafe"]["holdout"]["roiPct"] >= 200.0
        and chosen[course]["bestProductionSafe"]["holdout"]["cappedRoiPct"] >= 110.0
        and chosen[course]["bestProductionSafe"]["holdout"]["hitRatePct"] >= v7.REQUIRED_HIT
        for course in COURSES
    )

    compact_chosen = {}
    for course, row in chosen.items():
        compact_chosen[course] = {}
        for name in ("bestOverall", "bestProductionSafe"):
            candidate = row[name]
            compact_chosen[course][name] = {
                "key": candidate["key"],
                "variant": candidate["variant"],
                "productionSafe": candidate["productionSafe"],
                "scheme": candidate["scheme"],
                "developmentScore": candidate["developmentScore"],
                "development": candidate["development"],
                "holdout": candidate["holdout"],
                "full": candidate["full"],
                "monthly": candidate["monthly"],
            }
        compact_chosen[course]["topDevelopmentCandidates"] = row["topDevelopmentCandidates"]

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v7.1-shadow-regime-policy",
        "productionChanged": False,
        "method": (
            "Keep five races per venue/day and spend the full course budget on every selected race. "
            "For every target month, choose fixed-budget ticket policies separately for pre-race regimes "
            "using only earlier rolling out-of-sample months. Select the regime scheme and race-selection "
            "variant on May 2025-April 2026, then evaluate May-August 2026 as a final untouched holdout."
        ),
        "factors": [
            "surface", "distance band", "race class", "field size", "race-number band",
            "track condition", "top-win probability", "normalized entropy",
        ],
        "guardrails": {
            "selectedRacesPerVenueDay": 5,
            "noEmptyRaceSelection": True,
            "fullBudgetEverySelectedRace": True,
            "policyCountPerCourse": POLICY_COUNT,
            "minimumRegimeRaces": MIN_REGIME_RACES,
            "minimumRegimeMonths": MIN_REGIME_MONTHS,
            "developmentEnd": DEVELOPMENT_END,
            "finalHoldoutStart": FINAL_HOLDOUT_START,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
            "rollingMonths": months,
        },
        "modelAudit": model_audit,
        "coverage": coverage,
        "chosen": compact_chosen,
        "overallHoldoutPass200": overall_holdout_pass,
        "productionSafeHoldoutPass200": safe_holdout_pass,
    }
    Path("v7-regime-policy-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "chosen": {
            course: {
                "overall": {
                    "key": compact_chosen[course]["bestOverall"]["key"],
                    "scheme": compact_chosen[course]["bestOverall"]["scheme"],
                    "development": compact_chosen[course]["bestOverall"]["development"],
                    "holdout": compact_chosen[course]["bestOverall"]["holdout"],
                },
                "safe": {
                    "key": compact_chosen[course]["bestProductionSafe"]["key"],
                    "scheme": compact_chosen[course]["bestProductionSafe"]["scheme"],
                    "development": compact_chosen[course]["bestProductionSafe"]["development"],
                    "holdout": compact_chosen[course]["bestProductionSafe"]["holdout"],
                },
            }
            for course in COURSES
        },
        "overallHoldoutPass200": overall_holdout_pass,
        "productionSafeHoldoutPass200": safe_holdout_pass,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
