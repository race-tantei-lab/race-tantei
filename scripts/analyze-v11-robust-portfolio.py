import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "analysis-results" / "v10-robust-high-roi.json"
OUTPUT = ROOT / "v11-robust-portfolio.json"


def combine(rows, period):
    metrics = [row[period] for row in rows]
    stake = sum(row["stakeYen"] for row in metrics)
    returned = sum(row["returnYen"] for row in metrics)
    hits = sum(row["hits"] for row in metrics)
    tickets = sum(row["races"] for row in metrics)
    maximum = max((row["maxSinglePayoutYen"] for row in metrics), default=0)
    return {
        "tickets": tickets,
        "hits": hits,
        "stakeYen": stake,
        "returnYen": returned,
        "profitYen": returned - stake,
        "roiPct": returned / stake * 100 if stake else 0.0,
        "hitRatePct": hits / tickets * 100 if tickets else 0.0,
        "maxSinglePayoutYen": maximum,
        "maxSingleReturnShare": maximum / returned if returned else 1.0,
        "roiWithoutTop1Pct": max(0, returned - maximum) / stake * 100 if stake else 0.0,
    }


def combine_final_monthly(rows):
    months = {}
    for row in rows:
        for month, value in row["finalMonthly"].items():
            target = months.setdefault(month, {"tickets": 0, "hits": 0, "stakeYen": 0, "returnYen": 0})
            target["tickets"] += value["races"]
            target["hits"] += round(value["hitRatePct"] / 100 * value["races"])
            target["stakeYen"] += value["races"] * 100
            target["returnYen"] += value["returnYen"]
    for value in months.values():
        value["roiPct"] = value["returnYen"] / value["stakeYen"] * 100 if value["stakeYen"] else 0.0
        value["hitRatePct"] = value["hits"] / value["tickets"] * 100 if value["tickets"] else 0.0
    return months


def score(first, second):
    floor_roi = min(first["roiPct"], second["roiPct"])
    floor_trimmed = min(first["roiWithoutTop1Pct"], second["roiWithoutTop1Pct"])
    floor_hit = min(first["hitRatePct"], second["hitRatePct"])
    result = floor_roi * 0.42 + floor_trimmed * 0.43 + floor_hit * 2.0
    result -= max(0.0, first["maxSingleReturnShare"] - 0.30) * 100
    result -= max(0.0, second["maxSingleReturnShare"] - 0.30) * 120
    return result


def component(row):
    return {
        "variant": row["variant"],
        "selectionMode": row["selectionMode"],
        "filter": row["filter"],
        "code": row["code"],
        "betType": row["betType"],
        "predictedRanks": row["predictedRanks"],
    }


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates = source["summary"]["bestByPreHoldoutSelection"]
    portfolios = []
    for size in (2, 3, 4):
        for indexes in itertools.combinations(range(len(candidates)), size):
            rows = [candidates[index] for index in indexes]
            first = combine(rows, "developmentA")
            second = combine(rows, "developmentB")
            final = combine(rows, "finalHoldout")
            portfolios.append({
                "selectionScore": score(first, second),
                "components": [component(row) for row in rows],
                "developmentA": first,
                "developmentB": second,
                "finalHoldout": final,
                "finalMonthly": combine_final_monthly(rows),
            })
    portfolios.sort(key=lambda row: (row["selectionScore"], min(row["developmentA"]["roiWithoutTop1Pct"], row["developmentB"]["roiWithoutTop1Pct"])), reverse=True)
    winner = portfolios[0]
    promotion = (
        winner["developmentA"]["roiPct"] >= 110
        and winner["developmentB"]["roiPct"] >= 110
        and winner["finalHoldout"]["roiPct"] >= 200
        and winner["finalHoldout"]["roiWithoutTop1Pct"] >= 120
    )
    report = {
        "generatedAt": "2026-08-06",
        "modelVersion": "v11-shadow-robust-portfolio",
        "productionChanged": False,
        "promotionEligible": promotion,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "syntheticOddsUsed": False,
        "selectionUsesFinalHoldout": False,
        "sourceCandidateRule": "Only the ten candidates ordered by pre-holdout selection score in v10 are combined.",
        "summary": {
            "selectedPortfolio": winner,
            "topPreHoldoutPortfolios": portfolios[:10],
        },
        "portfolioCount": len(portfolios),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promotionEligible": promotion, "selectedPortfolio": winner}, ensure_ascii=False))


if __name__ == "__main__":
    main()
