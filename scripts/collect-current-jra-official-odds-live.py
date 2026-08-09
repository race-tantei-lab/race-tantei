import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "collect-current-jra-official-odds-fast.py"
spec = importlib.util.spec_from_file_location("fast_odds_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("FAST_ODDS_BASE_IMPORT_FAILED")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def parse_win_complete(page: str):
    rows = base.runtime.parse_odds_rows(page, "単勝")
    by_horse = {}
    for combination, low, high in rows:
        try:
            horse = int(combination)
        except ValueError:
            continue
        if 1 <= horse <= 30:
            by_horse[horse] = (float(low), float(high))
    horses = sorted(by_horse)
    if len(horses) < 2:
        raise RuntimeError(f"WIN_HORSES_TOO_FEW:{len(horses)}")
    return horses, [(str(h), by_horse[h][0], by_horse[h][1]) for h in horses]


base.parse_win = parse_win_complete

if __name__ == "__main__":
    base.main()
