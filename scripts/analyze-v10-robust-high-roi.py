import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v7-enriched-ranking.py"
OUTPUT = ROOT / "v10-robust-high-roi.json"

TRAIN_START = "2025-05-01"
TRAIN_END = "2025-11-01"
VALIDATION_END = "2026-05-01"
MIN_TRAIN_RACES = 120
MIN_VALIDATION_RACES = 120
TOP_RESULT_COUNT = 30
PRODUCTION_VARIANTS = ("point", "pair", "ensemble")
SELECTION_MODES = ("confidence", "concentration", "entropy")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


enriched = load_module("v10_enriched_source", SOURCE)
v7 = enriched.v7
base = enriched.base
v4 = enriched.v4


def in_period(race_date, start, end=None):
    return race_date >= start and (end is None or race_date < end)


def distance_band(value):
    distance = int(value or 0)
    if distance < 1400:
        return "sprint"
    if distance < 1800:
        return "mile"
    if distance < 2200:
        return "middle"
    return "long"


def field_band(race):
    size = len(race.get("runners", []))
    if size <= 10:
        return "small"
    if size <= 14:
        return "medium"
    return "large"


def race_band(race):
    number = int(race.get("raceNo") or 0)
    if number <= 4:
        return "early"
    if number <= 8:
        return "middle"
    return "late"


def summarize(rows):
    rows = list(rows)
    stake = len(rows) * 100
    payouts = np.asarray([float(row["payout"]) for row in rows], dtype=np.float64)
    returned = float(payouts.sum()) if len(payouts) else 0.0
    sorted_payouts = np.sort(payouts)[::-1] if len(payouts) else payouts
    by_month = defaultdict(list)
    for row in rows:
        by_month[row["raceDate"][:7]].append(row)
    monthly = {}
    for month, month_rows in sorted(by_month.items()):
        month_stake = len(month_rows) * 100
        month_return = sum(float(row["payout"]) for row in month_rows)
        monthly[month] = {
            "races": len(month_rows),
            "returnYen": int(round(month_return)),
            "roiPct": month_return / month_stake * 100 if month_stake else 0.0,
            "hitRatePct": sum(float(row["payout"]) > 0 for row in month_rows) / len(month_rows) * 100,
        }
    month_rois = [row["roiPct"] for row in monthly.values()]
    hits = int(np.sum(payouts > 0)) if len(payouts) else 0
    return {
        "races": len(rows),
        "hits": hits,
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": hits / len(rows) * 100 if rows else 0.0,
        "winningMonths": sum(value >= 100.0 for value in month_rois),
        "months": len(month_rois),
        "medianMonthlyRoiPct": float(np.median(month_rois)) if month_rois else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(month_rois, 0.25)) if month_rois else 0.0,
        "minimumMonthlyRoiPct": min(month_rois) if month_rois else 0.0,
        "maxSinglePayoutYen": int(round(sorted_payouts[0])) if len(sorted_payouts) else 0,
        "maxSingleReturnShare": float(sorted_payouts[0] / returned) if returned > 0 else 1.0,
        "roiWithoutTop1Pct": float(max(0.0, returned - sorted_payouts[:1].sum()) / stake * 100) if stake else 0.0,
        "roiWithoutTop3Pct": float(max(0.0, returned - sorted_payouts[:3].sum()) / stake * 100) if stake else 0.0,
        "monthly": monthly,
    }


def compact(metrics):
    return {key: value for key, value in metrics.items() if key != "monthly"}


def rows_for_primitive(races, primitive):
    return [
        {
            "raceId": race["raceId"],
            "raceDate": race["raceDate"],
            "venue": race["venue"],
            "surface": race.get("surface") or "unknown",
            "distanceBand": distance_band(race.get("distanceM")),
            "fieldBand": field_band(race),
            "raceBand": race_band(race),
            "payout": float(base.primitive_payout(race, primitive)),
        }
        for race in races
    ]


def filter_specs(train_races):
    specs = [{"name": "all", "kind": "all"}]
    categorical = {
        "surface": sorted({str(race.get("surface") or "unknown") for race in train_races}),
        "distanceBand": sorted({distance_band(race.get("distanceM")) for race in train_races}),
        "fieldBand": sorted({field_band(race) for race in train_races}),
        "raceBand": sorted({race_band(race) for race in train_races}),
    }
    for field, values in categorical.items():
        for value in values:
            specs.append({"name": f"{field}={value}", "kind": "category", "field": field, "value": value})

    metric_map = {
        "topProbability": "high",
        "probabilityGap": "high",
        "top3Concentration": "high",
        "entropy": "low",
    }
    quantiles = (0.35, 0.50, 0.65, 0.80)
    for field, direction in metric_map.items():
        values = np.asarray([float(race.get(field) or 0.0) for race in train_races], dtype=np.float64)
        if not len(values):
            continue
        for quantile in quantiles:
            threshold = float(np.quantile(values, quantile))
            specs.append({
                "name": f"{field}:{direction}:q{int(quantile * 100)}",
                "kind": "threshold",
                "field": field,
                "direction": direction,
                "threshold": threshold,
                "trainQuantile": quantile,
            })

    for surface in categorical["surface"]:
        for size in categorical["fieldBand"]:
            specs.append({
                "name": f"surface={surface}&fieldBand={size}",
                "kind": "double_category",
                "firstField": "surface",
                "firstValue": surface,
                "secondField": "fieldBand",
                "secondValue": size,
            })
    for distance in categorical["distanceBand"]:
        for band in categorical["raceBand"]:
            specs.append({
                "name": f"distanceBand={distance}&raceBand={band}",
                "kind": "double_category",
                "firstField": "distanceBand",
                "firstValue": distance,
                "secondField": "raceBand",
                "secondValue": band,
            })
    return specs


def race_value(race, field):
    if field == "surface":
        return str(race.get("surface") or "unknown")
    if field == "distanceBand":
        return distance_band(race.get("distanceM"))
    if field == "fieldBand":
        return field_band(race)
    if field == "raceBand":
        return race_band(race)
    return race.get(field)


def apply_filter(races, spec):
    if spec["kind"] == "all":
        return list(races)
    if spec["kind"] == "category":
        return [race for race in races if race_value(race, spec["field"]) == spec["value"]]
    if spec["kind"] == "double_category":
        return [
            race for race in races
            if race_value(race, spec["firstField"]) == spec["firstValue"]
            and race_value(race, spec["secondField"]) == spec["secondValue"]
        ]
    threshold = float(spec["threshold"])
    if spec["direction"] == "low":
        return [race for race in races if float(race.get(spec["field"]) or 0.0) <= threshold]
    return [race for race in races if float(race.get(spec["field"]) or 0.0) >= threshold]


def selection_score(train, validation):
    if train["races"] < MIN_TRAIN_RACES or validation["races"] < MIN_VALIDATION_RACES:
        return -1e9
    if train["hits"] < 4 or validation["hits"] < 4:
        return -1e9
    score = (
        min(train["roiPct"], 250.0) * 0.15
        + min(validation["roiPct"], 250.0) * 0.30
        + min(train["roiWithoutTop1Pct"], 200.0) * 0.12
        + min(validation["roiWithoutTop1Pct"], 200.0) * 0.20
        + min(train["medianMonthlyRoiPct"], 180.0) * 0.07
        + min(validation["medianMonthlyRoiPct"], 180.0) * 0.10
        + min(validation["hitRatePct"], 25.0) * 0.06
    )
    score -= max(0.0, 0.50 - (1.0 - train["maxSingleReturnShare"])) * 120.0
    score -= max(0.0, 0.50 - (1.0 - validation["maxSingleReturnShare"])) * 160.0
    score -= max(0, 2 - train["winningMonths"]) * 18.0
    score -= max(0, 2 - validation["winningMonths"]) * 24.0
    return score


def main():
    runner_rows, payouts = v4.load_data()
    base_races = v4.build_dataset(runner_rows, payouts)
    extra_rows = enriched.load_extra_rows()
    races = enriched.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(TRAIN_START[:7], last_month)
    predictions, model_audit = enriched.rolling_predictions(races, months)

    candidates = []
    for variant in PRODUCTION_VARIANTS:
        for mode in SELECTION_MODES:
            selected = []
            coverage = []
            for month in months:
                source = predictions[variant][month]
                picked = v7.select_five_strict(source, mode)
                selected.extend(picked)
                coverage.append({
                    "month": month,
                    "sourceRaces": len(source),
                    "selectedRaces": len(picked),
                    "expectedSelectedRaces": v7.expected_selected_count(source),
                })
            train_races = [race for race in selected if in_period(race["raceDate"], TRAIN_START, TRAIN_END)]
            validation_races = [race for race in selected if in_period(race["raceDate"], TRAIN_END, VALIDATION_END)]
            final_races = [race for race in selected if in_period(race["raceDate"], VALIDATION_END)]
            specs = filter_specs(train_races)
            for spec in specs:
                filtered_train = apply_filter(train_races, spec)
                filtered_validation = apply_filter(validation_races, spec)
                if len(filtered_train) < MIN_TRAIN_RACES or len(filtered_validation) < MIN_VALIDATION_RACES:
                    continue
                filtered_final = apply_filter(final_races, spec)
                for primitive in base.PRIMITIVES:
                    train_metrics = summarize(rows_for_primitive(filtered_train, primitive))
                    validation_metrics = summarize(rows_for_primitive(filtered_validation, primitive))
                    score = selection_score(train_metrics, validation_metrics)
                    if score <= -1e8:
                        continue
                    final_metrics = summarize(rows_for_primitive(filtered_final, primitive))
                    name, bet_type, ranks = primitive
                    candidates.append({
                        "variant": variant,
                        "selectionMode": mode,
                        "filter": spec,
                        "code": name,
                        "betType": bet_type,
                        "predictedRanks": list(ranks),
                        "selectionScore": score,
                        "developmentA": compact(train_metrics),
                        "developmentB": compact(validation_metrics),
                        "finalHoldout": compact(final_metrics),
                        "finalMonthly": final_metrics["monthly"],
                        "coverage": coverage,
                    })

    candidates.sort(
        key=lambda row: (
            row["selectionScore"],
            row["developmentB"]["roiWithoutTop1Pct"],
            row["developmentB"]["roiPct"],
            row["developmentB"]["hitRatePct"],
        ),
        reverse=True,
    )
    selected_top = candidates[:TOP_RESULT_COUNT]
    final_ranked = sorted(
        selected_top,
        key=lambda row: (
            row["finalHoldout"]["roiWithoutTop1Pct"],
            row["finalHoldout"]["roiPct"],
            row["finalHoldout"]["hitRatePct"],
        ),
        reverse=True,
    )

    x431_audit = next(
        (
            row for row in candidates
            if row["variant"] == "ensemble"
            and row["selectionMode"] == "confidence"
            and row["filter"]["name"] == "all"
            and row["code"] == "X431"
        ),
        None,
    )

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v10-shadow-robust-high-roi",
        "productionChanged": False,
        "promotionEligible": False,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "syntheticOddsUsed": False,
        "officialPreRaceCombinationOddsAvailable": False,
        "guardrails": {
            "trainA": f"{TRAIN_START}..{TRAIN_END}",
            "trainB": f"{TRAIN_END}..{VALIDATION_END}",
            "finalHoldout": f"{VALIDATION_END}..end",
            "minimumTrainRaces": MIN_TRAIN_RACES,
            "minimumValidationRaces": MIN_VALIDATION_RACES,
            "filtersChosenWithoutFinalHoldout": True,
            "fiveRacesPerVenueDay": True,
            "noMarketAuditVariant": True,
            "noSyntheticOdds": True,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
            "months": months,
        },
        "modelAudit": model_audit,
        "summary": {
            "bestByPreHoldoutSelection": selected_top[:10],
            "bestFinalAmongPreselectedTop30": final_ranked[:10],
            "x431RobustnessAudit": x431_audit,
        },
        "candidateCount": len(candidates),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidateCount": len(candidates),
        "bestByPreHoldoutSelection": [
            {
                "variant": row["variant"],
                "mode": row["selectionMode"],
                "filter": row["filter"]["name"],
                "ticket": f'{row["betType"]}:{row["predictedRanks"]}',
                "trainA": row["developmentA"]["roiPct"],
                "trainB": row["developmentB"]["roiPct"],
                "final": row["finalHoldout"]["roiPct"],
                "finalWithoutTop1": row["finalHoldout"]["roiWithoutTop1Pct"],
                "finalHit": row["finalHoldout"]["hitRatePct"],
                "finalRaces": row["finalHoldout"]["races"],
            }
            for row in selected_top[:10]
        ],
        "x431": None if x431_audit is None else {
            "trainA": x431_audit["developmentA"],
            "trainB": x431_audit["developmentB"],
            "final": x431_audit["finalHoldout"],
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
