import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
VERSION_PATTERN = re.compile(r"(?i)^v\d+(?:[.\-_].*)?$")
APPROVAL_PLACEHOLDER = '__APPROVED_MODEL_VERSION__'


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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_repo_path(value: Any) -> Path:
    require(isinstance(value, str) and value.strip(), "IMPLEMENTATION_PATH_MISSING")
    path = (ROOT / value).resolve()
    require(path.is_relative_to(ROOT), f"IMPLEMENTATION_PATH_OUTSIDE_REPOSITORY:{value}")
    return path


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


def validate_exploration_identity(report: dict[str, Any], config: dict[str, Any]) -> str:
    promotion = config["promotionRules"]
    if promotion.get("candidateVersionNumbersForbidden"):
        require(not report.get("modelVersion"), "EXPLORATION_MUST_NOT_HAVE_MODEL_VERSION")
    exploration_id = report.get("explorationId")
    require(isinstance(exploration_id, str) and exploration_id.strip(), "EXPLORATION_ID_MISSING")
    require(not VERSION_PATTERN.match(exploration_id.strip()), "EXPLORATION_ID_MUST_NOT_BE_VERSION_NUMBER")
    return exploration_id.strip()


def validate_implementation(report: dict[str, Any]) -> dict[str, Any]:
    implementation = report.get("productionImplementation")
    require(isinstance(implementation, dict), "PRODUCTION_IMPLEMENTATION_MISSING")
    candidate_policy = safe_repo_path(implementation.get("candidatePolicyPath"))
    require(candidate_policy.exists(), f"CANDIDATE_POLICY_NOT_FOUND:{candidate_policy}")
    require(candidate_policy.suffix == ".py", "CANDIDATE_POLICY_MUST_BE_PYTHON")
    expected_sha = implementation.get("candidatePolicySha256")
    require(isinstance(expected_sha, str) and len(expected_sha) == 64, "CANDIDATE_POLICY_SHA256_MISSING")
    actual_sha = file_sha256(candidate_policy)
    require(actual_sha == expected_sha, "CANDIDATE_POLICY_SHA256_MISMATCH")
    policy_source = candidate_policy.read_text(encoding="utf-8")
    require(APPROVAL_PLACEHOLDER in policy_source, "CANDIDATE_POLICY_APPROVAL_PLACEHOLDER_MISSING")
    require('MODEL_VERSION = "v16"' not in policy_source, "CANDIDATE_POLICY_PREMATURELY_VERSIONED")

    runner = safe_repo_path(implementation.get("productionRunnerPath", "scripts/run-final-course-production.py"))
    require(runner.exists(), f"PRODUCTION_RUNNER_NOT_FOUND:{runner}")
    return {
        "candidatePolicyPath": str(candidate_policy.relative_to(ROOT)),
        "candidatePolicySha256": actual_sha,
        "productionPolicyPath": "scripts/final-course-policy.py",
        "productionRunnerPath": str(runner.relative_to(ROOT)),
    }


def validate_report(report: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    promotion = config["promotionRules"]
    rules = config["immutableProjectRules"]
    exploration_id = validate_exploration_identity(report, config)

    require(report.get("promotionEligible") is True, "PROMOTION_ELIGIBLE_FALSE")
    require(report.get("productionChanged") is False, "CANDIDATE_MUST_BE_SHADOW_ONLY")
    require(flag(report, "sourceDataFrozen"), "SOURCE_DATA_NOT_FROZEN")
    require(flag(report, "actualJraPayoutsUsed") or flag(report, "actualJraPayoutsOnly"), "ACTUAL_JRA_PAYOUTS_NOT_CONFIRMED")
    require(report.get("syntheticOddsUsed") is False or flag(report, "syntheticOddsForbidden"), "SYNTHETIC_ODDS_NOT_FORBIDDEN")
    require(report.get("postResultLeakageUsed") is False or flag(report, "postResultLeakageForbidden"), "POST_RESULT_LEAKAGE_NOT_FORBIDDEN")
    require(
        flag(report, "officialOddsOnly")
        or (report.get("officialWinOddsUsed") is True and report.get("syntheticOddsUsed") is False),
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
    full_target = number(promotion["requireFullHistoricalRoiPct"])
    final_target = number(promotion["requireFinalHoldoutRoiPct"])
    min_races = int(promotion["minimumFinalHoldoutRacesPerCourse"])
    min_trimmed_roi = number(promotion["requireRoiWithoutTop1Pct"])
    minimum_selected = int(rules["minimumRacesPerVenueDay"])

    for course_name, course_config in config["courses"].items():
        course = courses[course_name]
        require(isinstance(course, dict), f"COURSE_INVALID:{course_name}")

        full = course.get("fullHistorical")
        require(isinstance(full, dict), f"FULL_HISTORICAL_MISSING:{course_name}")
        full_races = int(number(full.get("races")))
        full_roi = number(full.get("roiPct"), -1.0)
        require(full_races > 0, f"FULL_HISTORICAL_RACES_MISSING:{course_name}")
        require(full_roi >= full_target, f"FULL_HISTORICAL_ROI_BELOW_200:{course_name}:{full_roi:.6f}")

        final = course.get("finalHoldout")
        require(isinstance(final, dict), f"FINAL_HOLDOUT_MISSING:{course_name}")
        races = int(number(final.get("races")))
        roi = number(final.get("roiPct"), -1.0)
        trimmed_roi = number(final.get("roiWithoutTop1Pct"), -1.0)
        require(races >= min_races, f"FINAL_HOLDOUT_RACES_TOO_FEW:{course_name}:{races}")
        require(roi >= final_target, f"FINAL_HOLDOUT_ROI_BELOW_200:{course_name}:{roi:.6f}")
        require(trimmed_roi >= min_trimmed_roi, f"TOP1_DEPENDENCE_TOO_HIGH:{course_name}:{trimmed_roi:.6f}")

        coverage = course.get("coverage")
        require(isinstance(coverage, dict), f"COVERAGE_MISSING:{course_name}")
        minimum_coverage = int(number(coverage.get("minimumSelectedRaces")))
        require(minimum_coverage >= minimum_selected, f"RACES_PER_VENUE_DAY_BELOW_MINIMUM:{course_name}:{minimum_coverage}")

        policy = course.get("policy")
        require(policy is not None, f"POLICY_MISSING:{course_name}")
        ticket_lists = find_ticket_lists(policy)
        require(ticket_lists, f"POLICY_TICKETS_MISSING:{course_name}")
        allowed = set(course_config["allowedBetTypes"])
        required_distinct = int(course_config["minimumDistinctBetTypes"])
        for index, tickets in enumerate(ticket_lists):
            bet_types = {str(ticket.get("betType")) for ticket in tickets}
            require(not (bet_types == {"単勝"}), f"SINGLE_ONLY_POLICY:{course_name}:{index}")
            require(allowed.issubset(bet_types), f"BET_TYPE_DIVERSIFICATION_MISSING:{course_name}:{index}:{sorted(bet_types)}")
            require(len(bet_types) >= required_distinct, f"DISTINCT_BET_TYPES_TOO_FEW:{course_name}:{index}")
            stakes = [int(number(ticket.get("stakeYen"))) for ticket in tickets if "stakeYen" in ticket]
            if stakes:
                require(sum(stakes) == int(course_config["budgetYen"]), f"COURSE_BUDGET_NOT_EXACT:{course_name}:{index}:{sum(stakes)}")

        approved_courses[course_name] = {
            "fullHistoricalRaces": full_races,
            "fullHistoricalRoiPct": full_roi,
            "finalHoldoutRaces": races,
            "finalHoldoutRoiPct": roi,
            "roiWithoutTop1Pct": trimmed_roi,
            "minimumSelectedRacesPerVenueDay": minimum_coverage,
            "budgetYen": int(course_config["budgetYen"]),
            "requiredBetTypes": course_config["allowedBetTypes"],
        }

    implementation = validate_implementation(report)
    return exploration_id, approved_courses, implementation


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
    exploration_id, approved_courses, implementation = validate_report(report, config)

    approval = {
        "productionPromotionApproved": True,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "constraintsVersion": config["version"],
        "completionRoiPct": config["promotionRules"]["completionRoiPct"],
        "modelVersion": config["promotionRules"]["approvedModelVersion"],
        "sourceExplorationId": exploration_id,
        "sourceReport": str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
        "sourceReportSha256": hashlib.sha256(raw).hexdigest(),
        "implementation": implementation,
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
