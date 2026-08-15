export type TodayPerformanceBetRow = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  stakeYen: number;
  returnYen: number | null;
  settlementStatus: string;
  refundsJson: string | null;
};

export type TodayCoursePerformance = {
  course: string;
  totalRaces: number;
  settledRaces: number;
  hitRaces: number;
  refundRaces: number;
  stakeYen: number;
  returnYen: number;
  roiPct: number | null;
  complete: boolean;
};

function horseNos(combination: string): number[] {
  return (String(combination).match(/\d{1,2}/g) ?? [])
    .map(Number)
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= 18);
}

function refundSet(raw: string | null): Set<number> {
  try {
    const parsed = JSON.parse(String(raw ?? "[]"));
    return new Set(Array.isArray(parsed) ? parsed.map(Number).filter((value) => Number.isInteger(value)) : []);
  } catch {
    return new Set();
  }
}

function isRefundTicket(row: TodayPerformanceBetRow): boolean {
  const refunds = refundSet(row.refundsJson);
  return horseNos(row.combination).some((horseNo) => refunds.has(horseNo));
}

/**
 * Public live races are canonical only when one course has exactly two ticket
 * rows and both rows have settled. A partial or duplicate group is excluded
 * from stake/return/ROI until it becomes a valid complete group.
 */
export function summarizeTodayPerformance(
  rows: TodayPerformanceBetRow[],
  courses: readonly string[],
): TodayCoursePerformance[] {
  const byCourseRace = new Map<string, TodayPerformanceBetRow[]>();
  const raceIdsByCourse = new Map<string, Set<string>>();

  for (const raw of rows) {
    const row: TodayPerformanceBetRow = {
      ...raw,
      raceId: String(raw.raceId),
      course: String(raw.course),
      betType: String(raw.betType),
      combination: String(raw.combination),
      stakeYen: Number(raw.stakeYen ?? 0),
      returnYen: raw.returnYen === null ? null : Number(raw.returnYen),
      settlementStatus: String(raw.settlementStatus),
      refundsJson: raw.refundsJson === null ? null : String(raw.refundsJson),
    };
    if (!row.raceId || !row.course) continue;
    const key = `${row.course}\u0000${row.raceId}`;
    const list = byCourseRace.get(key) ?? [];
    list.push(row);
    byCourseRace.set(key, list);
    const ids = raceIdsByCourse.get(row.course) ?? new Set<string>();
    ids.add(row.raceId);
    raceIdsByCourse.set(row.course, ids);
  }

  return courses.map((course) => {
    const raceIds = raceIdsByCourse.get(course) ?? new Set<string>();
    let settledRaces = 0;
    let hitRaces = 0;
    let refundRaces = 0;
    let stakeYen = 0;
    let returnYen = 0;

    for (const raceId of raceIds) {
      const group = byCourseRace.get(`${course}\u0000${raceId}`) ?? [];
      const validComplete = group.length === 2 && group.every((row) => row.settlementStatus === "settled");
      if (!validComplete) continue;

      settledRaces += 1;
      stakeYen += group.reduce((sum, row) => sum + Number(row.stakeYen || 0), 0);
      returnYen += group.reduce((sum, row) => sum + Number(row.returnYen ?? 0), 0);

      let genuineHit = false;
      let hasRefund = false;
      for (const row of group) {
        const refunded = isRefundTicket(row);
        if (refunded) hasRefund = true;
        if (!refunded && Number(row.returnYen ?? 0) > 0) genuineHit = true;
      }
      if (genuineHit) hitRaces += 1;
      if (hasRefund) refundRaces += 1;
    }

    const totalRaces = raceIds.size;
    return {
      course,
      totalRaces,
      settledRaces,
      hitRaces,
      refundRaces,
      stakeYen,
      returnYen,
      roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
      complete: totalRaces > 0 && totalRaces === settledRaces,
    };
  });
}
