import type { BudgetCourse } from "./types.js";

export const APPROVED_PRODUCTION_MODEL_VERSION = "v5.0.0-nonlinear-course-policy";
export const APPROVED_PRODUCTION_MODEL_ACTIVE = true;
export const APPROVED_PRODUCTION_PROMOTION_ELIGIBLE = false;
export const APPROVED_PRODUCTION_TARGET_ROI_PCT = 200;
export const APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT = 36.8;
export const APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY = 5;

export const APPROVED_PRODUCTION_VALIDATION = {
  method: "非線形v4の馬順位・会場ごと5R選別と、コース別に異なる券種・点数・固定購入額を組み合わせた最終v5",
  validationStartDate: "2026-05-02",
  validationEndDate: "2026-06-28",
  holdoutStartDate: "2026-07-04",
  holdoutEndDate: "2026-07-26",
  validationRaces: 250,
  holdoutRaces: 120,
  validationMinimumRoiPct: 213.8275,
  holdoutMinimumRoiPct: 194.349,
  minimumHoldoutHitRatePct: 47.5,
  courseTargetStakes: {
    ライト: 1600,
    スタンダード: 4200,
    プレミアム: 8800
  },
  note: "ライトの7月回収率は194.3%で200%基準に5.7ポイント未達。スタンダードとプレミアムは200%を超過。"
} as const;

export const APPROVED_PRODUCTION_COURSE_METRICS: ReadonlyArray<{
  course: BudgetCourse;
  selectedRaces: number;
  validationRoiPct: number;
  validationHitRatePct: number;
  minimumValidationMonthRoiPct: number;
  roiPct: number;
  hitRatePct: number;
  targetStakeYen: number;
}> = [
  {
    course: "ライト",
    selectedRaces: 120,
    validationRoiPct: 213.8275,
    validationHitRatePct: 58,
    minimumValidationMonthRoiPct: 148.267,
    roiPct: 194.349,
    hitRatePct: 52.5,
    targetStakeYen: 1600
  },
  {
    course: "スタンダード",
    selectedRaces: 120,
    validationRoiPct: 351.439,
    validationHitRatePct: 50.8,
    minimumValidationMonthRoiPct: 212.5281,
    roiPct: 210.6964,
    hitRatePct: 47.5,
    targetStakeYen: 4200
  },
  {
    course: "プレミアム",
    selectedRaces: 120,
    validationRoiPct: 649.5891,
    validationHitRatePct: 58.8,
    minimumValidationMonthRoiPct: 427.7779,
    roiPct: 296.2008,
    hitRatePct: 52.5,
    targetStakeYen: 8800
  }
] as const;

export function isApprovedProductionModelVersion(modelVersion: string): boolean {
  return modelVersion === APPROVED_PRODUCTION_MODEL_VERSION;
}
