import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "official-odds-roi200-forward-search.json"
OUTPUT = ROOT / "official-odds-roi200-promotion-candidate.json"
POLICY = ROOT / "scripts" / "official-odds-roi200-policy-v2.py"
MODEL_VERSION = "v14.1-official-odds-constrained-roi200"

TEMPLATES = {
    "ライト": [
        {"betType": "単勝", "stakeYen": 300},
        {"betType": "ワイド", "stakeYen": 300},
        {"betType": "ワイド", "stakeYen": 300},
        {"betType": "ワイド", "stakeYen": 300},
        {"betType": "馬連", "stakeYen": 400},
        {"betType": "馬連", "stakeYen": 400},
    ],
    "スタンダード": [
        {"betType": "単勝", "stakeYen": 400},
        *[{"betType": "ワイド", "stakeYen": 300} for _ in range(4)],
        *[{"betType": "馬連", "stakeYen": 400} for _ in range(2)],
        *[{"betType": "馬単", "stakeYen": 300} for _ in range(5)],
        {"betType": "3連複", "stakeYen": 400},
        {"betType": "3連複", "stakeYen": 400},
        {"betType": "3連複", "stakeYen": 300},
    ],
    "プレミアム": [
        {"betType": "単勝", "stakeYen": 500},
        *[{"betType": "ワイド", "stakeYen": 500} for _ in range(2)],
        *[{"betType": "馬連", "stakeYen": 500} for _ in range(2)],
        *[{"betType": "馬単", "stakeYen": 600} for _ in range(3)],
        *[{"betType": "3連複", "stakeYen": 700} for _ in range(3)],
        *[{"betType": "3連単", "stakeYen": 700} for _ in range(4)],
        {"betType": "3連単", "stakeYen": 800},
    ],
}


def main():
    if not SOURCE.exists():
        raise SystemExit("OFFICIAL_ODDS_FORWARD_REPORT_MISSING")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if source.get("promotionEligible") is not True:
        OUTPUT.unlink(missing_ok=True)
        print(json.dumps({"promotionCandidateCreated": False, "status": source.get("status")}, ensure_ascii=False))
        return

    holdout = source.get("finalHoldout") or {}
    holdout_courses = holdout.get("courses") or {}
    coverage = holdout.get("coverage") or []
    minimum_coverage = min((int(row.get("selected") or 0) for row in coverage), default=0)
    if minimum_coverage < 5:
        raise SystemExit(f"OFFICIAL_ODDS_PROMOTION_COVERAGE_BELOW_FIVE:{minimum_coverage}")

    courses = {}
    for course, template in TEMPLATES.items():
        result = holdout_courses.get(course)
        if not isinstance(result, dict):
            raise SystemExit(f"OFFICIAL_ODDS_PROMOTION_COURSE_MISSING:{course}")
        if float(result.get("roiPct") or 0) < 200.0:
            raise SystemExit(f"OFFICIAL_ODDS_PROMOTION_ROI_BELOW_200:{course}:{result.get('roiPct')}")
        if float(result.get("roiWithoutTop1Pct") or 0) < 100.0:
            raise SystemExit(f"OFFICIAL_ODDS_PROMOTION_TOP1_DEPENDENCE:{course}")
        courses[course] = {
            "finalHoldout": result,
            "coverage": {"minimumSelectedRaces": minimum_coverage},
            "policy": {"dynamicOfficialOddsPolicy": True, "template": template},
        }

    policy_sha = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    report = {
        "generatedAt": source.get("generatedAt"),
        "modelVersion": MODEL_VERSION,
        "productionChanged": False,
        "promotionEligible": True,
        "sourceDataFrozen": True,
        "actualJraPayoutsUsed": True,
        "actualJraPayoutsOnly": True,
        "officialOddsOnly": True,
        "officialWinOddsUsed": True,
        "liveBetGenerationRequiresOfficialCombinationOdds": True,
        "officialCombinationOddsRequiredForLiveBets": True,
        "syntheticOddsUsed": False,
        "postResultLeakageUsed": False,
        "guardrails": {
            "sourceDataFrozen": True,
            "actualJraPayoutsOnly": True,
            "officialOddsOnly": True,
            "officialCombinationOddsRequiredForLiveBets": True,
            "syntheticOddsForbidden": True,
            "postResultLeakageForbidden": True,
        },
        "productionImplementation": {
            "candidatePolicyPath": "scripts/official-odds-roi200-policy-v2.py",
            "candidatePolicySha256": policy_sha,
            "productionRunnerPath": "scripts/publish-official-odds-roi200-production-v2.py",
        },
        "courses": courses,
        "sourceForwardReport": "analysis-results/official-odds-roi200-forward-search.json",
        "calibrationFactors": source.get("calibrationFactors"),
        "selectedRacesPerVenueDay": (source.get("bestDevelopmentConfiguration") or {}).get("racesPerVenueDay"),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promotionCandidateCreated": True, "modelVersion": MODEL_VERSION}, ensure_ascii=False))


if __name__ == "__main__":
    main()
