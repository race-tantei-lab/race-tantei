import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v10-robust-high-roi.py"
OUTPUT = ROOT / "v12-market-blend-ranking.json"

TRAIN_START = "2025-05-01"
TRAIN_END = "2025-11-01"
VALIDATION_END = "2026-05-01"
SELECTION_MODES = ("confidence", "concentration", "entropy", "disagreement", "edge")
TOP_CANDIDATES = 50
TOP_PORTFOLIOS = 30


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v10 = load_module("v12_v10_source", SOURCE)
enriched = v10.enriched
v7 = v10.v7
base = v10.base
v4 = v10.v4


def blend_specs():
    specs = []
    steps = (0.0, 0.25, 0.50, 0.75, 1.0)
    for point_weight in steps:
        for pair_weight in steps:
            market_weight = 1.0 - point_weight - pair_weight
            if market_weight < -1e-9:
                continue
            market_weight = max(0.0, market_weight)
            specs.append({
                "name": f"linear-p{point_weight:.2f}-r{pair_weight:.2f}-m{market_weight:.2f}",
                "kind": "linear",
                "point": point_weight,
                "pair": pair_weight,
                "market": market_weight,
            })
            if point_weight > 0 or pair_weight > 0:
                specs.append({
                    "name": f"geometric-p{point_weight:.2f}-r{pair_weight:.2f}-m{market_weight:.2f}",
                    "kind": "geometric",
                    "point": point_weight,
                    "pair": pair_weight,
                    "market": market_weight,
                })
    for source in ("point", "pair", "ensemble"):
        for alpha in (0.25, 0.50, 0.75, 1.0):
            specs.append({
                "name": f"value-{source}-a{alpha:.2f}",
                "kind": "value",
                "source": source,
                "alpha": alpha,
            })
    unique = {}
    for spec in specs:
        unique[spec["name"]] = spec
    return list(unique.values())


def aligned_probabilities(point_race, pair_race):
    point = {int(row["horseNo"]): float(row["probability"]) for row in point_race["runners"]}
    pair = {int(row["horseNo"]): float(row["probability"]) for row in pair_race["runners"]}
    market = {int(row["horseNo"]): float(row["market"]) for row in point_race["runners"]}
    return point, pair, market


def blend_race(point_race, pair_race, spec):
    point, pair, market = aligned_probabilities(point_race, pair_race)
    runners = []
    raw_values = []
    for original in point_race["runners"]:
        horse = int(original["horseNo"])
        p = max(1e-12, point[horse])
        q = max(1e-12, pair[horse])
        m = max(1e-12, market[horse])
        if spec["kind"] == "linear":
            value = spec["point"] * p + spec["pair"] * q + spec["market"] * m
        elif spec["kind"] == "geometric":
            value = p ** spec["point"] * q ** spec["pair"] * m ** spec["market"]
        else:
            if spec["source"] == "point":
                source_value = p
            elif spec["source"] == "pair":
                source_value = q
            else:
                source_value = 0.5 * p + 0.5 * q
            value = source_value / (m ** spec["alpha"])
        raw_values.append(max(1e-12, value))
    total = sum(raw_values)
    for original, value in zip(point_race["runners"], raw_values):
        copied = dict(original)
        probability = value / total
        copied["probability"] = probability
        copied["edge"] = probability / max(1e-12, float(original["market"]))
        runners.append(copied)
    runners.sort(key=lambda row: row["probability"], reverse=True)
    item = dict(point_race)
    item["runners"] = runners
    item["topProbability"] = runners[0]["probability"]
    item["probabilityGap"] = runners[0]["probability"] - runners[1]["probability"]
    item["top3Concentration"] = sum(row["probability"] for row in runners[:3])
    item["entropy"] = -sum(row["probability"] * math.log(max(1e-12, row["probability"])) for row in runners)
    item["disagreement"] = sum(abs(row["probability"] - row["market"]) for row in runners)
    item["maxEdge"] = max(row["edge"] for row in runners[:7])
    return item


def blend_month(point_races, pair_races, spec):
    pair_map = {race["raceId"]: race for race in pair_races}
    return [blend_race(race, pair_map[race["raceId"]], spec) for race in point_races]


def select_five(races, mode):
    groups = defaultdict(list)
    for race in races:
        groups[(race["raceDate"], race["venue"])].append(race)
    chosen = []
    for group in groups.values():
        if len(group) < 5:
            continue
        if mode == "confidence":
            group.sort(key=lambda race: (-race["topProbability"], race["raceNo"]))
        elif mode == "concentration":
            group.sort(key=lambda race: (-race["top3Concentration"], race["raceNo"]))
        elif mode == "entropy":
            group.sort(key=lambda race: (race["entropy"], race["raceNo"]))
        elif mode == "disagreement":
            group.sort(key=lambda race: (-race["disagreement"], race["raceNo"]))
        else:
            group.sort(key=lambda race: (-race["maxEdge"], race["raceNo"]))
        chosen.extend(group[:5])
    return chosen


def candidate_score(a, b):
    if a["races"] < 600 or b["races"] < 600:
        return -1e9
    if a["hits"] < 5 or b["hits"] < 5:
        return -1e9
    minimum_roi = min(a["roiPct"], b["roiPct"])
    minimum_trimmed = min(a["roiWithoutTop1Pct"], b["roiWithoutTop1Pct"])
    average_roi = (a["roiPct"] + b["roiPct"]) / 2
    median = min(a["medianMonthlyRoiPct"], b["medianMonthlyRoiPct"])
    score = (
        min(minimum_roi, 220.0) * 0.42
        + min(minimum_trimmed, 180.0) * 0.28
        + min(average_roi, 240.0) * 0.15
        + min(median, 180.0) * 0.10
        + min((a["hitRatePct"] + b["hitRatePct"]) / 2, 20.0) * 0.05
    )
    score -= max(0.0, a["maxSingleReturnShare"] - 0.45) * 160.0
    score -= max(0.0, b["maxSingleReturnShare"] - 0.45) * 180.0
    score -= max(0, 2 - a["winningMonths"]) * 18.0
    score -= max(0, 2 - b["winningMonths"]) * 22.0
    return score


def make_part(rows):
    payouts = sorted((float(row["payout"]) for row in rows), reverse=True)
    monthly = defaultdict(lambda: [0, 0.0, 0])
    for row in rows:
        month = row["raceDate"][:7]
        monthly[month][0] += 1
        monthly[month][1] += float(row["payout"])
        monthly[month][2] += int(float(row["payout"]) > 0)
    return {
        "n": len(rows),
        "returned": sum(payouts),
        "hits": sum(value > 0 for value in payouts),
        "top": payouts[:3],
        "monthly": dict(monthly),
    }


def combine_parts(parts):
    n = sum(part["n"] for part in parts)
    returned = sum(part["returned"] for part in parts)
    hits = sum(part["hits"] for part in parts)
    top = sorted([value for part in parts for value in part["top"]], reverse=True)[:3]
    monthly = defaultdict(lambda: [0, 0.0, 0])
    for part in parts:
        for month, values in part["monthly"].items():
            monthly[month][0] += values[0]
            monthly[month][1] += values[1]
            monthly[month][2] += values[2]
    stake = n * 100
    month_rois = []
    monthly_rows = {}
    for month, (count, month_return, month_hits) in sorted(monthly.items()):
        roi = month_return / (count * 100) * 100 if count else 0.0
        month_rois.append(roi)
        monthly_rows[month] = {
            "tickets": count,
            "returnYen": int(round(month_return)),
            "roiPct": roi,
            "hitRatePct": month_hits / count * 100 if count else 0.0,
        }
    return {
        "tickets": n,
        "hits": hits,
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": hits / n * 100 if n else 0.0,
        "winningMonths": sum(value >= 100.0 for value in month_rois),
        "months": len(month_rois),
        "medianMonthlyRoiPct": float(np.median(month_rois)) if month_rois else 0.0,
        "minimumMonthlyRoiPct": min(month_rois) if month_rois else 0.0,
        "maxSingleReturnShare": top[0] / returned if returned > 0 and top else 1.0,
        "roiWithoutTop1Pct": max(0.0, returned - sum(top[:1])) / stake * 100 if stake else 0.0,
        "roiWithoutTop3Pct": max(0.0, returned - sum(top[:3])) / stake * 100 if stake else 0.0,
        "monthly": monthly_rows,
    }


def compact(metrics):
    return {key: value for key, value in metrics.items() if key != "monthly"}


def main():
    runner_rows, payouts = v4.load_data()
    base_races = v4.build_dataset(runner_rows, payouts)
    extra_rows = enriched.load_extra_rows()
    races = enriched.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(TRAIN_START[:7], last_month)
    predictions, model_audit = enriched.rolling_predictions(races, months)

    specs = blend_specs()
    candidates = []
    for spec in specs:
        for mode in SELECTION_MODES:
            selected = []
            for month in months:
                blended = blend_month(predictions["point"][month], predictions["pair"][month], spec)
                selected.extend(select_five(blended, mode))
            train_races = [race for race in selected if TRAIN_START <= race["raceDate"] < TRAIN_END]
            validation_races = [race for race in selected if TRAIN_END <= race["raceDate"] < VALIDATION_END]
            final_races = [race for race in selected if race["raceDate"] >= VALIDATION_END]
            for primitive in base.PRIMITIVES:
                train_rows = v10.rows_for_primitive(train_races, primitive)
                validation_rows = v10.rows_for_primitive(validation_races, primitive)
                train_metrics = v10.summarize(train_rows)
                validation_metrics = v10.summarize(validation_rows)
                score = candidate_score(train_metrics, validation_metrics)
                if score <= -1e8:
                    continue
                candidates.append({
                    "blend": spec,
                    "selectionMode": mode,
                    "code": primitive[0],
                    "betType": primitive[1],
                    "predictedRanks": list(primitive[2]),
                    "score": score,
                    "developmentA": compact(train_metrics),
                    "developmentB": compact(validation_metrics),
                    "_primitive": primitive,
                    "_finalRaces": final_races,
                    "_trainRows": train_rows,
                    "_validationRows": validation_rows,
                })

    candidates.sort(
        key=lambda row: (
            row["score"],
            min(row["developmentA"]["roiPct"], row["developmentB"]["roiPct"]),
            min(row["developmentA"]["roiWithoutTop1Pct"], row["developmentB"]["roiWithoutTop1Pct"]),
        ),
        reverse=True,
    )
    preselected = candidates[:TOP_CANDIDATES]
    for row in preselected:
        final_rows = v10.rows_for_primitive(row.pop("_finalRaces"), row["_primitive"])
        row["_parts"] = {
            "train": make_part(row.pop("_trainRows")),
            "validation": make_part(row.pop("_validationRows")),
            "final": make_part(final_rows),
        }
        final_metrics = v10.summarize(final_rows)
        row["finalHoldout"] = compact(final_metrics)
        row["finalMonthly"] = final_metrics["monthly"]
        row.pop("_primitive")

    portfolios = []
    for first_index, second_index in itertools.combinations(range(len(preselected)), 2):
        first = preselected[first_index]
        second = preselected[second_index]
        if first["code"] == second["code"] and first["blend"]["name"] == second["blend"]["name"] and first["selectionMode"] == second["selectionMode"]:
            continue
        train = combine_parts([first["_parts"]["train"], second["_parts"]["train"]])
        validation = combine_parts([first["_parts"]["validation"], second["_parts"]["validation"]])
        score = candidate_score(
            {
                "races": train["tickets"], "hits": train["hits"], **{k: train[k] for k in (
                    "roiPct", "roiWithoutTop1Pct", "medianMonthlyRoiPct", "hitRatePct",
                    "maxSingleReturnShare", "winningMonths"
                )}
            },
            {
                "races": validation["tickets"], "hits": validation["hits"], **{k: validation[k] for k in (
                    "roiPct", "roiWithoutTop1Pct", "medianMonthlyRoiPct", "hitRatePct",
                    "maxSingleReturnShare", "winningMonths"
                )}
            },
        )
        if score <= -1e8:
            continue
        final = combine_parts([first["_parts"]["final"], second["_parts"]["final"]])
        portfolios.append({
            "score": score,
            "members": [
                {
                    "blend": first["blend"], "selectionMode": first["selectionMode"],
                    "code": first["code"], "betType": first["betType"], "predictedRanks": first["predictedRanks"],
                },
                {
                    "blend": second["blend"], "selectionMode": second["selectionMode"],
                    "code": second["code"], "betType": second["betType"], "predictedRanks": second["predictedRanks"],
                },
            ],
            "developmentA": compact(train),
            "developmentB": compact(validation),
            "finalHoldout": compact(final),
            "finalMonthly": final["monthly"],
        })
    portfolios.sort(key=lambda row: row["score"], reverse=True)

    for row in preselected:
        row.pop("_parts", None)

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v12-shadow-market-blend-ranking",
        "productionChanged": False,
        "promotionEligible": False,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "syntheticOddsUsed": False,
        "officialWinOddsUsed": True,
        "officialCombinationOddsUsed": False,
        "guardrails": {
            "blendChosenOnlyOnDevelopmentAAndB": True,
            "finalHoldoutNotUsedForSelection": True,
            "fiveRacesPerVenueDay": True,
            "minimumRacesEachDevelopmentHalf": 600,
            "rankingBlendCount": len(specs),
            "selectionModes": list(SELECTION_MODES),
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
        },
        "modelAudit": model_audit,
        "candidateCount": len(candidates),
        "summary": {
            "bestSinglesByDevelopment": preselected[:10],
            "bestSinglesFinalAmongPreselected50": sorted(
                preselected,
                key=lambda row: (
                    row["finalHoldout"]["roiWithoutTop1Pct"],
                    row["finalHoldout"]["roiPct"],
                ),
                reverse=True,
            )[:10],
            "bestPortfoliosByDevelopment": portfolios[:TOP_PORTFOLIOS],
            "bestPortfoliosFinalAmongPreselected": sorted(
                portfolios[:TOP_PORTFOLIOS],
                key=lambda row: (
                    row["finalHoldout"]["roiWithoutTop1Pct"],
                    row["finalHoldout"]["roiPct"],
                ),
                reverse=True,
            )[:10],
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "specs": len(specs),
        "candidates": len(candidates),
        "bestSingles": [
            {
                "blend": row["blend"]["name"],
                "mode": row["selectionMode"],
                "ticket": f'{row["betType"]}:{row["predictedRanks"]}',
                "A": row["developmentA"]["roiPct"],
                "B": row["developmentB"]["roiPct"],
                "F": row["finalHoldout"]["roiPct"],
                "FNoTop1": row["finalHoldout"]["roiWithoutTop1Pct"],
            }
            for row in preselected[:10]
        ],
        "bestPortfolios": [
            {
                "A": row["developmentA"]["roiPct"],
                "B": row["developmentB"]["roiPct"],
                "F": row["finalHoldout"]["roiPct"],
                "FNoTop1": row["finalHoldout"]["roiWithoutTop1Pct"],
            }
            for row in portfolios[:10]
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
