import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "generate-final-live-bets-snapshot.py"
spec = importlib.util.spec_from_file_location("final_live_snapshot", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("FINAL_LIVE_SNAPSHOT_IMPORT_FAILED")
wrapped = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wrapped
spec.loader.exec_module(wrapped)
base = wrapped.base

_original_history = base.history_features_remote


def history_features_remote_batched(collector, target, current_runners):
    out = {}
    for start in range(0, len(current_runners), 24):
        out.update(_original_history(collector, target, current_runners[start:start + 24]))
    return out


base.history_features_remote = history_features_remote_batched

if __name__ == "__main__":
    base.main()
