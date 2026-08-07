import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "analysis-results"
CONFIG_PATH = ROOT / "config" / "race-tantei-fixed-constraints.json"
APPROVAL_PATH = ROOT / "config" / "approved-production-model.json"
COMPLETION_REPORT_PATH = REPORTS / "v16-completion-report.json"
PRODUCTION_POLICY = ROOT / "scripts" / "final-course-policy.py"
VERIFIER_PATH = ROOT / "scripts" / "verify-production-candidate.py"
APPROVAL_PLACEHOLDER = "__APPROVED_MODEL_VERSION__"


def load_verifier():
    spec = importlib.util.spec_from_file_location("production_candidate_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PRODUCTION_VERIFIER_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report_score(courses):
    full = [float(row["fullHistoricalRoiPct"]) for row in courses.values()]
    final = [float(row["finalHoldoutRoiPct"]) for row in courses.values()]
    trimmed = [float(row["roiWithoutTop1Pct"]) for row in courses.values()]
    return min(final), min(full), min(trimmed), sum(final) / len(final)


def main() -> None:
    verifier = load_verifier()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    approved_version = str(config["promotionRules"]["approvedModelVersion"])
    candidates = []
    checked = 0

    for path in sorted(REPORTS.glob("exploration-*.json")):
        checked += 1
        try:
            raw = path.read_bytes()
            report = json.loads(raw.decode("utf-8"))
            if not isinstance(report, dict):
                continue
            exploration_id, courses, implementation = verifier.validate_report(report, config)
            candidates.append({
                "path": path,
                "raw": raw,
                "report": report,
                "explorationId": exploration_id,
                "courses": courses,
                "implementation": implementation,
                "score": report_score(courses),
            })
        except Exception:
            continue

    if not candidates:
        print(json.dumps({
            "promoted": False,
            "checkedExplorations": checked,
        }, ensure_ascii=False))
        return

    candidates.sort(key=lambda row: row["score"], reverse=True)
    chosen = candidates[0]
    candidate_policy = ROOT / chosen["implementation"]["candidatePolicyPath"]
    policy_source = candidate_policy.read_text(encoding="utf-8")
    if APPROVAL_PLACEHOLDER not in policy_source:
        raise RuntimeError("CANDIDATE_POLICY_APPROVAL_PLACEHOLDER_MISSING")
    promoted_source = policy_source.replace(APPROVAL_PLACEHOLDER, approved_version)
    if APPROVAL_PLACEHOLDER in promoted_source:
        raise RuntimeError("CANDIDATE_POLICY_APPROVAL_PLACEHOLDER_REMAINS")
    if f'MODEL_VERSION = "{approved_version}"' not in promoted_source:
        raise RuntimeError("PROMOTED_MODEL_VERSION_NOT_ASSIGNED")

    PRODUCTION_POLICY.write_text(promoted_source, encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    approval = {
        "productionPromotionApproved": True,
        "approvedAt": now,
        "constraintsVersion": config["version"],
        "completionRoiPct": config["promotionRules"]["completionRoiPct"],
        "modelVersion": approved_version,
        "sourceExplorationId": chosen["explorationId"],
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

    completion_report = dict(chosen["report"])
    completion_report["modelVersion"] = approved_version
    completion_report["completionApproved"] = True
    completion_report["approvedAt"] = now
    completion_report["sourceExplorationId"] = chosen["explorationId"]
    COMPLETION_REPORT_PATH.write_text(
        json.dumps(completion_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "promoted": True,
        "modelVersion": approved_version,
        "sourceExplorationId": chosen["explorationId"],
        "minimumFullHistoricalRoiPct": chosen["score"][1],
        "minimumFinalHoldoutRoiPct": chosen["score"][0],
        "minimumRoiWithoutTop1Pct": chosen["score"][2],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
