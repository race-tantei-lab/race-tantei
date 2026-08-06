import itertools
import math
from collections import defaultdict

MODEL_VERSION = "v5.0.0-nonlinear-course-policy"
COURSE_TARGET_STAKES = {"ライト": 1600, "スタンダード": 4200, "プレミアム": 8800}
COURSES = tuple(COURSE_TARGET_STAKES)
UNORDERED_TYPES = {"ワイド", "馬連", "3連複"}

TICKET_CONFIG = {
    "単勝": {"payout_ratio": 1.0, "reliability": 0.98},
    "ワイド": {"payout_ratio": 0.77, "reliability": 0.92},
    "馬連": {"payout_ratio": 0.77, "reliability": 0.89},
    "馬単": {"payout_ratio": 0.75, "reliability": 0.85},
    "3連複": {"payout_ratio": 0.75, "reliability": 0.82},
    "3連単": {"payout_ratio": 0.72, "reliability": 0.76},
}

TICKET_POLICIES = {
    "ライト": {
        "ticket_count": 6,
        "ev_weight": 2.002791382841485,
        "probability_weight": 0.9945825426512676,
        "odds_weight": 0.8745773805861319,
        "rank_weight": -0.16260266870806017,
        "first_weight": 0.20812264852025464,
        "temperature": 1.8092974375227913,
        "type_bias": {"単勝": -1.8823857505802501, "ワイド": 1.9861787771837367, "馬連": 2.282755209735998},
        "type_caps": {"単勝": 2, "ワイド": 4, "馬連": 2},
    },
    "スタンダード": {
        "ticket_count": 15,
        "ev_weight": 2.448426025483065,
        "probability_weight": 0.6442199397939466,
        "odds_weight": 1.10786229170172,
        "rank_weight": -0.4424013070881061,
        "first_weight": 0.19175246432695292,
        "temperature": 1.0713287921387726,
        "type_bias": {"単勝": 0.9815552702951948, "ワイド": -2.471790022375782, "馬連": -1.839918491936583, "馬単": -0.6995578694074225, "3連複": -2.4933270986794525},
        "type_caps": {"単勝": 1, "ワイド": 4, "馬連": 2, "馬単": 8, "3連複": 12},
    },
    "プレミアム": {
        "ticket_count": 16,
        "ev_weight": 1.4997241836636233,
        "probability_weight": 0.33235115100077034,
        "odds_weight": 0.44878479210632105,
        "rank_weight": -0.5280945621804399,
        "first_weight": 0.15055666817087598,
        "temperature": 2.1457988887321537,
        "type_bias": {"単勝": -2.195983671005196, "ワイド": 0.7970673189260613, "馬連": -0.9703925652940055, "馬単": -1.1629063402365234, "3連複": -0.366139876100982, "3連単": 1.6391215410163928},
        "type_caps": {"単勝": 2, "ワイド": 3, "馬連": 4, "馬単": 11, "3連複": 6, "3連単": 15},
    },
}


def clamp(value, low, high):
    return max(low, min(high, value))


def normalized_weights(runners, key, fallback_key=None):
    raw = []
    for runner in runners:
        value = float(runner.get(key) or 0)
        if value <= 0 and fallback_key:
            value = float(runner.get(fallback_key) or 0)
        raw.append(max(0.0, value))
    total = sum(raw)
    if total <= 0:
        return {int(runner["horseNo"]): 1 / max(1, len(runners)) for runner in runners}
    return {int(runner["horseNo"]): value / total for runner, value in zip(runners, raw)}


def market_weights(runners):
    raw = []
    for runner in runners:
        odds = float(runner.get("winOdds") or 0)
        probability = 1 / odds if odds > 1 else max(0.0001, float(runner.get("probability") or 0))
        raw.append(probability)
    total = sum(raw)
    return {int(runner["horseNo"]): value / max(1e-12, total) for runner, value in zip(runners, raw)}


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
    return clamp(ordered_probability((a, b), weights) + ordered_probability((b, a), weights), 0.0, 1.0)


def unordered_top_three(horses, weights):
    if len(set(horses)) != 3:
        return 0.0
    return clamp(sum(ordered_probability(order, weights) for order in itertools.permutations(horses)), 0.0, 1.0)


def wide_probability(a, b, weights):
    if a == b or len(weights) < 3:
        return 0.0
    return clamp(sum(unordered_top_three((a, b, third), weights) for third in weights if third not in {a, b}), 0.0, 1.0)


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


def candidate_score(candidate, policy):
    return (
        policy["ev_weight"] * math.log(max(0.05, candidate["expectedValuePct"] / 100))
        + policy["probability_weight"] * math.log(max(0.000001, candidate["hitProbability"]))
        + policy["odds_weight"] * math.log(max(1.1, candidate["assumedOdds"]))
        + policy["rank_weight"] * candidate["rankSum"]
        + policy["first_weight"] * (1 if candidate["includesFirst"] else 0)
        + policy["type_bias"].get(candidate["betType"], -99)
    )


def build_candidates(race):
    ranked = sorted([runner for runner in race.get("runners", []) if float(runner.get("probability") or 0) > 0], key=lambda row: -float(row.get("probability") or 0))
    if not ranked:
        return []
    for index, runner in enumerate(ranked, start=1):
        runner.setdefault("predictedOrder", index)
    model = normalized_weights(ranked, "probability")
    market = market_weights(ranked)
    by_horse = {int(runner["horseNo"]): runner for runner in ranked}
    first_horse = int(ranked[0]["horseNo"])
    pool = ranked[:6]
    candidates = []
    seen = set()

    def add(bet_type, horses):
        horses = canonical_horses(bet_type, horses)
        key = (bet_type, horses)
        if key in seen or len(set(horses)) != len(horses):
            return
        model_probability = event_probability(bet_type, horses, model)
        market_probability = event_probability(bet_type, horses, market)
        if model_probability <= 0 or market_probability <= 0:
            return
        config = TICKET_CONFIG[bet_type]
        if bet_type == "単勝":
            odds = float(by_horse[horses[0]].get("winOdds") or 0)
            if odds <= 1:
                return
        else:
            odds = config["payout_ratio"] / market_probability
        odds = math.floor(clamp(odds, 1.1, 2500.0) * 10) / 10
        expected_value = clamp(model_probability * odds * 100 * config["reliability"], 1.0, 9999.0)
        rank_sum = sum(int(by_horse[horse].get("predictedOrder") or 99) for horse in horses)
        candidates.append({
            "betType": bet_type,
            "horses": horses,
            "combination": "-".join(str(value) for value in horses),
            "assumedOdds": odds,
            "hitProbability": model_probability,
            "expectedValuePct": expected_value,
            "rankSum": rank_sum,
            "includesFirst": first_horse in horses,
        })
        seen.add(key)

    for runner in pool:
        add("単勝", (int(runner["horseNo"]),))
    for first, second in itertools.combinations(pool, 2):
        a, b = int(first["horseNo"]), int(second["horseNo"])
        add("ワイド", (a, b))
        add("馬連", (a, b))
        add("馬単", (a, b))
        add("馬単", (b, a))
    for first, second, third in itertools.combinations(pool, 3):
        horses = (int(first["horseNo"]), int(second["horseNo"]), int(third["horseNo"]))
        add("3連複", horses)
        for order in itertools.permutations(horses):
            add("3連単", order)
    return candidates


def select_candidates(course, candidates):
    policy = TICKET_POLICIES[course]
    ranked = sorted(
        [candidate for candidate in candidates if policy["type_caps"].get(candidate["betType"], 0) > 0],
        key=lambda candidate: candidate_score(candidate, policy),
        reverse=True,
    )
    selected = []
    counts = defaultdict(int)
    for candidate in ranked:
        if len(selected) >= policy["ticket_count"]:
            break
        bet_type = candidate["betType"]
        if counts[bet_type] >= policy["type_caps"].get(bet_type, 0):
            continue
        selected.append(candidate)
        counts[bet_type] += 1
    return selected


def allocate_stakes(course, selected):
    if not selected:
        return []
    policy = TICKET_POLICIES[course]
    target = COURSE_TARGET_STAKES[course]
    stakes = [100 for _ in selected]
    remaining = target - len(selected) * 100
    scores = [candidate_score(candidate, policy) for candidate in selected]
    maximum = max(scores)
    weights = [math.exp(clamp((score - maximum) / policy["temperature"], -12, 0)) for score in scores]
    while remaining >= 100:
        best_index = max(range(len(selected)), key=lambda index: weights[index] / (1 + stakes[index] / 100))
        stakes[best_index] += 100
        remaining -= 100
    return stakes


def build_bets(race):
    candidates = build_candidates(race)
    bets = []
    signatures = {}
    for course in COURSES:
        selected = select_candidates(course, candidates)
        stakes = allocate_stakes(course, selected)
        signatures[course] = tuple((item["betType"], item["combination"], stake) for item, stake in zip(selected, stakes))
        for item, stake in zip(selected, stakes):
            bets.append({
                "betType": f'{course}｜{item["betType"]}',
                "combination": item["combination"],
                "stakeYen": stake,
                "assumedOdds": item["assumedOdds"],
                "hitProbability": item["hitProbability"],
                "expectedValuePct": item["expectedValuePct"],
            })
    if len(set(signatures.values())) != len(COURSES):
        raise RuntimeError(f"FINAL_POLICY_COURSES_NOT_DISTINCT:{signatures}")
    return bets


def payout_key(bet_type, combination):
    values = tuple(int(value) for value in str(combination).replace("→", "-").replace("－", "-").split("-") if str(value).strip().isdigit())
    values = tuple(sorted(values)) if bet_type in UNORDERED_TYPES else values
    return f'{bet_type}:{"-".join(str(value) for value in values)}'


def evaluate(races):
    aggregate = {course: {"races": 0, "tickets": 0, "stakeYen": 0, "returnYen": 0, "hitRaces": 0, "monthly": defaultdict(lambda: [0, 0])} for course in COURSES}
    for race in races:
        bets = build_bets(race)
        race_returns = defaultdict(int)
        for bet in bets:
            course, ticket = bet["betType"].split("｜", 1)
            stake = int(bet["stakeYen"])
            horses = {int(value) for value in bet["combination"].split("-") if value}
            payout = 100 if horses & set(race.get("refunds", set())) else float(race.get("payouts", {}).get(payout_key(ticket, bet["combination"]), 0))
            returned = round(stake / 100 * payout)
            row = aggregate[course]
            row["tickets"] += 1
            row["stakeYen"] += stake
            row["returnYen"] += returned
            row["monthly"][race["raceDate"][:7]][0] += stake
            row["monthly"][race["raceDate"][:7]][1] += returned
            race_returns[course] += returned
        for course in COURSES:
            row = aggregate[course]
            row["races"] += 1
            row["hitRaces"] += int(race_returns[course] > 0)
    result = {}
    for course, row in aggregate.items():
        stake = row["stakeYen"]
        monthly = {month: returned / monthly_stake * 100 if monthly_stake else 0 for month, (monthly_stake, returned) in row["monthly"].items()}
        result[course] = {
            "races": row["races"],
            "tickets": row["tickets"],
            "stakeYen": stake,
            "returnYen": row["returnYen"],
            "profitYen": row["returnYen"] - stake,
            "roiPct": row["returnYen"] / stake * 100 if stake else None,
            "hitRaces": row["hitRaces"],
            "hitRatePct": row["hitRaces"] / row["races"] * 100 if row["races"] else None,
            "monthlyRoiPct": monthly,
            "minimumMonthlyRoiPct": min(monthly.values()) if monthly else None,
            "targetStakePerRace": COURSE_TARGET_STAKES[course],
        }
    return result
