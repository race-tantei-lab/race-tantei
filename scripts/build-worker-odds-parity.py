#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import sys
import time
from collections import deque
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "collect-jra-official-odds.py"
OUT = ROOT / "worker-odds-parity.json"
BET_TYPES = {"単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"}


def load_collector():
    spec = importlib.util.spec_from_file_location("worker_odds_parity_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules["worker_odds_parity_collector"] = module
    spec.loader.exec_module(module)
    return module


def crawl(collector, race: dict, max_pages: int = 28, max_depth: int = 3) -> dict | None:
    entry_html = collector.fetch_url(str(race["entryUrl"]))
    queue: deque[tuple[str, str, int]] = deque()
    queued: set[str] = set()
    for cname, context in collector.action_links(entry_html):
        if cname not in queued:
            queued.add(cname)
            queue.append((cname, context, 0))
    if not queue:
        queued.add(collector.JRA_ODDS_HOME_CNAME)
        queue.append((collector.JRA_ODDS_HOME_CNAME, "今週のオッズ", 0))

    target = (str(race["raceDate"]), str(race["venue"]), int(race["raceNo"]))
    seen: set[str] = set()
    found: dict[str, dict] = {}
    graph: list[dict] = []
    while queue and len(seen) < max_pages and len(found) < 6:
        cname, hint, depth = queue.popleft()
        if cname in seen:
            continue
        seen.add(cname)
        page = collector.fetch_url(collector.JRA_ODDS_URL, cname=cname)
        identity = collector.parse_page_identity(page)
        bet_type = collector.detect_bet_type(page, hint)
        links = collector.action_links(page)
        graph.append({"cname": cname, "depth": depth, "identity": list(identity) if identity else None, "betType": bet_type, "childCount": len(links)})
        if identity == target and bet_type in BET_TYPES:
            rows = collector.parse_odds_rows(page, bet_type)
            if rows:
                found[bet_type] = {
                    "cname": cname,
                    "hint": hint,
                    "depth": depth,
                    "html": page,
                    "identity": {"raceDate": identity[0], "venue": identity[1], "raceNo": identity[2]},
                    "betType": bet_type,
                    "rows": [{"betType": bet_type, "combination": combination, "oddsMin": low, "oddsMax": high} for combination, low, high in rows],
                }
        if depth < max_depth:
            for child, context in links:
                if child not in seen and child not in queued:
                    queued.add(child)
                    queue.append((child, context, depth + 1))
        time.sleep(0.08)
    if len(found) != 6:
        return None
    return {
        "race": race,
        "entryActionLinks": [{"cname": cname, "context": context} for cname, context in collector.action_links(entry_html)],
        "pagesFetched": len(seen),
        "maxFoundDepth": max(item["depth"] for item in found.values()),
        "graph": graph,
        "pages": [found[key] for key in ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")],
    }


def main() -> int:
    for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"):
        if not os.environ.get(key):
            raise RuntimeError(f"MISSING_ENV:{key}")
    collector = load_collector()
    today = dt.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    races = collector.d1_query(
        "SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,start_time_utc AS startTimeUtc,entry_url AS entryUrl FROM rt_races WHERE race_date=? AND entry_url IS NOT NULL AND entry_url<>'' ORDER BY CASE WHEN datetime(start_time_utc)>=datetime('now') THEN 0 ELSE 1 END,abs(strftime('%s',start_time_utc)-strftime('%s','now')),venue,race_no",
        [today],
    )
    errors: list[str] = []
    result = None
    for race in races[:8]:
        try:
            result = crawl(collector, race)
            if result is not None:
                break
        except Exception as error:
            errors.append(f"{race.get('raceId')}:{type(error).__name__}:{error}")
    if result is None:
        raise RuntimeError(f"NO_SIX_TYPE_JRA_ODDS_FIXTURE:{errors[:8]}")
    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "errors": errors, **result}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "status": "JRA_ODDS_FIXTURE_OK",
        "raceId": result["race"]["raceId"],
        "identity": [result["race"]["raceDate"], result["race"]["venue"], int(result["race"]["raceNo"])],
        "entryActionLinkCount": len(result["entryActionLinks"]),
        "pagesFetched": result["pagesFetched"],
        "maxFoundDepth": result["maxFoundDepth"],
        "rowsByType": {page["betType"]: len(page["rows"]) for page in result["pages"]},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
