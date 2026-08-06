import importlib.util
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v7 = load_module("v7_full", ROOT / "scripts" / "analyze-v7-full-period.py")
base = v7.base
v6 = v7.v6
v4 = v7.v4

v4.HOLDOUT_END = "2026-08-31"

ROLLING_START_MONTH = "2024-11"
NESTED_EVALUATION_START_MONTH = "2025-05"
FINAL_HOLDOUT_START_MONTH = "2026-05"
POLICY_COUNT = 1400
REQUIRED_HIT = 36.8
COURSES = tuple(v7.COURSES)
COURSE_BUDGETS = dict(v7.COURSE_BUDGETS)
CAP_MULTIPLE = dict(v7.CAP_MULTIPLE)

POINT_CONFIG = {
    "max_leaf_nodes": 31,
    "learning_rate": 0.025,
    "max_iter": 260,
    "l2_regularization": 8.0,
}
PAIR_CONFIG = dict(v7.MODEL_CONFIG)
TEMPERATURE = v7.TEMPERATURE
MODEL_VARIANTS = ("point", "pair", "ensemble", "market_audit")
RACE_MODES = ("confidence", "concentration", "entropy")

MARKET_FEATURE_INDICES = (0, 1, 2)


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def parse_time_seconds(value):
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return float(minutes) * 60.0 + float(seconds)
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def distance_band(distance):
    value = int(number(distance))
    if value < 1400:
        return "sprint"
    if value < 1800:
        return "mile"
    if value < 2200:
        return "middle"
    return "long"


def going_band(value):
    text = str(value or "")
    if "不" in text:
        return "bad"
    if "重" in text:
        return "heavy"
    if "稍" in text:
        return "yielding"
    return "good"


def class_level(race_name, conditions):
    text = f"{race_name or ''} {conditions or ''}"
    if "障害" in text:
        return 2.5
    if any(token in text for token in ("ＧⅠ", "GⅠ", "Ｇ１", "G1")):
        return 7.0
    if any(token in text for token in ("ＧⅡ", "GⅡ", "Ｇ２", "G2")):
        return 6.0
    if any(token in text for token in ("ＧⅢ", "GⅢ", "Ｇ３", "G3")):
        return 5.0
    if any(token in text for token in ("オープン", "ＯＰ", "OP", "リステッド")):
        return 4.0
    if any(token in text for token in ("3勝", "３勝", "1600万")):
        return 3.0
    if any(token in text for token in ("2勝", "２勝", "1000万")):
        return 2.0
    if any(token in text for token in ("1勝", "１勝", "500万")):
        return 1.0
    if "新馬" in text:
        return -0.5
    if "未勝利" in text:
        return 0.0
    return 1.5


def slope(values):
    rows = list(values)
    if len(rows) < 2:
        return 0.0
    x = np.arange(len(rows), dtype=np.float64)
    y = np.asarray(rows, dtype=np.float64)
    x = x - x.mean()
    denominator = float(np.dot(x, x))
    return float(np.dot(x, y - y.mean()) / denominator) if denominator > 0 else 0.0


def mean_std(values, default=0.0):
    rows = list(values)
    if not rows:
        return default, 0.0
    array = np.asarray(rows, dtype=np.float64)
    return float(array.mean()), float(array.std())


@dataclass
class RunningStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def z(self, value):
        if self.count < 20:
            return 0.0
        variance = self.m2 / max(1, self.count - 1)
        std = math.sqrt(max(1e-8, variance))
        return max(-4.0, min(4.0, (value - self.mean) / std))

    def update(self, value):
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)


@dataclass
class EntityStats:
    starts: int = 0
    wins: int = 0
    places: int = 0

    def rates(self):
        win = (self.wins + 0.08 * 12) / (self.starts + 12)
        place = (self.places + 0.25 * 12) / (self.starts + 12)
        return win, place, math.log1p(self.starts) / 6.0

    def update(self, finish):
        self.starts += 1
        self.wins += int(finish == 1)
        self.places += int(0 < finish <= 3)


@dataclass
class HorseForm:
    starts: int = 0
    last_date: str | None = None
    last_distance: int = 0
    last_surface: str = ""
    last_venue: str = ""
    last_jockey: str = ""
    last_trainer: str = ""
    last_class: float = 0.0
    last_assigned_weight: float = 0.0
    last_horse_weight: float = 0.0
    finishes: deque = field(default_factory=lambda: deque(maxlen=8))
    speed_scores: deque = field(default_factory=lambda: deque(maxlen=8))
    final3f_scores: deque = field(default_factory=lambda: deque(maxlen=8))
    market_residuals: deque = field(default_factory=lambda: deque(maxlen=8))

    def features(self, race_date, distance, surface, venue, jockey, trainer, klass, assigned_weight, horse_weight):
        recent_finish = list(self.finishes)[-5:]
        recent_speed = list(self.speed_scores)[-5:]
        recent_3f = list(self.final3f_scores)[-5:]
        recent_market = list(self.market_residuals)[-5:]
        finish_mean, finish_std = mean_std(recent_finish, 7.0)
        speed_mean, speed_std = mean_std(recent_speed, 0.0)
        final3f_mean, final3f_std = mean_std(recent_3f, 0.0)
        market_mean, market_std = mean_std(recent_market, 0.0)
        if self.last_date:
            days = max(0, (date.fromisoformat(race_date) - date.fromisoformat(self.last_date)).days)
        else:
            days = 90
        distance_delta = (distance - self.last_distance) / 800.0 if self.last_distance else 0.0
        class_delta = (klass - self.last_class) / 4.0 if self.starts else 0.0
        assigned_delta = (assigned_weight - self.last_assigned_weight) / 4.0 if self.starts else 0.0
        horse_weight_delta = (horse_weight - self.last_horse_weight) / 30.0 if self.starts and horse_weight > 0 and self.last_horse_weight > 0 else 0.0
        return [
            math.log1p(self.starts) / 4.0,
            min(days, 180) / 180.0,
            distance_delta,
            int(bool(self.last_surface) and surface != self.last_surface),
            int(bool(self.last_venue) and venue != self.last_venue),
            int(bool(self.last_jockey) and jockey != self.last_jockey),
            int(bool(self.last_trainer) and trainer != self.last_trainer),
            class_delta,
            assigned_delta,
            horse_weight_delta,
            -finish_mean / 12.0,
            finish_std / 6.0,
            -slope(recent_finish) / 4.0,
            speed_mean / 3.0,
            speed_std / 3.0,
            slope(recent_speed) / 2.0,
            final3f_mean / 3.0,
            final3f_std / 3.0,
            slope(recent_3f) / 2.0,
            market_mean,
            market_std,
            slope(recent_market),
        ]

    def update(self, race_date, distance, surface, venue, jockey, trainer, klass,
               assigned_weight, horse_weight, finish, speed_score, final3f_score, market_residual):
        self.starts += 1
        self.last_date = race_date
        self.last_distance = int(distance)
        self.last_surface = surface
        self.last_venue = venue
        self.last_jockey = jockey
        self.last_trainer = trainer
        self.last_class = float(klass)
        self.last_assigned_weight = float(assigned_weight)
        if horse_weight > 0:
            self.last_horse_weight = float(horse_weight)
        self.finishes.append(int(finish))
        self.speed_scores.append(float(speed_score))
        self.final3f_scores.append(float(final3f_score))
        self.market_residuals.append(float(market_residual))


def load_extra_rows():
    grouped = defaultdict(list)
    for start, end in v4.month_ranges(v4.CONTEXT_START, v4.HOLDOUT_END):
        rows = v4.sql(
            """
            SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
                   r.race_name raceName,r.conditions,r.surface,r.distance_m distanceM,
                   r.direction,r.weather,r.track_condition trackCondition,
                   rr.horse_no horseNo,rr.horse_name horseName,rr.jockey,rr.trainer,rr.stable,
                   rr.assigned_weight assignedWeight,rr.horse_weight horseWeight,
                   rr.win_odds winOdds,rr.popularity,rr.runner_status runnerStatus,
                   rs.finish_position finishPosition,rs.time_text timeText,
                   rs.margin_text marginText,rs.final3f
            FROM rt_races r
            JOIN rt_runners rr ON rr.race_id=r.race_id
            LEFT JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=rr.horse_no
            WHERE r.race_date>=? AND r.race_date<? AND r.status='finished'
            ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
            """,
            [start, end],
        )
        for row in rows:
            grouped[row["raceId"]].append(row)
    return grouped


def enrich_races(base_races, extra_rows):
    horse_forms = {}
    horse_surface = {}
    horse_distance = {}
    horse_venue = {}
    horse_jockey = {}
    jockey_trainer = {}
    speed_baselines = {}
    final3f_baselines = {}
    enriched = []

    def entity(store, key):
        if key not in store:
            store[key] = EntityStats()
        return store[key]

    for race in sorted(base_races, key=lambda item: (item["raceDate"], item["venue"], item["raceNo"])):
        raw_rows = extra_rows.get(race["raceId"], [])
        raw_by_horse = {int(number(row.get("horseNo"))): row for row in raw_rows}
        race_raw = raw_rows[0] if raw_rows else {}
        distance = int(number(race_raw.get("distanceM"), 0))
        surface = str(race_raw.get("surface") or "unknown")
        venue = str(race.get("venue") or race_raw.get("venue") or "")
        klass = class_level(race_raw.get("raceName"), race_raw.get("conditions"))
        context = (venue, surface, distance_band(distance), going_band(race_raw.get("trackCondition")))
        speed_baseline = speed_baselines.setdefault(context, RunningStats())
        final3f_baseline = final3f_baselines.setdefault(context, RunningStats())

        item = dict(race)
        item.update({
            "raceName": race_raw.get("raceName") or "",
            "conditions": race_raw.get("conditions") or "",
            "surface": surface,
            "distanceM": distance,
            "trackCondition": race_raw.get("trackCondition") or "",
            "direction": race_raw.get("direction") or "",
            "weather": race_raw.get("weather") or "",
            "classLevel": klass,
        })
        runners = []
        for runner in race["runners"]:
            copied = dict(runner)
            features = list(copied["features"])
            for index in MARKET_FEATURE_INDICES:
                if index < len(features):
                    features[index] = 0.0
            raw = raw_by_horse.get(int(runner["horseNo"]), {})
            horse_name = str(raw.get("horseName") or runner.get("horseName") or "")
            jockey = str(raw.get("jockey") or "")
            trainer = str(raw.get("trainer") or "")
            assigned = number(raw.get("assignedWeight"))
            horse_weight = number(raw.get("horseWeight"))
            form = horse_forms.setdefault(horse_name, HorseForm())
            form_features = form.features(
                race["raceDate"], distance, surface, venue, jockey, trainer, klass, assigned, horse_weight
            )
            surface_stats = entity(horse_surface, f"{horse_name}|{surface}").rates()
            distance_stats = entity(horse_distance, f"{horse_name}|{distance_band(distance)}").rates()
            venue_stats = entity(horse_venue, f"{horse_name}|{venue}").rates()
            horse_jockey_stats = entity(horse_jockey, f"{horse_name}|{jockey}").rates()
            jockey_trainer_stats = entity(jockey_trainer, f"{jockey}|{trainer}").rates()
            context_features = [
                klass / 7.0,
                int(str(race_raw.get("direction") or "") == "右"),
                int(str(race_raw.get("direction") or "") == "左"),
                int("晴" in str(race_raw.get("weather") or "")),
                int("雨" in str(race_raw.get("weather") or "")),
                int("曇" in str(race_raw.get("weather") or "")),
            ]
            features.extend(form_features)
            features.extend(surface_stats)
            features.extend(distance_stats)
            features.extend(venue_stats)
            features.extend(horse_jockey_stats)
            features.extend(jockey_trainer_stats)
            features.extend(context_features)
            copied["features"] = features
            runners.append(copied)
        item["runners"] = runners
        enriched.append(item)

        updates = []
        for raw in raw_rows:
            finish = int(number(raw.get("finishPosition")))
            if finish <= 0 or str(raw.get("runnerStatus") or "") != "active":
                continue
            seconds = parse_time_seconds(raw.get("timeText"))
            raw_speed = distance / seconds if distance > 0 and seconds > 0 else 0.0
            speed_score = speed_baseline.z(raw_speed) if raw_speed > 0 else 0.0
            raw_3f = number(raw.get("final3f"))
            final3f_score = -final3f_baseline.z(raw_3f) if raw_3f > 0 else 0.0
            odds = max(1.01, number(raw.get("winOdds"), 99.0))
            implied = 1.0 / odds
            market_residual = float(int(finish == 1) - implied)
            updates.append((raw, finish, raw_speed, raw_3f, speed_score, final3f_score, market_residual))

        for raw, finish, raw_speed, raw_3f, speed_score, final3f_score, market_residual in updates:
            horse_name = str(raw.get("horseName") or "")
            jockey = str(raw.get("jockey") or "")
            trainer = str(raw.get("trainer") or "")
            assigned = number(raw.get("assignedWeight"))
            horse_weight = number(raw.get("horseWeight"))
            horse_forms.setdefault(horse_name, HorseForm()).update(
                race["raceDate"], distance, surface, venue, jockey, trainer, klass,
                assigned, horse_weight, finish, speed_score, final3f_score, market_residual,
            )
            entity(horse_surface, f"{horse_name}|{surface}").update(finish)
            entity(horse_distance, f"{horse_name}|{distance_band(distance)}").update(finish)
            entity(horse_venue, f"{horse_name}|{venue}").update(finish)
            entity(horse_jockey, f"{horse_name}|{jockey}").update(finish)
            entity(jockey_trainer, f"{jockey}|{trainer}").update(finish)
            if raw_speed > 0:
                speed_baseline.update(raw_speed)
            if raw_3f > 0:
                final3f_baseline.update(raw_3f)
    return enriched


def flatten_pointwise(races):
    x, y, weights = [], [], []
    for race in races:
        field_size = max(1, len(race["runners"]))
        for runner in race["runners"]:
            x.append(runner["features"])
            y.append(int(runner["finish"] == 1))
            weights.append(1.0 / field_size)
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.int8), np.asarray(weights, dtype=np.float64)


def fit_pointwise(races):
    x, y, weights = flatten_pointwise(races)
    if len(y) == 0:
        raise RuntimeError("V7_2_POINT_EMPTY")
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=POINT_CONFIG["max_leaf_nodes"],
        learning_rate=POINT_CONFIG["learning_rate"],
        max_iter=POINT_CONFIG["max_iter"],
        l2_regularization=POINT_CONFIG["l2_regularization"],
        min_samples_leaf=50,
        random_state=2026080619,
    )
    model.fit(x, y, sample_weight=weights)
    return model


def point_probabilities(model, race):
    x = np.asarray([runner["features"] for runner in race["runners"]], dtype=np.float64)
    raw = model.predict_proba(x)[:, 1]
    raw = np.maximum(raw, 1e-10)
    return raw / raw.sum()


def attach_variant(races, point_model, pair_model, variant):
    attached = []
    for race in races:
        point = point_probabilities(point_model, race)
        pair = v6.pairwise_probabilities(pair_model, race, TEMPERATURE)
        market = np.asarray([runner["market"] for runner in race["runners"]], dtype=np.float64)
        if variant == "point":
            probability = point
        elif variant == "pair":
            probability = pair
        elif variant == "ensemble":
            probability = 0.50 * point + 0.50 * pair
        else:
            probability = 0.35 * point + 0.35 * pair + 0.30 * market
        probability = probability / max(1e-12, probability.sum())
        runners = []
        for runner, value in zip(race["runners"], probability):
            copied = dict(runner)
            copied["probability"] = float(value)
            copied["edge"] = float(value / max(1e-8, runner["market"]))
            runners.append(copied)
        runners.sort(key=lambda row: row["probability"], reverse=True)
        item = dict(race)
        item["runners"] = runners
        item["topProbability"] = runners[0]["probability"]
        item["probabilityGap"] = runners[0]["probability"] - runners[1]["probability"]
        item["top3Concentration"] = sum(row["probability"] for row in runners[:3])
        item["maxEdge"] = max(row["edge"] for row in runners[:7])
        item["disagreement"] = sum(abs(row["probability"] - row["market"]) for row in runners)
        item["entropy"] = -sum(row["probability"] * math.log(max(1e-12, row["probability"])) for row in runners)
        attached.append(item)
    return attached


def rolling_predictions(races, months):
    predictions = {variant: {} for variant in MODEL_VARIANTS}
    audit = {}
    for month in months:
        start, end = v7.month_bounds(month)
        train = [race for race in races if v7.DATA_START <= race["raceDate"] < start]
        target = [race for race in races if v7.in_range(race["raceDate"], start, end)]
        if not train or not target:
            raise RuntimeError(f"V7_2_EMPTY_MONTH:{month}:{len(train)}:{len(target)}")
        point_model = fit_pointwise(train)
        pair_model = v6.fit_pairwise(train, PAIR_CONFIG)
        for variant in MODEL_VARIANTS:
            predictions[variant][month] = attach_variant(target, point_model, pair_model, variant)
        audit[month] = {"trainRaces": len(train), "targetRaces": len(target)}
    return predictions, audit


def precompute_candidate(course, policies, selected_by_month, months):
    budget = COURSE_BUDGETS[course]
    cap_yen = budget * CAP_MULTIPLE[course]
    active = policies > 0
    rows = []
    for month in months:
        races = selected_by_month[month]
        matrix, _ = base.payout_matrix(races)
        returns = matrix @ policies.T.astype(np.float64)
        hits = ((matrix > 0).astype(np.int16) @ active.T.astype(np.int16)) > 0
        rows.append({
            "month": month,
            "races": len(races),
            "stake": budget * len(races),
            "rawRoi": returns.sum(axis=0) / max(1, budget * len(races)) * 100.0,
            "cappedRoi": np.minimum(returns, cap_yen).sum(axis=0) / max(1, budget * len(races)) * 100.0,
            "hitRate": hits.mean(axis=0) * 100.0,
            "totalReturn": returns.sum(axis=0),
            "maxSingleReturn": returns.max(axis=0),
            "targetReturns": returns,
            "targetHits": hits,
        })
    return rows


def choose_policy(rows, history_count):
    history = rows[:history_count]
    raw = np.vstack([row["rawRoi"] for row in history])
    capped = np.vstack([row["cappedRoi"] for row in history])
    hits = np.vstack([row["hitRate"] for row in history])
    total_stake = sum(row["stake"] for row in history)
    total_return = np.sum([row["totalReturn"] for row in history], axis=0)
    max_return = np.maximum.reduce([row["maxSingleReturn"] for row in history])
    total_raw = total_return / max(1, total_stake) * 100.0
    weights = np.asarray([row["stake"] for row in history], dtype=np.float64)
    total_capped = np.average(capped, axis=0, weights=weights)
    total_hit = np.average(hits, axis=0, weights=np.asarray([row["races"] for row in history], dtype=np.float64))
    q25 = np.quantile(capped, 0.25, axis=0)
    median = np.median(capped, axis=0)
    minimum = np.min(capped, axis=0)
    winning = np.sum(raw >= 100.0, axis=0)
    required_winning = max(2, math.ceil(history_count * 0.45))
    max_share = max_return / np.maximum(1.0, total_return)
    score = (
        q25 * 0.30 + median * 0.18 + total_capped * 0.16
        + np.minimum(total_raw, 350.0) * 0.10 + total_hit * 0.17 + minimum * 0.09
        - np.maximum(0.0, REQUIRED_HIT - total_hit) * 4.5
        - np.maximum(0.0, required_winning - winning) * 17.0
        - np.maximum(0.0, max_share - 0.20) * 320.0
    )
    best = int(np.argmax(score))
    return {
        "index": best,
        "score": float(score[best]),
        "historyRawRoiPct": float(total_raw[best]),
        "historyCappedRoiPct": float(total_capped[best]),
        "historyHitRatePct": float(total_hit[best]),
        "historyWinningMonths": int(winning[best]),
        "historyQ25CappedRoiPct": float(q25[best]),
        "historyMaxSingleReturnShare": float(max_share[best]),
    }


def evaluate_month(course, row, choice):
    budget = COURSE_BUDGETS[course]
    cap_yen = budget * CAP_MULTIPLE[course]
    returns = row["targetReturns"][:, choice["index"]]
    hits = row["targetHits"][:, choice["index"]]
    stake = budget * row["races"]
    returned = float(returns.sum())
    capped = float(np.minimum(returns, cap_yen).sum())
    return {
        "month": row["month"],
        "races": row["races"],
        "stakeYen": stake,
        "returnYen": int(round(returned)),
        "cappedReturnYen": int(round(capped)),
        "profitYen": int(round(returned - stake)),
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped / stake * 100 if stake else 0.0,
        "hitRatePct": float(hits.mean() * 100) if len(hits) else 0.0,
        "maxSingleReturnYen": int(round(float(returns.max()))) if len(returns) else 0,
    }


def aggregate(rows):
    stake = sum(row["stakeYen"] for row in rows)
    returned = sum(row["returnYen"] for row in rows)
    capped = sum(row["cappedReturnYen"] for row in rows)
    races = sum(row["races"] for row in rows)
    rois = [row["roiPct"] for row in rows]
    weighted_hits = sum(row["hitRatePct"] * row["races"] for row in rows)
    max_single = max((row["maxSingleReturnYen"] for row in rows), default=0)
    winning = sum(value >= 100.0 for value in rois)
    return {
        "months": len(rows),
        "races": races,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "cappedRoiPct": capped / stake * 100 if stake else 0.0,
        "hitRatePct": weighted_hits / races if races else 0.0,
        "winningMonths": winning,
        "winningMonthPct": winning / len(rows) * 100 if rows else 0.0,
        "minimumMonthlyRoiPct": min(rois) if rows else 0.0,
        "medianMonthlyRoiPct": float(np.median(rois)) if rows else 0.0,
        "q25MonthlyRoiPct": float(np.quantile(rois, 0.25)) if rows else 0.0,
        "maxSingleReturnShare": max_single / max(1, returned),
    }


def main():
    rows, payouts = v4.load_data()
    base_races = v4.build_dataset(rows, payouts)
    extra_rows = load_extra_rows()
    races = enrich_races(base_races, extra_rows)
    last_month = max(race["raceDate"][:7] for race in races)
    months = v7.month_sequence(ROLLING_START_MONTH, last_month)
    evaluation_months = [month for month in months if month >= NESTED_EVALUATION_START_MONTH]
    predictions, model_audit = rolling_predictions(races, months)

    selected = {}
    coverage = {}
    for variant in MODEL_VARIANTS:
        for mode in RACE_MODES:
            key = f"{variant}:{mode}"
            selected[key] = {}
            coverage[key] = {}
            for month in months:
                target = predictions[variant][month]
                picked = v7.select_five_strict(target, mode)
                selected[key][month] = picked
                coverage[key][month] = {
                    "sourceRaces": len(target),
                    "selectedRaces": len(picked),
                    "expectedSelectedRaces": v7.expected_selected_count(target),
                }

    v7.POLICY_COUNT = POLICY_COUNT
    report_courses = {}
    for course in COURSES:
        policies = v7.generate_policies(course)
        candidate_tables = {
            key: precompute_candidate(course, policies, selected[key], months)
            for key in selected
        }
        monthly = []
        for month in evaluation_months:
            target_index = months.index(month)
            choices = []
            for key, table in candidate_tables.items():
                choice = choose_policy(table, target_index)
                choice["key"] = key
                choice["productionSafe"] = not key.startswith("market_audit:")
                choices.append(choice)
            choices.sort(
                key=lambda row: (
                    row["productionSafe"],
                    row["score"],
                    row["historyQ25CappedRoiPct"],
                    row["historyHitRatePct"],
                ),
                reverse=True,
            )
            chosen = choices[0]
            key = chosen["key"]
            result = evaluate_month(course, candidate_tables[key][target_index], chosen)
            monthly.append({
                "month": month,
                "key": key,
                "variant": key.split(":", 1)[0],
                "mode": key.split(":", 1)[1],
                "productionSafe": chosen["productionSafe"],
                "history": {name: value for name, value in chosen.items() if name not in {"index", "key", "productionSafe"}},
                "policy": base.describe_policy(policies[chosen["index"]]),
                "result": result,
            })
        development_rows = [row["result"] for row in monthly if row["month"] < FINAL_HOLDOUT_START_MONTH]
        holdout_rows = [row["result"] for row in monthly if row["month"] >= FINAL_HOLDOUT_START_MONTH]
        report_courses[course] = {
            "development": aggregate(development_rows),
            "finalHoldout": aggregate(holdout_rows),
            "full": aggregate([row["result"] for row in monthly]),
            "monthly": monthly,
        }

    holdout_pass = all(
        report_courses[course]["finalHoldout"]["roiPct"] >= 200.0
        and report_courses[course]["finalHoldout"]["cappedRoiPct"] >= 110.0
        and report_courses[course]["finalHoldout"]["hitRatePct"] >= REQUIRED_HIT
        for course in COURSES
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v7.2-shadow-enriched-ranking",
        "productionChanged": False,
        "promotionEligible": holdout_pass,
        "method": (
            "Create chronological pre-race features for distance/surface/venue/class changes, rest, jockey and trainer changes, "
            "recent finish/speed/final-3F trends, historical market residuals, exact context records and entity interactions. "
            "Train pointwise, pairwise and ensemble market-free ranking models before every target month, force five races per venue/day, "
            "select a full-budget course policy only from earlier rolling OOS months, and reserve May-August 2026 as a final holdout."
        ),
        "guardrails": {
            "selectedRacesPerVenueDay": 5,
            "noEmptyRaceSelection": True,
            "fullBudgetEverySelectedRace": True,
            "currentRaceMarketRemovedFromPromotableModels": True,
            "marketAuditCannotPromote": True,
            "policyCountPerCourse": POLICY_COUNT,
            "finalHoldoutStart": FINAL_HOLDOUT_START_MONTH,
        },
        "period": {
            "dataStart": min(race["raceDate"] for race in races),
            "dataEnd": max(race["raceDate"] for race in races),
            "finishedRaces": len(races),
            "rollingMonths": months,
            "evaluationMonths": evaluation_months,
        },
        "modelAudit": model_audit,
        "coverage": coverage,
        "courses": report_courses,
    }
    Path("v7-enriched-ranking-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "modelVersion": report["modelVersion"],
        "courses": {
            course: {
                "development": report_courses[course]["development"],
                "finalHoldout": report_courses[course]["finalHoldout"],
                "full": report_courses[course]["full"],
            }
            for course in COURSES
        },
        "promotionEligible": holdout_pass,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
