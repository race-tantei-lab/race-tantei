#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "scripts" / "research-evaluate-canonical-transfer-final.py"
TARGET_RACE_ID = "2026-08-09-niigata-12"
TARGET_DATE = "2026-08-09"

spec = importlib.util.spec_from_file_location("canonical_transfer_final", FINAL)
if spec is None or spec.loader is None:
    raise RuntimeError(f"MODULE_LOAD_FAILED:{FINAL}")
final = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = final
spec.loader.exec_module(final)
base = final.fast.base_mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--odds", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pmod = base.load_module(ROOT / "scripts" / "generate-final-preday-selection.py", "single_preday_bins")
    gen = base.load_module(ROOT / "scripts" / "generate-final-live-bets.py", "single_live_generator")
    demand_mod = base.load_module(ROOT / "scripts" / "research-ten-year-canonical-demand.py", "single_demand_helpers")
    rules = base.load_rules(ROOT / args.rules)
    rules_by_bet = base.group_rules(rules)

    odds_row = None
    with (ROOT / args.odds).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if str(row.get("raceId")) == TARGET_RACE_ID:
                    odds_row = row
                    break
    if odds_row is None:
        raise RuntimeError("TARGET_ODDS_NOT_FOUND")

    state = {
        "horse_hist": collections.defaultdict(lambda: collections.deque(maxlen=3)),
        "horse_starts": collections.Counter(),
        "jstats": collections.defaultdict(lambda: [0, 0]),
        "tstats": collections.defaultdict(lambda: [0, 0]),
    }

    current_date = None
    day_bundles = []
    target_bundle = None

    def finish_day(date, bundles):
        nonlocal target_bundle
        if not date:
            return False
        if date < TARGET_DATE:
            demand_mod.update_state_for_date(state, bundles)
            return False
        if date == TARGET_DATE:
            for bundle in bundles:
                if str((bundle.get("race") or {}).get("raceId") or "") == TARGET_RACE_ID:
                    target_bundle = bundle
                    return True
            return False
        return True

    with (ROOT / args.corpus).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            bundle = json.loads(line)
            date = str((bundle.get("race") or {}).get("raceDate") or "")
            if current_date is None:
                current_date = date
            if date != current_date:
                if finish_day(current_date, day_bundles):
                    break
                day_bundles = []
                current_date = date
            day_bundles.append(bundle)
        else:
            finish_day(current_date, day_bundles)

    if target_bundle is None and current_date == TARGET_DATE:
        finish_day(current_date, day_bundles)
    if target_bundle is None:
        raise RuntimeError("TARGET_BUNDLE_NOT_FOUND")

    chosen = base.build_tickets(demand_mod, pmod, gen, state, target_bundle, odds_row, rules_by_bet)
    payouts = base.payout_index(target_bundle)
    courses = {}
    for course, budget in base.COURSES.items():
        returned, rows = base.settle_course(gen, chosen, budget, payouts)
        courses[course] = {
            "stakeYen": budget,
            "returnYen": returned,
            "tickets": rows,
        }

    result = {
        "raceId": TARGET_RACE_ID,
        "raceDate": TARGET_DATE,
        "chosenTickets": len(chosen),
        "courses": courses,
        "syntheticOddsUsed": False,
        "targetRaceResultsUsedForSelection": False,
        "bettingEligibilitySource": "official_final_win_market",
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"raceId":TARGET_RACE_ID,"chosenTickets":len(chosen),"returns":{k:v["returnYen"] for k,v in courses.items()}},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
