import type { BudgetCourse } from "./types.js";

export const APPROVED_PRODUCTION_MODEL_VERSION = "v4.1.0-nonlinear-hgb-5r";
export const APPROVED_PRODUCTION_MODEL_ACTIVE = true;
export const APPROVED_PRODUCTION_TARGET_ROI_PCT = 200;
export const APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT = 36.8;
export const APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY = 5;

export const APPROVED_PRODUCTION_VALIDATION = {
  method: "市場確率と時系列の馬・騎手・調教師・厩舎・近走・コース適性を使う非線形モデル",
  validationStartDate: "2026-05-02",
  validationEndDate: "2026-06-28",
  holdoutStartDate: "2026-07-04",
  holdoutEndDate: "2026-07-26",
  validationRaces: 250,
  holdoutRaces: 120,
  validationRoiPct: 662.256,
  validationHitRatePct: 50.8,
  minimumValidationMonthRoiPct: 251.0273,
  holdoutRoiPct: 237,
  holdoutHitRatePct: 48.3333,
  allocation: {
    wideTop1Top2Pct: 10,
    wideTop1Top3Pct: 10,
    trioTop1Top2Top3Pct: 80
  }
} as const;

export const APPROVED_PRODUCTION_COURSE_METRICS: ReadonlyArray<{
  course: BudgetCourse;
  selectedRaces: number;
  roiPct: number;
  hitRatePct: number;
}> = ["ライト", "スタンダード", "プレミアム"].map((course) => ({
  course: course as BudgetCourse,
  selectedRaces: APPROVED_PRODUCTION_VALIDATION.holdoutRaces,
  roiPct: APPROVED_PRODUCTION_VALIDATION.holdoutRoiPct,
  hitRatePct: APPROVED_PRODUCTION_VALIDATION.holdoutHitRatePct
}));

export function isApprovedProductionModelVersion(modelVersion: string): boolean {
  return modelVersion === APPROVED_PRODUCTION_MODEL_VERSION;
}
