import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v6_shadow", ROOT / "scripts" / "analyze-v6-shadow.py")
v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v6)


def clean_policy_metrics(metrics):
    cleaned = {}
    for course, row in metrics.items():
        monthly = row.get("monthlyRoiPct", {})
        cleaned[course] = {
            "races": int(row["races"]),
            "tickets": int(row["tickets"]),
            "stakeYen": int(row["stakeYen"]),
            "returnYen": int(row["returnYen"]),
            "profitYen": int(row["profitYen"]),
            "roiPct": round(float(row["roiPct"]), 4),
            "hitRatePct": round(float(row["hitRatePct"]), 4),
            "monthlyRois": {month: round(float(value), 4) for month, value in monthly.items()},
        }
    return cleaned


def portfolio_score(metrics):
    course_scores = []
    for row in metrics.values():
        monthly = list(row.get("monthlyRoiPct", {}).values())
        minimum_month = min(monthly) if monthly else 0.0
        course_scores.append(
            float(row["roiPct"]) * 0.30
            + minimum_month * 0.45
            + float(row["hitRatePct"]) * 0.25
        )
    return min(course_scores) if course_scores else -999.0


v6.clean_policy_metrics = clean_policy_metrics
v6.portfolio_score = portfolio_score
v6.main()
