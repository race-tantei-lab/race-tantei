#!/usr/bin/env python3
"""Read-only production audit: actual bets, missing T-15 locks, settlements and ROI.

Date-bounded production D1 reads; no migrations, writes, backfills, model
changes or website modifications. Excludes still-running JST race day.
Historical backtest is deliberately NOT included in actual production ROI.
"""
from __future__ import annotations
import collections
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
COURSES = ("ライト", "スタンダード", "プレミアム")
LIMIT = 5000

def query(sql: str, params: list[str]) -> list[dict]:
    a = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    d = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    t = os.environ["CLOUDFLARE_API_TOKEN"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{a}/d1/database/{d}/query"
    req = urllib.request.Request(url, method="POST", data=json.dumps({
        "sql": sql, "params": params,
    }).encode(), headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"PRODUCTION_D1_READ_BLOCKED_HTTP_{error.code}: {body[:600]}") from None
    if result.get("success") is not True:
        raise RuntimeError(f"PRODUCTION_D1_QUERY_FAILED: {str(result.get('errors'))[:600]}")
    return ((result.get("result") or [{}])[0].get("results") or [])

def decode_selected(states: list[dict]) -> dict[str, list[dict]]:
    result = {}
    for row in states:
        key = str(row.get("stateKey") or "")
        date = key.removeprefix("final_daily_selection:")
        if not date.startswith("2026-") or len(date) != 10:
            continue
        payload = json.loads(str(row.get("stateValue") or "{}"))
        if payload.get("sourceModel") != "ten-year-completed-model":
            raise AssertionError(f"wrong selection model for {date}")
        selected = payload.get("selected")
        if not isinstance(selected, list):
            raise AssertionError(f"selected list missing for {date}")
        ids = [str(x.get("raceId") or "") for x in selected]
        if len(ids) != len(set(ids)):
            raise AssertionError(f"duplicate selected races for {date}")
        result[date] = selected
    return result

def locked_on_time(bets: list[dict], race: dict, date: str) -> bool:
    raw = str(race.get("startTimeJst") or "")
    if len(raw) < 5 or ":" not in raw:
        return False
    start = dt.datetime.fromisoformat(date + "T" + raw[:5] + ":00+09:00")
    cutoff = start - dt.timedelta(minutes=15)
    for bet in bets:
        locked = str(bet.get("lockedAt") or "")
        try:
            at = dt.datetime.fromisoformat(locked.replace("Z", "+00:00"))
        except ValueError:
            return False
        if at > cutoff:
            return False
    return True

def audit(states: list[dict], bets: list[dict]) -> dict:
    selected = decode_selected(states)
    by_id = collections.defaultdict(list)
    for row in bets:
        by_id[(str(row.get("raceId")), str(row.get("course")))].append(row)
    result = {"basis": "actual-production-bets-only-no-backtest",
              "periodDays": len(selected), "selectionRaces": 0,
              "courses": {}, "daily": [], "missingRaceIds": [],
              "lateRaceIds": [], "unsettledRaceIds": []}
    totals = {course: {"expectedRaces": 0, "finalizedRaces": 0,
                       "settledRaces": 0, "stakeYen": 0,
                       "returnYen": 0, "missingRaces": 0,
                       "lateRaces": 0, "unsettledRaces": 0}
              for course in COURSES}
    for date, races in sorted(selected.items()):
        day = {"date": date, "selectedRaces": len(races), "courses": {}}
        result["selectionRaces"] += len(races)
        for course in COURSES:
            sums = {k: 0 for k in totals[course]}
            sums["expectedRaces"] = len(races)
            for race in races:
                rid = str(race.get("raceId"))
                rows = by_id.get((rid, course), [])
                if len(rows) != 2:
                    sums["missingRaces"] += 1
                    result["missingRaceIds"].append({"date": date, "course": course, "raceId": rid, "rows": len(rows)})
                    continue
                if not locked_on_time(rows, race, date):
                    sums["lateRaces"] += 1
                    result["lateRaceIds"].append({"date": date, "course": course, "raceId": rid})
                    continue
                sums["finalizedRaces"] += 1
                if not all(row.get("settlementStatus") == "settled" for row in rows):
                    sums["unsettledRaces"] += 1
                    result["unsettledRaceIds"].append({"date": date, "course": course, "raceId": rid})
                    continue
                stake = sum(int(row.get("stakeYen") or 0) for row in rows)
                if stake <= 0 or any(row.get("returnYen") is None for row in rows):
                    raise AssertionError(f"missing settled stake/return: {rid}:{course}")
                sums["settledRaces"] += 1
                sums["stakeYen"] += stake
                sums["returnYen"] += sum(int(row["returnYen"]) for row in rows)
            day["courses"][course] = {**sums,
                "roiPct": round(100 * sums["returnYen"] / sums["stakeYen"], 2) if sums["stakeYen"] else None}
            for key in sums:
                totals[course][key] += sums[key]
        result["daily"].append(day)
    result["courses"] = {
        course: {**s, "roiPct": round(100 * s["returnYen"] / s["stakeYen"], 2) if s["stakeYen"] else None}
        for course, s in totals.items()
    }
    result["missingCount"] = len(result["missingRaceIds"])
    result["lateCount"] = len(result["lateRaceIds"])
    result["unsettledCount"] = len(result["unsettledRaceIds"])
    result["payoutProvenance"] = "D1-recorded; not independently cross-checked with JRA"
    return result

def self_test() -> None:
    day = "2026-11-01"
    selection = [{"stateKey": "final_daily_selection:" + day, "stateValue": json.dumps({
        "sourceModel": "ten-year-completed-model",
        "selected": [{"raceId": day+"-tokyo-01", "startTimeJst": "10:00"},
                     {"raceId": day+"-tokyo-02", "startTimeJst": "11:00"}]})}]
    bets = []
    for course in COURSES:
        for typ, r in (("単勝", 2000), ("ワイド", 0)):
            bets.append({"raceId":day+"-tokyo-01", "course":course,
                         "lockedAt": "2026-11-01T00:00:00Z", "settlementStatus":"settled",
                         "stakeYen": 1000, "returnYen": r, "betType":typ})
    report = audit(selection, bets)
    assert report["selectionRaces"] == 2
    assert report["courses"]["ライト"]["settledRaces"] == 1
    assert report["courses"]["ライト"]["missingRaces"] == 1
    assert report["courses"]["ライト"]["roiPct"] == 100
    assert report["missingCount"] == 3
    assert report["lateCount"] == 0
    print("ACTUAL_ROI_READ_ONLY_AUDIT_SELFTEST_OK")


def summarize_live_records(states: list[dict], bets: list[dict], calendar: list[dict]) -> dict:
    """Separate all recorded settlement from strictly T-15-locked settlement.

    Only frozen selected races; use light course once to avoid triplicate bets.
    Never treat a missing prediction as a realized loss or imply that a
    post-deadline lock was a legitimate pre-race prediction.
    """
    selected = decode_selected(states)
    by_id = collections.defaultdict(list)
    for b in bets:
        by_id[(str(b.get("raceId") or ""), str(b.get("course") or ""))].append(b)
    modes = {}
    for mode in ("recorded", "deadline_valid"):
        sums = collections.defaultdict(lambda: {"races": 0, "tickets": 0, "stakeYen": 0, "returnYen": 0, "hits": 0})
        by_date = collections.defaultdict(lambda: {"races": 0, "stakeYen": 0, "returnYen": 0})
        for date, races in sorted(selected.items()):
            for race in races:
                rid = str(race.get("raceId") or "")
                rows = by_id.get((rid, "ライト"), [])
                if len(rows) != 2 or any(str(b.get("settlementStatus")) != "settled" for b in rows):
                    continue
                if mode == "deadline_valid" and not locked_on_time(rows, race, date):
                    continue
                if any(b.get("returnYen") is None or int(b.get("stakeYen") or 0) <= 0 for b in rows):
                    continue
                venue = rid.split("-")[3] if len(rid.split("-")) >= 5 else "unknown"
                day = by_date[date]
                day["races"] += 1
                for b in rows:
                    stake = int(b["stakeYen"])
                    returned = int(b["returnYen"])
                    typ = str(b.get("betType") or "unknown")
                    odds = float(b.get("assumedOdds") or 0)
                    bucket = ("missing" if odds <= 0 else "1-3" if odds < 3 else "3-10" if odds < 10 else "10-30" if odds < 30 else "30-100" if odds < 100 else "100+")
                    for key in (("total", "all"), ("betType", typ), ("venue", venue), ("oddsBand", bucket)):
                        entry = sums[key]
                        entry["tickets"] += 1
                        entry["stakeYen"] += stake
                        entry["returnYen"] += returned
                        entry["hits"] += int(returned > 0)
                    day["stakeYen"] += stake
                    day["returnYen"] += returned
                for key in (("total", "all"), ("venue", venue)):
                    sums[key]["races"] += 1
        def format_entry(e):
            return {**e, "roiPct": round(100 * e["returnYen"] / e["stakeYen"], 2) if e["stakeYen"] else None,
                    "profitYen": e["returnYen"] - e["stakeYen"]}
        modes[mode] = {"byDate": {date: format_entry(v) for date, v in sorted(by_date.items())},
                       "byBreakdown": {kind: {name: format_entry(v) for (k, name), v in sorted(sums.items()) if k == kind}
                                       for kind in ("total", "betType", "venue", "oddsBand")}}
    missing_calendar_dates = sorted({str(row.get("raceDate")) for row in calendar} - set(selected))
    return {"basis": "real-selected-light-course-two-bets-only", "modes": modes,
            "calendarRaceDates": len(calendar), "frozenSelectionDates": len(selected),
            "calendarDatesMissingFrozenSelection": missing_calendar_dates,
            "calendar": calendar}

def main() -> None:
    if "--self-test" in sys.argv:
        self_test()
        return
    now = dt.datetime.now(JST).date()
    yesterday = now - dt.timedelta(days=1)
    start = dt.date(2026, 8, 10)
    end_exclusive = yesterday + dt.timedelta(days=1)
    # Both queries are bounded and use only already persisted rows.
    states = query("""
      SELECT state_key AS stateKey, state_value AS stateValue
      FROM rt_system_state WHERE state_key>=? AND state_key<?
      ORDER BY state_key LIMIT 150
    """, ["final_daily_selection:" + str(start), "final_daily_selection:" + str(end_exclusive)])
    bets = query("""
      SELECT race_id AS raceId, course, stake_yen AS stakeYen,
             return_yen AS returnYen, settlement_status AS settlementStatus,
             locked_at AS lockedAt,bet_type AS betType,assumed_odds AS assumedOdds
      FROM rt_public_bets
      WHERE race_id>=? AND race_id<?
        AND source_prediction_id=-2
      ORDER BY race_id, course, id LIMIT 5000
    """, [str(start) + "-", str(end_exclusive) + "-"])
    calendar = query("""
      SELECT race_date AS raceDate, COUNT(*) AS races
      FROM rt_races
      WHERE race_date>=? AND race_date<?
      GROUP BY race_date ORDER BY race_date LIMIT 150
    """, [str(start), str(end_exclusive)])
    if not states:
        raise AssertionError("NO_PRODUCTION_SELECTION_ROWS: audit cannot assert actual results")
    if len(bets) >= LIMIT:
        raise AssertionError("ROW_LIMIT_REACHED: refuse incomplete ROI audit")
    report = audit(states, bets)
    report["period"] = {"from": str(start), "through": str(yesterday)}
    report["queries"] = 3
    print("FULL_PERIOD_LIVE_ROI_DETAIL", json.dumps(summarize_live_records(states, bets, calendar), ensure_ascii=False, separators=(",",":")))
    print("ACTUAL_PRODUCTION_ROI_READONLY_AUDIT", json.dumps(report, ensure_ascii=False, separators=(",",":")))
    if report["missingCount"] or report["lateCount"] or report["unsettledCount"]:
        raise AssertionError("ACTUAL_PRODUCTION_BETS_OR_SETTLEMENT_INCOMPLETE: do not certify ROI")
    print("ACTUAL_PRODUCTION_ROI_LOCK_AND_SETTLEMENT_COMPLETE")

if __name__ == "__main__":
    main()
