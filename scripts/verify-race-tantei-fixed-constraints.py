import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "race-tantei-fixed-constraints.json"
DOC = ROOT / "docs" / "RACE_TANTEI_NON_NEGOTIABLE_RULES.md"
VISIBLE = ROOT / "config" / "season-stratified-holdout-v1.json"
FINAL = ROOT / "config" / "season-stratified-final-audit-v1.json"
PRODUCTION_POLICY = ROOT / "scripts" / "final-course-policy.py"
PROMOTION_GATE = ROOT / "scripts" / "verify-production-candidate.py"
PROMOTER = ROOT / "scripts" / "find-and-promote-production-candidate.py"

ALL_BET_TYPES = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]
DATE_FEATURES = [
    "calendarYear", "calendarMonth", "dayOfYearSin", "dayOfYearCos",
    "weekOfYearSin", "weekOfYearCos", "daysSinceArchiveStart",
    "seasonQuarter", "venue", "venueXMonth",
]


def main() -> None:
    actual = json.loads(CONFIG.read_text(encoding="utf-8"))
    if actual.get("version") != 9:
        raise SystemExit("FIXED_CONSTRAINT_VERSION_MUST_BE_9")

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
        "calendarSeasonalityMustBeModeled": True,
    }
    for k, v in required_imm.items():
        if imm.get(k) != v:
            raise SystemExit(f"IMMUTABLE_RULE_CHANGED:{k}")

    vp = actual.get("validationProtocol", {})
    if vp.get("type") != "nested_season_stratified_group_holdout":
        raise SystemExit("NESTED_SEASON_GROUP_HOLDOUT_REQUIRED")
    if vp.get("visibleDevelopmentValidationConfig") != "config/season-stratified-holdout-v1.json":
        raise SystemExit("VISIBLE_VALIDATION_CONFIG_CHANGED")
    if vp.get("untouchedFinalAuditConfig") != "config/season-stratified-final-audit-v1.json":
        raise SystemExit("FINAL_AUDIT_CONFIG_CHANGED")
    if vp.get("splitUnit") != "raceDate" or vp.get("stratification") != "year-month":
        raise SystemExit("INVALID_GROUP_HOLDOUT")
    if vp.get("sameDateMustStayTogether") is not True or vp.get("randomRaceLevelSplitForbidden") is not True:
        raise SystemExit("DATE_GROUPING_REQUIRED")
    if vp.get("finalAuditOutcomeUseForDiscoveryForbidden") is not True:
        raise SystemExit("FINAL_AUDIT_LEAKAGE_FORBIDDEN")
    if vp.get("developmentMayUseAllNonFinalAuditDates") is not True:
        raise SystemExit("DEVELOPMENT_SET_RULE_CHANGED")
    if vp.get("historicalFinalAuditIsGeneralizationTestNotWalkForwardReplay") is not True:
        raise SystemExit("FINAL_AUDIT_PURPOSE_CHANGED")
    if vp.get("livePredictionStillUsesOnlyInformationAvailableAtPredictionTime") is not True:
        raise SystemExit("LIVE_CAUSALITY_REQUIRED")
    if vp.get("singleTailPeriodAsSoleCompletionHoldoutForbidden") is not True:
        raise SystemExit("TAIL_ONLY_HOLDOUT_FORBIDDEN")
    if vp.get("dateFeaturesRequired") != DATE_FEATURES:
        raise SystemExit("DATE_FEATURES_CHANGED")

    visible = json.loads(VISIBLE.read_text(encoding="utf-8"))
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    visible_dates = set(visible.get("holdoutDates", []))
    final_dates = set(final.get("finalAuditDates", []))
    if not visible_dates or not final_dates:
        raise SystemExit("VALIDATION_OR_FINAL_DATES_MISSING")
    if visible_dates & final_dates:
        raise SystemExit("FINAL_AUDIT_MUST_NOT_OVERLAP_VISIBLE_VALIDATION")
    if final.get("outcomeFieldsUsedForSplit") is not False:
        raise SystemExit("FINAL_AUDIT_SPLIT_MUST_NOT_USE_OUTCOMES")
    if final.get("counts", {}).get("minimumSelectedFinalAuditRacesPerCourseAtFivePerVenueDay", 0) < 100:
        raise SystemExit("FINAL_AUDIT_SAMPLE_TOO_SMALL")
    if final.get("evaluationRules", {}).get("finalAuditOutcomeMustNotBeInspectedBeforeModelFreeze") is not True:
        raise SystemExit("MODEL_MUST_FREEZE_BEFORE_FINAL_AUDIT")
    if final.get("evaluationRules", {}).get("modelRuleAndThresholdChangesAfterOpeningFinalAuditForbidden") is not True:
        raise SystemExit("FINAL_AUDIT_POST_TUNING_FORBIDDEN")

    promo = actual["promotionRules"]
    required_promo = {
        "completionRoiPct": 200.0,
        "approvedModelVersion": "v16",
        "minimumFinalHoldoutRacesPerCourse": 100,
        "requireEveryCourseToPass": True,
        "requireFullHistoricalRoiPct": 200.0,
        "requireSeasonStratifiedFinalAuditRoiPct": 200.0,
        "requireRoiWithoutTop1Pct": 100.0,
        "requireFullHistoricalPeriodCoverage": True,
        "candidateVersionNumbersForbidden": True,
        "incompleteCandidateIsNotModel": True,
        "implementationBeforeAllGatesPassForbidden": True,
        "failedCandidateMayBeRecordedInternally": True,
        "automaticProductionChangeFromFailedCandidateForbidden": True,
    }
    for k, v in required_promo.items():
        if promo.get(k) != v:
            raise SystemExit(f"PROMOTION_RULE_CHANGED:{k}")

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
        "各開催日・各会場で、購入対象を5レース未満にしてはならない。",
        "各購入対象レースで最低2種類の異なる券種を含める。",
        "完全未使用の最終監査は `config/season-stratified-final-audit-v1.json` の35開催日とする。",
        "最終監査35開催日の着順・払戻などの結果を、モデル発見、ルール選択、閾値調整、資金配分調整に使ってはならない。",
        "実際の未来レースを予測するときは、その予測時点までに取得できる情報だけを使う。",
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
