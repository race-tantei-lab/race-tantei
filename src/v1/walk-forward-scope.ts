export const WALK_FORWARD_SCOPE_VERSION = "walk-forward-12m-v2";

export const WALK_FORWARD_CONTEXT_START_DATE = "2024-05-01";
export const WALK_FORWARD_TRAIN_START_DATE = "2025-05-01";
export const WALK_FORWARD_TRAIN_END_DATE = "2026-04-30";
export const WALK_FORWARD_VALIDATION_START_DATE = "2026-05-02";
export const WALK_FORWARD_VALIDATION_END_DATE = "2026-06-28";
export const WALK_FORWARD_HOLDOUT_START_DATE = "2026-07-04";
export const WALK_FORWARD_HOLDOUT_END_DATE = "2026-07-26";

export const WALK_FORWARD_BASE_MODEL_VERSION = "walk-forward-base-v1";

export type WalkForwardSplit = "train" | "validation" | "holdout";

function inRange(value: string, start: string, end: string): boolean {
  return value >= start && value <= end;
}

export function walkForwardSplitForDate(raceDate: string): WalkForwardSplit | null {
  if (inRange(raceDate, WALK_FORWARD_TRAIN_START_DATE, WALK_FORWARD_TRAIN_END_DATE)) return "train";
  if (inRange(raceDate, WALK_FORWARD_VALIDATION_START_DATE, WALK_FORWARD_VALIDATION_END_DATE)) return "validation";
  if (inRange(raceDate, WALK_FORWARD_HOLDOUT_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE)) return "holdout";
  return null;
}

export function isWalkForwardDate(raceDate: string): boolean {
  return walkForwardSplitForDate(raceDate) !== null;
}

export function isWalkForwardArchiveDate(raceDate: string): boolean {
  return inRange(raceDate, WALK_FORWARD_CONTEXT_START_DATE, WALK_FORWARD_HOLDOUT_END_DATE);
}

function monthRange(startYearMonth: string, endYearMonth: string): string[] {
  const values: string[] = [];
  let year = Number(startYearMonth.slice(0, 4));
  let month = Number(startYearMonth.slice(4, 6));
  const endYear = Number(endYearMonth.slice(0, 4));
  const endMonth = Number(endYearMonth.slice(4, 6));
  while (year < endYear || (year === endYear && month <= endMonth)) {
    values.push(`${year}${String(month).padStart(2, "0")}`);
    month += 1;
    if (month === 13) {
      year += 1;
      month = 1;
    }
  }
  return values;
}

export const WALK_FORWARD_ARCHIVE_MONTHS = monthRange("202405", "202607");

export function assertWalkForwardScope(): void {
  const ordered = [
    WALK_FORWARD_CONTEXT_START_DATE,
    WALK_FORWARD_TRAIN_START_DATE,
    WALK_FORWARD_TRAIN_END_DATE,
    WALK_FORWARD_VALIDATION_START_DATE,
    WALK_FORWARD_VALIDATION_END_DATE,
    WALK_FORWARD_HOLDOUT_START_DATE,
    WALK_FORWARD_HOLDOUT_END_DATE
  ];
  for (let index = 1; index < ordered.length; index += 1) {
    if ((ordered[index - 1] ?? "") >= (ordered[index] ?? "")) {
      throw new Error(`WALK_FORWARD_SCOPE_OVERLAP:${ordered.join(":")}`);
    }
  }
}

assertWalkForwardScope();
