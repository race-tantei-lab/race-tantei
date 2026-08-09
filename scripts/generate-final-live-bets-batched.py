import importlib.util
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "generate-final-live-bets.py"
STATE_KEY = "final_rule_learning:state"

spec = importlib.util.spec_from_file_location("final_live_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("FINAL_LIVE_BASE_IMPORT_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

_original_history_features_remote = base.history_features_remote
_original_rule_score = base.rule_score


def history_features_remote_batched(collector, target, current_runners):
    # Cloudflare D1 rejects oversized bind lists. 24 runners keeps the horse,
    # jockey and trainer parameter sets comfortably below the REST bind limit.
    out = {}
    for start in range(0, len(current_runners), 24):
        chunk = current_runners[start : start + 24]
        out.update(_original_history_features_remote(collector, target, chunk))
    return out


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


def bucket_log_adjustment(key, maximum_weight):
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
        bet = int(bet)
        venue = int(vals.get("venue"))
        odds = int(vals.get("odds"))
    except (TypeError, ValueError):
        return 1.0

    adjustment = 0.0
    adjustment += bucket_log_adjustment(f"b:{bet}", 0.40)
    adjustment += bucket_log_adjustment(f"b:{bet}|v:{venue}", 0.20)
    adjustment += bucket_log_adjustment(f"b:{bet}|o:{odds}", 0.25)
    adjustment += bucket_log_adjustment(f"b:{bet}|v:{venue}|o:{odds}", 0.15)
    return max(0.80, min(1.20, math.exp(adjustment)))


def learned_rule_score(rules_by_bet, bet, vals, preday=False):
    score = float(_original_rule_score(rules_by_bet, bet, vals, preday))
    if score <= 0:
        return score
    return score * learning_factor(vals, bet)


base.history_features_remote = history_features_remote_batched
base.rule_score = learned_rule_score

if __name__ == "__main__":
    base.main()
