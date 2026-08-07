import itertools
import math
from collections import defaultdict

# Operational policy for live predictions. This is intentionally not called v16.
# v16 remains reserved for a candidate that passes every completion gate.
MODEL_VERSION = "operational-three-course-policy"

COURSE_TARGET_STAKES = {
    "ライト": 2000,
    "スタンダード": 5000,
    "プレミアム": 10000,
}
COURSES = tuple(COURSE_TARGET_STAKES)
UNORDERED_TYPES = {"ワイド", "馬連", "3連複"}
OFFICIAL_ODDS_SOURCE = "jra_official"

COURSE_SPECS = {
    "ライト": {
        "ticket_count": 6,
        "required_types": ("単勝", "ワイド", "馬連"),
        "type_caps": {"単勝": 2, "ワイド": 2, "馬連": 2},
        "pool_size": 8,
        "max_ticket_share": 0.40,
        "probability_weight": 0.95,
        "ev_weight": 1.55,
        "odds_weight": 0.28,
        "rank_penalty": 0.10,
        "edge_bonus": 0.28,
        "type_bias": {"単勝": -0.10, "ワイド": 0.28, "馬連": 0.40},
    },
    "スタンダード": {
        "ticket_count": 15,
        "required_types": ("単勝", "ワイド", "馬連", "馬単", "3連複"),
        "type_caps": {"単勝": 2, "ワイド": 4, "馬連": 3, "馬単": 3, "3連複": 3},
        "pool_size": 8,
        "max_ticket_share": 0.30,
        "probability_weight": 0.70,
        "ev_weight": 1.85,
        "odds_weight": 0.34,
        "rank_penalty": 0.09,
        "edge_bonus": 0.36,
        "type_bias": {"単勝": -0.15, "ワイド": 0.12, "馬連": 0.24, "馬単": 0.34, "3連複": 0.50},
    },
    "プレミアム": {
        "ticket_count": 16,
        "required_types": ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"),
        "type_caps": {"単勝": 2, "ワイド": 3, "馬連": 3, "馬単": 3, "3連複": 3, "3連単": 4},
        "pool_size": 9,
        "max_ticket_share": 0.24,
        "probability_weight": 0.50,
        "ev_weight": 2.05,
        "odds_weight": 0.42,
        "rank_penalty": 0.07,
        "edge_bonus": 0.46,
        "type_bias": {"単勝": -0.25, "ワイド": 0.05, "馬連": 0.14, "馬単": 0.28, "3連複": 0.48, "3連単": 0.72},
    },
}


def clamp(value, low, high):
    return max(low, min(high, value))


def normalized_weights(runners, key):
    raw = [max(0.0, float(runner.get(key) or 0.0)) for runner in runners]
    total = sum(raw)
    if total <= 0:
        return {int(runner["horseNo"]): 1.0 / max(1, len(runners)) for runner in runners}
    return {int(runner["horseNo"]): value / total for runner, value in zip(runners, raw)}


def ordered_probability(order, weights):
    remaining = sum(weights.values())
    probability = 1.0
    used = set()
    for horse_no in order:
        if horse_no in used or remaining <= 0:
            return 0.0
        weight = weights.get(horse_no, 0.0)
        if weight <= 0:
            return 0.0
        probability *= weight / remaining
        remaining -= weight
        used.add(horse_no)
    return clamp(probability, 0.0, 1.0)


def unordered_top_two(a, b, weights):
    return clamp(
        ordered_probability((a, b), weights) + ordered_probability((b, a), weights),
        0.0,
        1.0,
    )


def unordered_top_three(horses, weights):
    if len(set(horses)) != 3:
        return 0.0
    return clamp(
        sum(ordered_probability(order, weights) for order in itertools.permutations(horses)),
        0.0,
        1.0,
    )


def wide_probability(a, b, place_weights):
    if a == b or len(place_weights) < 3:
        return 0.0
    return clamp(
        sum(
            unordered_top_three((a, b, third), place_weights)
            for third in place_weights
            if third not in {a, b}
        ),
        0.0,
        1.0,
    )


def event_probability(bet_type, horses, win_weights, place_weights):
    if bet_type == "単勝":
        return clamp(win_weights.get(horses[0], 0.0), 0.0, 1.0)
    if bet_type == "ワイド":
        return wide_probability(horses[0], horses[1], place_weights)
    if bet_type == "馬連":
        return unordered_top_two(horses[0], horses[1], win_weights)
    if bet_type == "馬単":
        return ordered_probability(horses[:2], win_weights)
    if bet_type == "3連複":
        return unordered_top_three(horses[:3], place_weights)
    if bet_type == "3連単":
        return ordered_probability(horses[:3], win_weights)
    return 0.0


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


def _runner_probability(runner, primary, fallback):
    value = runner.get(primary)
    if value is None:
        value = runner.get(fallback)
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def build_candidates(race, pool_size=9):
    official = official_odds_map(race)
    if not official:
        return []

    raw_runners = list(race.get("runners", []))
    ranked = [
        dict(runner)
        for runner in raw_runners
        if _runner_probability(runner, "probability", "winProbability") > 0
    ]
    ranked.sort(
        key=lambda row: -_runner_probability(row, "probability", "winProbability")
    )
    if len(ranked) < 3:
        return []

    for index, runner in enumerate(ranked, start=1):
        runner["predictedOrder"] = index

    win_input = []
    place_input = []
    for runner in ranked:
        copied_win = dict(runner)
        copied_place = dict(runner)
        copied_win["_p"] = _runner_probability(runner, "probability", "winProbability")
        place_value = _runner_probability(runner, "placeProbability", "top3Probability")
        copied_place["_p"] = place_value if place_value > 0 else copied_win["_p"]
        win_input.append(copied_win)
        place_input.append(copied_place)

    win_weights = normalized_weights(win_input, "_p")
    place_weights = normalized_weights(place_input, "_p")
    by_horse = {int(runner["horseNo"]): runner for runner in ranked}
    pool = ranked[: min(pool_size, len(ranked))]
    first_horse = int(ranked[0]["horseNo"])

    candidates = []
    seen = set()

    def add(bet_type, horses):
        horses = canonical_horses(bet_type, horses)
        if len(set(horses)) != len(horses):
            return
        signature = (bet_type, horses)
        if signature in seen:
            return
        published_odds = official.get(odds_key(bet_type, horses))
        if published_odds is None:
            return
        probability = event_probability(bet_type, horses, win_weights, place_weights)
        if probability <= 0:
            return
        expected_value = clamp(probability * published_odds * 100.0, 0.1, 9999.0)
        rank_sum = sum(int(by_horse[horse]["predictedOrder"]) for horse in horses)
        edge_values = []
        for horse in horses:
            runner = by_horse[horse]
            try:
                market = float(runner.get("market") or runner.get("marketProbability") or 0.0)
            except (TypeError, ValueError):
                market = 0.0
            if market > 0:
                edge_values.append(win_weights.get(horse, 0.0) / market)
        model_edge = sum(edge_values) / len(edge_values) if edge_values else 1.0
        candidates.append({
            "betType": bet_type,
            "horses": horses,
            "combination": "-".join(str(value) for value in horses),
            "officialOdds": published_odds,
            "hitProbability": probability,
            "expectedValuePct": expected_value,
            "rankSum": rank_sum,
            "includesFirst": first_horse in horses,
            "modelEdge": clamp(model_edge, 0.10, 10.0),
            "oddsSource": OFFICIAL_ODDS_SOURCE,
        })
        seen.add(signature)

    for runner in pool:
        add("単勝", (int(runner["horseNo"]),))

    for first, second in itertools.combinations(pool, 2):
        a = int(first["horseNo"])
        b = int(second["horseNo"])
        add("ワイド", (a, b))
        add("馬連", (a, b))
        add("馬単", (a, b))
        add("馬単", (b, a))

    triple_pool = pool[: min(7, len(pool))]
    for first, second, third in itertools.combinations(triple_pool, 3):
        horses = (
            int(first["horseNo"]),
            int(second["horseNo"]),
            int(third["horseNo"]),
        )
        add("3連複", horses)
        for order in itertools.permutations(horses):
            add("3連単", order)

    return candidates


def candidate_score(candidate, spec):
    return (
        spec["ev_weight"] * math.log(max(0.02, candidate["expectedValuePct"] / 100.0))
        + spec["probability_weight"] * math.log(max(1e-8, candidate["hitProbability"]))
        + spec["odds_weight"] * math.log(max(1.01, candidate["officialOdds"]))
        - spec["rank_penalty"] * candidate["rankSum"]
        + spec["edge_bonus"] * math.log(max(0.1, candidate.get("modelEdge", 1.0)))
        + spec["type_bias"].get(candidate["betType"], -99.0)
    )


def select_candidates(course, candidates):
    spec = COURSE_SPECS[course]
    allowed = set(spec["required_types"])
    eligible = [candidate for candidate in candidates if candidate["betType"] in allowed]
    if not eligible:
        return []

    selected = []
    selected_keys = set()
    counts = defaultdict(int)

    # First reserve one valid official-odds ticket for every required bet type.
    for bet_type in spec["required_types"]:
        typed = [candidate for candidate in eligible if candidate["betType"] == bet_type]
        if not typed:
            return []
        best = max(typed, key=lambda candidate: candidate_score(candidate, spec))
        key = (best["betType"], best["combination"])
        selected.append(best)
        selected_keys.add(key)
        counts[bet_type] += 1

    # Fill the remaining slots by course-specific value score while respecting type caps.
    ranked = sorted(eligible, key=lambda candidate: candidate_score(candidate, spec), reverse=True)
    for candidate in ranked:
        if len(selected) >= spec["ticket_count"]:
            break
        bet_type = candidate["betType"]
        key = (bet_type, candidate["combination"])
        if key in selected_keys:
            continue
        if counts[bet_type] >= spec["type_caps"].get(bet_type, 0):
            continue
        selected.append(candidate)
        selected_keys.add(key)
        counts[bet_type] += 1

    if len(selected) != spec["ticket_count"]:
        return []
    if any(counts[bet_type] < 1 for bet_type in spec["required_types"]):
        return []
    return selected


def allocate_stakes(course, selected):
    if not selected:
        return []
    spec = COURSE_SPECS[course]
    target = COURSE_TARGET_STAKES[course]
    ticket_count = len(selected)
    stakes = [100 for _ in selected]
    remaining = target - 100 * ticket_count
    max_stake = max(100, int(target * spec["max_ticket_share"] // 100) * 100)

    scores = [candidate_score(candidate, spec) for candidate in selected]
    maximum = max(scores)
    weights = [math.exp(clamp(score - maximum, -10.0, 0.0)) for score in scores]

    while remaining >= 100:
        available = [index for index, stake in enumerate(stakes) if stake + 100 <= max_stake]
        if not available:
            available = list(range(len(stakes)))
        best_index = max(
            available,
            key=lambda index: weights[index] / (1.0 + stakes[index] / 100.0),
        )
        stakes[best_index] += 100
        remaining -= 100

    if sum(stakes) != target:
        raise RuntimeError(f"COURSE_BUDGET_NOT_EXHAUSTED:{course}:{sum(stakes)}:{target}")
    return stakes


def build_bets(race):
    # Generate once from the largest pool. Each course then has its own scoring/caps/stakes.
    candidates = build_candidates(race, pool_size=max(spec["pool_size"] for spec in COURSE_SPECS.values()))
    if not candidates:
        return []

    bets = []
    signatures = {}
    for course in COURSES:
        selected = select_candidates(course, candidates)
        if not selected:
            return []
        stakes = allocate_stakes(course, selected)
        signatures[course] = tuple(
            (item["betType"], item["combination"], stake)
            for item, stake in zip(selected, stakes)
        )
        for item, stake in zip(selected, stakes):
            bets.append({
                "betType": f'{course}｜{item["betType"]}',
                "combination": item["combination"],
                "stakeYen": stake,
                "assumedOdds": item["officialOdds"],
                "officialOdds": item["officialOdds"],
                "oddsSource": OFFICIAL_ODDS_SOURCE,
                "hitProbability": item["hitProbability"],
                "expectedValuePct": item["expectedValuePct"],
                "modelEdge": item.get("modelEdge", 1.0),
            })

    if len(set(signatures.values())) != len(signatures):
        raise RuntimeError(f"FINAL_POLICY_COURSES_NOT_DISTINCT:{signatures}")
    return bets


def race_value_score(race, course):
    candidates = build_candidates(race, pool_size=COURSE_SPECS[course]["pool_size"])
    selected = select_candidates(course, candidates)
    if not selected:
        return -1e18
    spec = COURSE_SPECS[course]
    values = sorted((candidate_score(candidate, spec) for candidate in selected), reverse=True)
    return sum(values[: min(6, len(values))]) / max(1, min(6, len(values)))


def select_minimum_five_per_venue_day(races, course):
    grouped = defaultdict(list)
    for race in races:
        grouped[(race.get("raceDate"), race.get("venue"))].append(race)
    selected = []
    for _, rows in grouped.items():
        scored = sorted(rows, key=lambda race: race_value_score(race, course), reverse=True)
        viable = [race for race in scored if race_value_score(race, course) > -1e17]
        if len(viable) < 5:
            # Do not silently reduce below the project minimum.
            continue
        selected.extend(viable[:5])
    return selected


def payout_key(bet_type, combination):
    values = tuple(
        int(value)
        for value in str(combination).replace("→", "-").replace("－", "-").split("-")
        if str(value).strip().isdigit()
    )
    values = tuple(sorted(values)) if bet_type in UNORDERED_TYPES else values
    return f'{bet_type}:{"-".join(str(value) for value in values)}'


def evaluate(races):
    aggregate = {
        course: {
            "races": 0,
            "tickets": 0,
            "stakeYen": 0,
            "returnYen": 0,
            "hitRaces": 0,
            "skippedNoOfficialOdds": 0,
            "monthly": defaultdict(lambda: [0, 0]),
        }
        for course in COURSES
    }

    for race in races:
        bets = build_bets(race)
        if not bets:
            for course in COURSES:
                aggregate[course]["skippedNoOfficialOdds"] += 1
            continue

        race_returns = defaultdict(int)
        for bet in bets:
            course, ticket = bet["betType"].split("｜", 1)
            stake = int(bet["stakeYen"])
            horses = {int(value) for value in bet["combination"].split("-") if value}
            refund_horses = set(race.get("refunds", set()))
            if horses & refund_horses:
                payout = 100
            else:
                payout = float(race.get("payouts", {}).get(payout_key(ticket, bet["combination"]), 0))
            returned = round(stake / 100.0 * payout)
            row = aggregate[course]
            row["tickets"] += 1
            row["stakeYen"] += stake
            row["returnYen"] += returned
            month = str(race.get("raceDate") or "")[:7]
            row["monthly"][month][0] += stake
            row["monthly"][month][1] += returned
            race_returns[course] += returned

        for course in COURSES:
            row = aggregate[course]
            row["races"] += 1
            row["hitRaces"] += int(race_returns[course] > 0)

    result = {}
    for course, row in aggregate.items():
        stake = row["stakeYen"]
        monthly = {
            month: returned / monthly_stake * 100.0 if monthly_stake else 0.0
            for month, (monthly_stake, returned) in row["monthly"].items()
        }
        result[course] = {
            "races": row["races"],
            "tickets": row["tickets"],
            "stakeYen": stake,
            "returnYen": row["returnYen"],
            "profitYen": row["returnYen"] - stake,
            "roiPct": row["returnYen"] / stake * 100.0 if stake else None,
            "hitRaces": row["hitRaces"],
            "hitRatePct": row["hitRaces"] / row["races"] * 100.0 if row["races"] else None,
            "skippedNoOfficialOdds": row["skippedNoOfficialOdds"],
            "monthly": monthly,
        }
    return result
