import base64
import json
import math
import zlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "config" / "v16-uniform-rule-model.json"
MODEL_VERSION = "v16"
OFFICIAL_ODDS_SOURCE = "jra_official"
COURSE_STAKES = {
    "ライト": (1000, 1000),
    "スタンダード": (2500, 2500),
    "プレミアム": (5000, 5000),
}


def load_model():
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    if model.get("modelVersion") != MODEL_VERSION:
        raise RuntimeError("V16_MODEL_VERSION_MISMATCH")
    raw = zlib.decompress(base64.b64decode(model["rulePayload"]))
    payload = json.loads(raw.decode("utf-8"))
    rules = []
    for cols, vals, quality in payload["r"]:
        rules.append((tuple(cols.split("|")), tuple(vals.split("|")), float(quality)))
    if len(rules) != 800:
        raise RuntimeError(f"V16_RULE_COUNT_MISMATCH:{len(rules)}")
    return model, rules


MODEL, RULES = load_model()


def field_bin(field_size):
    value = int(field_size)
    if value <= 9:
        return "<=9"
    if value <= 11:
        return "10-11"
    if value <= 13:
        return "12-13"
    if value <= 15:
        return "14-15"
    return "16+"


def race_no_bin(race_no):
    value = int(race_no)
    if 1 <= value <= 3:
        return "0"
    if value <= 6:
        return "1"
    if value <= 9:
        return "2"
    return "3"


def distance_bin(distance_m):
    value = int(distance_m)
    if value <= 0:
        return None
    return str((value // 400) * 400)


def numeric_bin(value, boundaries):
    value = float(value)
    for index in range(len(boundaries) - 1):
        if boundaries[index] <= value < boundaries[index + 1]:
            return str(index)
    return None


def odds_bin(odds):
    return numeric_bin(float(odds), [0, 3, 5, 10, 20, 40, 80, 150, 300, 600, 1000, 3000, 1e18])


def residual_bin(ratio):
    return numeric_bin(float(ratio), [0, 0.8, 0.9, 0.95, 1, 1.05, 1.1, 1.2, 1.4, 2, 10, 1e18])


def rank_bin(rank):
    value = int(rank)
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if value == 3:
        return "3"
    if value <= 5:
        return "4-5"
    if value <= 10:
        return "6-10"
    return "11+"


def enrich_candidate(race, candidate):
    if candidate.get("oddsSource") != OFFICIAL_ODDS_SOURCE:
        raise RuntimeError("V16_REQUIRES_JRA_OFFICIAL_ODDS")
    if race.get("surface") in (None, "", "PARSE_MISS"):
        return None
    if race.get("distanceM") in (None, 0, "0"):
        return None
    resid_ratio = candidate.get("residRatio")
    if resid_ratio is None:
        model_probability = float(candidate.get("predProb") or 0.0)
        market_probability = float(candidate.get("marketProb") or 0.0)
        if model_probability <= 0 or market_probability <= 0:
            return None
        resid_ratio = model_probability / market_probability
    row = {
        "betType": str(candidate["betType"]),
        "venue": str(race["venue"]),
        "surface": str(race["surface"]),
        "distBin": distance_bin(race["distanceM"]),
        "fieldBin": field_bin(race["fieldSize"]),
        "raceNoBin": race_no_bin(race["raceNo"]),
        "oddsBin": odds_bin(candidate["odds"]),
        "residBin": residual_bin(resid_ratio),
        "rankBin": rank_bin(candidate["rank"]),
        "trackCondition": str(race.get("trackCondition") or ""),
        "weather": str(race.get("weather") or ""),
    }
    if any(value in (None, "PARSE_MISS", "nan", "None", "UNKNOWN", "不明") for value in row.values()):
        return None
    return row


def score_candidate(race, candidate):
    row = enrich_candidate(race, candidate)
    if row is None:
        return None
    match_count = 0
    quality_sum = 0.0
    quality_max = 0.0
    for cols, vals, quality in RULES:
        if all(row.get(col) == value for col, value in zip(cols, vals)):
            match_count += 1
            quality_sum += quality
            quality_max = max(quality_max, quality)
    score = quality_max + 1.4 * math.log1p(match_count) + 0.35 * math.log1p(max(0.0, quality_sum))
    out = dict(candidate)
    out["ruleMatchCount"] = match_count
    out["ruleQualitySum"] = quality_sum
    out["ruleQualityMax"] = quality_max
    out["uniformScore"] = score
    return out


def select_race(race, candidates):
    # The upstream v16 candidate engine supplies at most the top five predicted-EV
    # candidates for each of the six JRA bet types using official combination odds.
    scored = []
    for candidate in candidates:
        row = score_candidate(race, candidate)
        if row is not None:
            scored.append(row)
    by_type = defaultdict(list)
    for row in scored:
        by_type[row["betType"]].append(row)
    best_types = []
    for bet_type, rows in by_type.items():
        rows.sort(key=lambda row: (-row["uniformScore"], int(row["rank"]), float(row["odds"])))
        best_types.append(rows[0])
    best_types.sort(key=lambda row: (-row["uniformScore"], int(row["rank"]), float(row["odds"])))
    if len(best_types) < 2:
        return None
    first, second = best_types[:2]
    if first["betType"] == second["betType"]:
        raise RuntimeError("V16_DISTINCT_BET_TYPE_INVARIANT_BROKEN")
    race_score = first["uniformScore"] + 0.8 * second["uniformScore"]
    return {
        "raceId": race["raceId"],
        "raceDate": race["raceDate"],
        "venue": race["venue"],
        "raceNo": int(race["raceNo"]),
        "raceScore": race_score,
        "tickets": [first, second],
    }


def select_venue_day(races_with_candidates):
    selections = []
    for race, candidates in races_with_candidates:
        selected = select_race(race, candidates)
        if selected is not None:
            selections.append(selected)
    selections.sort(key=lambda row: (-row["raceScore"], row["raceNo"], row["raceId"]))
    if len(selections) < 5:
        raise RuntimeError(f"V16_VENUE_DAY_HAS_FEWER_THAN_FIVE_ELIGIBLE_RACES:{len(selections)}")
    return selections[:5]


def build_course_bets(selected_race, course):
    stakes = COURSE_STAKES[course]
    tickets = selected_race["tickets"]
    if len(tickets) != 2 or tickets[0]["betType"] == tickets[1]["betType"]:
        raise RuntimeError("V16_REQUIRES_TWO_DISTINCT_BET_TYPES")
    return [
        {
            "betType": ticket["betType"],
            "combination": ticket["combination"],
            "stakeYen": stake,
            "officialOdds": float(ticket["odds"]),
            "oddsSource": OFFICIAL_ODDS_SOURCE,
            "uniformScore": float(ticket["uniformScore"]),
            "ruleMatchCount": int(ticket["ruleMatchCount"]),
        }
        for ticket, stake in zip(tickets, stakes)
    ]
