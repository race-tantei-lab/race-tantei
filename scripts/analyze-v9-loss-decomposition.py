import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v7-enriched-ranking.py"
OUTPUT = ROOT / "v9-loss-decomposition.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


enriched = load_module("v9_enriched_source", SOURCE)
v7 = enriched.v7
base = enriched.base
v4 = enriched.v4

EVALUATION_START = "2025-05"
FINAL_HOLDOUT_START = "2026-05"
MODEL_VARIANTS = ("point", "pair", "ensemble", "market_audit", "market")
SELECTION_MODES = ("all", "confidence", "concentration", "entropy")
PRODUCTION_SAFE_VARIANTS = {"point", "pair", "ensemble"}
BET_TYPES = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")


def market_ranked(races):
    result = []
    for race in races:
        runners = []
        for runner in race["runners"]:
            copied = dict(runner)
            copied["probability"] = float(runner.get("market") or 0.0)
            copied["edge"] = 1.0
            runners.append(copied)
        runners.sort(key=lambda row: row["probability"], reverse=True)
        if len(runners) < 2:
            continue
        item = dict(race)
        item["runners"] = runners
        item["topProbability"] = runners[0]["probability"]
        item["probabilityGap"] = runners[0]["probability"] - runners[1]["probability"]
        item["top3Concentration"] = sum(row["probability"] for row in runners[:3])
        item["maxEdge"] = 1.0
        item["disagreement"] = 0.0
        item["entropy"] = -sum(
            row["probability"] * math.log(max(1e-12, row["probability"]))
            for row in runners
        )
        result.append(item)
    return result


def selected_rows(rows, mode):
    if mode == "all":
        return list(rows)
    return v7.select_five_strict(rows, mode)


def primitive_rows(races, primitive):
    rows = []
    for race in races:
        payout = float(base.primitive_payout(race, primitive))
        rows.append({
            "raceDate": race["raceDate"],
            "payout": payout,
            "hit": payout > 0,
        })
    return rows


def summarize(rows):
    stake = len(rows) * 100
    returned = sum(row["payout"] for row in rows)
    by_month = defaultdict(list)
    for row in rows:
        by_month[row["raceDate"][:7]].append(row)
    monthly = {}
    for month, month_rows in sorted(by_month.items()):
        month_stake = len(month_rows) * 100
        month_return = sum(row["payout"] for row in month_rows)
        monthly[month] = {
            "races": len(month_rows),
            "stakeYen": month_stake,
            "returnYen": int(round(month_return)),
            "roiPct": month_return / month_stake * 100 if month_stake else 0.0,
            "hitRatePct": sum(row["hit"] for row in month_rows) / len(month_rows) * 100 if month_rows else 0.0,
        }
    monthly_rois = [row["roiPct"] for row in monthly.values()]
    return {
        "races": len(rows),
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": sum(row["hit"] for row in rows) / len(rows) * 100 if rows else 0.0,
        "winningMonths": sum(value >= 100.0 for value in monthly_rois),
        "minimumMonthlyRoiPct": min(monthly_rois) if monthly_rois else 0.0,
        "medianMonthlyRoiPct": float(np.median(monthly_rois)) if monthly_rois else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(monthly_rois, 0.25)) if monthly_rois else 0.0,
        "monthly": monthly,
    }


def development_score(metrics):
    return (
        metrics["q25MonthlyRoiPct"] * 0.30
        + metrics["medianMonthlyRoiPct"] * 0.25
        + metrics["roiPct"] * 0.25
        + metrics["hitRatePct"] * 0.15
        + metrics["minimumMonthlyRoiPct"] * 0.05
        - max(0, 4 - metrics["winningMonths"]) * 8.0
    )


def split_rows(rows):
    development = [row for row in rows if row["raceDate"][:7] < FINAL_HOLDOUT_START]
    holdout = [row for row in rows if row["raceDate"][:7] >= FINAL_HOLDOUT_START]
    return development, holdout


def best_primitive_for_type(races, bet_type):
    candidates = []
    for primitive in base.PRIMITIVES:
        if primitive[1] != bet_type:
            continue
        rows = primitive_rows(races, primitive)
        development, holdout = split_rows(rows)
        development_metrics = summarize(development)
        candidates.append({
            "primitive": primitive,
            "score": development_score(development_metrics),
            "development": development_metrics,
            "holdoutRows": holdout,
            "fullRows": rows,
        })
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            row["score"],
            row["development"]["q25MonthlyRoiPct"],
            row["development"]["hitRatePct"],
        ),
        reverse=True,
    )
    chosen = candidates[0]
    name, chosen_type, ranks = chosen["primitive"]
    return {
        "code": name,
        "betType": chosen_type,
        "predictedRanks": list(ranks),
        "developmentSelectionScore": chosen["score"],
        "development": chosen["development"],
        "finalHoldout": summarize(chosen["holdoutRows"]),
        "full": summarize(chosen["fullRows"]),
    }


def compact(metrics):
    return {
        key: value
        for key, value in metrics.items()
        if key != "monthly"
    }


def main():
    rows, payouts = v4.load_data()
    base_races = v4.build_dataset(rows, payouts)
    extra_rows = enriched.load_extra_rows()
    races = enriched.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(EVALUATION_START, last_month)

    predictions, model_audit = enriched.rolling_predictions(races, months)
    predictions["market"] = {
        month: market_ranked([
            race for race in races
            if v7.in_range(race["raceDate"], *v7.month_bounds(month))
        ])
        for month in months
    }

    report_rows = []
    for variant in MODEL_VARIANTS:
        for mode in SELECTION_MODES:
            chosen_races = []
            coverage = []
            for month in months:
                source = predictions[variant][month]
                picked = selected_rows(source, mode)
                chosen_races.extend(picked)
                coverage.append({
                    "month": month,
                    "sourceRaces": len(source),
                    "selectedRaces": len(picked),
                    "expectedFivePerVenueDay": v7.expected_selected_count(source),
                })
            by_type = {}
            for bet_type in BET_TYPES:
                selected = best_primitive_for_type(chosen_races, bet_type)
                if selected:
                    selected["development"] = compact(selected["development"])
                    selected["finalHoldout"] = compact(selected["finalHoldout"])
                    selected["full"] = compact(selected["full"])
                    by_type[bet_type] = selected
            report_rows.append({
                "variant": variant,
                "selectionMode": mode,
                "productionSafeRanking": variant in PRODUCTION_SAFE_VARIANTS,
                "coverage": coverage,
                "bestPrimitiveByBetType": by_type,
            })

    comparisons = []
    for row in report_rows:
        for bet_type, value in row["bestPrimitiveByBetType"].items():
            comparisons.append({
                "variant": row["variant"],
                "selectionMode": row["selectionMode"],
                "productionSafeRanking": row["productionSafeRanking"],
                "betType": bet_type,
                "code": value["code"],
                "predictedRanks": value["predictedRanks"],
                "developmentRoiPct": value["development"]["roiPct"],
                "finalHoldoutRoiPct": value["finalHoldout"]["roiPct"],
                "finalHoldoutHitRatePct": value["finalHoldout"]["hitRatePct"],
                "fullRoiPct": value["full"]["roiPct"],
            })
    safe = [row for row in comparisons if row["productionSafeRanking"]]
    safe.sort(
        key=lambda row: (
            row["finalHoldoutRoiPct"],
            row["finalHoldoutHitRatePct"],
        ),
        reverse=True,
    )
    market = [row for row in comparisons if row["variant"] == "market"]
    market.sort(key=lambda row: row["finalHoldoutRoiPct"], reverse=True)

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v9-shadow-loss-decomposition",
        "productionChanged": False,
        "sourceDataFrozen": True,
        "sourceFinishedRaces": len(races),
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "evaluationMonths": months,
            "finalHoldoutStart": FINAL_HOLDOUT_START,
        },
        "method": (
            "Keep the repaired 7,695-race dataset fixed. Rebuild pointwise, pairwise and ensemble rankings chronologically. "
            "Separately compare all races versus strict five-per-venue-day selection, and evaluate each transparent fixed predicted-rank primitive by bet type. "
            "Select each primitive only on May 2025-April 2026 development months and report May-August 2026 untouched results. "
            "The pure market ranking and market-audit blend are diagnostic only and cannot promote."
        ),
        "modelAudit": model_audit,
        "rows": report_rows,
        "summary": {
            "bestProductionSafeHoldout": safe[:12],
            "bestMarketDiagnosticHoldout": market[:12],
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
