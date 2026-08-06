import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v10-robust-high-roi.py"
OUTPUT = ROOT / "v11-portfolio-high-roi.json"

POOL_SIZE = 60
TOP_PORTFOLIOS = 50
PORTFOLIO_SIZES = (2, 3)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v10 = load_module("v11_v10_source", SOURCE)
enriched = v10.enriched
v7 = v10.v7
base = v10.base
v4 = v10.v4


def primitive_by_code(code):
    for primitive in base.PRIMITIVES:
        if primitive[0] == code:
            return primitive
    raise KeyError(code)


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
    month_rows = {}
    month_rois = []
    for month, (month_n, month_return, month_hits) in sorted(monthly.items()):
        roi = month_return / (month_n * 100) * 100 if month_n else 0.0
        month_rois.append(roi)
        month_rows[month] = {
            "tickets": month_n,
            "returnYen": int(round(month_return)),
            "roiPct": roi,
            "hitRatePct": month_hits / month_n * 100 if month_n else 0.0,
        }
    max_share = top[0] / returned if returned > 0 and top else 1.0
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
        "medianMonthlyRoiPct": sorted(month_rois)[len(month_rois) // 2] if month_rois else 0.0,
        "minimumMonthlyRoiPct": min(month_rois) if month_rois else 0.0,
        "maxSingleReturnShare": max_share,
        "roiWithoutTop1Pct": max(0.0, returned - sum(top[:1])) / stake * 100 if stake else 0.0,
        "roiWithoutTop3Pct": max(0.0, returned - sum(top[:3])) / stake * 100 if stake else 0.0,
        "monthly": month_rows,
    }


def compact(metrics):
    return {key: value for key, value in metrics.items() if key != "monthly"}


def portfolio_score(a, b):
    if a["tickets"] < 400 or b["tickets"] < 400:
        return -1e9
    if a["hits"] < 8 or b["hits"] < 8:
        return -1e9
    minimum_roi = min(a["roiPct"], b["roiPct"])
    average_roi = (a["roiPct"] + b["roiPct"]) / 2
    minimum_trimmed = min(a["roiWithoutTop1Pct"], b["roiWithoutTop1Pct"])
    minimum_median = min(a["medianMonthlyRoiPct"], b["medianMonthlyRoiPct"])
    score = (
        min(minimum_roi, 220.0) * 0.42
        + min(average_roi, 240.0) * 0.18
        + min(minimum_trimmed, 180.0) * 0.24
        + min(minimum_median, 160.0) * 0.10
        + min((a["hitRatePct"] + b["hitRatePct"]) / 2, 20.0) * 0.06
    )
    score -= max(0.0, a["maxSingleReturnShare"] - 0.45) * 150.0
    score -= max(0.0, b["maxSingleReturnShare"] - 0.45) * 180.0
    score -= max(0, 2 - a["winningMonths"]) * 16.0
    score -= max(0, 2 - b["winningMonths"]) * 20.0
    return score


def main():
    runner_rows, payouts = v4.load_data()
    base_races = v4.build_dataset(runner_rows, payouts)
    extra_rows = enriched.load_extra_rows()
    races = enriched.enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(v10.TRAIN_START[:7], last_month)
    predictions, model_audit = enriched.rolling_predictions(races, months)

    selected_cache = {}
    candidate_meta = []
    for variant in v10.PRODUCTION_VARIANTS:
        for mode in v10.SELECTION_MODES:
            key = f"{variant}:{mode}"
            selected = []
            for month in months:
                selected.extend(v7.select_five_strict(predictions[variant][month], mode))
            train_races = [race for race in selected if v10.in_period(race["raceDate"], v10.TRAIN_START, v10.TRAIN_END)]
            validation_races = [race for race in selected if v10.in_period(race["raceDate"], v10.TRAIN_END, v10.VALIDATION_END)]
            final_races = [race for race in selected if v10.in_period(race["raceDate"], v10.VALIDATION_END)]
            selected_cache[key] = {
                "train": train_races,
                "validation": validation_races,
                "final": final_races,
            }
            for spec in v10.filter_specs(train_races):
                filtered_train = v10.apply_filter(train_races, spec)
                filtered_validation = v10.apply_filter(validation_races, spec)
                if len(filtered_train) < v10.MIN_TRAIN_RACES or len(filtered_validation) < v10.MIN_VALIDATION_RACES:
                    continue
                for primitive in base.PRIMITIVES:
                    train_rows = v10.rows_for_primitive(filtered_train, primitive)
                    validation_rows = v10.rows_for_primitive(filtered_validation, primitive)
                    train_metrics = v10.summarize(train_rows)
                    validation_metrics = v10.summarize(validation_rows)
                    score = v10.selection_score(train_metrics, validation_metrics)
                    if score <= -1e8:
                        continue
                    candidate_meta.append({
                        "variant": variant,
                        "mode": mode,
                        "cacheKey": key,
                        "filter": spec,
                        "code": primitive[0],
                        "betType": primitive[1],
                        "predictedRanks": list(primitive[2]),
                        "singleScore": score,
                        "train": v10.compact(train_metrics),
                        "validation": v10.compact(validation_metrics),
                    })

    by_score = sorted(candidate_meta, key=lambda row: row["singleScore"], reverse=True)[:POOL_SIZE]
    by_train = sorted(
        candidate_meta,
        key=lambda row: (row["train"]["roiWithoutTop1Pct"], row["train"]["roiPct"]),
        reverse=True,
    )[:20]
    by_validation = sorted(
        candidate_meta,
        key=lambda row: (row["validation"]["roiWithoutTop1Pct"], row["validation"]["roiPct"]),
        reverse=True,
    )[:20]
    pool_map = {}
    for row in by_score + by_train + by_validation:
        signature = (row["variant"], row["mode"], row["filter"]["name"], row["code"])
        pool_map[signature] = row
    pool = list(pool_map.values())
    pool.sort(key=lambda row: row["singleScore"], reverse=True)
    pool = pool[:80]

    for row in pool:
        primitive = primitive_by_code(row["code"])
        source = selected_cache[row["cacheKey"]]
        row["parts"] = {}
        for period in ("train", "validation", "final"):
            filtered = v10.apply_filter(source[period], row["filter"])
            event_rows = v10.rows_for_primitive(filtered, primitive)
            row["parts"][period] = make_part(event_rows)

    portfolios = []
    for size in PORTFOLIO_SIZES:
        for indices in itertools.combinations(range(len(pool)), size):
            members = [pool[index] for index in indices]
            identities = {(row["code"], row["filter"]["name"]) for row in members}
            if len(identities) < 2:
                continue
            train = combine_parts([row["parts"]["train"] for row in members])
            validation = combine_parts([row["parts"]["validation"] for row in members])
            score = portfolio_score(train, validation)
            if score <= -1e8:
                continue
            portfolios.append({
                "score": score,
                "members": [
                    {
                        "variant": row["variant"],
                        "selectionMode": row["mode"],
                        "filter": row["filter"],
                        "code": row["code"],
                        "betType": row["betType"],
                        "predictedRanks": row["predictedRanks"],
                    }
                    for row in members
                ],
                "developmentA": compact(train),
                "developmentB": compact(validation),
                "_indices": indices,
            })

    portfolios.sort(
        key=lambda row: (
            row["score"],
            min(row["developmentA"]["roiPct"], row["developmentB"]["roiPct"]),
            min(row["developmentA"]["roiWithoutTop1Pct"], row["developmentB"]["roiWithoutTop1Pct"]),
        ),
        reverse=True,
    )
    preselected = portfolios[:TOP_PORTFOLIOS]
    for row in preselected:
        members = [pool[index] for index in row.pop("_indices")]
        final = combine_parts([member["parts"]["final"] for member in members])
        row["finalHoldout"] = compact(final)
        row["finalMonthly"] = final["monthly"]

    final_ranked = sorted(
        preselected,
        key=lambda row: (
            row["finalHoldout"]["roiWithoutTop1Pct"],
            row["finalHoldout"]["roiPct"],
            row["finalHoldout"]["hitRatePct"],
        ),
        reverse=True,
    )

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v11-shadow-portfolio-high-roi",
        "productionChanged": False,
        "promotionEligible": False,
        "actualJraPayoutsUsed": True,
        "syntheticOddsUsed": False,
        "sourceDataFrozen": True,
        "guardrails": {
            "portfolioChosenOnlyOnDevelopmentAAndB": True,
            "finalHoldoutNotUsedForSelection": True,
            "portfolioSizes": list(PORTFOLIO_SIZES),
            "candidatePool": len(pool),
            "minimumTicketsPerDevelopmentHalf": 400,
            "minimumHitsPerDevelopmentHalf": 8,
            "fiveRacesPerVenueDay": True,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
        },
        "modelAudit": model_audit,
        "candidateCount": len(candidate_meta),
        "portfolioCount": len(portfolios),
        "summary": {
            "bestByPreHoldoutSelection": preselected[:10],
            "bestFinalAmongPreselectedTop50": final_ranked[:10],
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidateCount": len(candidate_meta),
        "pool": len(pool),
        "portfolioCount": len(portfolios),
        "best": [
            {
                "members": [f'{m["betType"]}:{m["predictedRanks"]}:{m["filter"]["name"]}' for m in row["members"]],
                "A": row["developmentA"]["roiPct"],
                "B": row["developmentB"]["roiPct"],
                "F": row["finalHoldout"]["roiPct"],
                "FNoTop1": row["finalHoldout"]["roiWithoutTop1Pct"],
                "FHit": row["finalHoldout"]["hitRatePct"],
                "FTickets": row["finalHoldout"]["tickets"],
            }
            for row in preselected[:10]
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
