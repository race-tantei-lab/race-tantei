#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "research-evaluate-canonical-transfer.py"
FAST_PATH = ROOT / "scripts" / "research-evaluate-canonical-transfer-fast.py"
DEMAND_PATH = ROOT / "scripts" / "research-ten-year-canonical-demand.py"
PREDAY_PATH = ROOT / "scripts" / "generate-final-preday-selection.py"
GEN_PATH = ROOT / "scripts" / "generate-final-live-bets.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--demand", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--odds", required=True)
    ap.add_argument("--repair")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    year = str(args.year)

    base = load(BASE_PATH, f"year_base_{year}")
    fast = load(FAST_PATH, f"year_fast_{year}")
    demand_mod = load(DEMAND_PATH, f"year_demand_{year}")
    pmod = load(PREDAY_PATH, f"year_preday_{year}")
    gen = load(GEN_PATH, f"year_gen_{year}")

    rules = base.load_rules(ROOT / args.rules)
    rules_by_bet = base.group_rules(rules)

    demand = {}
    for row in load_jsonl(ROOT / args.demand):
        if str(row.get("raceDate") or "").startswith(year + "-"):
            demand[str(row["raceId"])] = row
    if not demand:
        raise RuntimeError(f"NO_DEMAND_FOR_YEAR:{year}")

    odds = {}
    for row in load_jsonl(ROOT / args.odds):
        rid = str(row.get("raceId") or "")
        if rid and str(row.get("raceDate") or "").startswith(year + "-"):
            odds[rid] = row
    repaired_used = 0
    if args.repair and (ROOT / args.repair).exists():
        for row in load_jsonl(ROOT / args.repair):
            rid = str(row.get("raceId") or "")
            if rid in demand and str(row.get("raceDate") or "").startswith(year + "-"):
                odds[rid] = row
                repaired_used += 1

    demand_ids = set(demand)
    odds_ids = set(odds)
    missing = sorted(demand_ids - odds_ids)
    extra = sorted(odds_ids - demand_ids)

    state = {
        "horse_hist": collections.defaultdict(lambda: collections.deque(maxlen=3)),
        "horse_starts": collections.Counter(),
        "jstats": collections.defaultdict(lambda: [0, 0]),
        "tstats": collections.defaultdict(lambda: [0, 0]),
    }
    overall = {course: base.init_stat() for course in base.COURSES}
    return_rows = {course: [] for course in base.COURSES}
    errors = []
    seen = set()
    evaluated = 0

    def process_day(date, bundles):
        nonlocal evaluated
        for bundle in bundles:
            race = bundle.get("race") or {}
            rid = str(race.get("raceId") or "")
            if rid not in demand_ids:
                continue
            seen.add(rid)
            if rid not in odds:
                continue
            try:
                chosen = fast.fast_build_tickets(base, demand_mod, pmod, gen, state, bundle, odds[rid], rules_by_bet)
                payouts = base.payout_index(bundle)
                for course, budget in base.COURSES.items():
                    returned, rows = base.settle_course(gen, chosen, budget, payouts)
                    base.add_stat(overall[course], budget, returned, len(rows), returned > 0)
                    return_rows[course].append({"raceId": rid, "raceDate": date, "returnYen": returned})
                evaluated += 1
            except Exception as exc:
                errors.append({
                    "raceId": rid,
                    "raceDate": date,
                    "venue": race.get("venue"),
                    "raceNo": race.get("raceNo"),
                    "error": f"{type(exc).__name__}:{exc}",
                })
        demand_mod.update_state_for_date(state, bundles)

    current_date = None
    day = []
    with (ROOT / args.corpus).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            bundle = json.loads(line)
            date = str(bundle.get("race", {}).get("raceDate") or "")
            if date[:4] > year:
                break
            if current_date is None:
                current_date = date
            if date != current_date:
                process_day(current_date, day)
                day = []
                current_date = date
            day.append(bundle)
    if current_date is not None:
        process_day(current_date, day)

    missing_corpus = sorted(demand_ids - seen)
    courses = {}
    for course, budget in base.COURSES.items():
        stat = base.finalize_stat(overall[course])
        top = sorted(return_rows[course], key=lambda row: row["returnYen"], reverse=True)[:25]
        exact_selected_stake = len(demand_ids) * budget
        lower_bound_roi = round(100.0 * overall[course]["returnYen"] / exact_selected_stake, 4) if exact_selected_stake else None
        courses[course] = {
            **stat,
            "selectedDemandRaces": len(demand_ids),
            "missingOddsRaces": len(missing),
            "exactSelectedStakeYen": exact_selected_stake,
            "zeroReturnLowerBoundRoiPct": lower_bound_roi,
            "topRaceReturns": top,
        }

    result = {
        "purpose": "research_only_year_shard_canonical_297_transfer",
        "year": year,
        "sourceRuleCount": 297,
        "selectedDemandRaces": len(demand_ids),
        "oddsRaces": len(odds_ids),
        "repairedOddsRowsUsed": repaired_used,
        "missingOddsRaceCount": len(missing),
        "missingOddsRaceIds": missing,
        "extraOddsRaceCount": len(extra),
        "evaluatedRaces": evaluated,
        "evaluationErrorCount": len(errors),
        "evaluationErrors": errors,
        "missingDemandRacesInCorpus": missing_corpus,
        "courses": courses,
        "historicalFinalOddsUsed": True,
        "targetDayResultsUsedForSelection": False,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "year": year,
        "selected": len(demand_ids),
        "odds": len(odds_ids),
        "missing": len(missing),
        "evaluated": evaluated,
        "errors": len(errors),
        "roi": {course: courses[course]["roiPct"] for course in base.COURSES},
        "lowerBoundRoi": {course: courses[course]["zeroReturnLowerBoundRoiPct"] for course in base.COURSES},
    }, ensure_ascii=False), flush=True)
    if errors or missing_corpus:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
