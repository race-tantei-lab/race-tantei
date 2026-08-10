#!/usr/bin/env python3
import importlib.util
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "research-evaluate-canonical-transfer.py"


def load_base():
    spec = importlib.util.spec_from_file_location("canonical_transfer_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{BASE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def fast_build_tickets(base_mod, demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet):
    race = bundle["race"]
    rid = str(race["raceId"])
    runners = base_mod.active_runners(bundle)
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
        odd = base_mod.midpoint(win_map.get(str(horse)))
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
    base = base_mod.base_values(pmod, gen, race, n)
    tickets = []

    for bt, jp, en, k, ordered in base_mod.SPECS:
        market = official.get(en) or {}
        if not market:
            continue

        # Build market ranks once from official rows. This is behavior-equivalent
        # to sorting the original theoretical rows by (odds, theory-order index),
        # because itertools combinations/permutations are lexicographic in runner positions.
        ranked = []
        for combo, value in market.items():
            odd = base_mod.midpoint(value)
            if odd is None or odd <= 1:
                continue
            try:
                horses = tuple(int(x) for x in str(combo).split("-"))
            except Exception:
                continue
            if len(horses) != k or len(set(horses)) != k or any(h not in pos_by_horse for h in horses):
                continue
            if jp in base_mod.UNORDERED:
                horses = tuple(sorted(horses))
            positions = tuple(pos_by_horse[h] for h in horses)
            if not ordered:
                positions = tuple(sorted(positions))
            norm_combo = "-".join(str(x) for x in horses)
            ranked.append((float(odd), positions, norm_combo))
        ranked.sort(key=lambda row: (row[0], row[1]))
        rank_by_combo = {combo: rank for rank, (_, _, combo) in enumerate(ranked, 1)}

        candidate_rules = demand_mod.prefilter_rules(rules_by_bet.get(bt, []), base, bt)
        if not candidate_rules:
            continue

        # Full-score positive implies preday-score positive because preday mode only
        # removes UNKNOWN predicates. Therefore we first test unordered horse sets
        # against known predicates, and only then expand orders for exacta/trifecta.
        for position_set in itertools.combinations(range(n), k):
            horses_set = tuple(hnos[i] for i in position_set)
            fs = [features[horse] for horse in horses_set]
            known_vals = dict(base)
            known_vals.update({
                "bet": bt,
                "goodcnt": min(3, sum(1 for row in fs if row[0] >= 3)),
                "bestform": max(row[0] for row in fs),
                "bestspeed": max(row[1] for row in fs),
                "bestj": max(row[2] for row in fs),
                "bestt": max(row[3] for row in fs),
                "expcnt": min(3, sum(1 for row in fs if row[4] >= 2)),
                "top3lastsum": min(7, sum(row[5] for row in fs)),
            })
            pre = 0.0
            for rule in candidate_rules:
                if demand_mod.rule_matches_preday(rule, known_vals):
                    pre = max(pre, float(rule.get("newScore", 0.0)))
            if pre <= 0:
                continue

            orders = itertools.permutations(position_set, k) if ordered else (position_set,)
            for positions in orders:
                horses = tuple(hnos[i] for i in positions)
                combo_horses = tuple(sorted(horses)) if jp in base_mod.UNORDERED else horses
                combo = "-".join(str(x) for x in combo_horses)
                odd = base_mod.midpoint(market.get(combo))
                if odd is None or odd <= 1:
                    continue
                market_rank = rank_by_combo.get(combo)
                if market_rank is None:
                    continue
                pops = [popularity[pos_by_horse[horse]] for horse in horses]
                market_probability = gen.market_prob(tuple(positions), en, weights)
                assumed = gen.PAYOUT_RATIO[en] / max(market_probability, 1e-15)
                ratio = float(odd) / assumed
                vals = dict(known_vals)
                vals.update({
                    "odds": gen.bsearch(gen.ODDS_EDGES, float(odd)),
                    "mrank": gen.market_rank_bin(market_rank),
                    "minpop": gen.minpop_bin(min(pops)),
                    "maxpop": gen.maxpop_bin(max(pops)),
                    "popsum": gen.popsum_bin(sum(pops)),
                    "favcnt": min(3, sum(1 for value in pops if value <= 1)),
                    "distort": gen.bsearch(gen.DISTORT_EDGES, ratio),
                })
                full = gen.rule_score(rules_by_bet, bt, vals, False)
                # Assert the optimization invariant on every retained ticket.
                canonical_pre = gen.rule_score(rules_by_bet, bt, vals, True)
                if abs(canonical_pre - pre) > 1e-9:
                    raise RuntimeError(f"FAST_PREDAY_SCORE_MISMATCH:{rid}:{bt}:{combo}:{canonical_pre}:{pre}")
                tickets.append({
                    "bet": bt,
                    "betType": jp,
                    "horses": list(horses),
                    "combo": combo,
                    "odds": float(odd),
                    "oddsBin": vals["odds"],
                    "full": full,
                    "pre": pre,
                })

    return gen.select_tickets(tickets)


def main():
    base_mod = load_base()
    base_mod.build_tickets = lambda demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet: fast_build_tickets(
        base_mod, demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet
    )
    base_mod.main()


if __name__ == "__main__":
    main()
