#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = {"odds", "track", "weather", "mrank", "minpop", "maxpop", "popsum", "favcnt", "distort"}


def load_rules():
    path = ROOT / "scripts" / "final-rules-payload.py"
    spec = importlib.util.spec_from_file_location("canonical_rules_payload", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.load_rules()
    if len(rows) != 316:
        raise RuntimeError(f"CANONICAL_RULE_COUNT_INVALID:{len(rows)}")
    return rows


def normalized_conditions(rule, preday=False):
    pairs = []
    seen = {}
    for name, value in rule.get("conditions", []):
        name = str(name)
        if preday and name in UNKNOWN:
            continue
        if name in seen and seen[name] != value:
            return None
        seen[name] = value
        pairs.append((name, value))
    return frozenset(pairs)


def score(rule):
    return float(rule.get("newScore", 0.0))


def find_dominator(index, active, rules, preday):
    target_conditions = normalized_conditions(rules[index], preday=preday)
    if target_conditions is None:
        return None
    target_score = score(rules[index])
    candidates = []
    for j in active:
        if j == index:
            continue
        other_conditions = normalized_conditions(rules[j], preday=preday)
        if other_conditions is None:
            continue
        other_score = score(rules[j])
        if other_score + 1e-12 < target_score:
            continue
        if not other_conditions.issubset(target_conditions):
            continue
        # Avoid deleting both members of a same-score/same-condition cycle.
        if other_score == target_score and other_conditions == target_conditions and j > index:
            continue
        candidates.append((
            -other_score,
            len(other_conditions),
            j,
        ))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def prune_rules(rules):
    active = set(range(len(rules)))
    removed = []
    changed = True
    while changed:
        changed = False
        # More specific/lower-score rules are the natural first removals.
        order = sorted(
            active,
            key=lambda i: (
                score(rules[i]),
                -len(normalized_conditions(rules[i], preday=False) or ()),
                i,
            ),
        )
        for i in order:
            if i not in active:
                continue
            full_dom = find_dominator(i, active, rules, preday=False)
            pre_dom = find_dominator(i, active, rules, preday=True)
            if full_dom is None or pre_dom is None:
                continue
            removed.append({
                "sourceIndex": i,
                "score": score(rules[i]),
                "conditions": list(rules[i].get("conditions", [])),
                "fullDominatorIndex": full_dom,
                "predayDominatorIndex": pre_dom,
            })
            active.remove(i)
            changed = True
    survivors = sorted(active)
    return survivors, removed


def verify_behavior_equivalence(rules, survivors, removed):
    active = set(survivors)
    # Logical proof: every removed rule must still be dominated in both scoring modes
    # by a surviving rule. This is stronger than checking a finite sample of races.
    proofs = []
    for row in removed:
        i = int(row["sourceIndex"])
        full_dom = find_dominator(i, active | {i}, rules, preday=False)
        pre_dom = find_dominator(i, active | {i}, rules, preday=True)
        if full_dom is None or pre_dom is None:
            raise RuntimeError(f"PRUNING_PROOF_FAILED:{i}:{full_dom}:{pre_dom}")
        proofs.append({"sourceIndex": i, "fullDominatorIndex": full_dom, "predayDominatorIndex": pre_dom})
    return proofs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    args = ap.parse_args()

    rules = load_rules()
    survivors, removed = prune_rules(rules)
    proofs = verify_behavior_equivalence(rules, survivors, removed)

    if len(removed) != 19 or len(survivors) != 297:
        raise RuntimeError(f"EXPECTED_316_TO_297_BUT_GOT:{len(removed)}:{len(survivors)}")

    exact_groups = {}
    for i, rule in enumerate(rules):
        key = (tuple(sorted(normalized_conditions(rule, preday=False) or ())), score(rule))
        exact_groups.setdefault(key, []).append(i)
    exact_duplicates = [v for v in exact_groups.values() if len(v) > 1]

    out_rows = []
    for i in survivors:
        row = dict(rules[i])
        row["sourceIndex"] = i
        out_rows.append(row)

    out_path = ROOT / args.out
    meta_path = ROOT / args.meta
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "purpose": "research_only_behavior_equivalent_canonical_pruning",
        "sourceRuleCount": 316,
        "survivingRuleCount": len(survivors),
        "removedRuleCount": len(removed),
        "survivorSourceIndices": survivors,
        "removed": removed,
        "proofsAgainstSurvivingRules": proofs,
        "exactDuplicateGroups": exact_duplicates,
        "fullScoreBehaviorPreservedByLogicalDominance": True,
        "predayScoreBehaviorPreservedByLogicalDominance": True,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source": 316,
        "survivors": len(survivors),
        "removed": len(removed),
        "exactDuplicateGroups": len(exact_duplicates),
        "productionDatabaseWritten": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
