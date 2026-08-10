#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSES = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}
BET_TYPES = ["単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"]
EN = ["win", "umaren", "wide", "umatan", "trio", "trifecta"]
UNORDERED = {"馬連", "ワイド", "3連複"}
SPECS = [
    (0, "単勝", "win", 1, False),
    (1, "馬連", "umaren", 2, False),
    (2, "ワイド", "wide", 2, False),
    (3, "馬単", "umatan", 2, True),
    (4, "3連複", "trio", 3, False),
    (5, "3連単", "trifecta", 3, True),
]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_rules(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if len(rows) != 297:
        raise RuntimeError(f"RULE_COUNT_INVALID:{len(rows)}")
    return rows


def group_rules(rules):
    grouped = collections.defaultdict(list)
    for rule in rules:
        bet = next((value for name, value in rule.get("conditions", []) if name == "bet"), None)
        if bet is None:
            for bt in range(6):
                grouped[bt].append(rule)
        else:
            grouped[int(bet)].append(rule)
    return grouped


def midpoint(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        vals = []
        for x in value:
            try:
                vals.append(float(x))
            except Exception:
                pass
        return sum(vals) / len(vals) if vals else None
    try:
        return float(value)
    except Exception:
        return None


def load_odds_dir(path):
    odds = {}
    duplicate = []
    files = sorted(Path(path).glob("research-demanded-odds-*.jsonl"))
    for file in files:
        if file.name.endswith("-meta.jsonl"):
            continue
        with file.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                rid = str(row.get("raceId") or "")
                if not rid:
                    raise RuntimeError(f"ODDS_RACE_ID_MISSING:{file}")
                if rid in odds:
                    duplicate.append(rid)
                odds[rid] = row
    if duplicate:
        raise RuntimeError(f"DUPLICATE_ODDS_RACES:{duplicate[:20]}:count={len(duplicate)}")
    return odds, files


def payout_index(bundle):
    out = {}
    for row in bundle.get("payouts", []):
        bet = str(row.get("betType") or "")
        combo = str(row.get("combination") or "")
        if not bet or not combo:
            continue
        try:
            yen = int(row.get("payoutYen") or 0)
        except Exception:
            yen = 0
        if yen > 0:
            out[(bet, combo)] = max(out.get((bet, combo), 0), yen)
    return out


def period_key(date):
    year = int(date[:4])
    if date <= "2018-12-31":
        return "2016-08-10..2018"
    if year <= 2021:
        return "2019..2021"
    if year <= 2024:
        return "2022..2024"
    return "2025..2026-08-09"


def init_stat():
    return {
        "races": 0,
        "tickets": 0,
        "hitRaces": 0,
        "stakeYen": 0,
        "returnYen": 0,
    }


def add_stat(stat, stake, returned, tickets, hit):
    stat["races"] += 1
    stat["tickets"] += tickets
    stat["stakeYen"] += stake
    stat["returnYen"] += returned
    stat["hitRaces"] += int(hit)


def finalize_stat(stat):
    out = dict(stat)
    stake = stat["stakeYen"]
    out["profitYen"] = stat["returnYen"] - stake
    out["roiPct"] = round(100.0 * stat["returnYen"] / stake, 4) if stake else None
    out["hitRacePct"] = round(100.0 * stat["hitRaces"] / stat["races"], 4) if stat["races"] else None
    out["avgTicketsPerRace"] = round(stat["tickets"] / stat["races"], 4) if stat["races"] else None
    return out


def base_values(pmod, gen, race, n):
    venue = str(race.get("venue") or "")
    surface = str(race.get("surface") or "障害")
    distance = int(race.get("distanceM") or 0)
    race_no = int(race.get("raceNo") or 0)
    date = str(race.get("raceDate") or "")
    conditions = str(race.get("conditions") or "").replace("500万下", "1勝クラス").replace("1000万下", "2勝クラス").replace("1600万下", "3勝クラス")
    race_name = str(race.get("raceName") or "").replace("500万下", "1勝クラス").replace("1000万下", "2勝クラス").replace("1600万下", "3勝クラス")
    weather = race.get("weather")
    track = race.get("trackCondition")
    return {
        "venue": pmod.VENUE_MAP[venue],
        "surface": {"芝": 0, "ダート": 1, "障害": 2}.get(surface, 2),
        "dist": pmod.distbin(distance),
        "track": {"良": 0, "稍重": 1, "重": 2, "不良": 3}.get(track, -1),
        "weather": gen.weatherbin(weather) if weather in ("晴", "曇", "雨", "小雨", "雪", "小雪") else -1,
        "field": pmod.fieldbin(n),
        "raceNo": pmod.rnobin(race_no),
        "season": pmod.seasonbin(int(date[5:7])),
        "rclass": pmod.classbin(race_name, conditions),
        "direction": pmod.directionbin(venue, surface, distance, race.get("direction")),
    }


def active_runners(bundle):
    rows = [row for row in bundle.get("runners", []) if (row.get("runnerStatus") or "active") == "active"]
    rows.sort(key=lambda row: int(row.get("horseNo") or 0))
    return rows


def build_tickets(demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet):
    race = bundle["race"]
    rid = str(race["raceId"])
    runners = active_runners(bundle)
    hnos = [int(row["horseNo"]) for row in runners]
    n = len(hnos)
    if n < 3:
        raise RuntimeError(f"RUNNERS_TOO_FEW:{rid}:{n}")
    features = {
        int(row["horseNo"]): demand_mod.feature_tuple(pmod, state, rid, row)
        for row in runners
    }
    official = odds_row.get("officialOdds") or {}
    win_map = official.get("win") or {}
    win = []
    missing_win = []
    for horse in hnos:
        odd = midpoint(win_map.get(str(horse)))
        if odd is None or odd <= 1:
            missing_win.append(horse)
        win.append(odd)
    if missing_win:
        raise RuntimeError(f"WIN_ODDS_INCOMPLETE:{rid}:{missing_win}")
    raw = [1.0 / value for value in win]
    total = sum(raw)
    weights = [value / total for value in raw]
    pop_order = sorted(range(n), key=lambda i: (win[i], i))
    popularity = [0] * n
    for rank, i in enumerate(pop_order, 1):
        popularity[i] = rank
    pos_by_horse = {horse: i for i, horse in enumerate(hnos)}
    base = base_values(pmod, gen, race, n)
    tickets = []

    for bt, jp, en, k, ordered in SPECS:
        market = official.get(en) or {}
        if not market:
            continue
        theory = list(itertools.permutations(range(n), k) if ordered else itertools.combinations(range(n), k))
        rows = []
        for positions in theory:
            horses = [hnos[i] for i in positions]
            combo = "-".join(str(x) for x in (sorted(horses) if jp in UNORDERED else horses))
            odd = midpoint(market.get(combo))
            if odd is not None and odd > 1:
                rows.append((positions, horses, combo, float(odd)))
        rows_sorted = sorted(enumerate(rows), key=lambda item: (item[1][3], item[0]))
        rank_by_index = {original: rank for rank, (original, _) in enumerate(rows_sorted, 1)}
        for idx, (positions, horses, combo, odd) in enumerate(rows):
            fs = [features[horse] for horse in horses]
            pops = [popularity[pos_by_horse[horse]] for horse in horses]
            market_probability = gen.market_prob(positions, en, weights)
            assumed = gen.PAYOUT_RATIO[en] / max(market_probability, 1e-15)
            ratio = odd / assumed
            vals = dict(base)
            vals.update({
                "bet": bt,
                "odds": gen.bsearch(gen.ODDS_EDGES, odd),
                "mrank": gen.market_rank_bin(rank_by_index[idx]),
                "minpop": gen.minpop_bin(min(pops)),
                "maxpop": gen.maxpop_bin(max(pops)),
                "popsum": gen.popsum_bin(sum(pops)),
                "favcnt": min(3, sum(1 for value in pops if value <= 1)),
                "distort": gen.bsearch(gen.DISTORT_EDGES, ratio),
                "goodcnt": min(3, sum(1 for row in fs if row[0] >= 3)),
                "bestform": max(row[0] for row in fs),
                "bestspeed": max(row[1] for row in fs),
                "bestj": max(row[2] for row in fs),
                "bestt": max(row[3] for row in fs),
                "expcnt": min(3, sum(1 for row in fs if row[4] >= 2)),
                "top3lastsum": min(7, sum(row[5] for row in fs)),
            })
            full = gen.rule_score(rules_by_bet, bt, vals, False)
            pre = gen.rule_score(rules_by_bet, bt, vals, True)
            if full > 0 or pre > 0:
                tickets.append({
                    "bet": bt,
                    "betType": jp,
                    "horses": horses,
                    "combo": combo,
                    "odds": odd,
                    "oddsBin": vals["odds"],
                    "full": full,
                    "pre": pre,
                })
    chosen = gen.select_tickets(tickets)
    return chosen


def settle_course(gen, chosen, budget, payouts):
    units = gen.allocate([ticket["oddsBin"] for ticket in chosen], budget // 100)
    returned = 0
    rows = []
    for ticket, unit in zip(chosen, units):
        stake = unit * 100
        payout_per_100 = payouts.get((ticket["betType"], ticket["combo"]), 0)
        ticket_return = unit * payout_per_100
        returned += ticket_return
        rows.append({
            "betType": ticket["betType"],
            "combination": ticket["combo"],
            "stakeYen": stake,
            "returnYen": ticket_return,
            "historicalFinalOdds": ticket["odds"],
            "fullScore": ticket["full"],
            "predayScore": ticket["pre"],
        })
    if sum(row["stakeYen"] for row in rows) != budget:
        raise RuntimeError(f"BUDGET_ALLOCATION_INVALID:{budget}:{rows}")
    return returned, rows


def concentration(rows, total_return):
    ordered = sorted(rows, key=lambda row: row["returnYen"], reverse=True)
    def pct(n):
        return round(100.0 * sum(row["returnYen"] for row in ordered[:n]) / total_return, 4) if total_return else 0.0
    return {
        "largestRaceReturnYen": ordered[0]["returnYen"] if ordered else 0,
        "largestRaceId": ordered[0]["raceId"] if ordered else None,
        "top1ReturnSharePct": pct(1),
        "top5ReturnSharePct": pct(5),
        "top10ReturnSharePct": pct(10),
        "top25ReturnSharePct": pct(25),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--demand", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pmod = load_module(ROOT / "scripts" / "generate-final-preday-selection.py", "transfer_preday_bins")
    gen = load_module(ROOT / "scripts" / "generate-final-live-bets.py", "transfer_live_generator")
    demand_mod = load_module(ROOT / "scripts" / "research-ten-year-canonical-demand.py", "transfer_demand_helpers")
    rules = load_rules(ROOT / args.rules)
    rules_by_bet = group_rules(rules)

    demand = {}
    with (ROOT / args.demand).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            demand[str(row["raceId"])] = row
    odds, odds_files = load_odds_dir(ROOT / args.odds_dir)
    demand_ids = set(demand)
    odds_ids = set(odds)
    missing_odds = sorted(demand_ids - odds_ids)
    extra_odds = sorted(odds_ids - demand_ids)

    state = {
        "horse_hist": collections.defaultdict(lambda: collections.deque(maxlen=3)),
        "horse_starts": collections.Counter(),
        "jstats": collections.defaultdict(lambda: [0, 0]),
        "tstats": collections.defaultdict(lambda: [0, 0]),
    }
    overall = {course: init_stat() for course in COURSES}
    yearly = {course: collections.defaultdict(init_stat) for course in COURSES}
    periods = {course: collections.defaultdict(init_stat) for course in COURSES}
    return_rows = {course: [] for course in COURSES}
    race_records = []
    evaluation_errors = []
    selected_seen = set()

    current_date = None
    day_bundles = []

    def process_day(date, bundles):
        if not date:
            return
        for bundle in bundles:
            race = bundle.get("race") or {}
            rid = str(race.get("raceId") or "")
            if rid not in demand_ids:
                continue
            selected_seen.add(rid)
            if rid not in odds:
                continue
            try:
                chosen = build_tickets(demand_mod, pmod, gen, state, bundle, odds[rid], rules_by_bet)
                payouts = payout_index(bundle)
                record = {
                    "raceId": rid,
                    "raceDate": date,
                    "venue": race.get("venue"),
                    "raceNo": race.get("raceNo"),
                    "chosenTickets": len(chosen),
                    "courses": {},
                }
                for course, budget in COURSES.items():
                    returned, rows = settle_course(gen, chosen, budget, payouts)
                    hit = returned > 0
                    add_stat(overall[course], budget, returned, len(rows), hit)
                    add_stat(yearly[course][date[:4]], budget, returned, len(rows), hit)
                    add_stat(periods[course][period_key(date)], budget, returned, len(rows), hit)
                    return_rows[course].append({"raceId": rid, "raceDate": date, "returnYen": returned})
                    record["courses"][course] = {
                        "stakeYen": budget,
                        "returnYen": returned,
                        "tickets": rows,
                    }
                race_records.append(record)
            except Exception as exc:
                evaluation_errors.append({
                    "raceId": rid,
                    "raceDate": date,
                    "venue": race.get("venue"),
                    "raceNo": race.get("raceNo"),
                    "error": f"{type(exc).__name__}:{exc}",
                })
        demand_mod.update_state_for_date(state, bundles)

    with (ROOT / args.corpus).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            bundle = json.loads(line)
            date = str(bundle.get("race", {}).get("raceDate") or "")
            if current_date is None:
                current_date = date
            if date != current_date:
                process_day(current_date, day_bundles)
                day_bundles = []
                current_date = date
            day_bundles.append(bundle)
    if current_date is not None:
        process_day(current_date, day_bundles)

    missing_in_corpus = sorted(demand_ids - selected_seen)
    odds_complete = not missing_odds
    evaluation_complete = not evaluation_errors and not missing_in_corpus and len(race_records) == len(demand_ids)
    courses = {}
    all_three_pass = True
    for course in COURSES:
        finalized = finalize_stat(overall[course])
        pass200 = bool(finalized["roiPct"] is not None and finalized["roiPct"] >= 200.0)
        all_three_pass = all_three_pass and pass200
        courses[course] = {
            **finalized,
            "pass200": pass200,
            "byYear": {year: finalize_stat(stat) for year, stat in sorted(yearly[course].items())},
            "byPeriod": {period: finalize_stat(stat) for period, stat in periods[course].items()},
            "returnConcentration": concentration(return_rows[course], overall[course]["returnYen"]),
        }

    hard_gate_eligible = odds_complete and evaluation_complete
    result = {
        "purpose": "research_only_canonical_297_ten_year_transfer_diagnostic",
        "warning": "Retrospective transfer diagnostic only. The canonical family was developed using 2024-2026 data, historical odds are final odds rather than 15-45 minute pre-start snapshots, and historical weather/track fields are result-record conditions.",
        "evaluationStart": "2016-08-10",
        "evaluationEnd": "2026-08-09",
        "sourceRuleCount": 297,
        "selectedDemandRaces": len(demand_ids),
        "oddsFiles": [file.name for file in odds_files],
        "oddsRaces": len(odds_ids),
        "missingOddsRaceCount": len(missing_odds),
        "missingOddsRaceIds": missing_odds,
        "extraOddsRaceCount": len(extra_odds),
        "extraOddsRaceIds": extra_odds[:100],
        "missingDemandRacesInCorpus": missing_in_corpus,
        "evaluationErrorCount": len(evaluation_errors),
        "evaluationErrors": evaluation_errors,
        "evaluatedRaces": len(race_records),
        "courses": courses,
        "hardGateEligible": hard_gate_eligible,
        "allThreeCoursesAtLeast200Pct": bool(hard_gate_eligible and all_three_pass),
        "historicalFinalOddsUsed": True,
        "prestartTimingValidationPerformed": False,
        "targetDayResultsUsedForSelection": False,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selectedDemandRaces": len(demand_ids),
        "oddsRaces": len(odds_ids),
        "missingOddsRaceCount": len(missing_odds),
        "evaluationErrorCount": len(evaluation_errors),
        "evaluatedRaces": len(race_records),
        "hardGateEligible": hard_gate_eligible,
        "allThreeCoursesAtLeast200Pct": result["allThreeCoursesAtLeast200Pct"],
        "roi": {course: courses[course]["roiPct"] for course in COURSES},
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
