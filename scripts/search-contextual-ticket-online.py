import gzip
import importlib.util
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "artifacts" / "completion-search-dataset.pkl.gz"
OUTPUT = ROOT / "analysis-results" / "exploration-contextual-ticket-online.json"
HELPER_PATH = ROOT / "scripts" / "search-joint-contextual-online.py"

spec = importlib.util.spec_from_file_location("joint_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

PRIMITIVES = helper.PRIMITIVES
BY_VARIANT_TYPE = helper.BY_VARIANT_TYPE
COURSES = helper.COURSES
UNORDERED = helper.UNORDERED
HOLDOUT_START = "2026-01-01"

PRIOR_ROI = 75.0
GLOBAL_PRIOR_N = 45.0
CTX_PRIOR_N = 20.0
TYPE_CAP = {
    "単勝": 2500.0,
    "ワイド": 5000.0,
    "馬連": 10000.0,
    "馬単": 15000.0,
    "3連複": 25000.0,
    "3連単": 50000.0,
}
CTX_WEIGHTS = {
    "global": 0.10,
    "venue": 0.12,
    "race_no": 0.10,
    "field": 0.08,
    "fav": 0.08,
    "surface": 0.07,
    "distance": 0.07,
    "venue_field": 0.14,
    "race_field": 0.11,
    "surface_distance": 0.07,
    "venue_surface": 0.06,
}
ROBUST_WEIGHT = 0.28


def distance_band(distance):
    d = int(distance or 0)
    if d < 1400:
        return 0
    if d < 1800:
        return 1
    if d < 2200:
        return 2
    return 3


def surface_band(surface):
    text = str(surface or "")
    if text == "芝":
        return 0
    if text == "ダート":
        return 1
    return 2


def class_band(level):
    x = float(level or 0.0)
    if x <= 0:
        return 0
    if x <= 1.5:
        return 1
    if x <= 3.5:
        return 2
    return 3


def race_contexts(races, basic_contexts):
    out = []
    for race, base in zip(races, basic_contexts):
        row = dict(base)
        row["surface"] = surface_band(race.get("surface"))
        row["distance"] = distance_band(race.get("distanceM"))
        row["class"] = class_band(race.get("classLevel"))
        out.append(row)
    return out


def valid_mask(field_size):
    return np.asarray([max(ranks) <= field_size for _, _, ranks in PRIMITIVES], dtype=bool)


def type_mask(types):
    allowed = set(types)
    return np.asarray([bet_type in allowed for _, bet_type, _ in PRIMITIVES], dtype=bool)


def context_roi(sum_arr, count_arr, global_est):
    return (sum_arr + global_est * CTX_PRIOR_N) / np.maximum(1e-9, count_arr + CTX_PRIOR_N)


def global_roi(gsum, gcount):
    return (gsum + PRIOR_ROI * GLOBAL_PRIOR_N) / np.maximum(1e-9, gcount + GLOBAL_PRIOR_N)


def actual_signature(race, primitive_idx, maps):
    variant, bet_type, ranks = PRIMITIVES[primitive_idx]
    order = maps[variant]
    if max(ranks) > len(order):
        return None
    horses = tuple(order[r - 1] for r in ranks)
    if bet_type in UNORDERED:
        horses = tuple(sorted(horses))
    return bet_type, horses


def pick_tickets(race, scores, course, spec):
    maps = helper.ranking_maps(race)
    field_size = len(race["runners"])
    valid = valid_mask(field_size)
    allowed = type_mask(spec["types"])
    usable = valid & allowed & np.isfinite(scores)
    selected = []
    signatures = set()

    for bet_type in spec["types"]:
        indices = np.where(usable & np.asarray([p[1] == bet_type for p in PRIMITIVES]))[0]
        if not len(indices):
            return None
        order = indices[np.argsort(-scores[indices])]
        chosen = None
        for idx in order:
            sig = actual_signature(race, int(idx), maps)
            if sig is None or sig in signatures:
                continue
            chosen = int(idx)
            signatures.add(sig)
            break
        if chosen is None:
            return None
        selected.append(chosen)

    all_order = np.where(usable)[0]
    all_order = all_order[np.argsort(-scores[all_order])]
    for idx in all_order:
        if len(selected) >= spec["tickets"]:
            break
        idx = int(idx)
        if idx in selected:
            continue
        sig = actual_signature(race, idx, maps)
        if sig is None or sig in signatures:
            continue
        selected.append(idx)
        signatures.add(sig)
    if len(selected) != spec["tickets"]:
        return None

    total_units = spec["budget"] // 100
    units = np.ones(len(selected), dtype=np.int16)
    remaining = total_units - len(selected)
    max_units = max(1, int(math.floor(total_units * spec["max_share"])))
    selected_scores = np.asarray([scores[idx] for idx in selected], dtype=np.float64)
    desirability = np.maximum(1.0, selected_scores - 55.0)
    if course == "スタンダード":
        desirability = np.power(desirability, 1.10)
    elif course == "プレミアム":
        desirability = np.power(desirability, 1.18)
    while remaining > 0:
        eligible = np.where(units < max_units)[0]
        if not len(eligible):
            eligible = np.arange(len(units))
        weight = desirability[eligible] / np.maximum(1.0, units[eligible] ** 0.70)
        weight = weight / weight.sum()
        j = int(eligible[np.argmax(weight)])
        units[j] += 1
        remaining -= 1

    portfolio_score = float(np.average(selected_scores, weights=units))
    return np.asarray(selected, dtype=np.int32), units, portfolio_score


def summarize(records, budget):
    if not records:
        return {
            "races": 0,
            "stakeYen": 0,
            "returnYen": 0,
            "roiPct": None,
            "roiWithoutMaxPct": None,
            "roiWithoutTop1Pct": None,
        }
    returns = np.asarray([r["returnYen"] for r in records], dtype=np.float64)
    stake = len(records) * budget
    total = float(returns.sum())
    k = max(1, int(math.ceil(len(returns) * 0.01)))
    return {
        "races": len(records),
        "stakeYen": int(stake),
        "returnYen": int(round(total)),
        "roiPct": total / stake * 100.0,
        "roiWithoutMaxPct": (total - float(returns.max())) / stake * 100.0,
        "roiWithoutTop1Pct": (total - float(np.sort(returns)[-k:].sum())) / stake * 100.0,
        "hitRatePct": float(np.mean(returns > 0) * 100.0),
        "maxRaceReturnYen": int(round(float(returns.max()))),
    }


def main():
    with gzip.open(DATASET, "rb") as handle:
        payload = pickle.load(handle)
    races = list(payload["races"])
    races.sort(key=lambda r: (r["raceDate"], r["venue"], int(r["raceNo"])))
    payout, basic = helper.build_payout_matrix(races)
    ctx = race_contexts(races, basic)
    primitive_count = payout.shape[1]

    venues = sorted(set(c["venue"] for c in ctx))
    vid = {v: i for i, v in enumerate(venues)}
    shapes = {
        "venue": (len(venues), primitive_count),
        "race_no": (13, primitive_count),
        "field": (4, primitive_count),
        "fav": (4, primitive_count),
        "surface": (3, primitive_count),
        "distance": (4, primitive_count),
        "class": (4, primitive_count),
        "venue_field": (len(venues), 4, primitive_count),
        "race_field": (13, 4, primitive_count),
        "surface_distance": (3, 4, primitive_count),
        "venue_surface": (len(venues), 3, primitive_count),
    }
    sums = {k: np.zeros(shape, dtype=np.float64) for k, shape in shapes.items()}
    counts = {k: np.zeros(shape, dtype=np.float32) for k, shape in shapes.items()}
    gsum = np.zeros(primitive_count, dtype=np.float64)
    gcount = np.zeros(primitive_count, dtype=np.float32)

    type_caps = np.asarray([TYPE_CAP[t] for _, t, _ in PRIMITIVES], dtype=np.float64)
    day_groups = defaultdict(list)
    for i, c in enumerate(ctx):
        day_groups[(c["date"], c["venue"])].append(i)

    records = {course: [] for course in COURSES}
    coverage = []
    for day_key in sorted(day_groups):
        idxs = day_groups[day_key]
        if len(idxs) < 5:
            coverage.append({"date": day_key[0], "venue": day_key[1], "races": len(idxs)})
            continue

        frozen = {course: [] for course in COURSES}
        for i in idxs:
            c = ctx[i]
            v = vid[c["venue"]]
            r = c["raceNo"]
            f = c["fieldBand"]
            o = c["favBand"]
            s = c["surface"]
            d = c["distance"]
            ge = global_roi(gsum, gcount)
            parts = {
                "global": ge,
                "venue": context_roi(sums["venue"][v], counts["venue"][v], ge),
                "race_no": context_roi(sums["race_no"][r], counts["race_no"][r], ge),
                "field": context_roi(sums["field"][f], counts["field"][f], ge),
                "fav": context_roi(sums["fav"][o], counts["fav"][o], ge),
                "surface": context_roi(sums["surface"][s], counts["surface"][s], ge),
                "distance": context_roi(sums["distance"][d], counts["distance"][d], ge),
                "venue_field": context_roi(
                    sums["venue_field"][v, f], counts["venue_field"][v, f], ge
                ),
                "race_field": context_roi(
                    sums["race_field"][r, f], counts["race_field"][r, f], ge
                ),
                "surface_distance": context_roi(
                    sums["surface_distance"][s, d], counts["surface_distance"][s, d], ge
                ),
                "venue_surface": context_roi(
                    sums["venue_surface"][v, s], counts["venue_surface"][v, s], ge
                ),
            }
            weighted = np.zeros(primitive_count, dtype=np.float64)
            for name, weight in CTX_WEIGHTS.items():
                weighted += weight * parts[name]
            robust_stack = np.vstack(
                [
                    parts["venue"],
                    parts["race_no"],
                    parts["field"],
                    parts["venue_field"],
                    parts["race_field"],
                    parts["surface_distance"],
                ]
            )
            q25 = np.quantile(robust_stack, 0.25, axis=0)
            score = (1.0 - ROBUST_WEIGHT) * weighted + ROBUST_WEIGHT * q25
            score[~valid_mask(len(races[i]["runners"]))] = -1e9

            for course, course_spec in COURSES.items():
                picked = pick_tickets(races[i], score, course, course_spec)
                if picked is not None:
                    selected, units, p_score = picked
                    frozen[course].append((p_score, -c["raceNo"], i, selected, units))

        for course, course_spec in COURSES.items():
            choices = sorted(frozen[course], reverse=True)[:5]
            if len(choices) != 5:
                coverage.append(
                    {
                        "date": day_key[0],
                        "venue": day_key[1],
                        "course": course,
                        "selectable": len(choices),
                    }
                )
                continue
            for p_score, _, i, selected, units in choices:
                returned = float(np.sum(payout[i, selected] * units))
                records[course].append(
                    {
                        "date": ctx[i]["date"],
                        "venue": ctx[i]["venue"],
                        "raceNo": ctx[i]["raceNo"],
                        "returnYen": returned,
                        "score": p_score,
                    }
                )

        for i in idxs:
            c = ctx[i]
            v = vid[c["venue"]]
            r = c["raceNo"]
            f = c["fieldBand"]
            o = c["favBand"]
            s = c["surface"]
            d = c["distance"]
            cl = c["class"]
            valid = valid_mask(len(races[i]["runners"]))
            observed = np.minimum(payout[i].astype(np.float64), type_caps)
            observed = np.where(valid, observed, 0.0)
            inc = valid.astype(np.float32)
            gsum += observed
            gcount += inc
            keys = {
                "venue": (v,),
                "race_no": (r,),
                "field": (f,),
                "fav": (o,),
                "surface": (s,),
                "distance": (d,),
                "class": (cl,),
                "venue_field": (v, f),
                "race_field": (r, f),
                "surface_distance": (s, d),
                "venue_surface": (v, s),
            }
            for name, key in keys.items():
                sums[name][key] += observed
                counts[name][key] += inc

    results = {}
    completion = True
    reasons = []
    for course, course_spec in COURSES.items():
        full = summarize(records[course], course_spec["budget"])
        holdout = summarize(
            [r for r in records[course] if r["date"] >= HOLDOUT_START], course_spec["budget"]
        )
        quarterly = {}
        qrows = defaultdict(list)
        for record in records[course]:
            year, month = map(int, record["date"][:7].split("-"))
            quarter = (month - 1) // 3 + 1
            qrows[f"{year}-Q{quarter}"].append(record)
        for quarter, rows in sorted(qrows.items()):
            quarterly[quarter] = summarize(rows, course_spec["budget"])
        checks = {
            "fullRoi200": full["roiPct"] is not None and full["roiPct"] >= 200,
            "holdoutRoi200": holdout["roiPct"] is not None and holdout["roiPct"] >= 200,
            "holdout100Races": holdout["races"] >= 100,
            "top1Trim100": full["roiWithoutTop1Pct"] is not None
            and full["roiWithoutTop1Pct"] >= 100,
            "maxTrim100": full["roiWithoutMaxPct"] is not None
            and full["roiWithoutMaxPct"] >= 100,
            "coverage": not coverage,
        }
        if not all(checks.values()):
            completion = False
            reasons.append({"course": course, "failed": [k for k, v in checks.items() if not v]})
        results[course] = {
            "full": full,
            "holdout": holdout,
            "quarterly": quarterly,
            "checks": checks,
        }

    out = {
        "schema": 1,
        "explorationId": "contextual-ticket-online-20260808",
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
            "primitiveCount": len(PRIMITIVES),
            "rankingVariants": list(helper.VARIANTS),
            "minimumRacesPerVenueDay": 5,
            "holdoutStart": HOLDOUT_START,
            "updateRule": "all five races for each course are frozen before venue-day outcomes update the learner",
            "contextWeights": CTX_WEIGHTS,
            "robustWeight": ROBUST_WEIGHT,
            "typeLearningCaps": TYPE_CAP,
        },
        "coverageFailures": coverage,
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
