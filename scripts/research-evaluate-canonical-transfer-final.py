#!/usr/bin/env python3
"""Final research wrapper: exact accelerated evaluator + pre-race scratch safety.

Historical runner_status can lag same-day scratches/exclusions. The official
final win market is the authoritative pre-race set of betting-eligible horses.
This wrapper removes only runners absent from that final official win market
before ticket generation. It never uses finish positions or payouts for this
filter and leaves chronological feature-state updates unchanged.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAST = ROOT / "scripts" / "research-evaluate-canonical-transfer-fast.py"

spec = importlib.util.spec_from_file_location("canonical_transfer_fast", FAST)
if spec is None or spec.loader is None:
    raise RuntimeError(f"MODULE_LOAD_FAILED:{FAST}")
fast = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fast
spec.loader.exec_module(fast)

_original_build = fast.exact_fast_build_tickets


def scratch_safe_build(demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet):
    official = odds_row.get("officialOdds") or {}
    win_map = official.get("win") or {}
    betting_horses = {
        int(horse)
        for horse, value in win_map.items()
        if str(horse).isdigit() and (fast.base_mod.midpoint(value) or 0) > 1
    }
    if len(betting_horses) < 3:
        rid = str((bundle.get("race") or {}).get("raceId") or "")
        raise RuntimeError(f"OFFICIAL_WIN_BETTING_HORSES_TOO_FEW:{rid}:{sorted(betting_horses)}")

    all_runners = list(bundle.get("runners") or [])
    runner_horses = {int(row["horseNo"]) for row in all_runners if row.get("horseNo") is not None}
    missing_rows = sorted(betting_horses - runner_horses)
    if missing_rows:
        rid = str((bundle.get("race") or {}).get("raceId") or "")
        raise RuntimeError(f"OFFICIAL_WIN_RUNNER_ROW_MISSING:{rid}:{missing_rows}")

    filtered = dict(bundle)
    filtered["runners"] = [
        row for row in all_runners
        if int(row.get("horseNo") or 0) in betting_horses
    ]
    return _original_build(demand_mod, pmod, gen, state, filtered, odds_row, rules_by_bet)


fast.base_mod.build_tickets = scratch_safe_build

if __name__ == "__main__":
    fast.base_mod.main()
