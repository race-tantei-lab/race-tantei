import type { ValidationConfig } from "./validation.js";

export const THREE_MONTH_SCOPE_VERSION = "three-month-2026-05-02-to-2026-08-02-v2-correct-popularity";
export const THREE_MONTH_START_DATE = "2026-05-02";
export const THREE_MONTH_EVALUATION_END_DATE = "2026-07-26";
export const THREE_MONTH_TUNING_START_DATE = "2026-08-01";
export const THREE_MONTH_END_DATE = "2026-08-02";

export const THREE_MONTH_RACE_DATES = [
  "2026-05-02", "2026-05-03", "2026-05-09", "2026-05-10",
  "2026-05-16", "2026-05-17", "2026-05-23", "2026-05-24",
  "2026-05-30", "2026-05-31",
  "2026-06-06", "2026-06-07", "2026-06-13", "2026-06-14",
  "2026-06-20", "2026-06-21", "2026-06-27", "2026-06-28",
  "2026-07-04", "2026-07-05", "2026-07-11", "2026-07-12",
  "2026-07-18", "2026-07-19", "2026-07-25", "2026-07-26",
  "2026-08-01", "2026-08-02"
] as const;

function labelForDate(raceDate: string): string {
  const [year, month, day] = raceDate.split("-");
  return `${year}年${Number(month)}月${Number(day)}日`;
}

export const THREE_MONTH_VALIDATION_CONFIGS: readonly ValidationConfig[] =
  THREE_MONTH_RACE_DATES.map((raceDate) => ({
    raceDate,
    modelVersion: `validation-${raceDate}-roi-policy-v1-3m`,
    label: labelForDate(raceDate)
  }));

export function isThreeMonthDate(value: string): boolean {
  return (THREE_MONTH_RACE_DATES as readonly string[]).includes(value);
}

export function isThreeMonthTuningDate(value: string): boolean {
  return value >= THREE_MONTH_TUNING_START_DATE && value <= THREE_MONTH_END_DATE;
}
