import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
v67 = load_module(
    "v67_full_period",
    ROOT / "scripts" / "analyze-v6-full-period-walkforward.py",
)
v4 = v67.v4
v6 = v67.v6
base = v67.base
v4.HOLDOUT_END = "2026-08-31"

FEATURE_COUNT = 51
FEATURE_VARIANTS = {
    "full_strict_prior_day": tuple(range(FEATURE_COUNT)),
    "market_only": (0, 1, 2),
    "market_and_static": tuple([0, 1, 2] + list(range(25, FEATURE_COUNT))),
    "history_without_market": tuple(range(3, FEATURE_COUNT)),
    "no_popularity": tuple(index for index in range(FEATURE_COUNT) if index != 2),
    "no_entity_history": tuple(list(range(0, 3)) + list(range(25, FEATURE_COUNT))),
    "horse_history_plus_market": tuple(list(range(0, 11)) + list(range(25, FEATURE_COUNT))),
    "trainer_stable_plus_market": tuple(list(range(0, 3)) + list(range(13, 17)) + list(range(21, 25)) + list(range(25, FEATURE_COUNT))),
}

MODEL_CONFIG = {
    "max_leaf_nodes": 15,
    "learning_rate": 0.04,
    "max_iter": 140,
    "l2_regularization": 8.0,
}
AUDIT_MODES = ("confidence", "edge", "disagreement")
AUDIT_CODES = ("S1", "W12", "Q12", "E12", "T123", "X123")
CODE_INDEX = {
    code: index
    for index, code in v67.CODE_BY_INDEX.items()
    if code in AUDIT_CODES
}


def build_dataset_prior_day(rows, payout_maps):
    grouped = defaultdict(list)
    metadata = {}
    for row in rows:
        race_id = row["raceId"]
        grouped[race_id].append(row)
        metadata[race_id] = row

    by_date = defaultdict(list)
    for race_id, raw in metadata.items():
        by_date[raw["raceDate"]].append(race_id)

    stores = {
        name: {}
        for name in [
            "horse",
            "jockey",
            "trainer",
            "stable",
            "horse_course",
            "jockey_course",
            "trainer_course",
            "stable_course",
        ]
    }
    races = []
    for race_date in sorted(by_date):
        date_ids = sorted(
            by_date[race_date],
            key=lambda race_id: (
                metadata[race_id]["venue"],
                v4.number(metadata[race_id]["raceNo"]),
            ),
        )

        # Materialize every race of the date before updating any history store.
        for race_id in date_ids:
            raw = metadata[race_id]
            venue = raw["venue"]
            surface = raw.get("surface") or "unknown"
            distance = v4.number(raw.get("distanceM"))
            d_bucket = v4.distance_bucket(distance)
            active = [
                row
                for row in grouped[race_id]
                if row.get("runnerStatus") == "active"
                and v4.number(row.get("winOdds")) > 1
                and v4.number(row.get("finishPosition")) > 0
            ]
            inverse = [1 / v4.number(row["winOdds"]) for row in active]
            total_inverse = sum(inverse)
            winner_exists = any(
                v4.number(row.get("finishPosition")) == 1 for row in active
            )
            built_runners = []
            if len(active) >= 3 and winner_exists and total_inverse > 0:
                field_size = len(active)
                for index, row in enumerate(active):
                    market = inverse[index] / total_inverse
                    horse = v4.get_history(
                        stores["horse"], row.get("horseName") or ""
                    ).features(race_date)
                    jockey = v4.get_history(
                        stores["jockey"], row.get("jockey") or ""
                    ).features(race_date)
                    trainer = v4.get_history(
                        stores["trainer"], row.get("trainer") or ""
                    ).features(race_date)
                    stable = v4.get_history(
                        stores["stable"], row.get("stable") or ""
                    ).features(race_date)
                    horse_course = v4.get_history(
                        stores["horse_course"],
                        f'{row.get("horseName")}|{venue}|{surface}|{d_bucket}',
                    ).features(race_date)
                    jockey_course = v4.get_history(
                        stores["jockey_course"],
                        f'{row.get("jockey")}|{surface}|{d_bucket}',
                    ).features(race_date)
                    trainer_course = v4.get_history(
                        stores["trainer_course"],
                        f'{row.get("trainer")}|{surface}|{d_bucket}',
                    ).features(race_date)
                    stable_course = v4.get_history(
                        stores["stable_course"],
                        f'{row.get("stable")}|{surface}|{d_bucket}',
                    ).features(race_date)
                    condition = str(raw.get("trackCondition") or "")
                    venue_flags = [int(venue == item) for item in v4.VENUES]
                    features = [
                        math.log(max(market, 1e-8)),
                        market,
                        -v4.number(row.get("popularity"), field_size / 2) / field_size,
                        horse[0],
                        horse[1],
                        -horse[2] / 12,
                        horse[3],
                        -horse[4] / 12,
                        horse[5],
                        (36 - horse[6]) / 5,
                        -horse[7] / 180,
                        jockey[0],
                        jockey[1],
                        trainer[0],
                        trainer[1],
                        stable[0],
                        stable[1],
                        horse_course[0],
                        horse_course[1],
                        jockey_course[0],
                        jockey_course[1],
                        trainer_course[0],
                        trainer_course[1],
                        stable_course[0],
                        stable_course[1],
                        (v4.number(row.get("assignedWeight")) - 55) / 6,
                        (v4.number(row.get("horseWeight")) - 480) / 100,
                        max(-30, min(30, v4.number(row.get("weightChange")))) / 30,
                        (v4.parse_age(row.get("sexAge")) - 4) / 5,
                        int("牝" in str(row.get("sexAge") or "")),
                        int("セ" in str(row.get("sexAge") or "")),
                        (v4.number(row.get("frameNo")) - 4.5) / 4.5,
                        field_size / 18,
                        distance / 3200,
                        v4.number(raw.get("raceNo")) / 12,
                        int(surface == "芝"),
                        int(surface == "ダート"),
                        int("良" in condition),
                        int("稍" in condition),
                        int("重" in condition and "不" not in condition),
                        int("不" in condition),
                        *venue_flags,
                    ]
                    built_runners.append(
                        {
                            "horseNo": int(v4.number(row.get("horseNo"))),
                            "horseName": row.get("horseName") or "",
                            "features": features,
                            "market": market,
                            "winOdds": v4.number(row.get("winOdds")),
                            "popularity": int(v4.number(row.get("popularity"), 99)),
                            "finish": int(v4.number(row.get("finishPosition"))),
                        }
                    )
                try:
                    refunds = set(json.loads(raw.get("refunds") or "[]"))
                except Exception:
                    refunds = set()
                races.append(
                    {
                        "raceId": race_id,
                        "raceDate": race_date,
                        "venue": venue,
                        "raceNo": int(v4.number(raw.get("raceNo"))),
                        "runners": built_runners,
                        "payouts": payout_maps.get(race_id, {}),
                        "refunds": refunds,
                    }
                )

        # Update only after all races on the date have been materialized.
        for race_id in date_ids:
            raw = metadata[race_id]
            venue = raw["venue"]
            surface = raw.get("surface") or "unknown"
            distance = v4.number(raw.get("distanceM"))
            d_bucket = v4.distance_bucket(distance)
            for row in grouped[race_id]:
                finish = int(v4.number(row.get("finishPosition")))
                if finish <= 0:
                    continue
                final3f = v4.number(row.get("final3f"))
                keys = {
                    "horse": row.get("horseName") or "",
                    "jockey": row.get("jockey") or "",
                    "trainer": row.get("trainer") or "",
                    "stable": row.get("stable") or "",
                    "horse_course": f'{row.get("horseName")}|{venue}|{surface}|{d_bucket}',
                    "jockey_course": f'{row.get("jockey")}|{surface}|{d_bucket}',
                    "trainer_course": f'{row.get("trainer")}|{surface}|{d_bucket}',
                    "stable_course": f'{row.get("stable")}|{surface}|{d_bucket}',
                }
                for store_name, key in keys.items():
                    v4.get_history(stores[store_name], key).update(
                        finish, final3f, race_date
                    )
    return races


def mask_features(races, kept_indices):
    kept = set(kept_indices)
    result = []
    for race in races:
        item = dict(race)
        runners = []
        for runner in race["runners"]:
            copied = dict(runner)
            copied["features"] = [
                value if index in kept else 0.0
                for index, value in enumerate(runner["features"])
            ]
            runners.append(copied)
        item["runners"] = runners
        result.append(item)
    return result


def quarter_key(month):
    year, value = map(int, month.split("-"))
    return f"{year}-Q{((value - 1) // 3) + 1}"


def variant_predictions(races, months):
    result = {}
    cache = {}
    for month in months:
        start, end = v67.month_bounds(month)
        target = [race for race in races if start <= race["raceDate"] <= end]
        train = [race for race in races if race["raceDate"] < start]
        if not target:
            continue
        if len(train) < 500:
            result[month] = v67.attach_market_only(target)
            continue
        key = quarter_key(month)
        if key not in cache:
            cache[key] = v6.fit_pairwise(train, MODEL_CONFIG)
        result[month] = v6.attach_pairwise(cache[key], target, 0.60, 1.30)
    return result


def primitive_benchmark(races):
    matrix, _ = base.payout_matrix(races)
    rows = {}
    for code in AUDIT_CODES:
        index = CODE_INDEX[code]
        payouts = matrix[:, index]
        stake = len(payouts) * 100
        returned = float(payouts.sum())
        hits = int(np.sum(payouts > 0))
        rows[code] = {
            "races": len(payouts),
            "hits": hits,
            "hitRatePct": hits / len(payouts) * 100 if len(payouts) else 0.0,
            "roiPct": returned / stake * 100 if stake else 0.0,
            "returnYen": int(round(returned)),
            "maximumPayout": float(np.max(payouts)) if len(payouts) else 0.0,
        }
    return rows


def popularity_integrity(rows):
    grouped = defaultdict(list)
    for row in rows:
        if (
            row.get("runnerStatus") == "active"
            and v4.number(row.get("winOdds")) > 1
            and v4.number(row.get("finishPosition")) > 0
        ):
            grouped[row["raceId"]].append(row)

    exact = 0
    pairwise_total = 0
    pairwise_consistent = 0
    favorite_wins = 0
    races = 0
    finish_equals_popularity = 0
    runner_count = 0
    samples = []
    for race_id, runners in grouped.items():
        if len(runners) < 3:
            continue
        races += 1
        odds_order = sorted(runners, key=lambda row: v4.number(row["winOdds"]))
        popularity_order = sorted(
            runners, key=lambda row: v4.number(row.get("popularity"), 99)
        )
        exact += int(
            [row["horseNo"] for row in odds_order]
            == [row["horseNo"] for row in popularity_order]
        )
        favorite_wins += int(v4.number(popularity_order[0]["finishPosition"]) == 1)
        for first in range(len(runners)):
            for second in range(first + 1, len(runners)):
                a, b = runners[first], runners[second]
                odds_relation = v4.number(a["winOdds"]) < v4.number(b["winOdds"])
                popularity_relation = v4.number(a.get("popularity"), 99) < v4.number(
                    b.get("popularity"), 99
                )
                pairwise_total += 1
                pairwise_consistent += int(odds_relation == popularity_relation)
        for row in runners:
            runner_count += 1
            finish_equals_popularity += int(
                int(v4.number(row.get("popularity"), 99))
                == int(v4.number(row.get("finishPosition"), 0))
            )
        if len(samples) < 25 and [row["horseNo"] for row in odds_order] != [
            row["horseNo"] for row in popularity_order
        ]:
            samples.append(
                {
                    "raceId": race_id,
                    "raceDate": runners[0]["raceDate"],
                    "oddsOrder": [
                        [int(v4.number(row["horseNo"])), v4.number(row["winOdds"])]
                        for row in odds_order[:5]
                    ],
                    "popularityOrder": [
                        [
                            int(v4.number(row["horseNo"])),
                            int(v4.number(row.get("popularity"), 99)),
                        ]
                        for row in popularity_order[:5]
                    ],
                }
            )
    return {
        "races": races,
        "exactOddsPopularityOrderPct": exact / races * 100 if races else 0.0,
        "pairwiseOddsPopularityConsistencyPct": pairwise_consistent
        / pairwise_total
        * 100
        if pairwise_total
        else 0.0,
        "favoriteWinRatePct": favorite_wins / races * 100 if races else 0.0,
        "finishEqualsPopularityPct": finish_equals_popularity
        / runner_count
        * 100
        if runner_count
        else 0.0,
        "sampleOrderMismatches": samples,
    }


def main():
    rows, payouts = v4.load_data()
    strict_races = build_dataset_prior_day(rows, payouts)
    months = [
        month
        for month in v67.month_sequence(v67.START_MONTH, v67.END_MONTH)
        if any(race["raceDate"].startswith(month) for race in strict_races)
    ]

    variants = {}
    for name, kept_indices in FEATURE_VARIANTS.items():
        masked = mask_features(strict_races, kept_indices)
        predictions = variant_predictions(masked, months)
        modes = {}
        for mode in AUDIT_MODES:
            selected = []
            for month in months:
                if month not in predictions:
                    continue
                rows_selected, _ = v67.select_five_complete(
                    predictions[month], mode
                )
                selected.extend(rows_selected)
            modes[mode] = primitive_benchmark(selected)
        variants[name] = {
            "keptFeatureIndices": list(kept_indices),
            "modes": modes,
        }

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.8-feature-leakage-audit",
        "method": (
            "Rebuild every feature using prior dates only, then run quarterly chronological "
            "models under feature ablations and settle fixed primitives on five selected races "
            "per venue-day."
        ),
        "data": {
            "firstRaceDate": min(race["raceDate"] for race in strict_races),
            "lastRaceDate": max(race["raceDate"] for race in strict_races),
            "races": len(strict_races),
            "months": months,
        },
        "popularityIntegrity": popularity_integrity(rows),
        "variants": variants,
    }
    Path("v6-8-feature-leakage-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "popularityIntegrity": report["popularityIntegrity"],
                "x123": {
                    variant: {
                        mode: row["modes"][mode]["X123"]
                        for mode in AUDIT_MODES
                    }
                    for variant, row in variants.items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
