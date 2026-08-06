import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "analysis-results"
CONFIG_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
APPROVAL_PATH = ROOT / "config" / "approved-production-model.json"
PRODUCTION_POLICY = ROOT / "scripts" / "final-course-policy.py"
VERIFIER_PATH = ROOT / "scripts" / "verify-production-candidate.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("production_candidate_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PRODUCTION_VERIFIER_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report_score(courses):
    rois = [float(row["finalHoldoutRoiPct"]) for row in courses.values()]
    trimmed = [float(row["roiWithoutTop1Pct"]) for row in courses.values()]
    return min(rois), min(trimmed), sum(rois) / len(rois)


def main() -> None:
    verifier = load_verifier()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    candidates = []
    rejected = []

    for path in sorted(REPORTS.glob("*.json")):
        if path.name in {"approved-production-model.json", "production-final-course-model.json"}:
            continue
        try:
            raw = path.read_bytes()
            report = json.loads(raw.decode("utf-8"))
            if not isinstance(report, dict):
                continue
            courses, implementation = verifier.validate_report(report, config)
            candidates.append({
                "path": path,
                "raw": raw,
                "report": report,
                "courses": courses,
                "implementation": implementation,
                "score": report_score(courses),
            })
        except Exception as error:
            rejected.append({"path": str(path.relative_to(ROOT)), "reason": str(error)})

    if not candidates:
        print(json.dumps({
            "promoted": False,
            "reason": "NO_PRODUCTION_CANDIDATE_PASSED",
            "checkedReports": len(rejected),
        }, ensure_ascii=False))
        return

    candidates.sort(key=lambda row: row["score"], reverse=True)
    chosen = candidates[0]
    candidate_policy = ROOT / chosen["implementation"]["candidatePolicyPath"]
    policy_source = candidate_policy.read_text(encoding="utf-8")
    model_version = str(chosen["report"].get("modelVersion") or "")
    if model_version and model_version not in policy_source:
        raise RuntimeError("CANDIDATE_POLICY_MODEL_VERSION_MISMATCH")

    shutil.copyfile(candidate_policy, PRODUCTION_POLICY)
    approval = {
        "productionPromotionApproved": True,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "constraintsVersion": config["version"],
        "targetRoiPct": config["promotionRules"]["targetRoiPct"],
        "modelVersion": model_version,
        "sourceReport": str(chosen["path"].relative_to(ROOT)),
        "sourceReportSha256": hashlib.sha256(chosen["raw"]).hexdigest(),
        "productionPolicyPath": str(PRODUCTION_POLICY.relative_to(ROOT)),
        "productionPolicySha256": hashlib.sha256(PRODUCTION_POLICY.read_bytes()).hexdigest(),
        "candidatePolicyPath": chosen["implementation"]["candidatePolicyPath"],
        "candidatePolicySha256": chosen["implementation"]["candidatePolicySha256"],
        "productionRunnerPath": chosen["implementation"]["productionRunnerPath"],
        "courses": chosen["courses"],
    }
    APPROVAL_PATH.write_text(json.dumps(approval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "promoted": True,
        "modelVersion": model_version,
        "sourceReport": approval["sourceReport"],
        "minimumFinalHoldoutRoiPct": chosen["score"][0],
        "minimumRoiWithoutTop1Pct": chosen["score"][1],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
