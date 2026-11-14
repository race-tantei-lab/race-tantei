#!/usr/bin/env python3
"""Leakage-safe adaptive-window cash-ROI meta selector. Research only.

Input JSONL: one record per historically frozen strategy/race decision:
raceDate, venue, raceId, strategy, windowDays, stakeYen, returnYen,
lockedAt, startTimeJst. Only bets genuinely frozen before T-15 are valid.
Each (raceId,strategy,windowDays) must have one record. A strategy must
provide complete coverage of the target venue/day to be eligible.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import math
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
WINDOWS = (90, 180, 365, 730, 1095, 1825, 3650)
MIN_HISTORY_BETS = 100
MIN_DAYS = 20
MIN_VENUE_RACES = 3


def parse_time(value):
    result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(JST)


def load_rows(path):
    rows = []
    seen = set()
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("raceDate", "venue", "raceId", "strategy", "windowDays",
                        "stakeYen", "returnYen", "lockedAt", "startTimeJst"):
                if key not in row:
                    raise ValueError(f"missing {key}")
            day = dt.date.fromisoformat(row["raceDate"])
            start = parse_time(f"{day.isoformat()}T{row['startTimeJst']}+09:00")
            if parse_time(row["lockedAt"]) > start - dt.timedelta(minutes=15):
                raise ValueError(f"late bet lock: {row['raceId']}")
            stake, paid = int(row["stakeYen"]), int(row["returnYen"])
            if stake <= 0 or paid < 0 or stake % 100 or paid % 10:
                raise ValueError("invalid stake or payout")
            key = (row["raceId"], row["strategy"], int(row["windowDays"]))
            if key in seen:
                raise ValueError(f"duplicate decision {key}")
            seen.add(key)
            rows.append({**row, "day": day, "stake": stake, "paid": paid,
                         "windowDays": int(row["windowDays"])})
    rows.sort(key=lambda x: (x["day"], x["venue"], x["raceId"]))
    return rows


def stats(rows):
    stake = sum(r["stake"] for r in rows)
    paid = sum(r["paid"] for r in rows)
    biggest = max((r["paid"] for r in rows), default=0)
    hits = sum(r["paid"] > 0 for r in rows)
    return {"bets": len(rows), "stakeYen": stake, "returnYen": paid,
            "roiPct": 100 * paid / stake if stake else None,
            "roiWithoutLargestPct": 100 * (paid - biggest) / stake if stake else None,
            "hitPct": 100 * hits / len(rows) if rows else None}


def choose(history, target_day, target_venue, candidates, min_bets, min_days):
    scored = []
    for candidate in sorted(candidates):
        strategy, window = candidate
        eligible = [r for r in history
                    if r["strategy"] == strategy and r["windowDays"] == window
                    and r["day"] < target_day
                    and (target_day - r["day"]).days <= window]
        if len(eligible) < min_bets or len({r["day"] for r in eligible}) < min_days:
            continue
        # Venue-specific evidence is useful, but insufficient samples
        # must fall back to global history, not to future information.
        venue_rows = [r for r in eligible if r["venue"] == target_venue]
        sample = venue_rows if (len(venue_rows) >= min_bets and
                                 len({r["day"] for r in venue_rows}) >= min_days) else eligible
        s = stats(sample)
        # Conservative objective; extreme single payouts never dominate.
        score = min(s["roiPct"], s["roiWithoutLargestPct"])
        # Shrink toward break-even to reduce short-sample selection noise.
        score = 100 + (score - 100) * len(sample) / (len(sample) + 300)
        scored.append((score, len(sample), candidate))
    if not scored:
        return None
    return max(scored)[2]


def evaluate(rows, min_bets=MIN_HISTORY_BETS, min_days=MIN_DAYS,
             min_venue_races=MIN_VENUE_RACES):
    groups = collections.defaultdict(list)
    history = []
    for row in rows:
        groups[(row["day"], row["venue"])].append(row)
    selected, skipped, decisions = [], [], []
    ordered_groups = sorted(groups.items())
    for index, ((day, venue), group) in enumerate(ordered_groups):
        by_candidate = collections.defaultdict(list)
        for row in group:
            by_candidate[(row["strategy"], row["windowDays"])].append(row)
        race_ids = {r["raceId"] for r in group}
        # Require complete identical race coverage to prevent survivor bias.
        candidates = {key for key, rr in by_candidate.items()
                      if {r["raceId"] for r in rr} == race_ids
                      and len(rr) == len(race_ids)}
        choice = choose(history, day, venue, candidates, min_bets, min_days)
        if len(race_ids) < min_venue_races or choice is None:
            skipped.append({"date": day.isoformat(), "venue": venue,
                            "reason": "coverage_or_history", "races": len(race_ids)})
        else:
            bets = by_candidate[choice]
            selected.extend(bets)
            decisions.append({"date": day.isoformat(), "venue": venue,
                              "strategy": choice[0], "windowDays": choice[1],
                              "races": len(bets), **stats(bets)})
        # Results from every venue on this date become visible tomorrow only.
        if index + 1 == len(ordered_groups) or ordered_groups[index + 1][0][0] != day:
            history.extend(r for r in rows if r["day"] == day)
    report = {"researchOnly": True, "productionModified": False,
              "overall": stats(selected), "decisions": decisions,
              "skippedVenueDays": skipped,
              "years": {str(year): stats([r for r in selected if r["day"].year == year])
                        for year in sorted({r["day"].year for r in selected})}}
    report["meetsRoi200"] = (report["overall"]["roiPct"] is not None
                              and report["overall"]["roiPct"] >= 200
                              and report["overall"]["roiWithoutLargestPct"] >= 200)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-history-bets", type=int, default=MIN_HISTORY_BETS)
    parser.add_argument("--min-history-days", type=int, default=MIN_DAYS)
    args = parser.parse_args()
    result = evaluate(load_rows(args.input), args.min_history_bets, args.min_history_days)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                           default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "decisions"},
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
