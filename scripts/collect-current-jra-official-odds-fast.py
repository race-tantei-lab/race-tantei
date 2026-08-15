import gzip
import hashlib
import importlib.util
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "scripts" / "collect-current-jra-official-odds.py"
SELECTION_PATH = ROOT / "analysis-results" / "final-aug9-selection.json"
spec = importlib.util.spec_from_file_location("current_odds_wrapper", CURRENT)
if spec is None or spec.loader is None:
    raise RuntimeError("CURRENT_ODDS_WRAPPER_IMPORT_FAILED")
current = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = current
spec.loader.exec_module(current)
runtime = current.runtime
base = runtime.base

TYPE_PREFIX = {
    "単勝": "pw151ou", "馬連": "pw154ou", "ワイド": "pw155ou",
    "馬単": "pw156ou", "3連複": "pw157ou", "3連単": "pw158ou",
}
ROWS_PATH = ROOT / "current-selected-official-odds.json.gz"


def selected_ids() -> set[str]:
    if not SELECTION_PATH.exists():
        raise RuntimeError(f"SELECTION_FILE_MISSING:{SELECTION_PATH}")
    payload = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    ids = {str(row["raceId"]) for row in payload.get("selected", [])}
    if len(ids) != 15:
        raise RuntimeError(f"SELECTED_RACE_COUNT_INVALID:{len(ids)}")
    if payload.get("resultDataUsedForTargetDay") is not False:
        raise RuntimeError("TARGET_RESULT_DATA_USED")
    return ids


def same_race_link(cname: str, race_date_digits: str, race_no: int) -> bool:
    return race_date_digits in cname and current.current_race_no_from_cname(cname) == race_no


def exact_decimal_odds(text: str) -> tuple[float, float] | None:
    clean = text.replace(",", "").replace("－", "-").strip()
    m = re.fullmatch(r"(\d+\.\d+)(?:\s*-\s*(\d+\.\d+))?", clean)
    if not m:
        return None
    low = float(m.group(1)); high = float(m.group(2) or m.group(1))
    return (low, high) if low > 0 and high >= low and high <= 100000 else None


def parse_win(page: str) -> tuple[list[int], list[tuple[str, float, float]]]:
    rows = base.parsed_rows(page)
    header_index = -1
    pairs: list[tuple[int, int]] = []
    for i, row in enumerate(rows):
        horse_indexes = [j for j, cell in enumerate(row) if cell.strip() == "馬番"]
        win_indexes = [j for j, cell in enumerate(row) if cell.strip() == "単勝" or cell.strip().startswith("単勝")]
        if not horse_indexes or not win_indexes:
            continue
        candidate_pairs: list[tuple[int, int]] = []
        for pos, horse_index in enumerate(horse_indexes):
            block_end = horse_indexes[pos + 1] if pos + 1 < len(horse_indexes) else len(row)
            within = [win_index for win_index in win_indexes if horse_index < win_index < block_end]
            if within:
                candidate_pairs.append((horse_index, within[0]))
        if candidate_pairs:
            header_index = i
            pairs = candidate_pairs
            break
    if header_index < 0 or not pairs:
        raise RuntimeError("WIN_HEADER_NOT_FOUND")

    by_horse: dict[int, tuple[float, float]] = {}
    for row in rows[header_index + 1:]:
        if "馬番" in row and any(cell == "単勝" or cell.startswith("単勝") for cell in row):
            continue
        for horse_index, win_index in pairs:
            if len(row) <= max(horse_index, win_index):
                continue
            horse_text = row[horse_index].strip()
            if not re.fullmatch(r"\d{1,2}", horse_text):
                continue
            odds = exact_decimal_odds(row[win_index])
            horse = int(horse_text)
            if odds and 1 <= horse <= 30:
                by_horse.setdefault(horse, odds)

    horses = sorted(by_horse)
    if len(horses) < 2:
        raise RuntimeError(f"WIN_HORSES_TOO_FEW:{len(horses)}")
    return horses, [(str(h), *by_horse[h]) for h in horses]


def find_type_cnames(page: str, race_date_digits: str, race_no: int) -> dict[str, str]:
    actions = [cname for cname, _ in base.action_links(page) if same_race_link(cname, race_date_digits, race_no)]
    result = {}
    for bet_type, prefix in TYPE_PREFIX.items():
        candidates = [c for c in actions if c.startswith(prefix)]
        if candidates:
            result[bet_type] = candidates[0]
    return result


def add_records(records: dict, race: dict, bet_type: str, cname: str, page: str,
                rows: list[tuple[str, float, float]], captured_iso: str, captured: datetime) -> None:
    source_hash = hashlib.sha256(page.encode("utf-8", errors="replace")).hexdigest()
    for combination, low, high in rows:
        records[(race["raceId"], bet_type, combination)] = {
            "raceId": race["raceId"], "raceDate": race["raceDate"], "venue": race["venue"], "raceNo": int(race["raceNo"]),
            "betType": bet_type, "combination": combination, "oddsMin": low, "oddsMax": high, "capturedAtUtc": captured_iso,
            "startTimeUtc": race.get("startTimeUtc"), "secondsToStart": base.seconds_to_start(race.get("startTimeUtc"), captured),
            "sourceCname": cname, "sourceHash": source_hash,
        }


def main() -> None:
    current.self_test(); base.ensure_schema()
    target_ids = selected_ids()
    captured = datetime.now(timezone.utc); captured_iso = captured.isoformat()
    source = base.upcoming_races()
    races = []
    for race in source:
        if race["raceId"] not in target_ids:
            continue
        seconds = base.seconds_to_start(race.get("startTimeUtc"), captured)
        # Normal generation happens much earlier. This path must still be able to
        # recover a missed ticket right up until the published start time.
        if seconds is None or seconds <= 0:
            continue
        races.append(race)

    records = {}; errors = []; entry_pages = odds_pages = 0; parsed_by_type = defaultdict(int)
    print(json.dumps({"eligibleFixedTargets": [(r["raceId"], r.get("startTimeUtc")) for r in races]}, ensure_ascii=False), flush=True)
    for race in races:
        entry_url = race.get("entryUrl")
        if not entry_url:
            errors.append(f"RACE:{race['raceId']}:ENTRY_URL_MISSING")
            continue
        race_date_digits = str(race["raceDate"]).replace("-", ""); race_no = int(race["raceNo"])
        try:
            entry_html = runtime.fetch_url(entry_url); entry_pages += 1
            entry_actions = [c for c, _ in base.action_links(entry_html) if same_race_link(c, race_date_digits, race_no)]
            win_seeds = [c for c in entry_actions if c.startswith(TYPE_PREFIX["単勝"])]
            if not win_seeds:
                raise RuntimeError("WIN_CNAME_NOT_FOUND")
            win_cname = win_seeds[0]
            win_page = runtime.fetch_url(base.JRA_ODDS_URL, cname=win_cname, referer=entry_url); odds_pages += 1
            horses, win_rows = parse_win(win_page)
            add_records(records, race, "単勝", win_cname, win_page, win_rows, captured_iso, captured)
            parsed_by_type["単勝"] += len(win_rows)
            type_cnames = find_type_cnames(win_page, race_date_digits, race_no)
            for bet_type in ["馬連", "ワイド", "馬単", "3連複", "3連単"]:
                cname = type_cnames.get(bet_type)
                if not cname:
                    raise RuntimeError(f"{bet_type}_CNAME_NOT_FOUND")
                page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL); odds_pages += 1
                identity = runtime.parse_page_identity(page, cname)
                if identity != (race["raceDate"], race["venue"], race_no):
                    raise RuntimeError(f"{bet_type}_IDENTITY_MISMATCH:{identity}")
                parsed = runtime.parse_odds_rows(page, bet_type)
                if not parsed:
                    raise RuntimeError(f"{bet_type}_NO_PARSED_ROWS")
                add_records(records, race, bet_type, cname, page, parsed, captured_iso, captured)
                parsed_by_type[bet_type] += len(parsed)
                time.sleep(max(base.REQUEST_PAUSE_SECONDS, 0.5))
        except Exception as error:
            errors.append(f"RACE:{race['raceId']}:{type(error).__name__}:{error}")

    rows = list(records.values())
    with gzip.open(ROWS_PATH, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, separators=(",", ":"))

    persistence_warning = None
    try:
        runtime.insert_rows([row for row in rows if row["betType"] == "単勝"])
    except Exception as error:
        persistence_warning = f"SINGLE_WIN_DISPLAY_PERSIST_FAILED:{type(error).__name__}:{error}"
        print(persistence_warning, flush=True)

    counts = defaultdict(int); covered = defaultdict(set)
    for row in rows:
        counts[row["betType"]] += 1; covered[row["betType"]].add(row["raceId"])
    report = {
        "generatedAt": captured_iso,
        "status": "parsed_selected_official_odds" if rows else "waiting_for_official_odds",
        "oddsSource": "jra_official",
        "eligibleFixedTargetCount": len(races),
        "entryPagesFetched": entry_pages,
        "oddsPagesFetched": odds_pages,
        "parsedOddsRows": len(rows),
        "rowsByBetType": dict(sorted(counts.items())),
        "racesByBetType": {k: len(v) for k, v in sorted(covered.items())},
        "errorCount": len(errors),
        "errors": errors[:100],
        "persistenceWarning": persistence_warning,
        "rowsFile": ROWS_PATH.name,
    }
    base.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if races and (errors or any(len(covered.get(t, set())) < len(races) for t in TYPE_PREFIX)):
        raise RuntimeError("SELECTED_OFFICIAL_ODDS_INCOMPLETE")


if __name__ == "__main__":
    main()
