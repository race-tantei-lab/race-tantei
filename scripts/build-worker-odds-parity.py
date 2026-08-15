#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import sys
import time
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "scripts" / "collect-current-jra-official-odds-live.py"
OUT = ROOT / "worker-odds-parity.json"
BET_ORDER = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")


def load_live():
    spec = importlib.util.spec_from_file_location("worker_odds_parity_live", LIVE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("LIVE_ODDS_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules["worker_odds_parity_live"] = module
    spec.loader.exec_module(module)
    return module


def page_fixture(runtime, bet_type: str, cname: str, hint: str, page: str, target: tuple[str, str, int], parse_rows) -> dict:
    identity = runtime.parse_page_identity(page, cname)
    if identity != target:
        raise RuntimeError(f"{bet_type}_IDENTITY_MISMATCH:{identity}:{target}")
    rows = parse_rows(page)
    if not rows:
        raise RuntimeError(f"{bet_type}_NO_PARSED_ROWS")
    return {
        "cname": cname,
        "hint": hint,
        "depth": 0 if bet_type == "単勝" else 1,
        "html": page,
        "identity": {"raceDate": identity[0], "venue": identity[1], "raceNo": identity[2]},
        "betType": bet_type,
        "rows": [
            {"betType": bet_type, "combination": combination, "oddsMin": float(low), "oddsMax": float(high)}
            for combination, low, high in rows
        ],
    }


def collect_one(live, race: dict) -> dict:
    fast = live.base
    runtime = fast.runtime
    base = fast.base
    entry_url = str(race["entryUrl"])
    race_date_digits = str(race["raceDate"]).replace("-", "")
    race_no = int(race["raceNo"])
    target = (str(race["raceDate"]), str(race["venue"]), race_no)

    entry_html = runtime.fetch_url(entry_url)
    entry_links = base.action_links(entry_html)
    same_race_actions = [
        (cname, context)
        for cname, context in entry_links
        if fast.same_race_link(cname, race_date_digits, race_no)
    ]
    win_seeds = [(cname, context) for cname, context in same_race_actions if cname.startswith(fast.TYPE_PREFIX["単勝"])]
    if not win_seeds:
        raise RuntimeError("WIN_CNAME_NOT_FOUND")
    win_cname, win_hint = win_seeds[0]
    win_page = runtime.fetch_url(base.JRA_ODDS_URL, cname=win_cname, referer=entry_url)
    _horses, win_rows = live.parse_win_complete(win_page)
    pages = [
        page_fixture(runtime, "単勝", win_cname, win_hint, win_page, target, lambda _page: win_rows)
    ]

    type_cnames = fast.find_type_cnames(win_page, race_date_digits, race_no)
    action_context = {cname: context for cname, context in base.action_links(win_page)}
    for bet_type in ("ワイド", "馬連", "馬単", "3連複", "3連単"):
        cname = type_cnames.get(bet_type)
        if not cname:
            raise RuntimeError(f"{bet_type}_CNAME_NOT_FOUND")
        page = runtime.fetch_url(base.JRA_ODDS_URL, cname=cname, referer=base.JRA_ODDS_URL)
        pages.append(
            page_fixture(
                runtime,
                bet_type,
                cname,
                action_context.get(cname, f"{bet_type}オッズ"),
                page,
                target,
                lambda source, bt=bet_type: runtime.parse_odds_rows(source, bt),
            )
        )
        time.sleep(0.08)

    by_type = {page["betType"]: page for page in pages}
    if set(by_type) != set(BET_ORDER):
        raise RuntimeError(f"SIX_TYPE_COVERAGE_FAILED:{sorted(by_type)}")
    return {
        "race": race,
        "entryHtml": entry_html,
        "entryActionLinks": [{"cname": cname, "context": context} for cname, context in entry_links],
        "pagesFetched": 7,
        "maxFoundDepth": 1,
        "pages": [by_type[bet_type] for bet_type in BET_ORDER],
    }


def main() -> int:
    for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"):
        if not os.environ.get(key):
            raise RuntimeError(f"MISSING_ENV:{key}")
    live = load_live()
    fast = live.base
    fast.current.self_test()
    today = dt.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    races = fast.base.d1_query(
        "SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,start_time_utc AS startTimeUtc,entry_url AS entryUrl FROM rt_races WHERE race_date=? AND entry_url IS NOT NULL AND entry_url<>'' ORDER BY CASE WHEN datetime(start_time_utc)>=datetime('now') THEN 0 ELSE 1 END,abs(strftime('%s',start_time_utc)-strftime('%s','now')),venue,race_no",
        [today],
    )
    errors: list[str] = []
    result = None
    for race in races[:6]:
        try:
            result = collect_one(live, race)
            break
        except Exception as error:
            errors.append(f"{race.get('raceId')}:{type(error).__name__}:{error}")
    if result is None:
        raise RuntimeError(f"NO_SIX_TYPE_JRA_ODDS_FIXTURE:{errors[:6]}")

    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "errors": errors, **result}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "status": "JRA_ODDS_FAST_FIXTURE_OK",
        "raceId": result["race"]["raceId"],
        "identity": [result["race"]["raceDate"], result["race"]["venue"], int(result["race"]["raceNo"])],
        "entryActionLinkCount": len(result["entryActionLinks"]),
        "pagesFetched": result["pagesFetched"],
        "rowsByType": {page["betType"]: len(page["rows"]) for page in result["pages"]},
        "priorErrors": errors,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
