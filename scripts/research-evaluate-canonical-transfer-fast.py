#!/usr/bin/env python3
"""Exact-behavior accelerator for the canonical ten-year transfer evaluator.

The base evaluator remains authoritative. This wrapper applies two proven-safe
optimizations only:
1) exact rule matching via integer bitsets, verified against the original matcher;
2) skip expensive order-specific calculations for a horse set when its preday
   score is zero. All rule scores are strictly positive, and preday matching is
   the same full rule match with UNKNOWN fields ignored, so full>0 implies pre>0.
All race state, odds ranking, probabilities, ticket selection, allocation,
settlement and result output otherwise use the same formulas and ordering.
"""
import importlib.util
import itertools
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "research-evaluate-canonical-transfer.py"
UNKNOWN = {"odds", "track", "weather", "mrank", "minpop", "maxpop", "popsum", "favcnt", "distort"}


def load_base():
    spec = importlib.util.spec_from_file_location("canonical_transfer_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{BASE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


base_mod = load_base()
_original_load_module = base_mod.load_module
_original_rule_score = None
_cache = {}
_validated = set()


def _normalized_conditions(rule, preday):
    seen = {}
    for name, value in rule.get("conditions", []):
        if preday and name in UNKNOWN:
            continue
        if name in seen and seen[name] != value:
            return None
        seen[name] = value
    return tuple(seen.items())


def _compile(rules_by_bet, bet, preday):
    rows = list(rules_by_bet.get(bet, []))
    conditions = [_normalized_conditions(rule, preday) for rule in rows]
    fields = sorted({name for cond in conditions if cond is not None for name, _ in cond})
    omit = {name: 0 for name in fields}
    value_masks = {name: {} for name in fields}
    possible = 0
    for idx, cond in enumerate(conditions):
        bit = 1 << idx
        if cond is None:
            continue
        possible |= bit
        cdict = dict(cond)
        for name in fields:
            if name not in cdict:
                omit[name] |= bit
            else:
                value = cdict[name]
                value_masks[name][value] = value_masks[name].get(value, 0) | bit
    scores = sorted(
        ((float(rule["newScore"]), idx) for idx, rule in enumerate(rows)),
        key=lambda row: (-row[0], row[1]),
    )
    return possible, fields, omit, value_masks, scores


def _fast_score(rules_by_bet, bet, vals, preday=False):
    key = (id(rules_by_bet), int(bet), bool(preday))
    compiled = _cache.get(key)
    if compiled is None:
        compiled = _compile(rules_by_bet, int(bet), bool(preday))
        _cache[key] = compiled
    mask, fields, omit, value_masks, scores = compiled
    for name in fields:
        mask &= omit[name] | value_masks[name].get(vals.get(name), 0)
        if not mask:
            return 0.0
    for score, idx in scores:
        if mask & (1 << idx):
            return score
    return 0.0


def _validate_matcher(rules_by_bet):
    token = id(rules_by_bet)
    if token in _validated:
        return
    if _original_rule_score is None:
        raise RuntimeError("ORIGINAL_RULE_SCORE_NOT_CAPTURED")
    all_scores = [float(rule["newScore"]) for rows in rules_by_bet.values() for rule in rows]
    if not all_scores or min(all_scores) <= 0:
        raise AssertionError(f"NONPOSITIVE_RULE_SCORE:{min(all_scores) if all_scores else None}")
    rng = random.Random(20260811)
    tested = 0
    for bet in range(6):
        rows = list(rules_by_bet.get(bet, []))
        domains = {}
        for rule in rows:
            for name, value in rule.get("conditions", []):
                domains.setdefault(name, set()).add(value)
        names = sorted(domains)
        choices = {
            name: [None, *sorted(values, key=lambda x: (str(type(x)), str(x)))]
            for name, values in domains.items()
        }
        tests = []
        for rule in rows:
            vals = {name: value for name, value in rule.get("conditions", [])}
            vals["bet"] = bet
            tests.append(vals)
            field = next((name for name in names if name != "bet" and name in vals), None)
            if field is not None:
                alt = next((x for x in choices[field] if x != vals[field]), None)
                if alt is not None:
                    changed = dict(vals)
                    changed[field] = alt
                    tests.append(changed)
        for _ in range(1600):
            vals = {name: rng.choice(choices[name]) for name in names}
            vals["bet"] = bet
            tests.append(vals)
        for preday in (False, True):
            for vals in tests:
                slow = float(_original_rule_score(rules_by_bet, bet, vals, preday))
                fast = float(_fast_score(rules_by_bet, bet, vals, preday))
                tested += 1
                if abs(slow - fast) > 1e-12:
                    raise AssertionError(f"FAST_RULE_MATCH_MISMATCH:{bet}:{preday}:{slow}:{fast}:{vals}")
    _validated.add(token)
    print(f"FAST_RULE_MATCHER_EQUIVALENCE:success tests={tested}", flush=True)


def fast_rule_score(rules_by_bet, bet, vals, preday=False):
    _validate_matcher(rules_by_bet)
    return _fast_score(rules_by_bet, bet, vals, preday)


def exact_fast_build_tickets(demand_mod, pmod, gen, state, bundle, odds_row, rules_by_bet):
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
    race_base = base_mod.base_values(pmod, gen, race, n)
    tickets = []

    for bt, jp, en, k, ordered in base_mod.SPECS:
        market = official.get(en) or {}
        if not market:
            continue

        # Preserve the base evaluator's exact market-rank ordering: theoretical
        # combination order first, invalid/null odds skipped, then stable sort by odds.
        theory = itertools.permutations(range(n), k) if ordered else itertools.combinations(range(n), k)
        ranked_rows = []
        for positions in theory:
            horses = [hnos[i] for i in positions]
            combo = "-".join(str(x) for x in (sorted(horses) if jp in base_mod.UNORDERED else horses))
            odd = base_mod.midpoint(market.get(combo))
            if odd is not None and odd > 1:
                ranked_rows.append((tuple(positions), combo, float(odd)))
        ranked_order = sorted(enumerate(ranked_rows), key=lambda item: (item[1][2], item[0]))
        rank_by_combo = {row[1][1]: rank for rank, row in enumerate(ranked_order, 1)}

        # Preday-visible runner aggregates are symmetric in horse order. Compute
        # them once per horse set and skip all permutations when preday score=0.
        for position_set in itertools.combinations(range(n), k):
            set_horses = [hnos[i] for i in position_set]
            fs = [features[horse] for horse in set_horses]
            known_vals = dict(race_base)
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
            pre = gen.rule_score(rules_by_bet, bt, known_vals, True)
            if pre <= 0:
                continue

            orders = itertools.permutations(position_set, k) if ordered else (position_set,)
            for positions in orders:
                horses = [hnos[i] for i in positions]
                combo = "-".join(str(x) for x in (sorted(horses) if jp in base_mod.UNORDERED else horses))
                odd = base_mod.midpoint(market.get(combo))
                if odd is None or odd <= 1:
                    continue
                market_rank = rank_by_combo.get(combo)
                if market_rank is None:
                    raise RuntimeError(f"FAST_MARKET_RANK_MISSING:{rid}:{bt}:{combo}")
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
                canonical_pre = gen.rule_score(rules_by_bet, bt, vals, True)
                if abs(canonical_pre - pre) > 1e-12:
                    raise RuntimeError(f"FAST_PREDAY_INVARIANCE_MISMATCH:{rid}:{bt}:{combo}:{canonical_pre}:{pre}")
                if full > 0 or pre > 0:
                    tickets.append({
                        "bet": bt,
                        "betType": jp,
                        "horses": horses,
                        "combo": combo,
                        "odds": float(odd),
                        "oddsBin": vals["odds"],
                        "full": full,
                        "pre": pre,
                    })
    return gen.select_tickets(tickets)


def patched_load_module(path, name):
    global _original_rule_score
    mod = _original_load_module(path, name)
    if Path(path).name == "generate-final-live-bets.py":
        _original_rule_score = mod.rule_score
        mod.rule_score = fast_rule_score
    return mod


base_mod.load_module = patched_load_module
base_mod.build_tickets = exact_fast_build_tickets

if __name__ == "__main__":
    base_mod.main()
