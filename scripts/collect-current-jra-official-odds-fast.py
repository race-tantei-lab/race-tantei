import hashlib
import importlib.util
import json
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
        local_links: list[tuple[str, str]] = []
        for cname, context in base.action_links(entry_html):
            if race_date_digits not in cname:
                continue
            if current.current_race_no_from_cname(cname) != race_no:
                continue
            local_links.append((cname, context))

        for cname, context in local_links:
            if cname in fetched_cnames:
                continue
            fetched_cnames.add(cname)
            try:
                page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname)
                odds_pages += 1
                identity = runtime.parse_page_identity(page, cname)
                bet_type = base.detect_bet_type(page, context)
                if identity is None or bet_type is None:
                    continue
                target = next(
                    (
                        row for row in races
                        if row["raceDate"] == identity[0]
                        and row["venue"] == identity[1]
                        and int(row["raceNo"]) == identity[2]
                    ),
                    None,
                )
                if target is None:
                    continue
                source_hash = hashlib.sha256(page.encode("utf-8", errors="replace")).hexdigest()
                for combination, low, high in base.parse_odds_rows(page, bet_type):
                    records[(target["raceId"], bet_type, combination)] = {
                        "raceId": target["raceId"],
                        "betType": bet_type,
                        "combination": combination,
                        "oddsMin": low,
                        "oddsMax": high,
                        "capturedAtUtc": captured_iso,
                        "startTimeUtc": target.get("startTimeUtc"),
                        "secondsToStart": base.seconds_to_start(target.get("startTimeUtc"), captured),
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
