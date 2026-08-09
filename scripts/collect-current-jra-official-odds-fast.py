import hashlib
import importlib.util
import itertools
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "scripts" / "collect-current-jra-official-odds.py"
spec = importlib.util.spec_from_file_location("current_odds_wrapper", CURRENT)
if spec is None or spec.loader is None:
    raise RuntimeError("CURRENT_ODDS_WRAPPER_IMPORT_FAILED")
current = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = current
spec.loader.exec_module(current)
runtime = current.runtime
base = runtime.base

TYPE_PREFIX = {
    "単勝": "pw151ou",
    "馬連": "pw154ou",
    "ワイド": "pw155ou",
    "馬単": "pw156ou",
    "3連複": "pw157ou",
    "3連単": "pw158ou",
}


def same_race_link(cname: str, race_date_digits: str, race_no: int) -> bool:
    return race_date_digits in cname and current.current_race_no_from_cname(cname) == race_no


def exact_decimal_odds(text: str) -> tuple[float, float] | None:
    clean = text.replace(",", "").replace("－", "-").strip()
    m = re.fullmatch(r"(\d+\.\d+)(?:\s*-\s*(\d+\.\d+))?", clean)
    if not m:
        return None
    low = float(m.group(1)); high = float(m.group(2) or m.group(1))
    if low <= 0 or high < low or high > 100000:
        return None
    return low, high


def parse_win(page: str) -> tuple[list[int], list[tuple[str, float, float]]]:
    rows = base.parsed_rows(page)
    header_index = -1; horse_index = -1; win_index = -1
    for i, row in enumerate(rows):
        if "馬番" in row and any(cell == "単勝" or cell.startswith("単勝") for cell in row):
            header_index = i
            horse_index = row.index("馬番")
            win_index = next(j for j, cell in enumerate(row) if cell == "単勝" or cell.startswith("単勝"))
            break
    if header_index < 0:
        raise RuntimeError("WIN_HEADER_NOT_FOUND")
    values: list[tuple[int, float, float]] = []
    for row in rows[header_index + 1:]:
        if len(row) <= max(horse_index, win_index):
            continue
        if not re.fullmatch(r"\d{1,2}", row[horse_index].strip()):
            continue
        odds = exact_decimal_odds(row[win_index])
        if odds is None:
            continue
        horse = int(row[horse_index])
        if 1 <= horse <= 30:
            values.append((horse, odds[0], odds[1]))
    # Deduplicate while preserving horse-number order.
    by_horse: dict[int, tuple[float, float]] = {}
    for horse, low, high in values:
        by_horse.setdefault(horse, (low, high))
    horses = sorted(by_horse)
    if len(horses) < 2:
        raise RuntimeError(f"WIN_HORSES_TOO_FEW:{len(horses)}")
    return horses, [(str(h), by_horse[h][0], by_horse[h][1]) for h in horses]


def expected_combinations(bet_type: str, horses: list[int]) -> list[tuple[int, ...]]:
    if bet_type in {"馬連", "ワイド"}:
        return list(itertools.combinations(horses, 2))
    if bet_type == "馬単":
        return list(itertools.permutations(horses, 2))
    if bet_type == "3連複":
        return list(itertools.combinations(horses, 3))
    if bet_type == "3連単":
        return list(itertools.permutations(horses, 3))
    raise RuntimeError(f"UNSUPPORTED_MATRIX_TYPE:{bet_type}")


def parse_matrix(page: str, bet_type: str, horses: list[int]) -> list[tuple[str, float, float]]:
    # JRA's combination pages render the leading horse(s) as group headers.
    # Each actual odds row therefore contains only the final horse number and odds.
    # The rows are in canonical lexicographic combination/permutation order.
    actual: list[tuple[int, float, float]] = []
    for row in base.parsed_rows(page):
        if len(row) != 2 or not re.fullmatch(r"\d{1,2}", row[0].strip()):
            continue
        odds = exact_decimal_odds(row[1])
        if odds is None:
            continue
        actual.append((int(row[0]), odds[0], odds[1]))
    expected = expected_combinations(bet_type, horses)
    if len(actual) != len(expected):
        raise RuntimeError(f"{bet_type}_ROW_COUNT_MISMATCH:{len(actual)}!={len(expected)}")
    out: list[tuple[str, float, float]] = []
    for combo, (last_horse, low, high) in zip(expected, actual):
        if combo[-1] != last_horse:
            raise RuntimeError(f"{bet_type}_ORDER_MISMATCH:{combo}:{last_horse}")
        out.append(("-".join(str(x) for x in combo), low, high))
    return out


def find_type_cnames(page: str, race_date_digits: str, race_no: int) -> dict[str, str]:
    actions = [cname for cname, _context in base.action_links(page) if same_race_link(cname, race_date_digits, race_no)]
    result: dict[str, str] = {}
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
            "raceId": race["raceId"], "betType": bet_type, "combination": combination,
            "oddsMin": low, "oddsMax": high, "capturedAtUtc": captured_iso,
            "startTimeUtc": race.get("startTimeUtc"),
            "secondsToStart": base.seconds_to_start(race.get("startTimeUtc"), captured),
            "sourceCname": cname, "sourceHash": source_hash,
        }


def main() -> None:
    current.self_test(); base.ensure_schema()
    races = base.upcoming_races()
    captured = datetime.now(timezone.utc); captured_iso = captured.isoformat()
    records: dict[tuple[str, str, str], dict] = {}
    errors: list[str] = []; entry_pages = 0; odds_pages = 0; parsed_by_type = defaultdict(int)

    for race in races:
        entry_url = race.get("entryUrl")
        if not entry_url:
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
                rows = parse_matrix(page, bet_type, horses)
                add_records(records, race, bet_type, cname, page, rows, captured_iso, captured)
                parsed_by_type[bet_type] += len(rows)
                time.sleep(base.REQUEST_PAUSE_SECONDS)
        except Exception as error:
            errors.append(f"RACE:{race['raceId']}:{type(error).__name__}:{error}")

    # Persist only when the current batch is reasonably small. The live inference step
    # consumes these same parsed rows in memory; massive raw 3連単 matrices must not block it.
    rows = list(records.values())
    if len(rows) <= 7000:
        runtime.insert_rows(rows)
        persisted_rows = len(rows)
    else:
        # Keep single-win odds in D1 for race-page display; exotic matrices are parsed successfully
        # and will be consumed by the inference runner without thousands of D1 round-trips.
        win_only = [row for row in rows if row["betType"] == "単勝"]
        runtime.insert_rows(win_only)
        persisted_rows = len(win_only)

    counts_by_type = defaultdict(int); races_by_type = defaultdict(set)
    for row in rows:
        counts_by_type[row["betType"]] += 1; races_by_type[row["betType"]].add(row["raceId"])
    report = {
        "generatedAt": captured_iso, "status": "parsed_official_odds" if rows else "waiting_for_official_odds",
        "oddsSource": "jra_official", "upcomingRaceCount": len(races), "entryPagesFetched": entry_pages,
        "oddsPagesFetched": odds_pages, "parsedOddsRows": len(rows), "persistedOddsRows": persisted_rows,
        "coveredRaces": len({row["raceId"] for row in rows}), "rowsByBetType": dict(sorted(counts_by_type.items())),
        "racesByBetType": {key: len(value) for key, value in sorted(races_by_type.items())},
        "errorCount": len(errors), "errors": errors[:100],
    }
    base.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if races and entry_pages == 0:
        raise RuntimeError("CURRENT_JRA_ENTRY_PAGES_UNREACHABLE")

if __name__ == "__main__":
    main()
