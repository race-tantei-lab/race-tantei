import importlib.util
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BATCHED_PATH = ROOT / "scripts" / "generate-final-live-bets-batched.py"
STATE_KEY = "final_rule_learning:state"

spec = importlib.util.spec_from_file_location("final_live_batched", BATCHED_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("FINAL_LIVE_BATCHED_IMPORT_FAILED")
batched = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = batched
spec.loader.exec_module(batched)
base = batched.base
_original_rule_score = base.rule_score


def load_learning_state():
    try:
        collector = base.load_collector(ROOT)
        rows = collector.d1_query(
            "SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1",
            [STATE_KEY],
        )
        if not rows:
            return {"buckets": {}}
        state = json.loads(str(rows[0].get("value") or "{}"))
        return state if isinstance(state, dict) else {"buckets": {}}
    except Exception:
        return {"buckets": {}}


LEARNING_STATE = load_learning_state()
BUCKETS = LEARNING_STATE.get("buckets") if isinstance(LEARNING_STATE.get("buckets"), dict) else {}


def bucket_factor(key, maximum_weight):
    row = BUCKETS.get(key)
    if not isinstance(row, dict):
        return 0.0
    try:
        factor = float(row.get("factor", 1.0))
        samples = int(row.get("samples", 0))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(factor) or samples <= 0:
        return 0.0
    evidence = min(1.0, samples / 20.0)
    return maximum_weight * evidence * math.log(max(0.50, min(1.50, factor)))


def learning_factor(vals, bet):
    try:
        venue = int(vals.get("venue"))
        odds = int(vals.get("odds"))
        bet = int(bet)
    except (TypeError, ValueError):
        return 1.0

    log_adjustment = 0.0
    log_adjustment += bucket_factor(f"b:{bet}", 0.40)
    log_adjustment += bucket_factor(f"b:{bet}|v:{venue}", 0.20)
    log_adjustment += bucket_factor(f"b:{bet}|o:{odds}", 0.25)
    log_adjustment += bucket_factor(f"b:{bet}|v:{venue}|o:{odds}", 0.15)
    return max(0.80, min(1.20, math.exp(log_adjustment)))


def learned_rule_score(rules_by_bet, bet, vals, preday=False):
    score = float(_original_rule_score(rules_by_bet, bet, vals, preday))
    if score <= 0:
        return score
    return score * learning_factor(vals, bet)


base.rule_score = learned_rule_score


if __name__ == "__main__":
    base.main()
