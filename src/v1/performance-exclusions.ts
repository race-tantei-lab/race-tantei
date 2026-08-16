export type PerformanceExclusionReason = "system_bet_generation_failure";

export interface PerformanceExclusion {
  raceId: string;
  reasonCode: PerformanceExclusionReason;
  displayReason: string;
  excludedFromPerformance: true;
}

export const PERFORMANCE_EXCLUSIONS: readonly PerformanceExclusion[] = [
  {
    raceId: "2026-08-16-chukyo-01",
    reasonCode: "system_bet_generation_failure",
    displayReason: "システム障害により締切時刻までに買い目を生成できませんでした（成績集計対象外）",
    excludedFromPerformance: true
  },
  {
    raceId: "2026-08-16-niigata-02",
    reasonCode: "system_bet_generation_failure",
    displayReason: "システム障害により締切時刻までに買い目を生成できませんでした（成績集計対象外）",
    excludedFromPerformance: true
  },
  {
    raceId: "2026-08-16-chukyo-04",
    reasonCode: "system_bet_generation_failure",
    displayReason: "システム障害により締切時刻までに買い目を生成できませんでした（成績集計対象外）",
    excludedFromPerformance: true
  }
];

const EXCLUSION_BY_RACE_ID = new Map(PERFORMANCE_EXCLUSIONS.map((row) => [row.raceId, row]));

export function performanceExclusionForRaceId(raceId: string): PerformanceExclusion | null {
  return EXCLUSION_BY_RACE_ID.get(raceId) ?? null;
}

export function performanceExclusionSql(column = "b.race_id"): string {
  if (!/^[A-Za-z_][A-Za-z0-9_.]*$/.test(column)) throw new Error(`INVALID_PERFORMANCE_EXCLUSION_COLUMN:${column}`);
  if (PERFORMANCE_EXCLUSIONS.length === 0) return "1=1";
  const values = PERFORMANCE_EXCLUSIONS.map((row) => `'${row.raceId.replaceAll("'", "''")}'`).join(",");
  return `${column} NOT IN (${values})`;
}
