import gzip
import importlib.util
import json
import pathlib
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAST = ROOT / "scripts" / "collect-current-jra-official-odds-fast.py"
spec = importlib.util.spec_from_file_location("aug9_fast_odds", FAST)
if spec is None or spec.loader is None:
    raise RuntimeError("FAST_ODDS_IMPORT_FAILED")
fast = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fast
spec.loader.exec_module(fast)

runtime = fast.runtime
base = fast.base
OUT = ROOT / "aug9-all-selected-official-odds.json.gz"
REPORT = ROOT / "analysis-results" / "aug9-all-selected-official-odds-report.json"


def parse_win_complete(page: str):
    rows = runtime.parse_odds_rows(page, "単勝")
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


def main() -> None:
    target_ids = sorted(fast.selected_ids())
    placeholders = ",".join("?" for _ in target_ids)
    races = base.d1_query(
        f"""
        SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo,
               start_time_utc AS startTimeUtc, entry_url AS entryUrl
        FROM rt_races
        WHERE race_id IN ({placeholders})
        ORDER BY venue, race_no
        """,
        target_ids,
    )
    if len(races) != 15:
        raise RuntimeError(f"AUG9_SELECTED_RACES_MISSING:{len(races)}")

    captured = datetime.now(timezone.utc)
    captured_iso = captured.isoformat()
    records = {}
    errors = []
    entry_pages = 0
    odds_pages = 0
    counts = defaultdict(int)
    covered = defaultdict(set)

    for race in races:
        entry_url = race.get("entryUrl")
        if not entry_url:
            errors.append(f"RACE:{race['raceId']}:ENTRY_URL_MISSING")
            continue
        digits = str(race["raceDate"]).replace("-", "")
        race_no = int(race["raceNo"])
        try:
            entry_html = runtime.fetch_url(entry_url)
            entry_pages += 1
            entry_actions = [c for c, _ in base.action_links(entry_html) if fast.same_race_link(c, digits, race_no)]
            win_seeds = [c for c in entry_actions if c.startswith(fast.TYPE_PREFIX["単勝"])]
            if not win_seeds:
                raise RuntimeError("WIN_CNAME_NOT_FOUND")
            win_cname = win_seeds[0]
            win_page = runtime.fetch_url(base.JRA_ODDS_URL, cname=win_cname, referer=entry_url)
            odds_pages += 1
            _, win_rows = parse_win_complete(win_page)
            fast.add_records(records, race, "単勝", win_cname, win_page, win_rows, captured_iso, captured)

            cnames = fast.find_type_cnames(win_page, digits, race_no)
            for bet_type in ["馬連", "ワイド", "馬単", "3連複", "3連単"]:
                cname = cnames.get(bet_type)
                if not cname:
                    raise RuntimeError(f"{bet_type}_CNAME_NOT_FOUND")
                page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
                odds_pages += 1
                identity = runtime.parse_page_identity(page, cname)
                if identity != (race["raceDate"], race["venue"], race_no):
                    raise RuntimeError(f"{bet_type}_IDENTITY_MISMATCH:{identity}")
                parsed = runtime.parse_odds_rows(page, bet_type)
                if not parsed:
                    raise RuntimeError(f"{bet_type}_NO_PARSED_ROWS")
                fast.add_records(records, race, bet_type, cname, page, parsed, captured_iso, captured)
                time.sleep(max(base.REQUEST_PAUSE_SECONDS, 0.35))
        except Exception as error:
            errors.append(f"RACE:{race['raceId']}:{type(error).__name__}:{error}")

    rows = list(records.values())
    for row in rows:
        counts[row["betType"]] += 1
        covered[row["betType"]].add(row["raceId"])
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, separators=(",", ":"))

    report = {
        "generatedAt": captured_iso,
        "selectedRaceCount": len(races),
        "officialOddsOnly": True,
        "resultDataUsedForBetGeneration": False,
        "entryPagesFetched": entry_pages,
        "oddsPagesFetched": odds_pages,
        "parsedOddsRows": len(rows),
        "racesByBetType": {k: len(v) for k, v in sorted(covered.items())},
        "rowsByBetType": dict(sorted(counts.items())),
        "errorCount": len(errors),
        "errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

    required = set(fast.TYPE_PREFIX)
    if errors or any(len(covered.get(t, set())) != 15 for t in required):
        raise RuntimeError("AUG9_ALL_SELECTED_OFFICIAL_ODDS_INCOMPLETE")


if __name__ == "__main__":
    main()
