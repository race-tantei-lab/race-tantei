import importlib.util
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
analysis = load_module("v6_ticket_ev", ROOT / "scripts" / "analyze-v6-ticket-ev.py")


def efficient_fit_ticket_model(training_races):
    rows = analysis.build_ticket_rows(training_races)
    if not rows:
        raise RuntimeError("V6_6_EMPTY_TICKET_TRAINING")
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray([int(row["payoutYen"] > 0) for row in rows], dtype=np.int8)
    race_indices = np.asarray([row["raceIndex"] for row in rows], dtype=np.int32)
    counts = np.bincount(race_indices, minlength=len(training_races))
    sample_weight = 1.0 / np.maximum(1, counts[race_indices])
    positive_rate = float(y.mean())
    positive_boost = min(4.0, max(1.0, (1.0 - positive_rate) / max(0.01, positive_rate) * 0.15))
    sample_weight[y == 1] *= positive_boost
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=31,
        learning_rate=0.035,
        max_iter=220,
        l2_regularization=5.0,
        min_samples_leaf=70,
        random_state=2026080620,
    )
    model.fit(x, y, sample_weight=sample_weight)
    return model, {
        "ticketRows": len(rows),
        "positiveRatePct": positive_rate * 100,
        "positiveBoost": positive_boost,
    }


def efficient_scored_races(model, races, alpha):
    copied_races = [dict(race) for race in races]
    flat_rows = []
    row_race_indices = []
    for race_index, race in enumerate(races):
        for primitive in analysis.base.PRIMITIVES:
            row = analysis.primitive_feature(race, primitive)
            if row is None:
                continue
            flat_rows.append(row)
            row_race_indices.append(race_index)
    if not flat_rows:
        for race in copied_races:
            race["ticketCandidates"] = []
        return copied_races
    predictions = model.predict_proba(
        np.asarray([row["features"] for row in flat_rows], dtype=np.float64)
    )[:, 1]
    candidates = [[] for _ in copied_races]
    for row, race_index, learned in zip(flat_rows, row_race_indices, predictions):
        learned = float(learned)
        probability = (1.0 - alpha) * row["modelProbability"] + alpha * learned
        probability = max(0.000001, min(0.999999, probability))
        expected_value = (
            probability
            * row["assumedOdds"]
            * 100.0
            * analysis.RELIABILITY[row["betType"]]
        )
        item = dict(row)
        item["learnedProbability"] = learned
        item["hitProbability"] = probability
        item["expectedValuePct"] = expected_value
        candidates[race_index].append(item)
    for race, rows in zip(copied_races, candidates):
        race["ticketCandidates"] = rows
    return copied_races


def efficient_evaluate_config(races, course, config):
    allowed_types = analysis.base.COURSE_ALLOWED_TYPES[course]
    source_group_counts = defaultdict(int)
    eligible_groups = defaultdict(list)
    for race in races:
        key = (race["raceDate"], race["venue"])
        source_group_counts[key] += 1
        eligible = [
            candidate
            for candidate in race["ticketCandidates"]
            if candidate["betType"] in allowed_types
            and candidate["assumedOdds"] <= config["maxOdds"]
            and candidate["expectedValuePct"] >= config["minEv"]
        ]
        eligible.sort(
            key=lambda row: (row["expectedValuePct"], row["hitProbability"]),
            reverse=True,
        )
        if eligible:
            top = eligible[: config["ticketLimit"]]
            copied = dict(race)
            copied["eligibleTickets"] = top
            copied["selectionScore"] = float(
                max(row["expectedValuePct"] for row in top)
                + np.mean([row["expectedValuePct"] for row in top]) * 0.35
            )
            eligible_groups[key].append(copied)

    expected_keys = [key for key, count in source_group_counts.items() if count >= 5]
    selected = []
    for key in expected_keys:
        group = eligible_groups.get(key, [])
        if len(group) < 5:
            return None
        group.sort(key=lambda race: (-race["selectionScore"], race["raceNo"]))
        selected.extend(group[:5])

    budget_units = analysis.base.COURSE_BUDGETS[course] // 100
    stake = returned = hit_races = 0
    single_returns = []
    monthly = defaultdict(lambda: {"races": 0, "stake": 0, "return": 0.0, "hits": 0})
    by_day = defaultdict(lambda: {"races": 0, "stake": 0, "return": 0.0, "hits": 0})
    for race in selected:
        tickets = race["eligibleTickets"][: config["ticketLimit"]]
        maximum_ev = max(ticket["expectedValuePct"] for ticket in tickets)
        edge_strength = max(0.0, maximum_ev / 100.0 - 1.0)
        fraction = min(
            1.0,
            max(
                config["minSpendFraction"],
                config["minSpendFraction"] + edge_strength / config["edgeScale"],
            ),
        )
        total_units = max(len(tickets), int(round(budget_units * fraction)))
        total_units = min(budget_units, total_units)
        units = analysis.allocate_units(tickets, total_units, config["allocationPower"])
        race_return = 0.0
        race_stake = total_units * 100
        for ticket, ticket_units in zip(tickets, units):
            value = ticket["payoutYen"] * ticket_units
            race_return += value
            single_returns.append(value)
        race_hit = int(race_return > 0)
        stake += race_stake
        returned += race_return
        hit_races += race_hit
        month = race["raceDate"][:7]
        monthly[month]["races"] += 1
        monthly[month]["stake"] += race_stake
        monthly[month]["return"] += race_return
        monthly[month]["hits"] += race_hit
        day = race["raceDate"]
        by_day[day]["races"] += 1
        by_day[day]["stake"] += race_stake
        by_day[day]["return"] += race_return
        by_day[day]["hits"] += race_hit

    def summarize(rows):
        output = {}
        for key, row in sorted(rows.items()):
            output[key] = {
                "races": row["races"],
                "stakeYen": int(row["stake"]),
                "returnYen": int(round(row["return"])),
                "roiPct": row["return"] / row["stake"] * 100 if row["stake"] else 0.0,
                "hitRatePct": row["hits"] / row["races"] * 100 if row["races"] else 0.0,
            }
        return output

    monthly_metrics = summarize(monthly)
    by_day_metrics = summarize(by_day)
    rois = [row["roiPct"] for row in monthly_metrics.values()]
    hits = [row["hitRatePct"] for row in monthly_metrics.values()]
    total_roi = returned / stake * 100 if stake else 0.0
    total_hit = hit_races / len(selected) * 100 if selected else 0.0
    q25_roi = float(np.quantile(rois, 0.25)) if rois else 0.0
    median_roi = float(np.median(rois)) if rois else 0.0
    minimum_roi = min(rois) if rois else 0.0
    minimum_hit = min(hits) if hits else 0.0
    max_single_share = max(single_returns) / returned if returned > 0 and single_returns else 1.0
    winning_months = sum(value >= 100.0 for value in rois)
    score = (
        q25_roi * 0.38
        + median_roi * 0.22
        + total_roi * 0.18
        + total_hit * 0.17
        + minimum_hit * 0.05
        - max(0.0, analysis.REQUIRED_HIT - total_hit) * 4.5
        - max(0.0, 2.0 - winning_months) * 30.0
        - max(0.0, max_single_share - 0.35) * 250.0
        - max(0.0, 65.0 - minimum_roi) * 1.5
    )
    return {
        "selectedRaces": len(selected),
        "stakeYen": int(stake),
        "returnYen": int(round(returned)),
        "profitYen": int(round(returned - stake)),
        "roiPct": total_roi,
        "hitRatePct": total_hit,
        "q25MonthlyRoiPct": q25_roi,
        "medianMonthlyRoiPct": median_roi,
        "minimumMonthlyRoiPct": minimum_roi,
        "minimumMonthlyHitRatePct": minimum_hit,
        "winningMonths": winning_months,
        "maxSingleReturnShare": max_single_share,
        "monthly": monthly_metrics,
        "byDay": by_day_metrics,
        "score": score,
    }


analysis.fit_ticket_model = efficient_fit_ticket_model
analysis.scored_races = efficient_scored_races
analysis.evaluate_config = efficient_evaluate_config
analysis.main()
