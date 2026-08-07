import gzip
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "artifacts" / "completion-search-dataset.pkl.gz"
OUTPUT = ROOT / "analysis-results" / "exploration-joint-contextual-online.json"

SEED = 202608080811
RNG = np.random.default_rng(SEED)
HOLDOUT_START = "2026-01-01"

COURSES = {
    "ライト": {
        "budget": 2000,
        "tickets": 6,
        "types": ("単勝", "ワイド", "馬連"),
        "max_share": 0.40,
        "learn_cap_multiple": 8.0,
        "type_weights": {"単勝": 1.0, "ワイド": 2.4, "馬連": 2.8},
    },
    "スタンダード": {
        "budget": 5000,
        "tickets": 15,
        "types": ("単勝", "ワイド", "馬連", "馬単", "3連複"),
        "max_share": 0.30,
        "learn_cap_multiple": 12.0,
        "type_weights": {"単勝": 0.7, "ワイド": 1.5, "馬連": 1.8, "馬単": 2.0, "3連複": 2.6},
    },
    "プレミアム": {
        "budget": 10000,
        "tickets": 16,
        "types": ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"),
        "max_share": 0.24,
        "learn_cap_multiple": 18.0,
        "type_weights": {"単勝": 0.5, "ワイド": 0.9, "馬連": 1.1, "馬単": 1.5, "3連複": 2.0, "3連単": 3.2},
    },
}
VARIANTS = ("market", "form", "blend", "value")
POLICY_COUNT = 4800
PRIOR_RACES = 36.0
PRIOR_ROI = 72.5
CTX_WEIGHTS = {
    "global": 0.12,
    "venue": 0.23,
    "race_no": 0.16,
    "field": 0.12,
    "venue_field": 0.22,
    "fav": 0.15,
}

UNORDERED = {"ワイド", "馬連", "3連複"}


def canon(bet_type, horses):
    values = tuple(int(x) for x in horses)
    if bet_type in UNORDERED:
        values = tuple(sorted(values))
    return values


def payout_key(bet_type, horses):
    values = canon(bet_type, horses)
    return f'{bet_type}:{"-".join(map(str, values))}'


def field_band(n):
    if n <= 10:
        return 0
    if n <= 13:
        return 1
    if n <= 15:
        return 2
    return 3


def fav_band(odds):
    if odds <= 2.0:
        return 0
    if odds <= 3.0:
        return 1
    if odds <= 5.0:
        return 2
    return 3


def zscore(values):
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return arr
    std = float(arr.std())
    if std < 1e-9:
        return np.zeros_like(arr)
    return (arr - float(arr.mean())) / std


def form_score(features):
    f = np.asarray(features, dtype=np.float64)

    def g(i):
        return float(f[i]) if i < len(f) and math.isfinite(float(f[i])) else 0.0

    return (
        2.4 * g(3)
        + 1.7 * g(4)
        + 1.2 * g(5)
        + 0.5 * g(6)
        + 1.5 * g(7)
        + 1.9 * g(8)
        + 0.8 * g(9)
        + 0.9 * g(11)
        + 0.7 * g(12)
        + 1.0 * g(13)
        + 0.7 * g(14)
        + 1.3 * g(17)
        + 1.0 * g(18)
        + 0.5 * g(19)
        + 0.4 * g(20)
        + 0.6 * g(21)
        + 0.45 * g(22)
        + 0.25 * g(23)
        + 0.2 * g(24)
    )


def ranking_maps(race):
    runners = list(race["runners"])
    markets = np.asarray(
        [max(1e-12, float(r.get("market") or 0.0)) for r in runners], dtype=np.float64
    )
    forms = np.asarray([form_score(r.get("features") or []) for r in runners], dtype=np.float64)
    mz = zscore(np.log(markets))
    fz = zscore(forms)
    scores = {
        "market": mz,
        "form": fz,
        "blend": 0.58 * mz + 0.42 * fz,
        "value": fz - 0.72 * mz,
    }
    result = {}
    for name, values in scores.items():
        order = np.argsort(-values, kind="stable")
        result[name] = [int(runners[i]["horseNo"]) for i in order]
    return result


def primitive_catalog():
    rows = []
    for variant in VARIANTS:
        for rank in range(1, 11):
            rows.append((variant, "単勝", (rank,)))
        for a in range(1, 11):
            for b in range(a + 1, 11):
                rows.append((variant, "ワイド", (a, b)))
                rows.append((variant, "馬連", (a, b)))
        for a in range(1, 9):
            for b in range(1, 9):
                if a != b:
                    rows.append((variant, "馬単", (a, b)))
        for a in range(1, 9):
            for b in range(a + 1, 9):
                for c in range(b + 1, 9):
                    rows.append((variant, "3連複", (a, b, c)))
        for a in range(1, 8):
            for b in range(1, 8):
                if b == a:
                    continue
                for c in range(1, 8):
                    if c == a or c == b:
                        continue
                    rows.append((variant, "3連単", (a, b, c)))
    return rows


PRIMITIVES = primitive_catalog()
BY_VARIANT_TYPE = defaultdict(list)
for idx, (variant, bet_type, ranks) in enumerate(PRIMITIVES):
    BY_VARIANT_TYPE[(variant, bet_type)].append(idx)


def build_payout_matrix(races):
    matrix = np.zeros((len(races), len(PRIMITIVES)), dtype=np.float32)
    contexts = []
    for i, race in enumerate(races):
        maps = ranking_maps(race)
        refunds = set(int(x) for x in (race.get("refunds") or set()))
        field = len(race["runners"])
        markets = sorted(
            [r for r in race["runners"] if float(r.get("market") or 0) > 0],
            key=lambda r: -float(r.get("market") or 0),
        )
        fav_odds = float(markets[0].get("winOdds") or 99.0) if markets else 99.0
        contexts.append(
            {
                "date": race["raceDate"],
                "venue": race["venue"],
                "raceNo": int(race["raceNo"]),
                "fieldBand": field_band(field),
                "favBand": fav_band(fav_odds),
            }
        )
        payouts = race.get("payouts") or {}
        for j, (variant, bet_type, ranks) in enumerate(PRIMITIVES):
            order = maps[variant]
            if max(ranks) > len(order):
                continue
            horses = tuple(order[r - 1] for r in ranks)
            if len(set(horses)) != len(horses):
                continue
            if refunds and any(h in refunds for h in horses):
                matrix[i, j] = 100.0
            else:
                matrix[i, j] = float(payouts.get(payout_key(bet_type, horses), 0.0) or 0.0)
    return matrix, contexts


def allocate_units(spec, selected, variant):
    total_units = spec["budget"] // 100
    ticket_count = spec["tickets"]
    max_units = max(1, int(math.floor(total_units * spec["max_share"])))
    units = np.ones(ticket_count, dtype=np.int16)
    remaining = total_units - ticket_count

    quality = []
    for primitive_idx in selected:
        _, bet_type, ranks = PRIMITIVES[primitive_idx]
        longshot = sum(ranks) / len(ranks)
        base = spec["type_weights"][bet_type]
        variant_boost = {"market": 1.0, "form": 0.95, "blend": 1.05, "value": 1.12}[variant]
        quality.append(
            max(0.05, base * variant_boost * (0.78 + 0.055 * longshot) * RNG.gamma(1.6, 1.0))
        )
    quality = np.asarray(quality, dtype=np.float64)

    while remaining > 0:
        eligible = np.where(units < max_units)[0]
        if len(eligible) == 0:
            eligible = np.arange(ticket_count)
        weights = quality[eligible] / np.maximum(1.0, units[eligible] ** 0.65)
        weights = weights / weights.sum()
        choice = int(RNG.choice(eligible, p=weights))
        units[choice] += 1
        remaining -= 1
    return units


def baseline_policy(course, spec, variant):
    patterns = {
        "ライト": {
            "単勝": [(1,)],
            "ワイド": [(1, 2), (1, 3), (2, 3)],
            "馬連": [(1, 2), (1, 3)],
        },
        "スタンダード": {
            "単勝": [(1,), (2,)],
            "ワイド": [(1, 2), (1, 3), (2, 3), (1, 4)],
            "馬連": [(1, 2), (1, 3), (2, 3)],
            "馬単": [(1, 2), (2, 1), (1, 3)],
            "3連複": [(1, 2, 3), (1, 2, 4), (1, 3, 4)],
        },
        "プレミアム": {
            "単勝": [(1,), (2,)],
            "ワイド": [(1, 2), (1, 3), (2, 3)],
            "馬連": [(1, 2), (1, 3), (2, 3)],
            "馬単": [(1, 2), (2, 1), (1, 3)],
            "3連複": [(1, 2, 3), (1, 2, 4), (1, 3, 4)],
            "3連単": [(1, 2, 3), (1, 3, 2)],
        },
    }
    selected = []
    for bet_type in spec["types"]:
        for ranks in patterns[course].get(bet_type, []):
            for idx in BY_VARIANT_TYPE[(variant, bet_type)]:
                if PRIMITIVES[idx][2] == ranks:
                    selected.append(idx)
                    break
            if len(selected) >= spec["tickets"]:
                break
        if len(selected) >= spec["tickets"]:
            break
    for bet_type in spec["types"]:
        for idx in BY_VARIANT_TYPE[(variant, bet_type)]:
            if idx not in selected:
                selected.append(idx)
            if len(selected) >= spec["tickets"]:
                break
        if len(selected) >= spec["tickets"]:
            break
    units = allocate_units(spec, selected[: spec["tickets"]], variant)
    return np.asarray(selected[: spec["tickets"]], dtype=np.int32), units


def generate_policies(course, spec, count):
    selected_rows = []
    unit_rows = []
    per_variant = max(1, count // len(VARIANTS))
    required = list(spec["types"])
    for variant in VARIANTS:
        base_idx, base_units = baseline_policy(course, spec, variant)
        selected_rows.append(base_idx)
        unit_rows.append(base_units)
        for _ in range(per_variant - 1):
            selected = []
            used = set()
            for bet_type in required:
                choices = BY_VARIANT_TYPE[(variant, bet_type)]
                idx = int(RNG.choice(choices))
                selected.append(idx)
                used.add(idx)
            type_probs = np.asarray([spec["type_weights"][t] for t in required], dtype=np.float64)
            type_probs /= type_probs.sum()
            guard = 0
            while len(selected) < spec["tickets"] and guard < 1000:
                guard += 1
                bet_type = str(RNG.choice(required, p=type_probs))
                idx = int(RNG.choice(BY_VARIANT_TYPE[(variant, bet_type)]))
                if idx in used:
                    continue
                selected.append(idx)
                used.add(idx)
            if len(selected) != spec["tickets"]:
                continue
            units = allocate_units(spec, selected, variant)
            selected_rows.append(np.asarray(selected, dtype=np.int32))
            unit_rows.append(units)
    return np.stack(selected_rows), np.stack(unit_rows)


def policy_return_matrix(payout_matrix, ticket_idx, units, chunk=400):
    n = payout_matrix.shape[0]
    p = ticket_idx.shape[0]
    out = np.zeros((n, p), dtype=np.float32)
    for start in range(0, p, chunk):
        end = min(p, start + chunk)
        block = np.zeros((n, end - start), dtype=np.float32)
        for t in range(ticket_idx.shape[1]):
            block += payout_matrix[:, ticket_idx[start:end, t]] * units[start:end, t][None, :]
        out[:, start:end] = block
    return out


def shrunk_roi(sum_return, count, budget):
    denom_count = count + PRIOR_RACES
    return (
        (sum_return + PRIOR_RACES * budget * (PRIOR_ROI / 100.0))
        / (denom_count * budget)
        * 100.0
    )


def evaluate_course(course, spec, raw_returns, contexts):
    p = raw_returns.shape[1]
    budget = spec["budget"]
    cap = budget * spec["learn_cap_multiple"]
    capped = np.minimum(raw_returns, cap).astype(np.float32)

    venues = sorted(set(c["venue"] for c in contexts))
    venue_id = {v: i for i, v in enumerate(venues)}
    gsum = np.zeros(p, dtype=np.float64)
    gn = 0
    vsum = np.zeros((len(venues), p), dtype=np.float64)
    vn = np.zeros(len(venues), dtype=np.int32)
    rsum = np.zeros((13, p), dtype=np.float64)
    rn = np.zeros(13, dtype=np.int32)
    fsum = np.zeros((4, p), dtype=np.float64)
    fn = np.zeros(4, dtype=np.int32)
    vfsum = np.zeros((len(venues), 4, p), dtype=np.float64)
    vfn = np.zeros((len(venues), 4), dtype=np.int32)
    osum = np.zeros((4, p), dtype=np.float64)
    on = np.zeros(4, dtype=np.int32)

    day_groups = defaultdict(list)
    for i, c in enumerate(contexts):
        day_groups[(c["date"], c["venue"])].append(i)
    keys = sorted(day_groups)

    selected_records = []
    coverage_failures = []
    for key in keys:
        idxs = day_groups[key]
        if len(idxs) < 5:
            coverage_failures.append({"date": key[0], "venue": key[1], "races": len(idxs)})
            continue
        race_choices = []
        for i in idxs:
            c = contexts[i]
            v = venue_id[c["venue"]]
            r = c["raceNo"]
            f = c["fieldBand"]
            o = c["favBand"]
            score = (
                CTX_WEIGHTS["global"] * shrunk_roi(gsum, gn, budget)
                + CTX_WEIGHTS["venue"] * shrunk_roi(vsum[v], int(vn[v]), budget)
                + CTX_WEIGHTS["race_no"] * shrunk_roi(rsum[r], int(rn[r]), budget)
                + CTX_WEIGHTS["field"] * shrunk_roi(fsum[f], int(fn[f]), budget)
                + CTX_WEIGHTS["venue_field"]
                * shrunk_roi(vfsum[v, f], int(vfn[v, f]), budget)
                + CTX_WEIGHTS["fav"] * shrunk_roi(osum[o], int(on[o]), budget)
            )
            best = int(np.argmax(score))
            race_choices.append((float(score[best]), -c["raceNo"], i, best))
        race_choices.sort(reverse=True)
        chosen = race_choices[:5]
        for expected, _, i, policy in chosen:
            selected_records.append(
                {
                    "raceIndex": i,
                    "date": contexts[i]["date"],
                    "venue": contexts[i]["venue"],
                    "raceNo": contexts[i]["raceNo"],
                    "policy": policy,
                    "expectedScore": expected,
                    "returnYen": float(raw_returns[i, policy]),
                }
            )

        # Current venue-day results are applied only after all five selections are frozen.
        for i in idxs:
            c = contexts[i]
            row = capped[i].astype(np.float64)
            v = venue_id[c["venue"]]
            r = c["raceNo"]
            f = c["fieldBand"]
            o = c["favBand"]
            gsum += row
            gn += 1
            vsum[v] += row
            vn[v] += 1
            rsum[r] += row
            rn[r] += 1
            fsum[f] += row
            fn[f] += 1
            vfsum[v, f] += row
            vfn[v, f] += 1
            osum[o] += row
            on[o] += 1

    def summarize(records):
        if not records:
            return {
                "races": 0,
                "stakeYen": 0,
                "returnYen": 0,
                "roiPct": None,
                "roiWithoutMaxPct": None,
                "roiWithoutTop1Pct": None,
            }
        returns = np.asarray([x["returnYen"] for x in records], dtype=np.float64)
        stake = len(records) * budget
        total = float(returns.sum())
        max_removed = total - float(returns.max())
        k = max(1, int(math.ceil(len(returns) * 0.01)))
        top_removed = total - float(np.sort(returns)[-k:].sum())
        return {
            "races": len(records),
            "stakeYen": int(stake),
            "returnYen": int(round(total)),
            "roiPct": total / stake * 100.0,
            "roiWithoutMaxPct": max_removed / stake * 100.0,
            "roiWithoutTop1Pct": top_removed / stake * 100.0,
            "hitRatePct": float(np.mean(returns > 0) * 100.0),
            "maxRaceReturnYen": int(round(float(returns.max()))),
        }

    full = summarize(selected_records)
    holdout = summarize([x for x in selected_records if x["date"] >= HOLDOUT_START])
    quarterly = {}
    byq = defaultdict(list)
    for x in selected_records:
        y, m = map(int, x["date"][:7].split("-"))
        q = (m - 1) // 3 + 1
        byq[f"{y}-Q{q}"].append(x)
    for q, rows in sorted(byq.items()):
        quarterly[q] = summarize(rows)

    return {
        "course": course,
        "full": full,
        "holdout": holdout,
        "coverageFailures": coverage_failures,
        "selectedVenueDays": len(keys) - len(coverage_failures),
        "quarterly": quarterly,
    }


def main():
    with gzip.open(DATASET, "rb") as handle:
        payload = pickle.load(handle)
    races = list(payload["races"])
    races.sort(key=lambda r: (r["raceDate"], r["venue"], int(r["raceNo"])))
    payout_matrix, contexts = build_payout_matrix(races)

    results = {}
    policy_meta = {}
    for course, spec in COURSES.items():
        ticket_idx, units = generate_policies(course, spec, POLICY_COUNT)
        raw_returns = policy_return_matrix(payout_matrix, ticket_idx, units)
        result = evaluate_course(course, spec, raw_returns, contexts)
        results[course] = result
        policy_meta[course] = {
            "policies": int(ticket_idx.shape[0]),
            "ticketsPerRace": spec["tickets"],
            "budgetYen": spec["budget"],
            "requiredTypes": list(spec["types"]),
            "maxTicketShare": spec["max_share"],
        }

    completion = True
    reasons = []
    for course, result in results.items():
        f = result["full"]
        h = result["holdout"]
        checks = {
            "fullRoi200": f["roiPct"] is not None and f["roiPct"] >= 200.0,
            "holdoutRoi200": h["roiPct"] is not None and h["roiPct"] >= 200.0,
            "holdout100Races": h["races"] >= 100,
            "top1Trim100": f["roiWithoutTop1Pct"] is not None
            and f["roiWithoutTop1Pct"] >= 100.0,
            "maxTrim100": f["roiWithoutMaxPct"] is not None
            and f["roiWithoutMaxPct"] >= 100.0,
            "coverage": not result["coverageFailures"],
        }
        result["checks"] = checks
        if not all(checks.values()):
            completion = False
            reasons.append({"course": course, "failed": [k for k, v in checks.items() if not v]})

    out = {
        "schema": 1,
        "explorationId": "joint-contextual-online-20260808",
        "modelVersion": None,
        "source": {
            "races": len(races),
            "start": races[0]["raceDate"],
            "end": races[-1]["raceDate"],
            "newRaceIngestion": False,
            "oldVersionResultsUsed": False,
            "actualJraPayoutsOnly": True,
            "currentResultLeakage": False,
        },
        "algorithm": {
            "rankingVariants": list(VARIANTS),
            "policyCountTargetPerCourse": POLICY_COUNT,
            "minimumRacesPerVenueDay": 5,
            "holdoutStart": HOLDOUT_START,
            "onlineUpdate": "venue-day results update only after all five selections for that venue-day are frozen",
            "learningReturnCapMultiples": {
                k: v["learn_cap_multiple"] for k, v in COURSES.items()
            },
            "contextWeights": CTX_WEIGHTS,
        },
        "policyMeta": policy_meta,
        "courses": results,
        "completionPassed": completion,
        "promotionEligible": completion,
        "failureReasons": reasons,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "completionPassed": completion,
                "courses": {
                    c: {
                        "fullRoi": r["full"]["roiPct"],
                        "holdoutRoi": r["holdout"]["roiPct"],
                        "trimTop1": r["full"]["roiWithoutTop1Pct"],
                        "races": r["full"]["races"],
                    }
                    for c, r in results.items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
