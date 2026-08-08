import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "race-tantei-fixed-constraints.json"
DOC = ROOT / "docs" / "RACE_TANTEI_NON_NEGOTIABLE_RULES.md"
PRODUCTION_POLICY = ROOT / "scripts" / "final-course-policy.py"
PROMOTION_GATE = ROOT / "scripts" / "verify-production-candidate.py"
PROMOTER = ROOT / "scripts" / "find-and-promote-production-candidate.py"

ALL_BET_TYPES = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]

EXPECTED = {
    "version": 6,
    "canonicalDocument": "docs/RACE_TANTEI_NON_NEGOTIABLE_RULES.md",
    "immutableProjectRules": {
        "minimumRacesPerVenueDay": 5,
        "mayIncreaseRaces": True,
        "mayDecreaseBelowMinimum": False,
        "officialOddsOnly": True,
        "officialCombinationOddsRequiredForLiveBets": True,
        "syntheticOddsForbidden": True,
        "missingHistoricalOddsMustRemainMissing": True,
        "actualJraPayoutsOnly": True,
        "postResultLeakageForbidden": True,
        "singleOnlyPortfolioForbidden": True,
        "minimumDistinctBetTypesPerRace": 2,
        "betTypeSelectionMayVaryByRace": True,
        "fullAvailablePeriodRequired": True,
        "droppingEvaluationPeriodsForbidden": True,
        "ticketCountFixed": False,
        "ticketCountMayVaryByCourseRaceAndPolicy": True,
    },
    "promotionRules": {
        "completionRoiPct": 200.0,
        "approvedModelVersion": "v16",
        "minimumFinalHoldoutRacesPerCourse": 100,
        "requireEveryCourseToPass": True,
        "requireFullHistoricalRoiPct": 200.0,
        "requireFinalHoldoutRoiPct": 200.0,
        "requireRoiWithoutTop1Pct": 100.0,
        "requireFullHistoricalPeriodCoverage": True,
        "candidateVersionNumbersForbidden": True,
        "incompleteCandidateIsNotModel": True,
        "implementationBeforeAllGatesPassForbidden": True,
        "failedCandidateMayBeRecordedInternally": True,
        "automaticProductionChangeFromFailedCandidateForbidden": True,
    },
    "operationRules": {
        "explainWorkBeforeStarting": True,
        "maximumSilentSeconds": 60,
        "continueWithoutRepeatedUserApproval": True,
        "progressReportsUseKeyNumbersOnly": True,
        "failedExplorationResultsReportedIndividually": False,
        "completionClaimBeforeAllGatesPassForbidden": True,
    },
    "courses": {
        "ライト": {
            "budgetYen": 2000,
            "allowedBetTypes": ALL_BET_TYPES,
            "requireEveryAllowedBetType": False,
            "minimumDistinctBetTypes": 2,
        },
        "スタンダード": {
            "budgetYen": 5000,
            "allowedBetTypes": ALL_BET_TYPES,
            "requireEveryAllowedBetType": False,
            "minimumDistinctBetTypes": 2,
        },
        "プレミアム": {
            "budgetYen": 10000,
            "allowedBetTypes": ALL_BET_TYPES,
            "requireEveryAllowedBetType": False,
            "minimumDistinctBetTypes": 2,
        },
    },
}

REQUIRED_DOC_TEXT = (
    "各開催日・各会場で、購入対象を5レース未満にしてはならない。",
    "買い目点数は固定しない。",
    "券種はレースごとに可変とする。",
    "各購入対象レースで最低2種類の異なる券種を含める。",
    "回収率200%以上は目標ではなく完成条件とする。",
    "探索途中の候補にはバージョン番号を付けない。",
    "`v16` という名称は、全条件と全ゲートを通過した完成物にだけ付与する。",
    "完成判定の全期間回収率は、利用可能な最初のレースから最新の終了済みレースまでを漏れなく含める。",
    "不合格結果を逐一ユーザーへ並べて報告しない。",
)

FORBIDDEN_PRODUCTION_PATTERNS = (
    "payout_ratio / market_probability",
    "PAYOUT_RATIO[bet_type] / market_probability",
    "market_probability = event_probability",
)


def main() -> None:
    actual = json.loads(CONFIG.read_text(encoding="utf-8"))
    if actual != EXPECTED:
        raise SystemExit(
            "FIXED_CONSTRAINTS_CHANGED: minimum five races, fixed budgets, flexible ticket counts, dynamic bet types with minimum two, "
            "official odds only, full-period coverage, completion ROI 200, no candidate version numbers, and reporting rules are immutable."
        )

    if not DOC.exists():
        raise SystemExit("CANONICAL_RULE_DOCUMENT_MISSING")
    document = DOC.read_text(encoding="utf-8")
    for text in REQUIRED_DOC_TEXT:
        if text not in document:
            raise SystemExit(f"CANONICAL_RULE_DOCUMENT_INCOMPLETE:{text}")

    if not PROMOTION_GATE.exists():
        raise SystemExit("PRODUCTION_PROMOTION_GATE_MISSING")
    if not PROMOTER.exists():
        raise SystemExit("PRODUCTION_PROMOTER_MISSING")

    source = PRODUCTION_POLICY.read_text(encoding="utf-8")
    if 'OFFICIAL_ODDS_SOURCE = "jra_official"' not in source:
        raise SystemExit("OFFICIAL_ODDS_SOURCE_NOT_ENFORCED")
    if 'race.get("oddsSource") != OFFICIAL_ODDS_SOURCE' not in source:
        raise SystemExit("LIVE_BETS_DO_NOT_REQUIRE_OFFICIAL_ODDS")
    for pattern in FORBIDDEN_PRODUCTION_PATTERNS:
        if pattern in source:
            raise SystemExit(f"SYNTHETIC_ODDS_PATTERN_FOUND:{pattern}")

    promotion_source = PROMOTER.read_text(encoding="utf-8")
    if 'approvedModelVersion' not in promotion_source or 'modelVersion' not in promotion_source:
        raise SystemExit("APPROVED_VERSION_MUST_BE_ASSIGNED_ONLY_BY_PROMOTER")

    if actual["immutableProjectRules"].get("ticketCountFixed") is not False:
        raise SystemExit("TICKET_COUNT_MUST_NOT_BE_FIXED")
    if actual["immutableProjectRules"].get("ticketCountMayVaryByCourseRaceAndPolicy") is not True:
        raise SystemExit("TICKET_COUNT_FLEXIBILITY_MISSING")
    if actual["immutableProjectRules"].get("minimumDistinctBetTypesPerRace") != 2:
        raise SystemExit("MINIMUM_TWO_BET_TYPES_REQUIRED")
    if actual["immutableProjectRules"].get("betTypeSelectionMayVaryByRace") is not True:
        raise SystemExit("BET_TYPE_SELECTION_MUST_BE_DYNAMIC")

    for course, spec in actual["courses"].items():
        if "ticketCount" in spec:
            raise SystemExit(f"TICKET_COUNT_MUST_NOT_BE_CANONICAL:{course}")
        if spec["budgetYen"] <= 0:
            raise SystemExit(f"INVALID_COURSE_BUDGET:{course}")
        if spec["allowedBetTypes"] != ALL_BET_TYPES:
            raise SystemExit(f"ALL_BET_TYPES_MUST_BE_AVAILABLE:{course}")
        if spec["requireEveryAllowedBetType"] is not False:
            raise SystemExit(f"EVERY_BET_TYPE_MUST_NOT_BE_REQUIRED:{course}")
        if spec["minimumDistinctBetTypes"] != 2:
            raise SystemExit(f"MINIMUM_TWO_BET_TYPES_REQUIRED:{course}")

    print("Fixed race-tantei constraints verified.")


if __name__ == "__main__":
    main()
