import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

SOURCE = Path(__file__).with_name("official-odds-roi200-policy.py")
spec = importlib.util.spec_from_file_location("official_odds_roi200_policy_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("OFFICIAL_ODDS_POLICY_BASE_LOAD_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

for name in dir(base):
    if not name.startswith("__"):
        globals()[name] = getattr(base, name)

MODEL_VERSION = "v14.1-official-odds-constrained-roi200"
OFFICIAL_ODDS_SOURCE = "jra_official"


def selected_race_ids(races):
    grouped = defaultdict(list)
    for race in races:
        if race.get("oddsSource") != OFFICIAL_ODDS_SOURCE:
            continue
        if race.get("officialOdds"):
            grouped[(race["raceDate"], race["venue"])].append(race)

    selected = set()
    incomplete_groups = []
    for key, group in sorted(grouped.items()):
        complete = []
        for race in group:
            summary = plans_for_race(race)
            if summary is None:
                continue
            race["officialOddsRoi200Summary"] = summary
            complete.append(race)
        complete.sort(
            key=lambda race: (
                -race["officialOddsRoi200Summary"]["jointProjectedRoiPct"],
                int(race.get("raceNo") or 99),
            )
        )
        if len(complete) < MINIMUM_RACES_PER_VENUE_DAY:
            incomplete_groups.append(
                {
                    "date": key[0],
                    "venue": key[1],
                    "completeOfficialOddsRaces": len(complete),
                }
            )
            continue
        take = min(MAXIMUM_RACES_PER_VENUE_DAY, len(complete))
        selected.update(race["raceId"] for race in complete[:take])

    if incomplete_groups:
        return set()
    return selected


def build_bets(race):
    if race.get("oddsSource") != OFFICIAL_ODDS_SOURCE:
        return []
    summary = race.get("officialOddsRoi200Summary") or plans_for_race(race)
    if not summary:
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
