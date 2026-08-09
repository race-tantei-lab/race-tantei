import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict, deque
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

TARGET_BET_TYPES = {"単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"}


def belongs_to_race(cname: str, race_date_digits: str, race_no: int) -> bool:
    return race_date_digits in cname and current.current_race_no_from_cname(cname) == race_no


def main() -> None:
    current.self_test()
    base.ensure_schema()
    races = base.upcoming_races()
    captured = datetime.now(timezone.utc)
    captured_iso = captured.isoformat()
    fetched_cnames: set[str] = set()
    records: dict[tuple[str, str, str], dict] = {}
    errors: list[str] = []
    entry_pages = 0
    odds_pages = 0

    for race in races:
        entry_url = race.get("entryUrl")
        if not entry_url:
            continue
        try:
            entry_html = runtime.fetch_url(entry_url)
            entry_pages += 1
        except Exception as error:
            errors.append(f"ENTRY:{race['raceId']}:{type(error).__name__}:{error}")
            continue

        race_date_digits = str(race["raceDate"]).replace("-", "")
        race_no = int(race["raceNo"])
        queue: deque[tuple[str, str]] = deque()
        queued: set[str] = set()
        for cname, context in base.action_links(entry_html):
            if belongs_to_race(cname, race_date_digits, race_no) and cname not in queued:
                queue.append((cname, context))
                queued.add(cname)

        while queue:
            cname, context = queue.popleft()
            if cname in fetched_cnames:
                continue
            fetched_cnames.add(cname)
            try:
                page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname)
                odds_pages += 1

                # JRA exposes the other bet-type tabs only after the first odds page opens.
                # Follow only links that remain on this exact date/race number.
                for child, child_context in base.action_links(page):
                    if belongs_to_race(child, race_date_digits, race_no) and child not in queued and child not in fetched_cnames:
                        queue.append((child, child_context))
                        queued.add(child)

                identity = runtime.parse_page_identity(page, cname)
                bet_type = base.detect_bet_type(page, context)
                if identity is None or bet_type not in TARGET_BET_TYPES:
                    continue
                if not (
                    identity[0] == race["raceDate"]
                    and identity[1] == race["venue"]
                    and identity[2] == race_no
                ):
                    continue

                source_hash = hashlib.sha256(page.encode("utf-8", errors="replace")).hexdigest()
                for combination, low, high in base.parse_odds_rows(page, bet_type):
                    records[(race["raceId"], bet_type, combination)] = {
                        "raceId": race["raceId"],
                        "betType": bet_type,
                        "combination": combination,
                        "oddsMin": low,
                        "oddsMax": high,
                        "capturedAtUtc": captured_iso,
                        "startTimeUtc": race.get("startTimeUtc"),
                        "secondsToStart": base.seconds_to_start(race.get("startTimeUtc"), captured),
                        "sourceCname": cname,
                        "sourceHash": source_hash,
                    }
                time.sleep(base.REQUEST_PAUSE_SECONDS)
            except Exception as error:
                errors.append(f"ODDS:{cname}:{type(error).__name__}:{error}")

    rows = list(records.values())
    runtime.insert_rows(rows)
    counts_by_type = defaultdict(int)
    races_by_type = defaultdict(set)
    for row in rows:
        counts_by_type[row["betType"]] += 1
        races_by_type[row["betType"]].add(row["raceId"])

    report = {
        "generatedAt": captured_iso,
        "status": "stored_official_odds" if rows else "waiting_for_official_odds",
        "oddsSource": "jra_official",
        "upcomingRaceCount": len(races),
        "entryPagesFetched": entry_pages,
        "oddsPagesFetched": odds_pages,
        "cnamesFetched": len(fetched_cnames),
        "storedOddsRows": len(rows),
        "coveredRaces": len({row["raceId"] for row in rows}),
        "rowsByBetType": dict(sorted(counts_by_type.items())),
        "racesByBetType": {key: len(value) for key, value in sorted(races_by_type.items())},
        "errorCount": len(errors),
        "errors": errors[:100],
    }
    base.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if races and entry_pages == 0:
        raise RuntimeError("CURRENT_JRA_ENTRY_PAGES_UNREACHABLE")


if __name__ == "__main__":
    main()
