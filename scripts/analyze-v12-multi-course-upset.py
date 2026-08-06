import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v7-enriched-ranking.py"
CONSTRAINTS = ROOT / "config" / "race-tantei-fixed-constraints.json"
OUTPUT = ROOT / "v12-multi-course-upset-analysis.json"

ROLLING_START = "2024-11"
DEV_A_START = "2025-05-01"
DEV_B_START = "2025-11-01"
FINAL_START = "2026-05-01"
VARIANTS = ("point", "pair", "ensemble")
MODES = ("confidence", "upset", "hybrid")
RACE_COUNTS = (5, 7)
THRESHOLDS = (0.35, 0.45, 0.55, 0.65)

EXPECTED = {
    "version": 1,
    "immutableProjectRules": {
        "minimumRacesPerVenueDay": 5,
        "mayIncreaseRaces": True,
        "mayDecreaseBelowMinimum": False,
        "officialOddsOnly": True,
        "syntheticOddsForbidden": True,
        "postResultLeakageForbidden": True,
    },
    "courses": {
        "ライト": {
            "budgetYen": 2000,
            "ticketCount": 6,
            "allowedBetTypes": ["単勝", "ワイド", "馬連"],
            "requireEveryAllowedBetType": True,
        },
        "スタンダード": {
            "budgetYen": 5000,
            "ticketCount": 15,
            "allowedBetTypes": ["単勝", "ワイド", "馬連", "馬単", "3連複"],
            "requireEveryAllowedBetType": True,
        },
        "プレミアム": {
            "budgetYen": 10000,
            "ticketCount": 16,
            "allowedBetTypes": ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"],
            "requireEveryAllowedBetType": True,
        },
    },
}

TYPE_COUNTS = {
    "ライト": {"単勝": 1, "ワイド": 3, "馬連": 2},
    "スタンダード": {"単勝": 1, "ワイド": 4, "馬連": 2, "馬単": 5, "3連複": 3},
    "プレミアム": {"単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 3, "3連複": 3, "3連単": 5},
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


enriched = load_module("v12_enriched", SOURCE)
v7 = enriched.v7
base = enriched.base
v4 = enriched.v4


def num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def verify_constraints():
    actual = json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
    if actual != EXPECTED:
        raise RuntimeError("V12_FIXED_CONSTRAINTS_CHANGED")
    for course, counts in TYPE_COUNTS.items():
        spec = actual["courses"][course]
        if sum(counts.values()) != spec["ticketCount"]:
            raise RuntimeError(f"V12_TICKET_COUNT_CHANGED:{course}")
        if set(counts) != set(spec["allowedBetTypes"]):
            raise RuntimeError(f"V12_BET_TYPES_CHANGED:{course}")
    return actual


def market_stats(race):
    values = np.asarray([max(1e-12, num(row.get("market"))) for row in race["runners"]])
    values /= max(1e-12, values.sum())
    ordered = np.sort(values)[::-1]
    return (
        float(ordered[0]),
        float(ordered[:3].sum()),
        float(-np.sum(values * np.log(np.maximum(values, 1e-12)))),
    )


def upset_x(race):
    m1, m3, me = market_stats(race)
    return [
        num(race.get("topProbability")),
        num(race.get("probabilityGap")),
        num(race.get("top3Concentration")),
        num(race.get("entropy")),
        num(race.get("disagreement")),
        num(race.get("maxEdge")),
        m1, m3, me,
        len(race["runners"]) / 18.0,
        num(race.get("raceNo")) / 12.0,
        num(race.get("distanceM")) / 3200.0,
        int(race.get("surface") == "芝"),
        int(race.get("surface") == "ダート"),
    ]


def upset_y(race):
    winner = next((row for row in race["runners"] if int(num(row.get("finish"))) == 1), None)
    return None if winner is None else int(int(num(winner.get("popularity"), 99)) >= 5)


def attach_upset(predictions, months):
    history = []
    audit = {}
    for month in months:
        target = predictions["ensemble"][month]
        x, y = [], []
        for race in history:
            label = upset_y(race)
            if label is not None:
                x.append(upset_x(race))
                y.append(label)
        if len(y) >= 500 and len(set(y)) == 2:
            model = HistGradientBoostingClassifier(
                max_leaf_nodes=15,
                learning_rate=0.035,
                max_iter=160,
                l2_regularization=6.0,
                min_samples_leaf=45,
                random_state=2026080632,
            )
            model.fit(np.asarray(x), np.asarray(y))
            probabilities = model.predict_proba(np.asarray([upset_x(r) for r in target]))[:, 1]
            source = "rolling_classifier"
        else:
            probabilities = np.asarray([
                min(0.85, max(0.08, 0.18 + 0.25 * num(r.get("disagreement"))
                              + 0.15 * num(r.get("entropy")) / 3.0
                              + 0.20 * (1.0 - market_stats(r)[1])))
                for r in target
            ])
            source = "cold_start"
        by_id = {race["raceId"]: float(p) for race, p in zip(target, probabilities)}
        for variant in VARIANTS:
            predictions[variant][month] = [
                {**race, "upsetProbability": by_id[race["raceId"]]}
                for race in predictions[variant][month]
            ]
        audit[month] = {"trainingRaces": len(y), "source": source}
        history.extend(target)
    return audit


def scale(values):
    values = np.asarray(values, dtype=float)
    span = values.max() - values.min()
    return np.zeros_like(values) if span < 1e-12 else (values - values.min()) / span


def select_races(races, mode, count):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected, coverage = [], []
    for key, group in sorted(grouped.items()):
        if len(group) < 5:
            raise RuntimeError(f"V12_SOURCE_BELOW_FIVE:{key}:{len(group)}")
        confidence = scale([num(r.get("topProbability")) for r in group])
        upset = scale([num(r.get("upsetProbability")) for r in group])
        disagreement = scale([num(r.get("disagreement")) for r in group])
        if mode == "confidence":
            score = confidence + 0.15 * upset
        elif mode == "upset":
            score = upset + 0.20 * disagreement
        else:
            score = 0.50 * confidence + 0.40 * upset + 0.10 * disagreement
        take = min(len(group), max(5, count))
        picked = [group[int(i)] for i in np.argsort(-score)[:take]]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    if min(row["selected"] for row in coverage) < 5:
        raise RuntimeError("V12_SELECTED_BELOW_FIVE")
    return selected, coverage


def risk(primitive):
    _, bet_type, ranks = primitive
    bonus = {"単勝": 0, "ワイド": .2, "馬連": .4, "馬単": .8, "3連複": 1, "3連単": 1.5}[bet_type]
    return float(np.mean(ranks) + 0.35 * max(ranks) + bonus)


def policy_candidates(course, primitives, budget):
    by_type = defaultdict(list)
    for primitive in primitives:
        by_type[primitive[1]].append(primitive)
    for bet_type in by_type:
        by_type[bet_type].sort(key=risk)
    rows = []
    for offset in range(8):
        normal, upset = [], []
        for bet_type, count in TYPE_COUNTS[course].items():
            pool = by_type[bet_type]
            normal.extend(pool[(offset + i) % len(pool)] for i in range(count))
            reverse = list(reversed(pool))
            upset.extend(reverse[(offset + i) % len(reverse)] for i in range(count))
        for threshold in THRESHOLDS:
            rows.append({
                "threshold": threshold,
                "normal": normal,
                "upset": upset,
                "normalUnits": allocate_units(normal, budget, False),
                "upsetUnits": allocate_units(upset, budget, True),
            })
    return rows


def allocate_units(primitives, budget, upset):
    units = [1] * len(primitives)
    scores = [math.exp((0.12 if upset else -0.20) * risk(p)) for p in primitives]
    remaining = budget // 100 - len(units)
    while remaining > 0:
        index = max(range(len(units)), key=lambda i: scores[i] / (1 + units[i] * .7))
        units[index] += 1
        remaining -= 1
    if sum(units) * 100 != budget:
        raise RuntimeError("V12_BUDGET_MISMATCH")
    return units


def matrix_for(candidates, primitives, side):
    index = {p[0]: i for i, p in enumerate(primitives)}
    matrix = np.zeros((len(candidates), len(primitives)), dtype=np.int16)
    for row, candidate in enumerate(candidates):
        for primitive, units in zip(candidate[side], candidate[f"{side}Units"]):
            matrix[row, index[primitive[0]]] += units
    return matrix


def payout_matrix(races, primitives):
    return np.asarray([[base.primitive_payout(race, p) for p in primitives] for race in races], dtype=float)


def summarize(returns, races, budget):
    returns = np.asarray(returns, dtype=float)
    stake = len(races) * budget
    total = float(returns.sum())
    top = float(returns.max()) if len(returns) else 0.0
    hits = int(np.sum(returns > 0))
    by_month = defaultdict(list)
    for race, value in zip(races, returns):
        by_month[race["raceDate"][:7]].append(float(value))
    monthly = {}
    for month, values in sorted(by_month.items()):
        s = len(values) * budget
        r = sum(values)
        monthly[month] = {
            "races": len(values), "stakeYen": s, "returnYen": round(r),
            "roiPct": r / s * 100 if s else 0,
            "hitRatePct": sum(v > 0 for v in values) / len(values) * 100,
        }
    return {
        "races": len(races), "hits": hits, "stakeYen": stake,
        "returnYen": round(total), "profitYen": round(total - stake),
        "roiPct": total / stake * 100 if stake else 0,
        "hitRatePct": hits / len(races) * 100 if races else 0,
        "roiWithoutTop1Pct": max(0, total - top) / stake * 100 if stake else 0,
        "maxSingleReturnShare": top / total if total > 0 else 1,
        "zeroHitMonths": sum(all(v <= 0 for v in values) for values in by_month.values()),
        "monthly": monthly,
    }


def compact(row):
    return {k: v for k, v in row.items() if k != "monthly"}


def score(a, b, course):
    minimum_hit = {"ライト": 12, "スタンダード": 7, "プレミアム": 3}[course]
    if min(a["races"], b["races"]) < 300 or min(a["hits"], b["hits"]) < 10:
        return -1e9
    value = (
        min(a["roiPct"], 180) * .20 + min(b["roiPct"], 180) * .30
        + min(a["roiWithoutTop1Pct"], 160) * .20
        + min(b["roiWithoutTop1Pct"], 160) * .25
        + min(a["hitRatePct"], 35) * .02 + min(b["hitRatePct"], 35) * .03
    )
    value -= max(0, 90 - min(a["roiPct"], b["roiPct"])) * 1.4
    value -= max(0, 75 - min(a["roiWithoutTop1Pct"], b["roiWithoutTop1Pct"])) * 1.2
    value -= max(0, minimum_hit - min(a["hitRatePct"], b["hitRatePct"])) * 3
    value -= max(0, a["maxSingleReturnShare"] - .30) * 180
    value -= max(0, b["maxSingleReturnShare"] - .30) * 220
    value -= (a["zeroHitMonths"] + b["zeroHitMonths"]) * 10
    return value


def describe(candidate):
    def side(name):
        return [
            {"code": p[0], "betType": p[1], "predictedRanks": list(p[2]), "stakeYen": u * 100}
            for p, u in zip(candidate[name], candidate[f"{name}Units"])
        ]
    return {"upsetThreshold": candidate["threshold"], "normal": side("normal"), "upset": side("upset")}


def main():
    constraints = verify_constraints()
    rows, payouts = v4.load_data()
    races = enriched.enrich_races(v4.build_dataset(rows, payouts), enriched.load_extra_rows())
    last_month = max(r["raceDate"][:7] for r in races)
    months = v7.month_sequence(ROLLING_START, last_month)
    predictions, ranking_audit = enriched.rolling_predictions(races, months)
    upset_audit = attach_upset(predictions, months)
    primitives = list(base.PRIMITIVES)

    candidates = {
        course: policy_candidates(course, primitives, spec["budgetYen"])
        for course, spec in constraints["courses"].items()
    }
    matrices = {
        course: {
            "normal": matrix_for(rows, primitives, "normal"),
            "upset": matrix_for(rows, primitives, "upset"),
        }
        for course, rows in candidates.items()
    }
    best = {course: None for course in candidates}

    for variant in VARIANTS:
        for mode in MODES:
            for count in RACE_COUNTS:
                selected, coverage = [], []
                for month in months:
                    if month < DEV_A_START[:7]:
                        continue
                    picked, cov = select_races(predictions[variant][month], mode, count)
                    selected.extend(picked)
                    coverage.extend(cov)
                payouts_all = payout_matrix(selected, primitives)
                upset_p = np.asarray([r["upsetProbability"] for r in selected])
                a_idx = [i for i, r in enumerate(selected) if DEV_A_START <= r["raceDate"] < DEV_B_START]
                b_idx = [i for i, r in enumerate(selected) if DEV_B_START <= r["raceDate"] < FINAL_START]
                for course, course_candidates in candidates.items():
                    budget = constraints["courses"][course]["budgetYen"]
                    normal_returns = payouts_all @ matrices[course]["normal"].T
                    upset_returns = payouts_all @ matrices[course]["upset"].T
                    for index, candidate in enumerate(course_candidates):
                        returns = np.where(upset_p >= candidate["threshold"],
                                           upset_returns[:, index], normal_returns[:, index])
                        a = summarize(returns[a_idx], [selected[i] for i in a_idx], budget)
                        b = summarize(returns[b_idx], [selected[i] for i in b_idx], budget)
                        value = score(a, b, course)
                        if best[course] is None or value > best[course]["selectionScore"]:
                            best[course] = {
                                "selectionScore": value, "variant": variant,
                                "selectionMode": mode, "racesPerVenueDay": count,
                                "candidateIndex": index, "developmentA": compact(a),
                                "developmentB": compact(b),
                            }

    results = {}
    for course, choice in best.items():
        selected, coverage = [], []
        for month in months:
            if month < DEV_A_START[:7]:
                continue
            picked, cov = select_races(
                predictions[choice["variant"]][month],
                choice["selectionMode"], choice["racesPerVenueDay"]
            )
            selected.extend(picked)
            coverage.extend(cov)
        payouts_all = payout_matrix(selected, primitives)
        upset_p = np.asarray([r["upsetProbability"] for r in selected])
        index = choice.pop("candidateIndex")
        candidate = candidates[course][index]
        normal_returns = payouts_all @ matrices[course]["normal"].T
        upset_returns = payouts_all @ matrices[course]["upset"].T
        returns = np.where(upset_p >= candidate["threshold"],
                           upset_returns[:, index], normal_returns[:, index])
        final_idx = [i for i, r in enumerate(selected) if r["raceDate"] >= FINAL_START]
        final = summarize(
            returns[final_idx], [selected[i] for i in final_idx],
            constraints["courses"][course]["budgetYen"]
        )
        results[course] = {
            **choice, "policy": describe(candidate), "finalHoldout": compact(final),
            "finalMonthly": final["monthly"],
            "coverage": {
                "groups": len(coverage),
                "minimumSelectedRaces": min(r["selected"] for r in coverage),
                "maximumSelectedRaces": max(r["selected"] for r in coverage),
            },
        }

    hit_minimum = {"ライト": 12, "スタンダード": 7, "プレミアム": 3}
    eligible = all(
        row["finalHoldout"]["roiPct"] >= 100
        and row["finalHoldout"]["roiWithoutTop1Pct"] >= 85
        and row["finalHoldout"]["hitRatePct"] >= hit_minimum[course]
        and row["coverage"]["minimumSelectedRaces"] >= 5
        for course, row in results.items()
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v12-shadow-multi-course-upset-aware",
        "productionChanged": False,
        "promotionEligible": eligible,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "officialWinOddsUsed": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "constraints": constraints,
        "period": {
            "dataStart": min(r["raceDate"] for r in races),
            "dataEnd": max(r["raceDate"] for r in races),
            "finishedRaces": len(races),
            "developmentA": f"{DEV_A_START}..{DEV_B_START}",
            "developmentB": f"{DEV_B_START}..{FINAL_START}",
            "finalHoldout": f"{FINAL_START}..end",
        },
        "rankingAudit": ranking_audit,
        "upsetAudit": upset_audit,
        "courses": results,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "promotionEligible": eligible,
        "courses": {
            course: {
                "racesPerVenueDay": row["racesPerVenueDay"],
                "finalHoldout": row["finalHoldout"],
            }
            for course, row in results.items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
