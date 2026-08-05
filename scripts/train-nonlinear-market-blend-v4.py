import itertools
import json
import math
import os
import random
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"

CONTEXT_START = "2024-05-01"
TRAIN_START = "2025-05-01"
TRAIN_END = "2026-04-30"
VALIDATION_END = "2026-06-28"
HOLDOUT_END = "2026-07-26"
REQUIRED_HIT = 36.8
TARGET_ROI = 200.0
VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]
COURSE_BUDGETS = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def sql(query, params=None):
    params = params or []
    body = json.dumps({"sql": query, "params": params}).encode()
    last_error = None
    for attempt in range(1, 7):
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("success"):
                raise RuntimeError(f"D1_ERROR:{payload.get('errors')}")
            time.sleep(0.05)
            return payload.get("result", [{}])[0].get("results", [])
        except Exception as error:
            last_error = error
            if attempt == 6:
                raise
            time.sleep(attempt * 1.5)
    raise last_error


def month_ranges(start, end):
    year, month = map(int, start[:7].split("-"))
    end_year, end_month = map(int, end[:7].split("-"))
    while (year, month) <= (end_year, end_month):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        yield f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"
        year, month = next_year, next_month


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def canonical(bet_type, combination):
    values = [int(value) for value in str(combination).replace("→", "-").replace("－", "-").split("-") if value.strip().isdigit()]
    if bet_type in {"ワイド", "馬連", "3連複"}:
        values.sort()
    return "-".join(map(str, values))


def parse_age(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else 4


def distance_bucket(distance):
    if distance < 1400:
        return "sprint"
    if distance < 1800:
        return "mile"
    if distance < 2200:
        return "middle"
    return "long"


@dataclass
class History:
    starts: int = 0
    wins: int = 0
    places: int = 0
    finish_sum: float = 0.0
    final3f_sum: float = 0.0
    final3f_count: int = 0
    recent: deque = None
    last_date: str = None

    def __post_init__(self):
        if self.recent is None:
            self.recent = deque(maxlen=8)

    def features(self, race_date):
        win = (self.wins + 0.08 * 12) / (self.starts + 12)
        place = (self.places + 0.25 * 12) / (self.starts + 12)
        avg_finish = self.finish_sum / self.starts if self.starts else 7.0
        recent = list(self.recent)[-5:]
        recent_avg = sum(recent) / len(recent) if recent else 7.0
        recent_place = sum(value <= 3 for value in recent) / len(recent) if recent else 0.25
        avg_3f = self.final3f_sum / self.final3f_count if self.final3f_count else 36.0
        if self.last_date:
            days = max(0, (date.fromisoformat(race_date) - date.fromisoformat(self.last_date)).days)
        else:
            days = 90
        return [win, place, avg_finish, math.log1p(self.starts), recent_avg, recent_place, avg_3f, min(days, 180)]

    def update(self, finish, final3f, race_date):
        self.starts += 1
        self.wins += int(finish == 1)
        self.places += int(0 < finish <= 3)
        self.finish_sum += finish if finish > 0 else 10
        if final3f > 0:
            self.final3f_sum += final3f
            self.final3f_count += 1
        self.recent.append(finish if finish > 0 else 10)
        self.last_date = race_date


def get_history(store, key):
    if key not in store:
        store[key] = History()
    return store[key]


def load_data():
    runner_rows = []
    payouts = defaultdict(dict)
    for start, end in month_ranges(CONTEXT_START, HOLDOUT_END):
        runner_rows.extend(sql(
            """
            SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
                   r.surface,r.distance_m distanceM,r.track_condition trackCondition,
                   r.refund_horse_nos_json refunds,
                   rr.horse_no horseNo,rr.frame_no frameNo,rr.horse_name horseName,
                   rr.sex_age sexAge,rr.horse_weight horseWeight,rr.weight_change weightChange,
                   rr.jockey,rr.assigned_weight assignedWeight,rr.trainer,rr.stable,
                   rr.win_odds winOdds,rr.popularity,rr.runner_status runnerStatus,
                   rs.finish_position finishPosition,rs.final3f
            FROM rt_races r
            JOIN rt_runners rr ON rr.race_id=r.race_id
            LEFT JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=rr.horse_no
            WHERE r.race_date>=? AND r.race_date<? AND r.status='finished'
            ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
            """,
            [start, end],
        ))
        for row in sql(
            """
            SELECT p.race_id raceId,p.bet_type betType,p.combination,p.payout_yen payoutYen
            FROM rt_payouts p JOIN rt_races r ON r.race_id=p.race_id
            WHERE r.race_date>=? AND r.race_date<?
            """,
            [start, end],
        ):
            payouts[row["raceId"]][f'{row["betType"]}:{canonical(row["betType"], row["combination"])}'] = number(row["payoutYen"])
    return runner_rows, payouts


def build_dataset(rows, payout_maps):
    grouped = defaultdict(list)
    metadata = {}
    for row in rows:
        race_id = row["raceId"]
        grouped[race_id].append(row)
        metadata[race_id] = row
    ordered_ids = sorted(grouped, key=lambda race_id: (
        metadata[race_id]["raceDate"], metadata[race_id]["venue"], number(metadata[race_id]["raceNo"])
    ))

    stores = {name: {} for name in [
        "horse", "jockey", "trainer", "stable", "horse_course", "jockey_course", "trainer_course", "stable_course"
    ]}
    races = []
    for race_id in ordered_ids:
        raw = metadata[race_id]
        race_date = raw["raceDate"]
        venue = raw["venue"]
        surface = raw.get("surface") or "unknown"
        distance = number(raw.get("distanceM"))
        d_bucket = distance_bucket(distance)
        active = [row for row in grouped[race_id] if row.get("runnerStatus") == "active" and number(row.get("winOdds")) > 1 and number(row.get("finishPosition")) > 0]
        inverse = [1 / number(row["winOdds"]) for row in active]
        total_inverse = sum(inverse)
        winner_exists = any(number(row.get("finishPosition")) == 1 for row in active)
        built_runners = []
        if len(active) >= 3 and winner_exists and total_inverse > 0:
            field_size = len(active)
            for index, row in enumerate(active):
                market = inverse[index] / total_inverse
                horse = get_history(stores["horse"], row.get("horseName") or "").features(race_date)
                jockey = get_history(stores["jockey"], row.get("jockey") or "").features(race_date)
                trainer = get_history(stores["trainer"], row.get("trainer") or "").features(race_date)
                stable = get_history(stores["stable"], row.get("stable") or "").features(race_date)
                horse_course = get_history(stores["horse_course"], f'{row.get("horseName")}|{venue}|{surface}|{d_bucket}').features(race_date)
                jockey_course = get_history(stores["jockey_course"], f'{row.get("jockey")}|{surface}|{d_bucket}').features(race_date)
                trainer_course = get_history(stores["trainer_course"], f'{row.get("trainer")}|{surface}|{d_bucket}').features(race_date)
                stable_course = get_history(stores["stable_course"], f'{row.get("stable")}|{surface}|{d_bucket}').features(race_date)
                condition = str(raw.get("trackCondition") or "")
                venue_flags = [int(venue == item) for item in VENUES]
                features = [
                    math.log(max(market, 1e-8)), market,
                    -number(row.get("popularity"), field_size / 2) / field_size,
                    horse[0], horse[1], -horse[2] / 12, horse[3], -horse[4] / 12, horse[5], (36 - horse[6]) / 5, -horse[7] / 180,
                    jockey[0], jockey[1], trainer[0], trainer[1], stable[0], stable[1],
                    horse_course[0], horse_course[1], jockey_course[0], jockey_course[1],
                    trainer_course[0], trainer_course[1], stable_course[0], stable_course[1],
                    (number(row.get("assignedWeight")) - 55) / 6,
                    (number(row.get("horseWeight")) - 480) / 100,
                    max(-30, min(30, number(row.get("weightChange")))) / 30,
                    (parse_age(row.get("sexAge")) - 4) / 5,
                    int("牝" in str(row.get("sexAge") or "")), int("セ" in str(row.get("sexAge") or "")),
                    (number(row.get("frameNo")) - 4.5) / 4.5,
                    field_size / 18, distance / 3200, number(raw.get("raceNo")) / 12,
                    int(surface == "芝"), int(surface == "ダート"),
                    int("良" in condition), int("稍" in condition), int("重" in condition and "不" not in condition), int("不" in condition),
                    *venue_flags,
                ]
                built_runners.append({
                    "horseNo": int(number(row.get("horseNo"))),
                    "horseName": row.get("horseName") or "",
                    "features": features,
                    "market": market,
                    "winOdds": number(row.get("winOdds")),
                    "popularity": int(number(row.get("popularity"), 99)),
                    "finish": int(number(row.get("finishPosition"))),
                })
            try:
                refunds = set(json.loads(raw.get("refunds") or "[]"))
            except Exception:
                refunds = set()
            races.append({
                "raceId": race_id, "raceDate": race_date, "venue": venue,
                "raceNo": int(number(raw.get("raceNo"))), "runners": built_runners,
                "payouts": payout_maps.get(race_id, {}), "refunds": refunds,
            })

        for row in grouped[race_id]:
            finish = int(number(row.get("finishPosition")))
            if finish <= 0:
                continue
            final3f = number(row.get("final3f"))
            keys = {
                "horse": row.get("horseName") or "",
                "jockey": row.get("jockey") or "",
                "trainer": row.get("trainer") or "",
                "stable": row.get("stable") or "",
                "horse_course": f'{row.get("horseName")}|{venue}|{surface}|{d_bucket}',
                "jockey_course": f'{row.get("jockey")}|{surface}|{d_bucket}',
                "trainer_course": f'{row.get("trainer")}|{surface}|{d_bucket}',
                "stable_course": f'{row.get("stable")}|{surface}|{d_bucket}',
            }
            for store_name, key in keys.items():
                get_history(stores[store_name], key).update(finish, final3f, race_date)
    return races


def split_name(race_date):
    if TRAIN_START <= race_date <= TRAIN_END:
        return "train"
    if TRAIN_END < race_date <= VALIDATION_END:
        return "validation"
    if VALIDATION_END < race_date <= HOLDOUT_END:
        return "holdout"
    return None


def flatten_runners(races):
    x, y, weights = [], [], []
    for race in races:
        field = len(race["runners"])
        for runner in race["runners"]:
            x.append(runner["features"])
            y.append(int(runner["finish"] == 1))
            weights.append(1 / max(1, field))
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.int8), np.asarray(weights, dtype=np.float64)


def attach_probabilities(model, races, blend):
    result = []
    for race in races:
        x = np.asarray([runner["features"] for runner in race["runners"]], dtype=np.float64)
        nonlinear = model.predict_proba(x)[:, 1]
        nonlinear = nonlinear / max(1e-12, nonlinear.sum())
        market = np.asarray([runner["market"] for runner in race["runners"]], dtype=np.float64)
        probability = (1 - blend) * market + blend * nonlinear
        probability = probability / max(1e-12, probability.sum())
        runners = []
        for runner, p in zip(race["runners"], probability):
            item = dict(runner)
            item["probability"] = float(p)
            item["edge"] = float(p / max(1e-8, runner["market"]))
            runners.append(item)
        runners.sort(key=lambda item: item["probability"], reverse=True)
        item = dict(race)
        item["runners"] = runners
        item["topProbability"] = runners[0]["probability"]
        item["probabilityGap"] = runners[0]["probability"] - runners[1]["probability"]
        item["maxEdge"] = max(runner["edge"] for runner in runners[:7])
        item["disagreement"] = sum(abs(runner["probability"] - runner["market"]) for runner in runners)
        result.append(item)
    return result


def ranking_metrics(races):
    loss = top1 = top3 = returned = count = 0
    monthly = defaultdict(lambda: [0, 0])
    for race in races:
        winner = next((runner for runner in race["runners"] if runner["finish"] == 1), None)
        if not winner:
            continue
        loss -= math.log(max(1e-12, winner["probability"]))
        order = race["runners"]
        count += 1
        month = race["raceDate"][:7]
        monthly[month][1] += 100
        if order[0]["finish"] == 1:
            top1 += 1
            payout = order[0]["winOdds"] * 100
            returned += payout
            monthly[month][0] += payout
        if any(item["finish"] == 1 for item in order[:3]):
            top3 += 1
    return {
        "races": count,
        "logLoss": loss / count if count else 999,
        "top1Pct": top1 / count * 100 if count else 0,
        "top3Pct": top3 / count * 100 if count else 0,
        "top1Roi": returned / (count * 100) * 100 if count else 0,
        "monthlyTop1Roi": {month: values[0] / values[1] * 100 if values[1] else 0 for month, values in monthly.items()},
    }


def bet_key(bet_type, horses):
    values = list(horses)
    if bet_type in {"ワイド", "馬連", "3連複"}:
        values.sort()
    return f'{bet_type}:{"-".join(map(str, values))}'


def template_bets(race, template):
    horses = [runner["horseNo"] for runner in race["runners"][:5]]
    if len(horses) < 5:
        return []
    h1, h2, h3, h4, h5 = horses
    templates = {
        "single1": [("単勝", (h1,))],
        "single2": [("単勝", (h1,)), ("単勝", (h2,))],
        "wide_anchor": [("ワイド", (h1, h2)), ("ワイド", (h1, h3))],
        "wide_box3": [("ワイド", pair) for pair in itertools.combinations((h1, h2, h3), 2)],
        "anchor_trio": [("単勝", (h1,)), ("ワイド", (h1, h2)), ("ワイド", (h1, h3)), ("3連複", (h1, h2, h3))],
        "mixed": [("ワイド", (h1, h2)), ("ワイド", (h1, h3)), ("馬連", (h1, h2)), ("3連複", (h1, h2, h3))],
        "trio_box4": [("3連複", combo) for combo in itertools.combinations((h1, h2, h3, h4), 3)],
        "exacta3": [("馬単", (h1, h2)), ("馬単", (h1, h3)), ("馬単", (h2, h1))],
        "upside": [("馬単", (h1, h2)), ("馬単", (h1, h3)), ("3連複", (h1, h2, h3)), ("3連単", (h1, h2, h3)), ("3連単", (h1, h3, h2))],
        "wide_longshot": [("ワイド", (h1, h3)), ("ワイド", (h1, h4)), ("ワイド", (h2, h4))],
        "trio_value": [("3連複", (h1, h2, h4)), ("3連複", (h1, h3, h4)), ("3連複", (h1, h2, h5))],
    }
    return templates[template]


def race_score(race, mode):
    if mode == "confidence":
        return race["topProbability"] * 5 + race["probabilityGap"] * 8
    if mode == "edge":
        return race["maxEdge"]
    if mode == "disagreement":
        return race["disagreement"]
    return race["topProbability"] * 3 + race["probabilityGap"] * 5 + math.log(max(1, race["maxEdge"]))


def select_races(races, count, mode):
    groups = defaultdict(list)
    for race in races:
        groups[(race["raceDate"], race["venue"])].append(race)
    selected = []
    for group in groups.values():
        group.sort(key=lambda race: (-race_score(race, mode), race["raceNo"]))
        if len(group) < 5:
            continue
        selected.extend(group[:max(5, count)])
    return selected


def evaluate_bets(races, template, budget):
    stake = returned = hit_races = 0
    monthly = defaultdict(lambda: [0, 0])
    for race in races:
        bets = template_bets(race, template)
        if not bets:
            continue
        units = max(len(bets), budget // 100)
        base = units // len(bets)
        remainder = units % len(bets)
        race_return = 0
        for index, (bet_type, horses) in enumerate(bets):
            ticket_units = base + int(index < remainder)
            ticket_stake = ticket_units * 100
            key = bet_key(bet_type, horses)
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
    return {"races": len(races), "roi": roi, "hit": hit, "minMonth": min_month, "monthlyRois": month_rois, "profit": returned - stake, "objective": objective}


def search_betting(validation, holdout):
    templates = ["single1", "single2", "wide_anchor", "wide_box3", "anchor_trio", "mixed", "trio_box4", "exacta3", "upside", "wide_longshot", "trio_value"]
    configs = []
    for mode in ["confidence", "edge", "disagreement", "combined"]:
        for count in range(5, 13):
            selected = select_races(validation, count, mode)
            policies = {}
            for course, budget in COURSE_BUDGETS.items():
                candidates = []
                for template in templates:
                    result = evaluate_bets(selected, template, budget)
                    candidates.append({"template": template, "result": result})
                eligible = [row for row in candidates if row["result"]["hit"] >= REQUIRED_HIT]
                pool = eligible or candidates
                pool.sort(key=lambda row: (row["result"]["objective"], row["result"]["roi"]), reverse=True)
                policies[course] = pool[0]
            aggregate = min(policies[course]["result"]["objective"] for course in COURSE_BUDGETS)
            configs.append({"mode": mode, "count": count, "policies": policies, "aggregate": aggregate})
    configs.sort(key=lambda row: row["aggregate"], reverse=True)
    winner = configs[0]
    holdout_selected = select_races(holdout, winner["count"], winner["mode"])
    holdout_results = {
        course: evaluate_bets(holdout_selected, winner["policies"][course]["template"], budget)
        for course, budget in COURSE_BUDGETS.items()
    }
    return winner, holdout_results


def rounded(value, digits=4):
    return round(float(value), digits)


def clean_metrics(metrics):
    result = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            result[key] = {k: rounded(v) for k, v in value.items()}
        elif isinstance(value, (int, float, np.floating)):
            result[key] = rounded(value)
        else:
            result[key] = value
    return result


def main():
    rows, payouts = load_data()
    races = build_dataset(rows, payouts)
    split_races = {name: [race for race in races if split_name(race["raceDate"]) == name] for name in ["train", "validation", "holdout"]}
    x_train, y_train, base_weights = flatten_runners(split_races["train"])

    configs = [
        {"max_leaf_nodes": 7, "learning_rate": 0.04, "max_iter": 140, "l2_regularization": 1.0, "longshotPower": 0.0},
        {"max_leaf_nodes": 15, "learning_rate": 0.035, "max_iter": 180, "l2_regularization": 2.0, "longshotPower": 0.0},
        {"max_leaf_nodes": 31, "learning_rate": 0.025, "max_iter": 220, "l2_regularization": 4.0, "longshotPower": 0.0},
        {"max_leaf_nodes": 7, "learning_rate": 0.04, "max_iter": 160, "l2_regularization": 1.5, "longshotPower": 0.12},
        {"max_leaf_nodes": 15, "learning_rate": 0.03, "max_iter": 200, "l2_regularization": 3.0, "longshotPower": 0.18},
        {"max_leaf_nodes": 31, "learning_rate": 0.02, "max_iter": 240, "l2_regularization": 6.0, "longshotPower": 0.25},
    ]

    trained = []
    train_runner_odds = np.asarray([runner["winOdds"] for race in split_races["train"] for runner in race["runners"]], dtype=np.float64)
    for config in configs:
        weights = base_weights.copy()
        winners = y_train == 1
        weights[winners] *= np.minimum(6.0, np.power(np.maximum(1.0, train_runner_odds[winners]), config["longshotPower"]))
        model = HistGradientBoostingClassifier(
            loss="log_loss", max_leaf_nodes=config["max_leaf_nodes"], learning_rate=config["learning_rate"],
            max_iter=config["max_iter"], l2_regularization=config["l2_regularization"],
            min_samples_leaf=40, random_state=42,
        )
        model.fit(x_train, y_train, sample_weight=weights)
        for blend in [0.1, 0.2, 0.3, 0.4, 0.5, 0.65, 0.8, 1.0]:
            validation = attach_probabilities(model, split_races["validation"], blend)
            metrics = ranking_metrics(validation)
            month_values = list(metrics["monthlyTop1Roi"].values())
            min_month = min(month_values) if month_values else 0
            score = metrics["logLoss"] - metrics["top1Pct"] * 0.0008 - min(180, metrics["top1Roi"]) * 0.00025 - min(180, min_month) * 0.00015
            trained.append({"model": model, "config": config, "blend": blend, "validation": validation, "metrics": metrics, "score": score})
    trained.sort(key=lambda row: row["score"])
    winner = trained[0]
    validation = winner["validation"]
    holdout = attach_probabilities(winner["model"], split_races["holdout"], winner["blend"])
    holdout_metrics = ranking_metrics(holdout)
    market_validation = ranking_metrics(attach_probabilities(winner["model"], split_races["validation"], 0.0))
    market_holdout = ranking_metrics(attach_probabilities(winner["model"], split_races["holdout"], 0.0))
    betting_winner, betting_holdout = search_betting(validation, holdout)

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "Nonlinear market blend v4 using chronological rolling factors and HistGradientBoostingClassifier.",
        "targetRoiPct": TARGET_ROI,
        "minimumRacesPerVenueDay": 5,
        "samples": {key: len(value) for key, value in split_races.items()},
        "selectedModel": {**winner["config"], "blend": winner["blend"]},
        "ranking": {
            "marketValidation": clean_metrics(market_validation),
            "modelValidation": clean_metrics(winner["metrics"]),
            "marketHoldout": clean_metrics(market_holdout),
            "modelHoldout": clean_metrics(holdout_metrics),
        },
        "selectedRaceConfiguration": {"mode": betting_winner["mode"], "count": betting_winner["count"]},
        "validation": {
            course: {"template": betting_winner["policies"][course]["template"], **clean_metrics(betting_winner["policies"][course]["result"])}
            for course in COURSE_BUDGETS
        },
        "holdout": {
            course: {**clean_metrics(betting_holdout[course]), "pass200": betting_holdout[course]["roi"] >= TARGET_ROI, "hitRequirementMet": betting_holdout[course]["hit"] >= REQUIRED_HIT}
            for course in COURSE_BUDGETS
        },
    }
    report["promotionEligible"] = all(item["pass200"] and item["hitRequirementMet"] for item in report["holdout"].values())
    Path("nonlinear-market-blend-v4.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f'Model: {report["selectedModel"]}')
    print(f'Ranking validation: market {report["ranking"]["marketValidation"]["logLoss"]} / model {report["ranking"]["modelValidation"]["logLoss"]}')
    print(f'Ranking holdout: market {report["ranking"]["marketHoldout"]["logLoss"]} / model {report["ranking"]["modelHoldout"]["logLoss"]}')
    for course in COURSE_BUDGETS:
        row = report["holdout"][course]
        print(f'{course}: validation {report["validation"][course]["roi"]}% / holdout {row["roi"]}% / hit {row["hit"]}% / 200% {"PASS" if row["pass200"] else "FAIL"}')
    print(f'Promotion eligible: {"YES" if report["promotionEligible"] else "NO"}')


if __name__ == "__main__":
    main()
