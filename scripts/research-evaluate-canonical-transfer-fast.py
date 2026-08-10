#!/usr/bin/env python3
"""Exact-behavior accelerator for the canonical ten-year transfer evaluator.

The chronological state, feature generation, market probabilities, ticket
selection, allocation, settlement and output all remain in the base evaluator.
Only rule matching is replaced by an equivalent integer-bitset matcher. A
large deterministic equivalence test runs before the first race is evaluated.
"""
import importlib.util
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


base = load_base()
_original_load_module = base.load_module
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


def _validate(rules_by_bet):
    token = id(rules_by_bet)
    if token in _validated:
        return
    if _original_rule_score is None:
        raise RuntimeError("ORIGINAL_RULE_SCORE_NOT_CAPTURED")
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
    _validate(rules_by_bet)
    return _fast_score(rules_by_bet, bet, vals, preday)


def patched_load_module(path, name):
    global _original_rule_score
    mod = _original_load_module(path, name)
    if Path(path).name == "generate-final-live-bets.py":
        _original_rule_score = mod.rule_score
        mod.rule_score = fast_rule_score
    return mod


base.load_module = patched_load_module

if __name__ == "__main__":
    base.main()
