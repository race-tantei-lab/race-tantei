import importlib.util
import json
from pathlib import Path

import numpy as np


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
base = load_module("v6_course_policy", ROOT / "scripts" / "analyze-v6-course-policy.py")

ORIGINAL_GENERATE = base.generate_policies
ORIGINAL_OPTIMIZE = base.optimize_course
ELIGIBLE_COUNTS = {}

MAX_TICKET_SHARE = {"ライト": 0.40, "スタンダード": 0.35, "プレミアム": 0.30}
MINIMUM_TYPES = {"ライト": 2, "スタンダード": 3, "プレミアム": 4}
MINIMUM_MONTH_ROI = 100.0
MINIMUM_MONTH_HIT = 25.0
MINIMUM_TOTAL_HIT = 36.8


def policy_type_count(units):
    return len({base.TYPE_BY_INDEX[index] for index, value in enumerate(units) if value > 0})


def robust_generate_policies(course, count=5000):
    candidates = ORIGINAL_GENERATE(course, count=max(7000, count))
    maximum_units = int((base.COURSE_BUDGETS[course] // 100) * MAX_TICKET_SHARE[course])
    kept = []
    for units in candidates:
        if int(units.max()) > maximum_units:
            continue
        if policy_type_count(units) < MINIMUM_TYPES[course]:
            continue
        kept.append(units)
    if not kept:
        raise RuntimeError(f"V6_2_NO_DIVERSIFIED_POLICIES:{course}")
    return np.asarray(kept, dtype=np.int16)


def robust_optimize_course(course, policies, matrices):
    combined_matrix = np.concatenate([matrices["validation"][0], matrices["july"][0]], axis=0)
    combined_months = np.concatenate([matrices["validation"][1], matrices["july"][1]], axis=0)
    best_eligible = None
    best_fallback = None
    eligible_count = 0

    for units in policies:
        metrics = base.period_metrics(combined_matrix, combined_months, units)
        score = base.policy_score(metrics)
        row = {"units": units.copy(), "metrics": metrics, "score": score}
        if best_fallback is None or row["score"] > best_fallback["score"]:
            best_fallback = row

        monthly = [value for key, value in metrics.items() if key != "TOTAL"]
        eligible = (
            metrics["TOTAL"]["hitRatePct"] >= MINIMUM_TOTAL_HIT
            and all(value["roiPct"] >= MINIMUM_MONTH_ROI for value in monthly)
            and all(value["hitRatePct"] >= MINIMUM_MONTH_HIT for value in monthly)
        )
        if not eligible:
            continue
        eligible_count += 1
        if best_eligible is None or row["score"] > best_eligible["score"]:
            best_eligible = row

    ELIGIBLE_COUNTS[course] = eligible_count
    return best_eligible or best_fallback


base.generate_policies = robust_generate_policies
base.optimize_course = robust_optimize_course
base.main()

source = Path("v6-course-policy-analysis.json")
report = json.loads(source.read_text(encoding="utf-8"))
report["modelVersion"] = "v6.2-shadow-robust-course-policy"
report["constraints"] = {
    "minimumMonthlyRoiPct": MINIMUM_MONTH_ROI,
    "minimumMonthlyHitRatePct": MINIMUM_MONTH_HIT,
    "minimumTotalHitRatePct": MINIMUM_TOTAL_HIT,
    "maximumTicketShare": MAX_TICKET_SHARE,
    "minimumDistinctBetTypes": MINIMUM_TYPES,
}
report["eligiblePolicyCounts"] = ELIGIBLE_COUNTS
report["promotionEligible"] = bool(report.get("promotionEligible")) and all(
    ELIGIBLE_COUNTS.get(course, 0) > 0 for course in base.COURSE_BUDGETS
)

output = Path("v6-course-policy-analysis-v2.json")
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "modelVersion": report["modelVersion"],
    "promotionEligible": report["promotionEligible"],
    "eligiblePolicyCounts": ELIGIBLE_COUNTS,
    "august": {
        course: row["august"]["TOTAL"]
        for course, row in report["winner"]["courses"].items()
    },
}, ensure_ascii=False))
