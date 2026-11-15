#!/usr/bin/env python3
"""Find qualified *method-generating* cash-ROI models, not a best loser.

A model is NEVER an individual strategy, an arbitrary ROI<200 experiment,
or an all-period hindsight allocation. Competing prediction methods are
already-frozen per-race ticket generators. This learner generates many
past-only meta-methods that adaptively switch the prediction algorithm,
training-window length and optional gap independently per venue-day.

Discovery uses validation outcomes only, with a subsequently untouched
holdout (fixed by CLI, not chosen after viewing returns). No model is
serialized unless all gates hold on BOTH time-separated periods:
  paid cash / stake >= 200%, cash removing largest paid race with stake
  retained >= 200%, hit races >= 20%, >= 3 races for every venue-day,
  complete source coverage and strictly pre-T15 predictions.
All intermediate computations are *search internals*, not model candidates.
No production write or auto-promotion is implemented.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import importlib.util
import itertools
import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "cash_meta_source", HERE / "research-adaptive-roi-cash-verifier.py")
CASH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CASH)

METHODS = ("trimmed_cash", "net_cash", "monthly_floor", "median_month")
SCOPES = ("global", "venue", "adaptive")
SHRINKAGES = (100, 300, 1000)
MIN_BETS = (24, 80)
MIN_DAYS = 6
MIN_RACES_PER_VENUE_DAY = 3


@dataclasses.dataclass(frozen=True)
class Algorithm:
    objective: str
    scope: str
    shrink: int
    min_bets: int

    def label(self):
        return f"{self.objective}:{self.scope}:shrink{self.shrink}:min{self.min_bets}"


def generate_methods():
    return [Algorithm(*parts) for parts in itertools.product(
        METHODS, SCOPES, SHRINKAGES, MIN_BETS)]


def normalize(cash_rows):
    out = []
    seen = set()
    for row in cash_rows:
        if row["stakeYen"] <= 0 or row["returnYen"] < 0:
            raise ValueError("INVALID_CASH_LEDGER")
        key = (row["raceId"], row["strategy"], int(row["windowDays"]),
               int(row.get("lagDays", 0)))
        if key in seen:
            raise ValueError("DUPLICATE_STRATEGY_DECISION")
        seen.add(key)
        out.append({**row, "day": dt.date.fromisoformat(row["raceDate"]),
                    "stake": int(row["stakeYen"]), "paid": int(row["returnYen"]),
                    "windowDays": int(row["windowDays"]),
                    "lagDays": int(row.get("lagDays", 0))})
    return sorted(out, key=lambda x: (x["day"], x["venue"], x["raceId"]))


def cash_metrics(rows):
    if not rows:
        return None
    stake = sum(r["stake"] for r in rows)
    paid = sum(r["paid"] for r in rows)
    largest_race = max(r["paid"] for r in rows)
    largest_ticket = max(int(r.get("maxWinningTicketReturn", r["paid"])) for r in rows)
    hits = sum(bool(r.get("hitRace", r["paid"] > 0)) for r in rows)
    return {
        "races": len(rows),
        "stakeYen": stake, "paidYen": paid,
        "profitYen": paid - stake,
        "cashRoiPct": 100 * paid / stake,
        # Removing an entire race payout is at least as strict as removing a ticket.
        "minusLargestRaceCashRoiPct": 100 * (paid - largest_race) / stake,
        "minusLargestTicketCashRoiPct": 100 * (paid - largest_ticket) / stake,
        "hitRaces": hits, "hitRacePct": 100 * hits / len(rows),
    }


def expert_score(rows, method):
    # Every row is a real paid ticket record, not a horse-win prediction score.
    a = cash_metrics(rows)
    if not a:
        return -math.inf
    if method.objective == "trimmed_cash":
        raw = min(a["cashRoiPct"], a["minusLargestRaceCashRoiPct"])
    elif method.objective == "net_cash":
        # Net yen per 100 yen risked, clipped against largest payout sensitivity.
        raw = 100 + 0.6 * (a["cashRoiPct"] - 100) + 0.4 * (
            a["minusLargestRaceCashRoiPct"] - 100)
    elif method.objective in ("monthly_floor", "median_month"):
        monthly = collections.defaultdict(list)
        for r in rows:
            monthly[r["raceDate"][:7]].append(r)
        measured = sorted(cash_metrics(v)["minusLargestRaceCashRoiPct"] for v in monthly.values())
        if method.objective == "monthly_floor":
            raw = measured[max(0, len(measured) // 4 - 1)]
        else:
            raw = statistics.median(measured)
    else:
        raise ValueError("UNKNOWN_META_METHOD")
    return 100 + (raw - 100) * len(rows) / (len(rows) + method.shrink)


def choose_method(past, day, venue, candidates, method):
    scores = []
    for key in sorted(candidates):
        algorithm, window, lag = key
        history = past.get(key, ())
        recent = []
        for row in reversed(history):
            age = (day - row["day"]).days
            if age > lag + window:
                break
            if lag < age:
                recent.append(row)
        if len(recent) < method.min_bets:
            continue
        if len({r["day"] for r in recent}) < MIN_DAYS:
            continue
        if method.scope == "global":
            samples = recent
        else:
            local = [r for r in recent if r["venue"] == venue]
            enough = (len(local) >= method.min_bets and
                      len({r["day"] for r in local}) >= MIN_DAYS)
            if method.scope == "venue" and not enough:
                continue
            samples = local if enough else recent
        scores.append((expert_score(samples, method), len(samples), key))
    return max(scores)[2] if scores else None


def replay(rows, method, start, through):
    #  All models are chosen from previously settled dates; outcomes for day d
    #  become visible only once *every* venue on d has been processed.
    groups = collections.defaultdict(list)
    by_day = collections.defaultdict(list)
    for row in rows:
        groups[(row["day"], row["venue"])].append(row)
        by_day[row["day"]].append(row)
    past = collections.defaultdict(list)
    purchased = []
    skipped = []
    selections = []
    ordered = sorted(groups.items())
    for i, ((day, venue), group) in enumerate(ordered):
        if day > through:
            break
        if day >= start:
            by_key = collections.defaultdict(list)
            for r in group:
                by_key[(r["strategy"], r["windowDays"], r["lagDays"])].append(r)
            all_ids = {r["raceId"] for r in group}
            complete = {key for key, subset in by_key.items()
                        if len(subset) == len(all_ids) and
                        {r["raceId"] for r in subset} == all_ids}
            chosen = choose_method(past, day, venue, complete, method)
            if len(all_ids) < MIN_RACES_PER_VENUE_DAY or chosen is None:
                skipped.append((str(day), venue))
            else:
                bought = by_key[chosen]
                purchased.extend(bought)
                selections.append({"date": str(day), "venue": venue,
                                   "strategy": chosen[0], "windowDays": chosen[1],
                                   "lagDays": chosen[2], "races": len(bought)})
        if i+1 == len(ordered) or ordered[i+1][0][0] != day:
            for r in by_day[day]:
                key = (r["strategy"], r["windowDays"], r["lagDays"])
                past[key].append(r)
    eligible_groups = {(date, venue) for date, venue in groups if start <= date <= through}
    counted_groups = {(s["date"], s["venue"]) for s in selections}
    # ISO string and date comparison are deliberately kept explicit.
    selected_group_dates = {(dt.date.fromisoformat(s["date"]), s["venue"]) for s in selections}
    valid_coverage = not skipped and len(eligible_groups) > 0 and eligible_groups == selected_group_dates
    stats = cash_metrics(purchased)
    return {"money": stats, "coverage": valid_coverage, "selected": selections,
            "examinedVenueDays": len(eligible_groups), "skippedVenueDays": len(skipped)}


def gate(replayed):
    # Never turn a failed run into a "model".
    m = replayed["money"]
    return (replayed["coverage"] and m is not None
            and m["cashRoiPct"] >= 200
            and m["minusLargestRaceCashRoiPct"] >= 200
            and m["minusLargestTicketCashRoiPct"] >= 200
            and m["hitRacePct"] >= 20
            and m["races"] >= 3 * replayed["examinedVenueDays"])


def discover(rows, validation_start, validation_end, holdout_start, holdout_end,
             algorithms=None):
    if not (validation_start <= validation_end < holdout_start <= holdout_end):
        raise ValueError("OVERLAPPING_OR_INVALID_HOLDOUT_SPLIT")
    if not any(r["day"] < validation_start for r in rows):
        raise ValueError("NO_EARLIER_TRAINING_HISTORY")
    if not any(validation_start <= r["day"] <= validation_end for r in rows):
        raise ValueError("VALIDATION_PERIOD_NOT_COVERED")
    if not any(holdout_start <= r["day"] <= holdout_end for r in rows):
        raise ValueError("HOLDOUT_PERIOD_NOT_COVERED")
    variants = generate_methods() if algorithms is None else algorithms
    validation_qualified = []
    for method in variants:
        outcome = replay(rows, method, validation_start, validation_end)
        if gate(outcome):
            validation_qualified.append((method, outcome))
    # Pick EXACTLY ONE method on validation, prior to reading ANY holdout payouts.
    # Validation failures never become named or serialized "models".
    validation_qualified.sort(
        key=lambda p: (p[1]["money"]["minusLargestRaceCashRoiPct"],
                       p[1]["money"]["profitYen"]), reverse=True)
    model_list = []
    if validation_qualified:
        method, dev = validation_qualified[0]
        forward = replay(rows, method, holdout_start, holdout_end)
        if gate(forward):
            model_list.append({
                "metaMethod": dataclasses.asdict(method),
                "validation": dev["money"],
                "independentHoldout": forward["money"],
                "holdoutVenueDays": forward["examinedVenueDays"],
                "minimumRacesPerVenueDay": MIN_RACES_PER_VENUE_DAY,
                "prospectiveT15ExternallyVerified": False,
                "productionEligible": False,
            })
    return {
        "researchOnly": True,
        "modelDefinition": "ROI>=200, exclude largest paid race ROI>=200, paid hit>=20%, >=3 venue-day races",
        "searchArchitecture": "Generate meta-methods; switch algorithms, historical horizons and embargo using only prior dates",
        "methodsGenerated": len(variants),
        "validationQualifiedCount": len(validation_qualified),
        "forwardVerifiedCount": len(model_list),
        "models": model_list,
        "historicalFrozenTicketInputsRequired": True,
        "externalJraSourceReconciliationRequired": True,
        "productionPromotionAllowed": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--historical-candidates", required=True,
                   help="Authentic pre-T15 frozen predictions from all algorithms")
    p.add_argument("--official-payouts", required=True,
                   help="Independently captured final JRA cash payout table")
    p.add_argument("--validation-start", required=True)
    p.add_argument("--validation-end", required=True)
    p.add_argument("--holdout-start", required=True)
    p.add_argument("--holdout-end", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    rows = normalize(CASH.reconcile(
        CASH.read_jsonl(a.historical_candidates),
        CASH.read_jsonl(a.official_payouts)))
    report = discover(rows, *(
        dt.date.fromisoformat(x) for x in
        (a.validation_start, a.validation_end,
         a.holdout_start, a.holdout_end)))
    dest = Path(a.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({
        "methodsGenerated": report["methodsGenerated"],
        "validationQualifiedCount": report["validationQualifiedCount"],
        "forwardVerifiedCount": report["forwardVerifiedCount"],
        "modelList": report["models"],
        "productionPromotionAllowed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
