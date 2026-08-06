import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"


class CandidateRejected(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateRejected(message)


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def find_ticket_lists(value: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, list):
        dict_rows = [row for row in value if isinstance(row, dict)]
        if dict_rows and all("betType" in row for row in dict_rows):
            found.append(dict_rows)
        for row in value:
            found.extend(find_ticket_lists(row))
    elif isinstance(value, dict):
        for row in value.values():
            found.extend(find_ticket_lists(row))
    return found


def flag(report: dict[str, Any], name: str) -> bool:
    if report.get(name) is True:
        return True
    for container_name in ("guardrails", "methodFlags", "constraints"):
        container = report.get(container_name)
        if isinstance(container, dict) and container.get(name) is True:
            return True
    return False


def validate_report(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    promotion = config["promotionRules"]
    rules = config["immutableProjectRules"]

    require(report.get("promotionEligible") is True, "PROMOTION_ELIGIBLE_FALSE")
    require(report.get("productionChanged") is False, "CANDIDATE_MUST_BE_SHADOW_ONLY")
    require(flag(report, "sourceDataFrozen"), "SOURCE_DATA_NOT_FROZEN")
    require(flag(report, "actualJraPayoutsUsed") or flag(report, "actualJraPayoutsOnly"), "ACTUAL_JRA_PAYOUTS_NOT_CONFIRMED")
    require(report.get("syntheticOddsUsed") is False or flag(report, "syntheticOddsForbidden"), "SYNTHETIC_ODDS_NOT_FORBIDDEN")
    require(report.get("postResultLeakageUsed") is False or flag(report, "postResultLeakageForbidden"), "POST_RESULT_LEAKAGE_NOT_FORBIDDEN")
    require(
        flag(report, "officialOddsOnly")
        or (
            report.get("officialWinOddsUsed") is True
            and report.get("syntheticOddsUsed") is False
        ),
        "OFFICIAL_ODDS_ONLY_NOT_CONFIRMED",
    )
    require(
        flag(report, "liveBetGenerationRequiresOfficialCombinationOdds")
        or flag(report, "officialCombinationOddsRequiredForLiveBets"),
        "LIVE_OFFICIAL_COMBINATION_ODDS_GATE_MISSING",
    )

    courses = report.get("courses")
    require(isinstance(courses, dict), "COURSES_MISSING")
    require(set(courses) == set(config["courses"]), "COURSE_SET_CHANGED")

    approved_courses: dict[str, Any] = {}
    target_roi = number(promotion["targetRoiPct"])
    min_races = int(promotion["minimumFinalHoldoutRacesPerCourse"])
    min_trimmed_roi = number(promotion["requireRoiWithoutTop1Pct"])
    minimum_selected = int(rules["minimumRacesPerVenueDay"])

    for course_name, course_config in config["courses"].items():
        course = courses[course_name]
        require(isinstance(course, dict), f"COURSE_INVALID:{course_name}")
        final = course.get("finalHoldout")
        require(isinstance(final, dict), f"FINAL_HOLDOUT_MISSING:{course_name}")

        races = int(number(final.get("races")))
        roi = number(final.get("roiPct"), -1.0)
        trimmed_roi = number(final.get("roiWithoutTop1Pct"), -1.0)
        require(races >= min_races, f"FINAL_HOLDOUT_RACES_TOO_FEW:{course_name}:{races}")
        require(roi >= target_roi, f"FINAL_HOLDOUT_ROI_BELOW_200:{course_name}:{roi:.6f}")
        require(trimmed_roi >= min_trimmed_roi, f"TOP1_DEPENDENCE_TOO_HIGH:{course_name}:{trimmed_roi:.6f}")

        coverage = course.get("coverage")
        require(isinstance(coverage, dict), f"COVERAGE_MISSING:{course_name}")
        minimum_coverage = int(number(coverage.get("minimumSelectedRaces")))
        require(
            minimum_coverage >= minimum_selected,
            f"RACES_PER_VENUE_DAY_BELOW_MINIMUM:{course_name}:{minimum_coverage}",
        )

        policy = course.get("policy")
        require(policy is not None, f"POLICY_MISSING:{course_name}")
        ticket_lists = find_ticket_lists(policy)
        require(ticket_lists, f"POLICY_TICKETS_MISSING:{course_name}")
        allowed = set(course_config["allowedBetTypes"])
        required_distinct = int(course_config["minimumDistinctBetTypes"])
        for index, tickets in enumerate(ticket_lists):
            bet_types = {str(ticket.get("betType")) for ticket in tickets}
            require("単勝" not in bet_types or len(bet_types) > 1, f"SINGLE_ONLY_POLICY:{course_name}:{index}")
            require(allowed.issubset(bet_types), f"BET_TYPE_DIVERSIFICATION_MISSING:{course_name}:{index}:{sorted(bet_types)}")
            require(len(bet_types) >= required_distinct, f"DISTINCT_BET_TYPES_TOO_FEW:{course_name}:{index}")
            stakes = [int(number(ticket.get("stakeYen"))) for ticket in tickets if "stakeYen" in ticket]
            if stakes:
                require(sum(stakes) == int(course_config["budgetYen"]), f"COURSE_BUDGET_NOT_EXACT:{course_name}:{index}:{sum(stakes)}")

        approved_courses[course_name] = {
            "finalHoldoutRaces": races,
            "finalHoldoutRoiPct": roi,
            "roiWithoutTop1Pct": trimmed_roi,
            "minimumSelectedRacesPerVenueDay": minimum_coverage,
            "budgetYen": int(course_config["budgetYen"]),
            "requiredBetTypes": course_config["allowedBetTypes"],
        }

    return approved_courses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--write-approval", type=Path)
    args = parser.parse_args()

    report_path = args.report.resolve()
    require(report_path.exists(), f"REPORT_NOT_FOUND:{report_path}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw = report_path.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    require(isinstance(report, dict), "REPORT_ROOT_MUST_BE_OBJECT")
    approved_courses = validate_report(report, config)

    approval = {
        "productionPromotionApproved": True,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "constraintsVersion": config["version"],
        "targetRoiPct": config["promotionRules"]["targetRoiPct"],
        "modelVersion": report.get("modelVersion"),
        "sourceReport": str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
        "sourceReportSha256": hashlib.sha256(raw).hexdigest(),
        "courses": approved_courses,
    }

    if args.write_approval:
        output = args.write_approval.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(approval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(approval, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except CandidateRejected as error:
        raise SystemExit(f"PRODUCTION_CANDIDATE_REJECTED:{error}")
