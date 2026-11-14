#!/usr/bin/env python3
"""Cash-settled, time-isolated adaptive-window research and prospective selection.

Requires historically frozen candidate tickets for EACH researched strategy/window,
plus independent per-race official JRA payouts. The program never reconstructs
past predictions from post-race odds and never edits production bets.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "adaptive_roi_core", ROOT / "research-adaptive-window-meta-roi.py")
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

TYPES = {"単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"}
UNORDERED = {"ワイド", "馬連", "3連複"}


def read_jsonl(path):
    result = []
    with Path(path).open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            if line.strip():
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{n}:{e}") from e
    return result


def combination(bet_type, value):
    # Reject free-text combinations, never guess a winning ticket.
    if bet_type not in TYPES:
        raise ValueError("UNSUPPORTED_BET_TYPE")
    parts = [p.strip() for p in str(value).replace("－", "-").split("-")]
    need = 1 if bet_type == "単勝" else 3 if bet_type in ("3連複", "3連単") else 2
    if len(parts) != need or not all(p.isdecimal() and 1 <= int(p) <= 18 for p in parts):
        raise ValueError(f"INVALID_COMBINATION:{bet_type}:{value}")
    numbers = [int(x) for x in parts]
    if len(set(numbers)) != len(numbers):
        raise ValueError("REPEATED_HORSE_NUMBER")
    if bet_type in UNORDERED:
        numbers.sort()
    return "-".join(str(x) for x in numbers)


def parse_start(row):
    start = str(row["startTimeJst"])
    if "T" in start:
        raise ValueError("START_TIME_MUST_BE_LOCAL_CLOCK")
    value = dt.datetime.fromisoformat(f"{row['raceDate']}T{start}+09:00")
    if value.utcoffset() != dt.timedelta(hours=9):
        raise ValueError("START_TIME_NOT_JST")
    return value


def validate_candidate(row, *, settled):
    for k in ("raceDate", "raceId", "venue", "strategy", "windowDays",
              "startTimeJst", "lockedAt", "modelTrainedThrough", "bets"):
        if k not in row:
            raise ValueError(f"MISSING:{k}")
    day = dt.date.fromisoformat(row["raceDate"])
    lag = int(row.get("lagDays", 0))
    if lag not in (0, 30, 90, 180, 365, 730):
        raise ValueError("INVALID_LAG_WINDOW")
    if dt.date.fromisoformat(row["modelTrainedThrough"]) >= day - dt.timedelta(days=lag):
        raise ValueError("POST_RACE_MODEL_TRAINING")
    if int(row["windowDays"]) not in CORE.WINDOWS:
        raise ValueError("INVALID_ROLLING_WINDOW")
    deadline = parse_start(row) - dt.timedelta(minutes=15)
    lock_time = CORE.parse_time(row["lockedAt"])
    if lock_time > deadline:
        raise ValueError("POST_T15_BET_LOCK")
    bets = row["bets"]
    if not isinstance(bets, list) or len(bets) < 2:
        raise ValueError("MINIMUM_TWO_TICKETS")
    types = set()
    stakes = 0
    for bet in bets:
        bet_type = bet["betType"]
        key = combination(bet_type, bet["combination"])
        if bet_type in types:
            raise ValueError("TWO_DIFFERENT_BET_TYPES_REQUIRED")
        types.add(bet_type)
        stake = bet["stakeYen"]
        if type(stake) is not int or stake <= 0 or stake % 100:
            raise ValueError("INVALID_STAKE")
        stakes += stake
        if bet.get("oddsSource") != "JRA":
            raise ValueError("OFFICIAL_JRA_ODDS_REQUIRED")
        if CORE.parse_time(bet["oddsCapturedAt"]) > deadline:
            raise ValueError("POST_T15_ODDS")
        if "returnYen" in bet or "winning" in bet:
            raise ValueError("POST_RESULT_FIELDS_IN_PREDICTION")
    if stakes <= 0:
        raise ValueError("INVALID_BUDGET")
    if "returnYen" in row or "settled" in row:
        raise ValueError("POST_RESULT_FIELDS_IN_PREDICTION")
    return stakes


def payout_table(rows):
    by_race = {}
    for row in rows:
        if row.get("payoutSource") != "JRA" or row.get("complete") is not True:
            raise ValueError("UNVERIFIED_OR_INCOMPLETE_JRA_PAYOUT")
        rid = str(row["raceId"])
        if rid in by_race:
            raise ValueError("DUPLICATE_OFFICIAL_RACE")
        table, refunds = {}, set()
        for payout in row["payouts"]:
            typ = payout["betType"]
            key = (typ, combination(typ, payout["combination"]))
            yen = payout["payoutYenPer100"]
            if type(yen) is not int or yen < 0:
                raise ValueError("INVALID_JRA_PAYOUT")
            if key in table:
                raise ValueError("DUPLICATE_JRA_PAYOUT")
            table[key] = yen
        for refund in row.get("refunds", []):
            typ = refund["betType"]
            key = (typ, combination(typ, refund["combination"]))
            if key in table:
                raise ValueError("PAYOUT_AND_REFUND_COLLISION")
            refunds.add(key)
        by_race[rid] = (row, table, refunds)
    return by_race


def reconcile(historical_bets, official_payouts):
    payouts = payout_table(official_payouts)
    reconciled = []
    seen = set()
    for row in historical_bets:
        stake = validate_candidate(row, settled=True)
        rid = str(row["raceId"])
        key = (rid, row["strategy"], int(row["windowDays"]), int(row.get("lagDays", 0)))
        if key in seen:
            raise ValueError("DUPLICATE_CANDIDATE")
        seen.add(key)
        if rid not in payouts:
            raise ValueError(f"MISSING_OFFICIAL_PAYOUT:{rid}")
        official, table, refunds = payouts[rid]
        if (official["raceDate"] != row["raceDate"]
                or official["venue"] != row["venue"]):
            raise ValueError("PAYOUT_RACE_IDENTITY_MISMATCH")
        settled_return = 0
        winning_returns = []
        refunded_bets = 0
        for bet in row["bets"]:
            ticket = (bet["betType"], combination(bet["betType"], bet["combination"]))
            is_refund = ticket in refunds
            per100 = 100 if is_refund else table.get(ticket, 0)
            ticket_return = bet["stakeYen"] // 100 * per100
            settled_return += ticket_return
            refunded_bets += int(is_refund)
            if not is_refund and per100 > 0:
                winning_returns.append(ticket_return)
        reconciled.append({
            "raceDate": row["raceDate"], "raceId": rid, "venue": row["venue"],
            "strategy": row["strategy"], "windowDays": int(row["windowDays"]),
            "lagDays": int(row.get("lagDays", 0)),
            "startTimeJst": row["startTimeJst"], "lockedAt": row["lockedAt"],
            "stakeYen": stake, "returnYen": settled_return,
            "hitRace": bool(winning_returns),
            "maxWinningTicketReturn": max(winning_returns, default=0),
            "refundedBets": refunded_bets,
        })
    return reconciled


def live_select(historical, live_candidates, min_bets, min_days):
    history = collections.defaultdict(list)
    for r in sorted(historical, key=lambda row: (row["raceDate"], row["raceId"])):
        normalized = {**r, "day": dt.date.fromisoformat(r["raceDate"]),
                      "stake": r["stakeYen"], "paid": r["returnYen"]}
        expert = (r["strategy"], int(r["windowDays"]), int(r.get("lagDays", 0)))
        history[expert].append(normalized)
    by_group = collections.defaultdict(list)
    distinct = set()
    for row in live_candidates:
        validate_candidate(row, settled=False)
        key = (row["raceId"], row["strategy"], int(row["windowDays"]),
               int(row.get("lagDays", 0)))
        if key in distinct:
            raise ValueError("DUPLICATE_LIVE_CANDIDATE")
        distinct.add(key)
        by_group[(row["raceDate"], row["venue"])].append(row)
    outputs = []
    for (date, venue), group in sorted(by_group.items()):
        day = dt.date.fromisoformat(date)
        races = {r["raceId"] for r in group}
        by_strategy = collections.defaultdict(list)
        for row in group:
            by_strategy[(row["strategy"], int(row["windowDays"]),
                         int(row.get("lagDays", 0)))].append(row)
        complete = {key for key, rr in by_strategy.items()
                    if {r["raceId"] for r in rr} == races and len(rr) == len(races)}
        picked = CORE.choose(history, day, venue, complete, min_bets, min_days)
        if picked is None or len(races) < 3:
            outputs.append({"date": date, "venue": venue, "status": "NO_VERIFIED_MODEL",
                            "races": len(races)})
            continue
        outputs.append({"date": date, "venue": venue, "status": "RESEARCH_SELECTION_ONLY",
                        "strategy": picked[0], "windowDays": picked[1],
                        "lagDays": picked[2],
                        "races": len(races), "bets": by_strategy[picked]})
    return outputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical-candidates", required=True)
    ap.add_argument("--official-payouts", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--live-candidates")
    ap.add_argument("--min-history-bets", type=int, default=100)
    ap.add_argument("--min-history-days", type=int, default=20)
    ap.add_argument("--evaluation-start", help="First untouched out-of-sample date")
    ap.add_argument("--evaluation-through", help="Last untouched out-of-sample date")
    args = ap.parse_args()
    historical = reconcile(read_jsonl(args.historical_candidates),
                           read_jsonl(args.official_payouts))
    # The source data has not magically become a true prospective holdout.
    # This report is an exploratory walk-forward diagnostic, not authorization
    # to promote a profitable model. Independent future frozen tests are required.
    result = CORE.evaluate(
        [{**r, "day": dt.date.fromisoformat(r["raceDate"]), "stake": r["stakeYen"],
          "paid": r["returnYen"]} for r in historical],
        args.min_history_bets, args.min_history_days,
        eval_start=dt.date.fromisoformat(args.evaluation_start) if args.evaluation_start else None,
        eval_through=dt.date.fromisoformat(args.evaluation_through) if args.evaluation_through else None)
    result["method"] = "prospective_candidate_decisions_plus_actual_JRA_payout_table"
    result["payoutsRecomputedFromTickets"] = True
    result["prospectiveIndependentHoldoutVerified"] = False
    result["productionPromotionAllowed"] = False
    if args.live_candidates:
        result["prospectiveSuggestions"] = live_select(
            historical, read_jsonl(args.live_candidates),
            args.min_history_bets, args.min_history_days)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                      encoding="utf-8")
    print(json.dumps({"overall": result["overall"],
                      "candidateVenueDays": len(result["decisions"]),
                      "blockedVenueDays": len(result["skippedVenueDays"]),
                      "productionPromotionAllowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
