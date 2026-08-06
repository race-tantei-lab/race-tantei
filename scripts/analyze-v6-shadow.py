import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v4 = load_module("v4_training", ROOT / "scripts" / "train-nonlinear-market-blend-v4.py")
policy = load_module("final_policy", ROOT / "scripts" / "final-course-policy.py")

# Load finished races through the latest available August date. Features remain chronological,
# because build_dataset updates every history store only after each race is materialized.
v4.HOLDOUT_END = "2026-08-31"

TRAIN_START = "2025-05-01"
TRAIN_END = "2026-04-30"
VALIDATION_START = "2026-05-01"
VALIDATION_END = "2026-06-30"
JULY_START = "2026-07-01"
JULY_END = "2026-07-31"
AUGUST_START = "2026-08-01"
AUGUST_END = "2026-08-02"

MODEL_CONFIGS = [
    {"max_leaf_nodes": 7, "learning_rate": 0.04, "max_iter": 160, "l2_regularization": 2.0},
    {"max_leaf_nodes": 15, "learning_rate": 0.03, "max_iter": 220, "l2_regularization": 4.0},
    {"max_leaf_nodes": 31, "learning_rate": 0.02, "max_iter": 260, "l2_regularization": 8.0},
]
BLENDS = [0.15, 0.30, 0.45, 0.60, 0.80, 1.00]
TEMPERATURES = [0.70, 1.00, 1.30]
RACE_MODES = ["confidence", "edge", "disagreement", "concentration", "entropy", "balanced"]


def in_range(race_date, start, end):
    return start <= race_date <= end


def pairwise_training_rows(races):
    x = []
    y = []
    weights = []
    for race in races:
        winner = next((runner for runner in race["runners"] if runner["finish"] == 1), None)
        if winner is None:
            continue
        losers = [runner for runner in race["runners"] if runner["finish"] != 1]
        if not losers:
            continue
        unit = 1.0 / (2 * len(losers))
        winner_features = np.asarray(winner["features"], dtype=np.float64)
        for loser in losers:
            loser_features = np.asarray(loser["features"], dtype=np.float64)
            difference = winner_features - loser_features
            x.append(difference)
            y.append(1)
            weights.append(unit)
            x.append(-difference)
            y.append(0)
            weights.append(unit)
    return (
        np.asarray(x, dtype=np.float64),
        np.asarray(y, dtype=np.int8),
        np.asarray(weights, dtype=np.float64),
    )


def fit_pairwise(races, config):
    x, y, weights = pairwise_training_rows(races)
    if len(y) == 0:
        raise RuntimeError("V6_PAIRWISE_TRAINING_EMPTY")
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=config["max_leaf_nodes"],
        learning_rate=config["learning_rate"],
        max_iter=config["max_iter"],
        l2_regularization=config["l2_regularization"],
        min_samples_leaf=45,
        random_state=20260806,
    )
    model.fit(x, y, sample_weight=weights)
    return model


def pairwise_probabilities(model, race, temperature):
    runners = race["runners"]
    count = len(runners)
    if count < 2:
        return np.asarray([1.0] * count, dtype=np.float64)
    scores = np.zeros(count, dtype=np.float64)
    comparisons = np.zeros(count, dtype=np.float64)
    rows = []
    pairs = []
    for first in range(count):
        first_features = np.asarray(runners[first]["features"], dtype=np.float64)
        for second in range(first + 1, count):
            second_features = np.asarray(runners[second]["features"], dtype=np.float64)
            rows.append(first_features - second_features)
            pairs.append((first, second))
    probabilities = model.predict_proba(np.asarray(rows, dtype=np.float64))[:, 1]
    for (first, second), probability in zip(pairs, probabilities):
        scores[first] += probability
        scores[second] += 1.0 - probability
        comparisons[first] += 1
        comparisons[second] += 1
    scores = scores / np.maximum(1.0, comparisons)
    scores = np.power(np.maximum(scores, 1e-8), temperature)
    return scores / max(1e-12, scores.sum())


def attach_pairwise(model, races, blend, temperature):
    attached = []
    for race in races:
        pairwise = pairwise_probabilities(model, race, temperature)
        market = np.asarray([runner["market"] for runner in race["runners"]], dtype=np.float64)
        probability = (1.0 - blend) * market + blend * pairwise
        probability = probability / max(1e-12, probability.sum())
        runners = []
        for runner, value in zip(race["runners"], probability):
            item = dict(runner)
            item["probability"] = float(value)
            item["edge"] = float(value / max(1e-8, runner["market"]))
            runners.append(item)
        runners.sort(key=lambda item: item["probability"], reverse=True)
        item = dict(race)
        item["runners"] = runners
        item["topProbability"] = runners[0]["probability"]
        item["probabilityGap"] = runners[0]["probability"] - runners[1]["probability"]
        item["top3Concentration"] = sum(runner["probability"] for runner in runners[:3])
        item["maxEdge"] = max(runner["edge"] for runner in runners[:7])
        item["disagreement"] = sum(abs(runner["probability"] - runner["market"]) for runner in runners)
        item["entropy"] = -sum(runner["probability"] * math.log(max(1e-12, runner["probability"])) for runner in runners)
        attached.append(item)
    return attached


def ranking_metrics_by_month(races):
    rows = defaultdict(lambda: {"races": 0, "loss": 0.0, "top1": 0, "top3": 0, "top1Return": 0.0})
    for race in races:
        winner = next((runner for runner in race["runners"] if runner["finish"] == 1), None)
        if winner is None:
            continue
        month = race["raceDate"][:7]
        row = rows[month]
        row["races"] += 1
        row["loss"] -= math.log(max(1e-12, winner["probability"]))
        row["top1"] += int(race["runners"][0]["finish"] == 1)
        row["top3"] += int(any(runner["finish"] == 1 for runner in race["runners"][:3]))
        if race["runners"][0]["finish"] == 1:
            row["top1Return"] += race["runners"][0]["winOdds"] * 100
    result = {}
    for month, row in sorted(rows.items()):
        count = row["races"]
        result[month] = {
            "races": count,
            "logLoss": row["loss"] / count if count else 999.0,
            "top1Pct": row["top1"] / count * 100 if count else 0.0,
            "top3Pct": row["top3"] / count * 100 if count else 0.0,
            "top1Roi": row["top1Return"] / (count * 100) * 100 if count else 0.0,
        }
    return result


def ranking_score(monthly):
    values = list(monthly.values())
    if not values:
        return 999.0
    worst_loss = max(row["logLoss"] for row in values)
    mean_loss = sum(row["logLoss"] for row in values) / len(values)
    minimum_top3 = min(row["top3Pct"] for row in values)
    minimum_top1 = min(row["top1Pct"] for row in values)
    return worst_loss * 0.70 + mean_loss * 0.30 - minimum_top3 * 0.0020 - minimum_top1 * 0.0010


def race_score(race, mode):
    if mode == "confidence":
        return race["topProbability"] * 6 + race["probabilityGap"] * 10
    if mode == "edge":
        return math.log(max(1.0, race["maxEdge"])) + race["topProbability"]
    if mode == "disagreement":
        return race["disagreement"]
    if mode == "concentration":
        return race["top3Concentration"] + race["probabilityGap"] * 2
    if mode == "entropy":
        return -race["entropy"]
    return (
        race["topProbability"] * 3
        + race["probabilityGap"] * 5
        + race["top3Concentration"]
        + math.log(max(1.0, race["maxEdge"])) * 0.7
        + race["disagreement"] * 0.4
        - race["entropy"] * 0.2
    )


def select_five(races, mode):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    for group in grouped.values():
        if len(group) < 5:
            continue
        group.sort(key=lambda race: (-race_score(race, mode), race["raceNo"]))
        selected.extend(group[:5])
    return selected


def clean_policy_metrics(metrics):
    cleaned = {}
    for course, row in metrics.items():
        cleaned[course] = {
            "races": int(row["races"]),
            "tickets": int(row["tickets"]),
            "stakeYen": int(row["stakeYen"]),
            "returnYen": int(row["returnYen"]),
            "profitYen": int(row["profitYen"]),
            "roiPct": round(float(row["roiPct"]), 4),
            "hitRatePct": round(float(row["hitRatePct"]), 4),
            "monthlyRois": {month: round(float(value), 4) for month, value in row["monthlyRois"].items()},
        }
    return cleaned


def portfolio_score(metrics):
    course_scores = []
    for row in metrics.values():
        monthly = list(row["monthlyRois"].values())
        minimum_month = min(monthly) if monthly else 0.0
        course_scores.append(
            row["roiPct"] * 0.30
            + minimum_month * 0.45
            + row["hitRatePct"] * 0.25
        )
    return min(course_scores) if course_scores else -999.0


def train_and_attach(train_races, target_races, config, blend, temperature):
    model = fit_pairwise(train_races, config)
    return model, attach_pairwise(model, target_races, blend, temperature)


def main():
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    train = [race for race in races if in_range(race["raceDate"], TRAIN_START, TRAIN_END)]
    validation_raw = [race for race in races if in_range(race["raceDate"], VALIDATION_START, VALIDATION_END)]
    july_raw = [race for race in races if in_range(race["raceDate"], JULY_START, JULY_END)]
    august_raw = [race for race in races if in_range(race["raceDate"], AUGUST_START, AUGUST_END)]

    ranking_candidates = []
    trained_models = []
    for config in MODEL_CONFIGS:
        model = fit_pairwise(train, config)
        trained_models.append((config, model))
        for blend in BLENDS:
            for temperature in TEMPERATURES:
                validation = attach_pairwise(model, validation_raw, blend, temperature)
                monthly = ranking_metrics_by_month(validation)
                ranking_candidates.append({
                    "config": config,
                    "model": model,
                    "blend": blend,
                    "temperature": temperature,
                    "validation": validation,
                    "monthly": monthly,
                    "score": ranking_score(monthly),
                })
    ranking_candidates.sort(key=lambda row: row["score"])

    portfolio_candidates = []
    for candidate in ranking_candidates[:8]:
        for mode in RACE_MODES:
            selected = select_five(candidate["validation"], mode)
            metrics = policy.evaluate(selected)
            portfolio_candidates.append({
                "candidate": candidate,
                "mode": mode,
                "selected": selected,
                "metrics": metrics,
                "score": portfolio_score(metrics),
            })
    portfolio_candidates.sort(key=lambda row: row["score"], reverse=True)
    winner = portfolio_candidates[0]
    chosen = winner["candidate"]

    # Freeze hyperparameters after May-June. Retrain chronologically before each later period.
    through_june = [race for race in races if TRAIN_START <= race["raceDate"] <= VALIDATION_END]
    july_model, july = train_and_attach(
        through_june,
        july_raw,
        chosen["config"],
        chosen["blend"],
        chosen["temperature"],
    )
    july_selected = select_five(july, winner["mode"])
    july_metrics = policy.evaluate(july_selected)

    through_july = [race for race in races if TRAIN_START <= race["raceDate"] <= JULY_END]
    _, august = train_and_attach(
        through_july,
        august_raw,
        chosen["config"],
        chosen["blend"],
        chosen["temperature"],
    )
    august_selected = select_five(august, winner["mode"])
    august_metrics = policy.evaluate(august_selected)

    report = {
        "generatedAt": v4.date.today().isoformat(),
        "modelVersion": "v6-shadow-pairwise-ranking",
        "productionChanged": False,
        "method": "Pairwise horse-ranking model blended with market probability; hyperparameters and 5R selection are chosen on May-June only, then retrained chronologically for July and August.",
        "samples": {
            "trainRaces": len(train),
            "validationRaces": len(validation_raw),
            "julyRaces": len(july_raw),
            "augustRaces": len(august_raw),
        },
        "selected": {
            "config": chosen["config"],
            "blend": chosen["blend"],
            "temperature": chosen["temperature"],
            "raceSelectionMode": winner["mode"],
            "validationRankingByMonth": chosen["monthly"],
            "validationPortfolio": clean_policy_metrics(winner["metrics"]),
        },
        "july": {
            "rankingByMonth": ranking_metrics_by_month(july),
            "selectedRaces": len(july_selected),
            "portfolio": clean_policy_metrics(july_metrics),
        },
        "august": {
            "rankingByMonth": ranking_metrics_by_month(august),
            "selectedRaces": len(august_selected),
            "portfolio": clean_policy_metrics(august_metrics),
        },
        "promotionEligible": all(
            row["roiPct"] >= 100 and row["hitRatePct"] >= 30
            for row in august_metrics.values()
        ) and all(row["roiPct"] >= 100 for row in july_metrics.values()),
    }
    Path("v6-shadow-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
