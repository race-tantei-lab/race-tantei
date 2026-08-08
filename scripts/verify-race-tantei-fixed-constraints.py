import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "race-tantei-fixed-constraints.json"
DOC = ROOT / "docs" / "RACE_TANTEI_NON_NEGOTIABLE_RULES.md"
SPLIT = ROOT / "config" / "season-stratified-holdout-v1.json"
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
    if actual.get("version") != 8:
        raise SystemExit("FIXED_CONSTRAINT_VERSION_MUST_BE_8")

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
    if vp.get("type") != "season_stratified_prequential_holdout":
        raise SystemExit("PREQUENTIAL_SEASON_VALIDATION_REQUIRED")
    if vp.get("splitConfig") != "config/season-stratified-holdout-v1.json":
        raise SystemExit("CANONICAL_SEASON_SPLIT_MISSING")
    if vp.get("splitUnit") != "raceDate" or vp.get("stratification") != "year-month":
        raise SystemExit("INVALID_SEASON_SPLIT")
    if vp.get("sameDateMustStayTogether") is not True or vp.get("randomRaceLevelSplitForbidden") is not True:
        raise SystemExit("DATE_GROUPING_REQUIRED")
    if vp.get("heldoutOutcomeUseBeforeItsRaceDateForbidden") is not True:
        raise SystemExit("CURRENT_HOLDOUT_OUTCOME_LEAKAGE_FORBIDDEN")
    if vp.get("pastHeldoutOutcomeMayEnterFutureTrainingAfterDate") is not True:
        raise SystemExit("PAST_RESULTS_MUST_BE_AVAILABLE_TO_FUTURE_PREDICTIONS")
    if vp.get("predictionUsesOnlyInformationStrictlyAvailableBeforeRaceDate") is not True:
        raise SystemExit("PREDICTION_MUST_BE_CAUSAL")
    if vp.get("singleTailPeriodAsSoleCompletionHoldoutForbidden") is not True:
        raise SystemExit("TAIL_ONLY_HOLDOUT_FORBIDDEN")
    if vp.get("dateFeaturesRequired") != DATE_FEATURES:
        raise SystemExit("DATE_FEATURES_CHANGED")

    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    if split.get("splitUnit") != "raceDate" or split.get("stratification") != "year-month":
        raise SystemExit("HOLDOUT_SPLIT_CONFIG_INVALID")
    if split.get("outcomeFieldsUsedForSplit") is not False:
        raise SystemExit("HOLDOUT_SPLIT_MUST_NOT_USE_OUTCOMES")
    if len(split.get("holdoutDates", [])) < 1:
        raise SystemExit("HOLDOUT_DATES_MISSING")
    if split.get("counts", {}).get("minimumSelectedHoldoutRacesPerCourseAtFivePerVenueDay", 0) < 100:
        raise SystemExit("HOLDOUT_SAMPLE_TOO_SMALL")
    if split.get("dateFeaturesRequired") != DATE_FEATURES:
        raise SystemExit("SPLIT_DATE_FEATURES_CHANGED")
    er = split.get("evaluationRules", {})
    if er.get("outcomeOnEvaluationDateCannotAffectThatDatesPrediction") is not True:
        raise SystemExit("SAME_DATE_OUTCOME_LEAKAGE")
    if er.get("futureDateInformationCannotAffectEarlierPrediction") is not True:
        raise SystemExit("FUTURE_DATE_LEAKAGE")
    if er.get("pastEvaluationDateOutcomeMayBeUsedOnlyAfterThatDateForLaterPredictions") is not True:
        raise SystemExit("PREQUENTIAL_UPDATE_RULE_MISSING")

    promo = actual["promotionRules"]
    required_promo = {
        "completionRoiPct": 200.0,
        "approvedModelVersion": "v16",
        "minimumFinalHoldoutRacesPerCourse": 100,
        "requireEveryCourseToPass": True,
        "requireFullHistoricalRoiPct": 200.0,
        "requireSeasonStratifiedHoldoutRoiPct": 200.0,
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
        "最後の数か月だけを唯一の完成ホールドアウトとして使わない。",
        "評価日が終了した後、その結果は実運用と同様に次回以降の予測学習へ使ってよい。",
        "開催日・季節性をモデル入力に含める。",
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
