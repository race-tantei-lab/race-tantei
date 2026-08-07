import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
APPROVAL_PATH = ROOT / "config" / "approved-production-model.json"
VERIFIER_PATH = ROOT / "scripts" / "verify-production-candidate.py"
APPROVAL_PLACEHOLDER = "__APPROVED_MODEL_VERSION__"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"APPROVED_PRODUCTION_MODEL_INVALID:{message}")


def load_verifier():
    spec = importlib.util.spec_from_file_location("approved_candidate_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("APPROVED_PRODUCTION_MODEL_INVALID:VERIFIER_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    require(APPROVAL_PATH.exists(), "APPROVAL_MANIFEST_MISSING")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    promotion = config["promotionRules"]

    require(approval.get("productionPromotionApproved") is True, "APPROVAL_FLAG_FALSE")
    require(approval.get("constraintsVersion") == config["version"], "CONSTRAINT_VERSION_MISMATCH")
    require(
        float(approval.get("completionRoiPct", 0)) >= float(promotion["completionRoiPct"]),
        "COMPLETION_ROI_WEAKENED",
    )
    approved_version = str(promotion["approvedModelVersion"])
    require(approval.get("modelVersion") == approved_version, "APPROVED_VERSION_MISMATCH")

    report_path = (ROOT / approval.get("sourceReport", "")).resolve()
    policy_path = (ROOT / approval.get("productionPolicyPath", "")).resolve()
    candidate_policy_path = (ROOT / approval.get("candidatePolicyPath", "")).resolve()
    for path in (report_path, policy_path, candidate_policy_path):
        require(path.is_relative_to(ROOT), f"PATH_OUTSIDE_REPOSITORY:{path}")
        require(path.exists(), f"FILE_MISSING:{path}")

    require(sha256(report_path) == approval.get("sourceReportSha256"), "SOURCE_REPORT_HASH_MISMATCH")
    require(sha256(policy_path) == approval.get("productionPolicySha256"), "PRODUCTION_POLICY_HASH_MISMATCH")
    require(sha256(candidate_policy_path) == approval.get("candidatePolicySha256"), "CANDIDATE_POLICY_HASH_MISMATCH")

    candidate_source = candidate_policy_path.read_text(encoding="utf-8")
    require(APPROVAL_PLACEHOLDER in candidate_source, "CANDIDATE_POLICY_PLACEHOLDER_MISSING")
    expected_production_source = candidate_source.replace(APPROVAL_PLACEHOLDER, approved_version)
    require(
        policy_path.read_text(encoding="utf-8") == expected_production_source,
        "PRODUCTION_POLICY_NOT_APPROVED_CANDIDATE_WITH_VERSION_INSERTED",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    verifier = load_verifier()
    exploration_id, courses, implementation = verifier.validate_report(report, config)
    require(exploration_id == approval.get("sourceExplorationId"), "SOURCE_EXPLORATION_ID_MISMATCH")
    require(set(courses) == set(approval.get("courses", {})), "APPROVED_COURSES_MISMATCH")
    require(implementation["candidatePolicyPath"] == approval.get("candidatePolicyPath"), "APPROVED_POLICY_PATH_MISMATCH")

    production_source = policy_path.read_text(encoding="utf-8")
    require(f'MODEL_VERSION = "{approved_version}"' in production_source, "MODEL_VERSION_NOT_IN_POLICY")
    require(APPROVAL_PLACEHOLDER not in production_source, "APPROVAL_PLACEHOLDER_REMAINS_IN_PRODUCTION")

    print(json.dumps({
        "approved": True,
        "modelVersion": approved_version,
        "completionRoiPct": approval["completionRoiPct"],
        "courses": approval["courses"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
