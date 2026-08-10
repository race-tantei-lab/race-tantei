import importlib.util
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "scripts" / "final-rules-payload.py"
OUTPUT = ROOT / "analysis-results" / "research-rule-complexity-audit.json"
BET_TYPES = range(6)


def load_rules():
    spec = importlib.util.spec_from_file_location("research_final_rules", RULES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("RULES_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rules = module.load_rules()
    if len(rules) != 316:
        raise RuntimeError(f"RULE_COUNT_INVALID:{len(rules)}")
    return rules


def normalized_conditions(rule):
    return tuple(sorted((str(name), json.dumps(value, ensure_ascii=False, sort_keys=True)) for name, value in rule.get("conditions", [])))


def applicability(rule):
    bet_values = [int(value) for name, value in rule.get("conditions", []) if name == "bet"]
    return set(bet_values) if bet_values else set(BET_TYPES)


def non_bet_set(rule):
    return frozenset((str(name), json.dumps(value, ensure_ascii=False, sort_keys=True)) for name, value in rule.get("conditions", []) if name != "bet")


def score(rule):
    return float(rule.get("newScore", 0.0))


def main():
    rules = load_rules()
    exact_groups = defaultdict(list)
    for index, rule in enumerate(rules):
        exact_groups[normalized_conditions(rule)].append(index)
    exact_duplicate_groups = [indexes for indexes in exact_groups.values() if len(indexes) > 1]

    by_bet = defaultdict(list)
    for index, rule in enumerate(rules):
        for bet in applicability(rule):
            by_bet[bet].append(index)

    dominated_by_bet = defaultdict(list)
    for bet, indexes in by_bet.items():
        for candidate in indexes:
            candidate_set = non_bet_set(rules[candidate])
            candidate_score = score(rules[candidate])
            dominators = []
            for other in indexes:
                if other == candidate:
                    continue
                other_set = non_bet_set(rules[other])
                if other_set.issubset(candidate_set) and score(rules[other]) >= candidate_score:
                    strict = other_set != candidate_set or score(rules[other]) > candidate_score
                    if strict:
                        dominators.append(other)
            if dominators:
                dominators.sort(key=lambda idx: (len(non_bet_set(rules[idx])), -score(rules[idx]), idx))
                dominated_by_bet[candidate].append({"bet": bet, "dominator": dominators[0]})

    removable = []
    for index, rule in enumerate(rules):
        applicable = applicability(rule)
        dominated_bets = {row["bet"] for row in dominated_by_bet.get(index, [])}
        if applicable and applicable.issubset(dominated_bets):
            removable.append(index)

    condition_counts = [len(non_bet_set(rule)) for rule in rules]
    bet_counts = Counter()
    for rule in rules:
        for bet in applicability(rule):
            bet_counts[bet] += 1

    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceRuleCount": len(rules),
        "analysisType": "data_independent_semantic_dominance",
        "predictionDataUsed": False,
        "exactDuplicateGroupCount": len(exact_duplicate_groups),
        "exactDuplicateRuleCountBeyondFirst": sum(len(group) - 1 for group in exact_duplicate_groups),
        "semanticallyDominatedRuleCount": len(removable),
        "minimumRuleCountWithoutChangingMaxScoreSemantics": len(rules) - len(removable),
        "conditionCountPerRule": {
            "min": min(condition_counts),
            "max": max(condition_counts),
            "mean": statistics.mean(condition_counts),
            "median": statistics.median(condition_counts),
            "distribution": dict(sorted(Counter(condition_counts).items())),
        },
        "rulesApplicableByBetIndex": dict(sorted(bet_counts.items())),
        "removableRules": [
            {
                "ruleIndex": index,
                "score": score(rules[index]),
                "conditions": rules[index].get("conditions", []),
                "dominatedForBets": dominated_by_bet[index],
            }
            for index in removable
        ],
        "exactDuplicateGroups": exact_duplicate_groups,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sourceRuleCount": report["sourceRuleCount"],
        "semanticRemovable": report["semanticallyDominatedRuleCount"],
        "minimumWithoutSemanticChange": report["minimumRuleCountWithoutChangingMaxScoreSemantics"],
        "exactDuplicateGroups": report["exactDuplicateGroupCount"],
        "conditionDistribution": report["conditionCountPerRule"]["distribution"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
