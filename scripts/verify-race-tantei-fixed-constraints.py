import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "race-tantei-fixed-constraints.json"
DOC = ROOT / "docs" / "RACE_TANTEI_NON_NEGOTIABLE_RULES.md"
PRODUCTION_POLICY = ROOT / "scripts" / "final-course-policy.py"
PROMOTION_GATE = ROOT / "scripts" / "verify-production-candidate.py"
PROMOTER = ROOT / "scripts" / "find-and-promote-production-candidate.py"

ALL_BET_TYPES = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]
AUX_CALENDAR_FEATURES = ["calendarMonthSin", "calendarMonthCos", "dayOfYearSin", "dayOfYearCos"]


def main() -> None:
    actual = json.loads(CONFIG.read_text(encoding="utf-8"))
    if actual.get("version") != 11:
        raise SystemExit("FIXED_CONSTRAINT_VERSION_MUST_BE_11")

    imm = actual["immutableProjectRules"]
    required_imm = {
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
        "calendarContextMustBeAvailableAsAuxiliaryFeatures": True,
        "calendarFeaturesMustNotBePrimaryDiscoveryAxis": True,
        "calendarOnlyOrYearSpecificRulesForbidden": True,
    }
    for key, value in required_imm.items():
        if imm.get(key) != value:
            raise SystemExit(f"IMMUTABLE_RULE_CHANGED:{key}")

    vp = actual.get("validationProtocol", {})
    if vp.get("type") != "season_balanced_date_group_crossfit":
        raise SystemExit("SEASON_BALANCED_CROSSFIT_REQUIRED")
    if vp.get("foldCount") != 5:
        raise SystemExit("FIVE_FOLDS_REQUIRED")
    if vp.get("splitUnit") != "raceDate" or vp.get("stratification") != "year-month":
        raise SystemExit("DATE_GROUPED_MONTH_BALANCED_SPLIT_REQUIRED")
    if vp.get("sameDateMustStayTogether") is not True:
        raise SystemExit("SAME_DATE_MUST_STAY_TOGETHER")
    if vp.get("randomRaceLevelSplitForbidden") is not True:
        raise SystemExit("RACE_LEVEL_RANDOM_SPLIT_FORBIDDEN")
    if vp.get("eachRaceDateMustBeOutOfFoldExactlyOnce") is not True:
        raise SystemExit("EVERY_DATE_MUST_BE_OOF_ONCE")
    if vp.get("outOfFoldOutcomeUseForThatPredictionForbidden") is not True:
        raise SystemExit("OOF_OUTCOME_LEAKAGE_FORBIDDEN")
    if vp.get("calendarFeatureRole") != "auxiliary_only":
        raise SystemExit("CALENDAR_FEATURES_MUST_BE_AUXILIARY")
    if vp.get("calendarFeatures") != AUX_CALENDAR_FEATURES:
        raise SystemExit("AUXILIARY_CALENDAR_FEATURES_CHANGED")
    if vp.get("rawCalendarYearFeatureForbidden") is not True:
        raise SystemExit("RAW_YEAR_FEATURE_FORBIDDEN")
    if vp.get("rawDateOrdinalFeatureForbidden") is not True:
        raise SystemExit("RAW_DATE_ORDINAL_FORBIDDEN")
    if vp.get("dateSpecificRuleDiscoveryForbidden") is not True:
        raise SystemExit("DATE_SPECIFIC_RULES_FORBIDDEN")
    if vp.get("previousOpenedFinalAuditIsDiagnosticOnly") is not True:
        raise SystemExit("OPENED_FINAL_AUDIT_MUST_BE_DIAGNOSTIC_ONLY")
    if vp.get("livePredictionStillUsesOnlyInformationAvailableAtPredictionTime") is not True:
        raise SystemExit("LIVE_CAUSALITY_REQUIRED")

    promo = actual["promotionRules"]
    required_promo = {
        "completionRoiPct": 200.0,
        "approvedModelVersion": "v16",
        "minimumCrossfitEvaluationRacesPerCourse": 100,
        "requireEveryCourseToPass": True,
        "requireFullHistoricalRoiPct": 200.0,
        "requireSeasonBalancedOutOfFoldRoiPct": 200.0,
        "requireRoiWithoutTop1Pct": 100.0,
        "requireFullHistoricalPeriodCoverage": True,
        "candidateVersionNumbersForbidden": True,
        "incompleteCandidateIsNotModel": True,
        "implementationBeforeAllGatesPassForbidden": True,
        "failedCandidateMayBeRecordedInternally": True,
        "automaticProductionChangeFromFailedCandidateForbidden": True,
    }
    for key, value in required_promo.items():
        if promo.get(key) != value:
            raise SystemExit(f"PROMOTION_RULE_CHANGED:{key}")

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

    doc = DOC.read_text(encoding="utf-8")
    for text in (
        "日付・季節は多数ある分析要素の一部として補助的に扱う。",
        "season-balanced 5-fold crossfit",
        "各開催日は必ず1回だけout-of-foldで評価する。",
        "回収率200%以上は目標ではなく完成条件とする。",
    ):
        if text not in doc:
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
    for pattern in (
        "payout_ratio / market_probability",
        "PAYOUT_RATIO[bet_type] / market_probability",
        "market_probability = event_probability",
    ):
        if pattern in source:
            raise SystemExit(f"SYNTHETIC_ODDS_PATTERN_FOUND:{pattern}")

    promotion_source = PROMOTER.read_text(encoding="utf-8")
    if 'approvedModelVersion' not in promotion_source or 'modelVersion' not in promotion_source:
        raise SystemExit("APPROVED_VERSION_MUST_BE_ASSIGNED_ONLY_BY_PROMOTER")

    print("Fixed race-tantei constraints verified.")


if __name__ == "__main__":
    main()
