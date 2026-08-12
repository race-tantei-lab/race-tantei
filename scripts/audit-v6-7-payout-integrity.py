import importlib.util
import json
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
base = v67.base
v4 = v67.v4
v4.HOLDOUT_END = "2026-08-31"

AUDIT_CODES = ("S1", "W12", "Q12", "E12", "T123", "X123")
CODE_INDEX = {
    code: index
    for index, code in v67.CODE_BY_INDEX.items()
    if code in AUDIT_CODES
}


def percentile(values, q):
    return float(np.quantile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def payout_distribution_and_consistency(races):
    values_by_type = defaultdict(list)
    keys_per_type_per_race = defaultdict(list)
    mismatches = []
    checked = 0

    for race in races:
        finish_by_horse = {
            int(runner["horseNo"]): int(runner["finish"])
            for runner in race["runners"]
        }
        counts = defaultdict(int)
        for key, payout in race.get("payouts", {}).items():
            if ":" not in key:
                continue
            bet_type, combination = key.split(":", 1)
            horses = tuple(
                int(value)
                for value in combination.split("-")
                if value.strip().isdigit()
            )
            values_by_type[bet_type].append(float(payout))
            counts[bet_type] += 1
            if any(horse in race.get("refunds", set()) for horse in horses):
                continue

            finishes = tuple(finish_by_horse.get(horse, 99) for horse in horses)
            valid = True
            if bet_type == "単勝":
                valid = len(finishes) == 1 and finishes[0] == 1
            elif bet_type == "ワイド":
                valid = len(finishes) == 2 and max(finishes) <= 3
            elif bet_type == "馬連":
                valid = len(finishes) == 2 and set(finishes) == {1, 2}
            elif bet_type == "馬単":
                valid = len(finishes) == 2 and finishes == (1, 2)
            elif bet_type == "3連複":
                valid = len(finishes) == 3 and set(finishes) == {1, 2, 3}
            elif bet_type == "3連単":
                valid = len(finishes) == 3 and finishes == (1, 2, 3)
            checked += 1
            if not valid and len(mismatches) < 100:
                mismatches.append(
                    {
                        "raceId": race["raceId"],
                        "raceDate": race["raceDate"],
                        "venue": race["venue"],
                        "raceNo": race["raceNo"],
                        "key": key,
                        "payoutYen": float(payout),
                        "finishes": list(finishes),
                    }
                )
        for bet_type, count in counts.items():
            keys_per_type_per_race[bet_type].append(count)

    distributions = {}
    for bet_type, values in sorted(values_by_type.items()):
        distributions[bet_type] = {
            "records": len(values),
            "minimum": min(values),
            "median": percentile(values, 0.50),
            "p90": percentile(values, 0.90),
            "p99": percentile(values, 0.99),
            "maximum": max(values),
            "meanWinningKeysPerRace": float(
                np.mean(keys_per_type_per_race[bet_type])
            ),
            "maximumWinningKeysPerRace": max(keys_per_type_per_race[bet_type]),
        }
    return {
        "checkedWinningPayouts": checked,
        "finishCombinationMismatchCount": len(mismatches),
        "sampleMismatches": mismatches,
        "payoutDistributionPer100Yen": distributions,
    }


def attach_and_select(races):
    months = [
        month
        for month in v67.month_sequence(v67.START_MONTH, v67.END_MONTH)
        if any(race["raceDate"].startswith(month) for race in races)
    ]
    predictions, training = v67.rolling_predictions(races, months)
    selected_by_mode = {mode: [] for mode in v67.RACE_MODES}
    coverage = []
    for month in months:
        if month not in predictions:
            continue
        for mode in v67.RACE_MODES:
            selected, rows = v67.select_five_complete(predictions[month], mode)
            selected_by_mode[mode].extend(selected)
            if mode == "balanced":
                coverage.extend(rows)
    return months, training, selected_by_mode, coverage


def benchmark_races(races):
    matrix, _ = base.payout_matrix(races)
    rows = {}
    for code in AUDIT_CODES:
        index = CODE_INDEX[code]
        payouts = matrix[:, index]
        hits = int(np.sum(payouts > 0))
        returned = float(payouts.sum())
        stake = len(payouts) * 100
        rows[code] = {
            "races": len(payouts),
            "hits": hits,
            "hitRatePct": hits / len(payouts) * 100 if len(payouts) else 0.0,
            "stakeYen": stake,
            "returnYen": int(round(returned)),
            "roiPct": returned / stake * 100 if stake else 0.0,
            "averagePayoutOnHit": returned / hits if hits else 0.0,
            "medianPayoutOnHit": float(np.median(payouts[payouts > 0]))
            if hits
            else 0.0,
            "maximumPayout": float(np.max(payouts)) if len(payouts) else 0.0,
        }
    return rows


def market_ranked_races(races):
    return v67.attach_market_only(races)


def actual_order_key(race, ranks):
    return [
        {
            "predictedRank": rank,
            "horseNo": int(race["runners"][rank - 1]["horseNo"]),
            "finish": int(race["runners"][rank - 1]["finish"]),
            "winOdds": float(race["runners"][rank - 1]["winOdds"]),
            "market": float(race["runners"][rank - 1]["market"]),
            "probability": float(race["runners"][rank - 1].get("probability") or 0.0),
        }
        for rank in ranks
    ]


def top_x123_hits(races, limit=100):
    matrix, _ = base.payout_matrix(races)
    index = CODE_INDEX["X123"]
    rows = []
    for race_index in np.flatnonzero(matrix[:, index] > 0):
        race = races[int(race_index)]
        rows.append(
            {
                "raceId": race["raceId"],
                "raceDate": race["raceDate"],
                "venue": race["venue"],
                "raceNo": race["raceNo"],
                "payoutPer100Yen": float(matrix[int(race_index), index]),
                "predictedTop3": actual_order_key(race, (1, 2, 3)),
            }
        )
    rows.sort(key=lambda row: row["payoutPer100Yen"], reverse=True)
    return rows[:limit]


def main():
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    months, training, selected_by_mode, coverage = attach_and_select(races)

    fixed = {
        mode: benchmark_races(selected)
        for mode, selected in selected_by_mode.items()
    }
    x123_examples = {
        mode: top_x123_hits(selected, limit=30)
        for mode, selected in selected_by_mode.items()
    }

    market_races = market_ranked_races(races)
    market_selected, market_coverage = v67.select_five_complete(
        market_races, "confidence"
    )

    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v6.7-integrity-audit",
        "data": {
            "firstRaceDate": min(race["raceDate"] for race in races),
            "lastRaceDate": max(race["raceDate"] for race in races),
            "races": len(races),
            "months": months,
            "modelTraining": training,
        },
        "coverage": {
            "venueDays": len(coverage),
            "selectedRaces": sum(row["selectedRaces"] for row in coverage),
            "zeroSelectedVenueDays": sum(row["selectedRaces"] == 0 for row in coverage),
            "shortVenueDays": [
                row for row in coverage if row["selectedRaces"] < 5
            ],
        },
        "payoutIntegrity": payout_distribution_and_consistency(races),
        "modelSelectedPrimitiveBenchmarks": fixed,
        "marketConfidenceSelectedPrimitiveBenchmarks": benchmark_races(
            market_selected
        ),
        "marketCoverage": market_coverage,
        "topX123WinningExamples": x123_examples,
    }
    Path("v6-7-integrity-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "period": [
                    report["data"]["firstRaceDate"],
                    report["data"]["lastRaceDate"],
                ],
                "payoutIntegrity": {
                    "checked": report["payoutIntegrity"]["checkedWinningPayouts"],
                    "mismatches": report["payoutIntegrity"][
                        "finishCombinationMismatchCount"
                    ],
                    "distribution": report["payoutIntegrity"][
                        "payoutDistributionPer100Yen"
                    ],
                },
                "modelBenchmarks": fixed,
                "marketBenchmarks": report[
                    "marketConfidenceSelectedPrimitiveBenchmarks"
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
