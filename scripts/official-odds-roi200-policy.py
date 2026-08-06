import itertools
import math
from collections import defaultdict

MODEL_VERSION = "v14.0-official-odds-constrained-roi200"
OFFICIAL_ODDS_SOURCE = "jra_official"
TARGET_ROI_PCT = 200.0
MINIMUM_RACES_PER_VENUE_DAY = 5
MAXIMUM_RACES_PER_VENUE_DAY = 12
COURSE_TARGET_STAKES = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
COURSE_TICKET_COUNTS = {"ライト": 6, "スタンダード": 15, "プレミアム": 16}
COURSE_TYPES = {
    "ライト": ("単勝", "ワイド", "馬連"),
    "スタンダード": ("単勝", "ワイド", "馬連", "馬単", "3連複"),
    "プレミアム": ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"),
}
COURSE_MIN_HIT_PROBABILITY = {"ライト": 0.025, "スタンダード": 0.008, "プレミアム": 0.0015}
COURSE_MAX_TICKET_SHARE = {"ライト": 0.35, "スタンダード": 0.30, "プレミアム": 0.25}
TYPE_CAPS = {
    "ライト": {"単勝": 2, "ワイド": 3, "馬連": 2},
    "スタンダード": {"単勝": 2, "ワイド": 4, "馬連": 3, "馬単": 5, "3連複": 4},
    "プレミアム": {"単勝": 2, "ワイド": 3, "馬連": 3, "馬単": 4, "3連複": 4, "3連単": 6},
}
DEFAULT_CALIBRATION = {
    "単勝": 0.72,
    "ワイド": 0.68,
    "馬連": 0.66,
    "馬単": 0.62,
    "3連複": 0.60,
    "3連単": 0.56,
}
UNORDERED_TYPES = {"ワイド", "馬連", "3連複"}
COURSES = tuple(COURSE_TARGET_STAKES)


def clamp(value, low, high):
    return max(low, min(high, value))


def normalized_weights(runners, key="probability"):
    raw = [max(0.0, float(runner.get(key) or 0.0)) for runner in runners]
    total = sum(raw)
    if total <= 0:
        return {int(runner["horseNo"]): 1.0 / max(1, len(runners)) for runner in runners}
    return {int(runner["horseNo"]): value / total for runner, value in zip(runners, raw)}


def ordered_probability(order, weights):
    remaining = sum(weights.values())
    value = 1.0
    used = set()
    for horse_no in order:
        if horse_no in used or remaining <= 0:
            return 0.0
        weight = weights.get(horse_no, 0.0)
        if weight <= 0:
            return 0.0
        value *= weight / remaining
        remaining -= weight
        used.add(horse_no)
    return clamp(value, 0.0, 1.0)


def unordered_top_two(a, b, weights):
    return clamp(ordered_probability((a, b), weights) + ordered_probability((b, a), weights), 0.0, 1.0)


def unordered_top_three(horses, weights):
    if len(set(horses)) != 3:
        return 0.0
    return clamp(sum(ordered_probability(order, weights) for order in itertools.permutations(horses)), 0.0, 1.0)


def wide_probability(a, b, weights):
    if a == b or len(weights) < 3:
        return 0.0
    return clamp(
        sum(unordered_top_three((a, b, third), weights) for third in weights if third not in {a, b}),
        0.0,
        1.0,
    )


def event_probability(bet_type, horses, weights):
    if bet_type == "単勝":
        return clamp(weights.get(horses[0], 0.0), 0.0, 1.0)
    if bet_type == "ワイド":
        return wide_probability(horses[0], horses[1], weights)
    if bet_type == "馬連":
        return unordered_top_two(horses[0], horses[1], weights)
    if bet_type == "馬単":
        return ordered_probability(horses[:2], weights)
    if bet_type == "3連複":
        return unordered_top_three(horses[:3], weights)
    return ordered_probability(horses[:3], weights)


def canonical_horses(bet_type, horses):
    values = tuple(int(value) for value in horses)
    return tuple(sorted(values)) if bet_type in UNORDERED_TYPES else values


def odds_key(bet_type, horses):
    values = canonical_horses(bet_type, horses)
    return f'{bet_type}:{"-".join(str(value) for value in values)}'


def official_odds_map(race):
    if race.get("oddsSource") != OFFICIAL_ODDS_SOURCE:
        return {}
    raw = race.get("officialOdds")
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for key, value in raw.items():
        try:
            odds = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(odds) and odds > 1.0:
            cleaned[str(key)] = math.floor(odds * 10.0) / 10.0
    return cleaned


def calibration_factor(race, bet_type):
    raw = race.get("officialOddsCalibration")
    if isinstance(raw, dict):
        try:
            value = float(raw.get(bet_type))
            if math.isfinite(value):
                return clamp(value, 0.20, 1.00)
        except (TypeError, ValueError):
            pass
    return DEFAULT_CALIBRATION[bet_type]


def conservative_probability(race, bet_type, model_probability, official_odds):
    market_floor = 0.68 / max(1.01, official_odds)
    shrink = calibration_factor(race, bet_type)
    if model_probability <= market_floor:
        return max(0.0, model_probability * shrink)
    return clamp(market_floor + shrink * (model_probability - market_floor), 0.0, model_probability)


def build_candidates(race):
    official = official_odds_map(race)
    if not official:
        return []
    ranked = sorted(
        [runner for runner in race.get("runners", []) if float(runner.get("probability") or 0.0) > 0.0],
        key=lambda runner: -float(runner.get("probability") or 0.0),
    )
    if len(ranked) < 3:
        return []
    for index, runner in enumerate(ranked, start=1):
        runner["predictedOrder"] = index
    model_weights = normalized_weights(ranked)
    first_horse = int(ranked[0]["horseNo"])
    rank_by_horse = {int(runner["horseNo"]): int(runner["predictedOrder"]) for runner in ranked}
    pool = [int(runner["horseNo"]) for runner in ranked[:8]]
    candidates = []
    seen = set()

    def add(bet_type, horses):
        horses = canonical_horses(bet_type, horses)
        signature = (bet_type, horses)
        if signature in seen or len(set(horses)) != len(horses):
            return
        published_odds = official.get(odds_key(bet_type, horses))
        if published_odds is None:
            return
        model_probability = event_probability(bet_type, horses, model_weights)
        if model_probability <= 0.0:
            return
        conservative = conservative_probability(race, bet_type, model_probability, published_odds)
        projected_roi = conservative * published_odds * 100.0
        candidates.append(
            {
                "betType": bet_type,
                "horses": horses,
                "combination": "-".join(str(value) for value in horses),
                "officialOdds": published_odds,
                "modelProbability": model_probability,
                "conservativeProbability": conservative,
                "projectedRoiPct": projected_roi,
                "predictedRankSum": sum(rank_by_horse.get(horse, 99) for horse in horses),
                "includesModelFirst": first_horse in horses,
                "oddsSource": OFFICIAL_ODDS_SOURCE,
            }
        )
        seen.add(signature)

    for horse in pool:
        add("単勝", (horse,))
    for a, b in itertools.combinations(pool, 2):
        add("ワイド", (a, b))
        add("馬連", (a, b))
        add("馬単", (a, b))
        add("馬単", (b, a))
    for horses in itertools.combinations(pool, 3):
        add("3連複", horses)
        for order in itertools.permutations(horses):
            add("3連単", order)
    return candidates


def candidate_score(candidate):
    probability = max(1e-9, candidate["conservativeProbability"])
    projected = max(1.0, candidate["projectedRoiPct"])
    return (
        math.log(projected / 100.0) * 4.0
        + math.log(probability) * 0.30
        - candidate["predictedRankSum"] * 0.025
        + (0.08 if candidate["includesModelFirst"] else 0.0)
    )


def choose_course_candidates(course, candidates):
    required_types = COURSE_TYPES[course]
    caps = TYPE_CAPS[course]
    target_count = COURSE_TICKET_COUNTS[course]
    by_type = defaultdict(list)
    for candidate in candidates:
        if candidate["betType"] in required_types:
            by_type[candidate["betType"]].append(candidate)
    for bet_type in by_type:
        by_type[bet_type].sort(key=candidate_score, reverse=True)
    if any(not by_type[bet_type] for bet_type in required_types):
        return []

    selected = []
    signatures = set()
    counts = defaultdict(int)
    for bet_type in required_types:
        candidate = by_type[bet_type][0]
        selected.append(candidate)
        signatures.add((candidate["betType"], candidate["combination"]))
        counts[bet_type] += 1

    ranked = sorted(
        [candidate for candidate in candidates if candidate["betType"] in required_types],
        key=candidate_score,
        reverse=True,
    )
    for candidate in ranked:
        if len(selected) >= target_count:
            break
        signature = (candidate["betType"], candidate["combination"])
        if signature in signatures:
            continue
        bet_type = candidate["betType"]
        if counts[bet_type] >= caps[bet_type]:
            continue
        if candidate["conservativeProbability"] < COURSE_MIN_HIT_PROBABILITY[course]:
            continue
        selected.append(candidate)
        signatures.add(signature)
        counts[bet_type] += 1

    if len(selected) != target_count:
        return []
    if set(candidate["betType"] for candidate in selected) != set(required_types):
        return []
    return selected


def allocate_stakes(course, selected):
    target = COURSE_TARGET_STAKES[course]
    stakes = [100 for _ in selected]
    remaining = target - sum(stakes)
    maximum_per_ticket = int(target * COURSE_MAX_TICKET_SHARE[course] // 100 * 100)
    while remaining >= 100:
        eligible = [
            index
            for index, stake in enumerate(stakes)
            if stake + 100 <= maximum_per_ticket
        ]
        if not eligible:
            raise RuntimeError(f"OFFICIAL_ODDS_STAKE_CAP_BLOCKED:{course}:{remaining}")
        best = max(
            eligible,
            key=lambda index: (
                selected[index]["projectedRoiPct"] - 100.0
            ) * math.sqrt(max(1e-9, selected[index]["conservativeProbability"])) / (1.0 + stakes[index] / 500.0),
        )
        stakes[best] += 100
        remaining -= 100
    if sum(stakes) != target:
        raise RuntimeError(f"OFFICIAL_ODDS_BUDGET_MISMATCH:{course}:{sum(stakes)}")
    return stakes


def plan_for_course(course, candidates):
    selected = choose_course_candidates(course, candidates)
    if not selected:
        return None
    stakes = allocate_stakes(course, selected)
    budget = COURSE_TARGET_STAKES[course]
    expected_return = sum(
        stake * candidate["projectedRoiPct"] / 100.0
        for candidate, stake in zip(selected, stakes)
    )
    projected_roi = expected_return / budget * 100.0
    portfolio_hit_probability = 1.0
    for candidate in selected:
        portfolio_hit_probability *= 1.0 - clamp(candidate["conservativeProbability"], 0.0, 1.0)
    portfolio_hit_probability = 1.0 - portfolio_hit_probability
    return {
        "course": course,
        "projectedRoiPct": projected_roi,
        "portfolioHitProbability": portfolio_hit_probability,
        "selected": selected,
        "stakes": stakes,
        "passesTarget": projected_roi >= TARGET_ROI_PCT,
    }


def plans_for_race(race):
    candidates = build_candidates(race)
    if not candidates:
        return None
    plans = {course: plan_for_course(course, candidates) for course in COURSES}
    if any(plan is None for plan in plans.values()):
        return None
    joint_minimum = min(plan["projectedRoiPct"] for plan in plans.values())
    return {
        "plans": plans,
        "jointProjectedRoiPct": joint_minimum,
        "allCoursesPass": all(plan["passesTarget"] for plan in plans.values()),
        "candidates": candidates,
    }


def selected_race_ids(races):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = set()
    for key, group in grouped.items():
        qualified = []
        for race in group:
            summary = plans_for_race(race)
            if summary and summary["allCoursesPass"]:
                race["officialOddsRoi200Summary"] = summary
                qualified.append(race)
        qualified.sort(
            key=lambda race: (
                -race["officialOddsRoi200Summary"]["jointProjectedRoiPct"],
                int(race.get("raceNo") or 99),
            )
        )
        if len(qualified) < MINIMUM_RACES_PER_VENUE_DAY:
            continue
        take = min(MAXIMUM_RACES_PER_VENUE_DAY, len(qualified))
        selected.update(race["raceId"] for race in qualified[:take])
    return selected


def build_bets(race):
    summary = race.get("officialOddsRoi200Summary") or plans_for_race(race)
    if not summary or not summary["allCoursesPass"]:
        return []
    bets = []
    course_signatures = {}
    for course in COURSES:
        plan = summary["plans"][course]
        signature = []
        for candidate, stake in zip(plan["selected"], plan["stakes"]):
            signature.append((candidate["betType"], candidate["combination"], stake))
            bets.append(
                {
                    "betType": f'{course}｜{candidate["betType"]}',
                    "combination": candidate["combination"],
                    "stakeYen": stake,
                    "assumedOdds": candidate["officialOdds"],
                    "officialOdds": candidate["officialOdds"],
                    "oddsSource": OFFICIAL_ODDS_SOURCE,
                    "hitProbability": candidate["conservativeProbability"],
                    "modelProbability": candidate["modelProbability"],
                    "expectedValuePct": candidate["projectedRoiPct"],
                    "courseProjectedRoiPct": plan["projectedRoiPct"],
                }
            )
        course_signatures[course] = tuple(signature)
    if len(set(course_signatures.values())) != len(course_signatures):
        raise RuntimeError(f"OFFICIAL_ODDS_COURSES_NOT_DISTINCT:{course_signatures}")
    for course in COURSES:
        course_bets = [bet for bet in bets if bet["betType"].startswith(f"{course}｜")]
        if sum(bet["stakeYen"] for bet in course_bets) != COURSE_TARGET_STAKES[course]:
            raise RuntimeError(f"OFFICIAL_ODDS_COURSE_BUDGET_INVALID:{course}")
        actual_types = {bet["betType"].split("｜", 1)[1] for bet in course_bets}
        if actual_types != set(COURSE_TYPES[course]):
            raise RuntimeError(f"OFFICIAL_ODDS_TYPE_DIVERSIFICATION_INVALID:{course}:{actual_types}")
    return bets


def candidate_audit_rows(race):
    candidates = build_candidates(race)
    return [
        {
            "raceId": race["raceId"],
            "betType": candidate["betType"],
            "combination": candidate["combination"],
            "modelProbability": candidate["modelProbability"],
            "conservativeProbability": candidate["conservativeProbability"],
            "officialOdds": candidate["officialOdds"],
            "projectedRoiPct": candidate["projectedRoiPct"],
            "predictedRankSum": candidate["predictedRankSum"],
            "includesModelFirst": int(candidate["includesModelFirst"]),
        }
        for candidate in candidates
    ]
