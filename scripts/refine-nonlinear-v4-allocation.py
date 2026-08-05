import importlib.util
import itertools
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

BASE_PATH = Path("scripts/train-nonlinear-market-blend-v4.py")
REPORT_PATH = Path("analysis-results/nonlinear-market-blend-v4.json")

spec = importlib.util.spec_from_file_location("nonlinear_v4", BASE_PATH)
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)


def allocation_vectors(total=10, slots=4):
    result = []
    for cuts in itertools.combinations_with_replacement(range(total + 1), slots - 1):
        values = []
        previous = 0
        for cut in cuts:
            values.append(cut - previous)
            previous = cut
        values.append(total - previous)
        if sum(value > 0 for value in values) >= 2:
            result.append(tuple(values))
    return sorted(set(result))


def unit_allocation(weights, total_units):
    positive = [index for index, weight in enumerate(weights) if weight > 0]
    if not positive:
        return [0] * len(weights)
    raw = [total_units * weight / sum(weights) if weight > 0 else 0 for weight in weights]
    units = [math.floor(value) for value in raw]
    remaining = total_units - sum(units)
    order = sorted(positive, key=lambda index: raw[index] - units[index], reverse=True)
    for index in order[:remaining]:
        units[index] += 1
    return units


def evaluate_weighted(races, budget, weights):
    stake = returned = hit_races = 0
    monthly = defaultdict(lambda: [0, 0])
    for race in races:
        bets = v4.template_bets(race, "mixed")
        if len(bets) != 4:
            continue
        units = unit_allocation(weights, max(1, budget // 100))
        race_return = 0
        for ticket_units, (bet_type, horses) in zip(units, bets):
            if ticket_units <= 0:
                continue
            ticket_stake = ticket_units * 100
            key = v4.bet_key(bet_type, horses)
            payout = 100 if any(horse in race["refunds"] for horse in horses) else race["payouts"].get(key, 0)
            value = payout * ticket_units
            stake += ticket_stake
            returned += value
            race_return += value
            monthly[race["raceDate"][:7]][0] += ticket_stake
            monthly[race["raceDate"][:7]][1] += value
        hit_races += int(race_return > 0)
    roi = returned / stake * 100 if stake else 0
    hit = hit_races / len(races) * 100 if races else 0
    month_rois = {month: values[1] / values[0] * 100 if values[0] else 0 for month, values in monthly.items()}
    min_month = min(month_rois.values()) if month_rois else 0
    objective = roi * 0.45 + min_month * 0.35 + hit * 0.20
    return {
        "races": len(races), "roi": roi, "hit": hit, "minMonth": min_month,
        "monthlyRois": month_rois, "profit": returned - stake, "objective": objective,
    }


def clean(result):
    output = {}
    for key, value in result.items():
        if isinstance(value, dict):
            output[key] = {month: round(float(roi), 4) for month, roi in value.items()}
        elif isinstance(value, (int, float, np.floating)):
            output[key] = round(float(value), 4)
        else:
            output[key] = value
    return output


def main():
    base_report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    selected = base_report["selectedModel"]

    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    split_races = {
        name: [race for race in races if v4.split_name(race["raceDate"]) == name]
        for name in ["train", "validation", "holdout"]
    }
    x_train, y_train, base_weights = v4.flatten_runners(split_races["train"])
    train_runner_odds = np.asarray([
        runner["winOdds"] for race in split_races["train"] for runner in race["runners"]
    ], dtype=np.float64)
    weights = base_weights.copy()
    winners = y_train == 1
    power = selected["longshotPower"]
    weights[winners] *= np.minimum(6.0, np.power(np.maximum(1.0, train_runner_odds[winners]), power))

    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=selected["max_leaf_nodes"],
        learning_rate=selected["learning_rate"],
        max_iter=selected["max_iter"],
        l2_regularization=selected["l2_regularization"],
        min_samples_leaf=40,
        random_state=42,
    )
    model.fit(x_train, y_train, sample_weight=weights)
    validation = v4.attach_probabilities(model, split_races["validation"], selected["blend"])
    holdout = v4.attach_probabilities(model, split_races["holdout"], selected["blend"])

    race_mode = base_report["selectedRaceConfiguration"]["mode"]
    race_count = base_report["selectedRaceConfiguration"]["count"]
    validation_selected = v4.select_races(validation, race_count, race_mode)
    holdout_selected = v4.select_races(holdout, race_count, race_mode)

    vectors = allocation_vectors()
    validation_results = {}
    holdout_results = {}
    for course, budget in v4.COURSE_BUDGETS.items():
        candidates = []
        for vector in vectors:
            result = evaluate_weighted(validation_selected, budget, vector)
            if result["hit"] < v4.REQUIRED_HIT:
                continue
            candidates.append({"weights": vector, "result": result})
        candidates.sort(
            key=lambda row: (
                row["result"]["minMonth"] >= 100,
                row["result"]["objective"],
                row["result"]["roi"],
            ),
            reverse=True,
        )
        winner = candidates[0]
        validation_results[course] = {
            "weights": {
                "wide_1_2": winner["weights"][0],
                "wide_1_3": winner["weights"][1],
                "quinella_1_2": winner["weights"][2],
                "trio_1_2_3": winner["weights"][3],
            },
            **clean(winner["result"]),
        }
        holdout_result = evaluate_weighted(holdout_selected, budget, winner["weights"])
        holdout_results[course] = {
            **clean(holdout_result),
            "pass200": holdout_result["roi"] >= v4.TARGET_ROI,
            "hitRequirementMet": holdout_result["hit"] >= v4.REQUIRED_HIT,
        }

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "Validation-only 10% allocation refinement for the fixed nonlinear v4 mixed portfolio.",
        "targetRoiPct": v4.TARGET_ROI,
        "minimumRacesPerVenueDay": 5,
        "fixedModel": selected,
        "fixedRaceConfiguration": {"mode": race_mode, "count": race_count},
        "ticketOrder": ["ワイド1-2", "ワイド1-3", "馬連1-2", "3連複1-2-3"],
        "validation": validation_results,
        "holdout": holdout_results,
    }
    report["promotionEligible"] = all(
        row["pass200"] and row["hitRequirementMet"] for row in holdout_results.values()
    )
    Path("nonlinear-v4-allocation-refinement.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for course in v4.COURSE_BUDGETS:
        print(
            f'{course}: weights {validation_results[course]["weights"]} / '
            f'validation {validation_results[course]["roi"]}% / '
            f'holdout {holdout_results[course]["roi"]}% / '
            f'hit {holdout_results[course]["hit"]}% / '
            f'200% {"PASS" if holdout_results[course]["pass200"] else "FAIL"}'
        )
    print(f'Promotion eligible: {"YES" if report["promotionEligible"] else "NO"}')


if __name__ == "__main__":
    main()
