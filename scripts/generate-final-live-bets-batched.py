import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "generate-final-live-bets.py"
spec = importlib.util.spec_from_file_location("final_live_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("FINAL_LIVE_BASE_IMPORT_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

_original = base.history_features_remote


def history_features_remote_batched(collector, target, current_runners):
    # Cloudflare D1 rejects oversized bind lists. 24 runners keeps the horse,
    # jockey and trainer parameter sets comfortably below the REST bind limit.
    out = {}
    for start in range(0, len(current_runners), 24):
        chunk = current_runners[start : start + 24]
        out.update(_original(collector, target, chunk))
    return out


base.history_features_remote = history_features_remote_batched

if __name__ == "__main__":
    base.main()
