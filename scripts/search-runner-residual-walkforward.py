import gzip
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "artifacts" / "completion-search-dataset.pkl.gz"
OUTPUT = ROOT / "analysis-results" / "exploration-runner-residual-walkforward.json"

COURSES = {
    "ライト": {"budget": 2000, "tickets": 6, "maxShare": 0.40},
    "スタンダード": {"budget": 5000, "tickets": 15, "maxShare": 0.30},
    "プレミアム": {"budget": 10000, "tickets": 16, "maxShare": 0.24},
}
HOLDOUT_START = "2026-01-01"
SEED = 202608080832
EPS = 1e-8
UNORDERED = {"ワイド", "馬連", "3連複"}

MODEL_CONFIG = {
    "max_leaf_nodes": 23,
    "learning_rate": 0.05,
    "max_iter": 110,
    "l2_regularization": 10.0,
    "min_samples_leaf": 55,
}


def quarter(date_text):
    y, m = map(int, date_text[:7].split("-"))
    return f"{y}-Q{(m - 1) // 3 + 1}"


def canonical(bet_type, horses):
    values = tuple(int(x) for x in horses)
    if bet_type in UNORDERED:
        values = tuple(sorted(values))
    return values


def payout_key(bet_type, horses):
    return f'{bet_type}:{"-".join(map(str, canonical(bet_type, horses)))}'


def safe_float(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def runner_features(race, runner, include_market):
    base = np.asarray(runner.get("features") or [], dtype=np.float64)
    if len(base) >= 3:
        base = base[3:]
    market = max(EPS, safe_float(runner.get("market"), EPS))
    popularity = safe_float(runner.get("popularity"), len(race["runners"]))
    field = max(1, len(race["runners"]))
    extra = [
        race.get("raceNo", 0) / 12.0,
        field / 18.0,
        safe_float(race.get("distanceM")) / 3200.0,
        safe_float(race.get("classLevel")) / 7.0,
        1.0 if str(race.get("surface") or "") == "芝" else 0.0,
        1.0 if str(race.get("surface") or "") == "ダート" else 0.0,
    ]
    if include_market:
        extra.extend(
            [
                math.log(market),
                market,
                -popularity / field,
                math.log(max(1.01, safe_float(runner.get("winOdds"), 99.0))),
            ]
        )
    return np.concatenate([base, np.asarray(extra, dtype=np.float64)])


def flatten(races, include_market, target):
    x, y, w = [], [], []
    for race in races:
        field = max(1, len(race["runners"]))
        unit = 1.0 / field
        for runner in race["runners"]:
            x.append(runner_features(race, runner, include_market))
            finish = int(runner.get("finish") or 99)
            if target == "win":
                y.append(int(finish == 1))
            else:
                y.append(int(0 < finish <= 3))
            w.append(unit)
    return (
        np.asarray(x, dtype=np.float64),
        np.asarray(y, dtype=np.int8),
        np.asarray(w, dtype=np.float64),
    )


def fit_model(races, include_market, target, seed_offset):
    x, y, w = flatten(races, include_market, target)
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=MODEL_CONFIG["max_leaf_nodes"],
        learning_rate=MODEL_CONFIG["learning_rate"],
        max_iter=MODEL_CONFIG["max_iter"],
        l2_regularization=MODEL_CONFIG["l2_regularization"],
        min_samples_leaf=MODEL_CONFIG["min_samples_leaf"],
        random_state=SEED + seed_offset,
    )
    model.fit(x, y, sample_weight=w)
    return model


def normalize_win(raw):
    raw = np.maximum(np.asarray(raw, dtype=np.float64), 1e-9)
    return raw / raw.sum()


def normalize_place(raw):
    raw = np.clip(np.asarray(raw, dtype=np.float64), 1e-6, 0.999)
    total = raw.sum()
    if total > 0:
        raw = raw * (min(3.0, len(raw)) / total)
    return np.clip(raw, 1e-5, 0.97)


def predict_race(race, models):
    xf = np.asarray([runner_features(race, r, False) for r in race["runners"]], dtype=np.float64)
    xm = np.asarray([runner_features(race, r, True) for r in race["runners"]], dtype=np.float64)
    form_win = normalize_win(models["form_win"].predict_proba(xf)[:, 1])
    market_win = normalize_win(models["market_win"].predict_proba(xm)[:, 1])
    form_place = normalize_place(models["form_place"].predict_proba(xf)[:, 1])
    market_place = normalize_place(models["market_place"].predict_proba(xm)[:, 1])
    official_market = np.asarray(
        [max(EPS, safe_float(r.get("market"), EPS)) for r in race["runners"]], dtype=np.float64
    )
    official_market /= official_market.sum()
    return {
        "formWin": form_win,
        "marketWin": market_win,
        "formPlace": form_place,
        "marketPlace": market_place,
        "officialMarket": official_market,
    }


def cold_prediction(race):
    market = np.asarray(
        [max(EPS, safe_float(r.get("market"), EPS)) for r in race["runners"]], dtype=np.float64
    )
    market /= market.sum()
    place = normalize_place(market * 3.0)
    return {
        "formWin": market.copy(),
        "marketWin": market.copy(),
        "formPlace": place.copy(),
        "marketPlace": place.copy(),
        "officialMarket": market.copy(),
    }


def build_oos_predictions(races):
    byq = defaultdict(list)
    for i, race in enumerate(races):
        byq[quarter(race["raceDate"])].append(i)
    quarters = sorted(byq)
    predictions = [None] * len(races)
    audit = {}
    for q_index, q in enumerate(quarters):
        target_indices = byq[q]
        target_start = min(races[i]["raceDate"] for i in target_indices)
        train = [r for r in races if r["raceDate"] < target_start]
        if len(train) < 450:
            for i in target_indices:
                predictions[i] = cold_prediction(races[i])
            audit[q] = {"trainRaces": len(train), "targetRaces": len(target_indices), "mode": "cold_market"}
            continue
        models = {
            "form_win": fit_model(train, False, "win", q_index * 10 + 1),
            "market_win": fit_model(train, True, "win", q_index * 10 + 2),
            "form_place": fit_model(train, False, "place", q_index * 10 + 3),
            "market_place": fit_model(train, True, "place", q_index * 10 + 4),
        }
        for i in target_indices:
            predictions[i] = predict_race(races[i], models)
        audit[q] = {"trainRaces": len(train), "targetRaces": len(target_indices), "mode": "walk_forward"}
    return predictions, audit, quarters


def z(values):
    arr = np.asarray(values, dtype=np.float64)
    std = float(arr.std())
    if std < 1e-10:
        return np.zeros_like(arr)
    return (arr - float(arr.mean())) / std


def family_grid():
    rows = []
    for alpha in (0.20, 0.45, 0.70, 0.95):
        for anchor_min in (1, 2, 3, 4):
            for anchor_max in (8, 12, 18):
                for partner_style in ("place", "balanced", "value"):
                    for race_metric in ("edge", "mass", "upset", "disagreement"):
                        for alloc_power in (0.7, 1.2):
                            rows.append(
                                {
                                    "alpha": alpha,
                                    "anchorMin": anchor_min,
                                    "anchorMax": anchor_max,
                                    "partnerStyle": partner_style,
                                    "raceMetric": race_metric,
                                    "allocPower": alloc_power,
                                }
                            )
    return rows


FAMILIES = family_grid()


def role_order(race, prediction, family):
    alpha = family["alpha"]
    pwin = alpha * prediction["formWin"] + (1.0 - alpha) * prediction["marketWin"]
    pwin = normalize_win(pwin)
    pplace = alpha * prediction["formPlace"] + (1.0 - alpha) * prediction["marketPlace"]
    pplace = normalize_place(pplace)
    market = prediction["officialMarket"]
    log_edge = np.log(np.maximum(EPS, pwin) / np.maximum(EPS, market))
    pop = np.asarray([int(r.get("popularity") or 99) for r in race["runners"]], dtype=np.int32)

    allowed = (pop >= family["anchorMin"]) & (pop <= family["anchorMax"])
    anchor_score = 1.10 * z(log_edge) + 0.55 * z(pwin) + 0.30 * z(pplace)
    anchor_score = np.where(allowed, anchor_score, -1e9)
    anchor = int(np.argmax(anchor_score))

    if family["partnerStyle"] == "place":
        partner_score = 0.78 * z(pplace) + 0.22 * z(pwin)
    elif family["partnerStyle"] == "balanced":
        partner_score = 0.48 * z(pplace) + 0.34 * z(pwin) + 0.18 * z(log_edge)
    else:
        partner_score = 0.40 * z(pplace) + 0.25 * z(pwin) + 0.35 * z(log_edge)
    partner_score[anchor] = -1e9
    partner_indices = list(np.argsort(-partner_score, kind="stable"))
    roles = [anchor] + partner_indices[:5]

    positive_edge = np.maximum(0.0, log_edge)
    if family["raceMetric"] == "edge":
        race_score = float(log_edge[anchor] + 0.25 * pwin[anchor])
    elif family["raceMetric"] == "mass":
        race_score = float(positive_edge[np.argsort(-positive_edge)[:4]].sum())
    elif family["raceMetric"] == "upset":
        race_score = float(pwin[pop >= 4].sum() + 0.35 * positive_edge.sum())
    else:
        race_score = float(np.abs(pwin - market).sum() + 0.20 * positive_edge.sum())
    return roles, pwin, pplace, log_edge, race_score


def ticket_structure(course, roles):
    A, B, C, D, E, F = roles[:6]
    if course == "ライト":
        return [
            ("単勝", (A,)),
            ("ワイド", (A, B)),
            ("ワイド", (A, C)),
            ("ワイド", (B, C)),
            ("馬連", (A, B)),
            ("馬連", (A, C)),
        ]
    if course == "スタンダード":
        return [
            ("単勝", (A,)),
            ("単勝", (B,)),
            ("ワイド", (A, B)),
            ("ワイド", (A, C)),
            ("ワイド", (A, D)),
            ("ワイド", (B, C)),
            ("馬連", (A, B)),
            ("馬連", (A, C)),
            ("馬連", (B, C)),
            ("馬単", (A, B)),
            ("馬単", (B, A)),
            ("馬単", (A, C)),
            ("3連複", (A, B, C)),
            ("3連複", (A, B, D)),
            ("3連複", (A, C, D)),
        ]
    return [
        ("単勝", (A,)),
        ("ワイド", (A, B)),
        ("ワイド", (A, C)),
        ("馬連", (A, B)),
        ("馬連", (A, C)),
        ("馬単", (A, B)),
        ("馬単", (B, A)),
        ("馬単", (A, C)),
        ("3連複", (A, B, C)),
        ("3連複", (A, B, D)),
        ("3連複", (A, C, D)),
        ("3連単", (A, B, C)),
        ("3連単", (A, C, B)),
        ("3連単", (B, A, C)),
        ("3連単", (B, C, A)),
        ("3連単", (A, B, D)),
    ]


def allocation(course, spec, tickets, roles, pwin, pplace, log_edge, power):
    budget_units = spec["budget"] // 100
    units = np.ones(len(tickets), dtype=np.int16)
    max_units = max(1, int(math.floor(budget_units * spec["maxShare"])))
    remaining = budget_units - len(tickets)
    type_weight = {
        "ライト": {"単勝": 1.35, "ワイド": 1.00, "馬連": 1.10},
        "スタンダード": {"単勝": 1.05, "ワイド": 0.95, "馬連": 1.05, "馬単": 1.00, "3連複": 1.05},
        "プレミアム": {"単勝": 0.75, "ワイド": 0.75, "馬連": 0.85, "馬単": 0.95, "3連複": 1.10, "3連単": 1.35},
    }[course]
    quality = []
    for bet_type, horse_indices in tickets:
        ps = []
        for idx in horse_indices:
            ps.append(max(1e-5, pplace[idx] if bet_type in {"ワイド", "3連複"} else pwin[idx]))
        q = math.exp(sum(math.log(x) for x in ps) / len(ps))
        edge = max(0.0, sum(log_edge[idx] for idx in horse_indices) / len(horse_indices))
        score = type_weight[bet_type] * (q ** 0.45) * ((1.0 + edge) ** power)
        quality.append(max(1e-5, score))
    quality = np.asarray(quality, dtype=np.float64)
    while remaining > 0:
        eligible = np.where(units < max_units)[0]
        if len(eligible) == 0:
            eligible = np.arange(len(units))
        score = quality[eligible] / np.maximum(1.0, units[eligible] ** 0.65)
        j = int(eligible[np.argmax(score)])
        units[j] += 1
        remaining -= 1
    return units


def settle(race, course, family, prediction):
    roles, pwin, pplace, log_edge, race_score = role_order(race, prediction, family)
    horse_nos = [int(race["runners"][idx]["horseNo"]) for idx in roles]
    role_pos = {roles[i]: horse_nos[i] for i in range(len(roles))}
    tickets_idx = ticket_structure(course, roles)
    tickets = [(t, tuple(role_pos[idx] for idx in hs)) for t, hs in tickets_idx]
    units = allocation(course, COURSES[course], tickets_idx, roles, pwin, pplace, log_edge, family["allocPower"])
    refunds = set(int(x) for x in (race.get("refunds") or set()))
    returned = 0.0
    for (bet_type, horses), unit in zip(tickets, units):
        payout = 0.0
        if refunds and any(h in refunds for h in horses):
            payout = 100.0
        else:
            payout = safe_float((race.get("payouts") or {}).get(payout_key(bet_type, horses)), 0.0)
        returned += float(unit) * payout
    return returned, race_score


def evaluate_family_period(races, predictions, indices, course, family):
    groups = defaultdict(list)
    for i in indices:
        groups[(races[i]["raceDate"], races[i]["venue"])].append(i)
    returns = []
    for key in sorted(groups):
        choices = []
        for i in groups[key]:
            returned, score = settle(races[i], course, family, predictions[i])
            choices.append((score, -int(races[i]["raceNo"]), i, returned))
        if len(choices) < 5:
            continue
        choices.sort(reverse=True)
        returns.extend(float(row[3]) for row in choices[:5])
    return np.asarray(returns, dtype=np.float64)


def family_period_matrix(races, predictions, quarters):
    byq = defaultdict(list)
    for i, race in enumerate(races):
        byq[quarter(race["raceDate"])].append(i)
    matrices = {course: {} for course in COURSES}
    for q in quarters:
        indices = byq[q]
        for course in COURSES:
            rows = []
            for family in FAMILIES:
                rows.append(evaluate_family_period(races, predictions, indices, course, family))
            race_counts = {len(x) for x in rows}
            if len(race_counts) != 1:
                raise RuntimeError(f"INCONSISTENT_SELECTION_COUNT:{course}:{q}:{sorted(race_counts)}")
            matrices[course][q] = np.stack(rows, axis=0)
    return matrices


def choose_family(history_arrays, budget):
    if len(history_arrays) < 2:
        return 0
    roi_rows = np.asarray([arr.sum(axis=1) / (arr.shape[1] * budget) * 100.0 for arr in history_arrays])
    total_returns = sum(arr.sum(axis=1) for arr in history_arrays)
    total_stake = sum(arr.shape[1] * budget for arr in history_arrays)
    total_roi = total_returns / total_stake * 100.0
    median = np.median(roi_rows, axis=0)
    q25 = np.quantile(roi_rows, 0.25, axis=0)
    wins = np.mean(roi_rows >= 100.0, axis=0) * 100.0
    downside = np.mean(np.maximum(0.0, 80.0 - roi_rows), axis=0)
    score = 0.38 * np.minimum(total_roi, 350.0) + 0.27 * median + 0.22 * q25 + 0.13 * wins - 0.45 * downside
    return int(np.argmax(score))


def summarize(returns, budget):
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) == 0:
        return {"races": 0, "stakeYen": 0, "returnYen": 0, "roiPct": None, "roiWithoutMaxPct": None, "roiWithoutTop1Pct": None}
    stake = len(returns) * budget
    total = float(returns.sum())
    k = max(1, int(math.ceil(len(returns) * 0.01)))
    return {
        "races": int(len(returns)),
        "stakeYen": int(stake),
        "returnYen": int(round(total)),
        "roiPct": total / stake * 100.0,
        "roiWithoutMaxPct": (total - float(returns.max())) / stake * 100.0,
        "roiWithoutTop1Pct": (total - float(np.sort(returns)[-k:].sum())) / stake * 100.0,
        "hitRatePct": float(np.mean(returns > 0) * 100.0),
        "maxRaceReturnYen": int(round(float(returns.max()))),
    }


def main():
    with gzip.open(DATASET, "rb") as handle:
        payload = pickle.load(handle)
    races = list(payload["races"])
    races.sort(key=lambda r: (r["raceDate"], r["venue"], int(r["raceNo"])))
    predictions, model_audit, quarters = build_oos_predictions(races)
    matrices = family_period_matrix(races, predictions, quarters)

    results = {}
    completion = True
    failure_reasons = []
    for course, spec in COURSES.items():
        history = []
        all_returns = []
        holdout_returns = []
        period_rows = {}
        for q in quarters:
            family_index = choose_family(history, spec["budget"])
            current_matrix = matrices[course][q]
            returns = current_matrix[family_index]
            history.append(current_matrix)
            all_returns.extend(returns.tolist())
            q_dates = [r["raceDate"] for r in races if quarter(r["raceDate"]) == q]
            if q_dates and min(q_dates) >= HOLDOUT_START:
                holdout_returns.extend(returns.tolist())
            period_rows[q] = {
                "familyIndex": family_index,
                "family": FAMILIES[family_index],
                "summary": summarize(returns, spec["budget"]),
            }
        full = summarize(all_returns, spec["budget"])
        holdout = summarize(holdout_returns, spec["budget"])
        checks = {
            "fullRoi200": full["roiPct"] is not None and full["roiPct"] >= 200.0,
            "holdoutRoi200": holdout["roiPct"] is not None and holdout["roiPct"] >= 200.0,
            "holdout100Races": holdout["races"] >= 100,
            "top1Trim100": full["roiWithoutTop1Pct"] is not None and full["roiWithoutTop1Pct"] >= 100.0,
            "maxTrim100": full["roiWithoutMaxPct"] is not None and full["roiWithoutMaxPct"] >= 100.0,
            "coverage": full["races"] == 3210,
        }
        if not all(checks.values()):
            completion = False
            failure_reasons.append({"course": course, "failed": [k for k, v in checks.items() if not v]})
        results[course] = {"full": full, "holdout": holdout, "periods": period_rows, "checks": checks}

    out = {
        "schema": 1,
        "explorationId": "runner-residual-walkforward-20260808",
        "modelVersion": None,
        "source": {
            "races": len(races),
            "start": races[0]["raceDate"],
            "end": races[-1]["raceDate"],
            "newRaceIngestion": False,
            "oldVersionResultsUsed": False,
            "actualJraPayoutsOnly": True,
            "currentResultLeakage": False,
            "historicalCombinationOddsUsed": False,
            "syntheticOddsUsed": False,
        },
        "model": {"type": "quarterly walk-forward HistGradientBoosting", "config": MODEL_CONFIG, "audit": model_audit},
        "portfolio": {"familyCount": len(FAMILIES), "minimumRacesPerVenueDay": 5, "familySelection": "prior OOS quarters only"},
        "courses": results,
        "completionPassed": completion,
        "promotionEligible": completion,
        "failureReasons": failure_reasons,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"completionPassed": completion, "familyCount": len(FAMILIES), "courses": {c: {"fullRoi": r["full"]["roiPct"], "holdoutRoi": r["holdout"]["roiPct"], "trimTop1": r["full"]["roiWithoutTop1Pct"], "races": r["full"]["races"]} for c, r in results.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
