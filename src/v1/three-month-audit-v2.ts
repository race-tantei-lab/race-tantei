import type { BudgetCourse } from "./types.js";
import { THREE_MONTH_END_DATE, THREE_MONTH_START_DATE } from "./three-month-scope.js";
import { nowIso } from "./utils.js";

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const TARGET_STAKES: Record<BudgetCourse, number> = {
  ライト: 1600,
  スタンダード: 4200,
  プレミアム: 8800
};

interface RaceRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
}

interface PredictionRow extends RaceRow {
  predictionId: number;
  modelVersion: string;
}

interface BetAggregateRow {
  predictionId: number;
  course: BudgetCourse;
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
  ticketFingerprint: string | null;
}

interface CourseValues {
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
  ticketFingerprint: string;
}

interface AuditRow extends RaceRow, CourseValues {
  course: BudgetCourse;
  targetStakeYen: number;
  predictionId: number;
  modelVersion: string;
}

function n(value: unknown): number {
  return Number(value ?? 0);
}

function average(values: number[]): number | null {
  return values.length === 0 ? null : values.reduce((sum, value) => sum + value, 0) / values.length;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
    : sorted[middle] ?? null;
}

function modelForDate(raceDate: string): string {
  return `validation-${raceDate}-roi-policy-v1-3m`;
}

function emptyValues(): CourseValues {
  return { tickets: 0, pendingTickets: 0, stakeYen: 0, returnYen: 0, ticketFingerprint: "" };
}

function valuesFor(
  map: Map<string, BetAggregateRow>,
  predictionId: number | null,
  course: BudgetCourse
): CourseValues {
  if (!predictionId) return emptyValues();
  const row = map.get(`${predictionId}:${course}`);
  return row ? {
    tickets: row.tickets,
    pendingTickets: row.pendingTickets,
    stakeYen: row.stakeYen,
    returnYen: row.returnYen,
    ticketFingerprint: row.ticketFingerprint ?? ""
  } : emptyValues();
}

function summarizeCourse(rows: AuditRow[], course: BudgetCourse): Record<string, unknown> {
  const values = rows.filter((row) => row.course === course);
  const hits = values.filter((row) => row.returnYen > 0);
  const misses = values.filter((row) => row.returnYen <= 0);
  const stakeYen = values.reduce((sum, row) => sum + row.stakeYen, 0);
  const returnYen = values.reduce((sum, row) => sum + row.returnYen, 0);
  const hitAverage = average(hits.map((row) => row.stakeYen));
  const missAverage = average(misses.map((row) => row.stakeYen));
  return {
    course,
    targetStakeYen: TARGET_STAKES[course],
    selectedRaces: values.length,
    fixedStakeRaces: values.filter((row) => row.stakeYen === TARGET_STAKES[course]).length,
    underStakeRaces: values.filter((row) => row.stakeYen < TARGET_STAKES[course]).length,
    overStakeRaces: values.filter((row) => row.stakeYen > TARGET_STAKES[course]).length,
    averageStakeYen: average(values.map((row) => row.stakeYen)),
    medianStakeYen: median(values.map((row) => row.stakeYen)),
    minimumStakeYen: values.length ? Math.min(...values.map((row) => row.stakeYen)) : null,
    maximumStakeYen: values.length ? Math.max(...values.map((row) => row.stakeYen)) : null,
    hitRaces: hits.length,
    missRaces: misses.length,
    averageHitStakeYen: hitAverage,
    averageMissStakeYen: missAverage,
    hitToMissAverageStakeRatio: hitAverage !== null && missAverage ? hitAverage / missAverage : null,
    stakeYen,
    returnYen,
    profitYen: returnYen - stakeYen,
    roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
    pendingTickets: values.reduce((sum, row) => sum + row.pendingTickets, 0)
  };
}

function periodSummary(rows: AuditRow[], startDate: string, endDate: string): Record<string, unknown> {
  const periodRows = rows.filter((row) => row.raceDate >= startDate && row.raceDate <= endDate);
  return {
    startDate,
    endDate,
    selectedRaceCourses: periodRows.length,
    courses: COURSES.map((course) => summarizeCourse(periodRows, course))
  };
}

export async function getThreeMonthStakeAuditV2(
  db: D1Database,
  liveModel: string,
  includeAllRows = false
): Promise<Record<string, any>> {
  const [raceResult, predictionResult, betResult, venueResult] = await Promise.all([
    db.prepare(`
      SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo
      FROM rt_races
      WHERE race_date BETWEEN ? AND ? AND status='finished'
      ORDER BY race_date, venue, race_no
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<RaceRow>(),
    db.prepare(`
      SELECT p.id AS predictionId, p.race_id AS raceId, r.race_date AS raceDate,
        r.venue, r.race_no AS raceNo, p.model_version AS modelVersion
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date BETWEEN ? AND ? AND p.status='locked'
      ORDER BY r.race_date, r.venue, r.race_no, p.id
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<PredictionRow>(),
    db.prepare(`
      SELECT predictionId, course, COUNT(*) AS tickets,
        SUM(CASE WHEN settlementStatus<>'settled' THEN 1 ELSE 0 END) AS pendingTickets,
        SUM(stakeYen) AS stakeYen, SUM(returnYen) AS returnYen,
        GROUP_CONCAT(ticketKey,'||') AS ticketFingerprint
      FROM (
        SELECT p.id AS predictionId,
          CASE
            WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
            WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
            WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
          END AS course,
          b.stake_yen AS stakeYen, COALESCE(b.return_yen,0) AS returnYen,
          b.settlement_status AS settlementStatus,
          b.bet_type || ':' || b.combination || ':' || b.stake_yen || ':' || COALESCE(b.return_yen,'') || ':' || b.settlement_status AS ticketKey
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date BETWEEN ? AND ?
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
        ORDER BY p.id, course, b.bet_type, b.combination, b.stake_yen, b.id
      )
      GROUP BY predictionId, course
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).all<BetAggregateRow>(),
    db.prepare(`
      SELECT COUNT(*) AS count FROM (
        SELECT race_date, venue FROM rt_races
        WHERE race_date BETWEEN ? AND ? AND status='finished'
        GROUP BY race_date, venue
      )
    `).bind(THREE_MONTH_START_DATE, THREE_MONTH_END_DATE).first<{ count: number }>()
  ]);

  const races = raceResult.results.map((row) => ({ ...row, raceNo: n(row.raceNo) }));
  const predictions = predictionResult.results.map((row) => ({
    ...row,
    predictionId: n(row.predictionId),
    raceNo: n(row.raceNo)
  }));
  const aggregates = new Map<string, BetAggregateRow>();
  for (const raw of betResult.results) {
    if (!COURSES.includes(raw.course)) continue;
    const row = {
      ...raw,
      predictionId: n(raw.predictionId),
      tickets: n(raw.tickets),
      pendingTickets: n(raw.pendingTickets),
      stakeYen: n(raw.stakeYen),
      returnYen: n(raw.returnYen)
    };
    aggregates.set(`${row.predictionId}:${row.course}`, row);
  }

  const predictionsByRace = new Map<string, PredictionRow[]>();
  for (const prediction of predictions) {
    const rows = predictionsByRace.get(prediction.raceId) ?? [];
    rows.push(prediction);
    predictionsByRace.set(prediction.raceId, rows);
  }

  const auditRows: AuditRow[] = [];
  const missingModelRaces: RaceRow[] = [];
  const displayMismatches: Record<string, unknown>[] = [];
  for (const race of races) {
    const exactModel = modelForDate(race.raceDate);
    const racePredictions = predictionsByRace.get(race.raceId) ?? [];
    const cumulative = racePredictions
      .filter((row) => row.modelVersion === exactModel)
      .sort((a, b) => b.predictionId - a.predictionId)[0] ?? null;
    const displayed = cumulative ?? racePredictions
      .filter((row) => row.modelVersion === liveModel)
      .sort((a, b) => b.predictionId - a.predictionId)[0] ?? null;
    if (!cumulative) missingModelRaces.push(race);
    if (displayed?.predictionId !== cumulative?.predictionId) {
      displayMismatches.push({
        ...race,
        displayedPredictionId: displayed?.predictionId ?? null,
        displayedModelVersion: displayed?.modelVersion ?? null,
        cumulativePredictionId: cumulative?.predictionId ?? null,
        cumulativeModelVersion: cumulative?.modelVersion ?? null
      });
    }
    if (!cumulative) continue;
    for (const course of COURSES) {
      const values = valuesFor(aggregates, cumulative.predictionId, course);
      if (values.tickets === 0) continue;
      auditRows.push({
        ...race,
        ...values,
        course,
        targetStakeYen: TARGET_STAKES[course],
        predictionId: cumulative.predictionId,
        modelVersion: cumulative.modelVersion
      });
    }
  }

  const stakeViolations = auditRows.filter((row) => row.stakeYen !== row.targetStakeYen);
  const pendingRows = auditRows.filter((row) => row.pendingTickets > 0);
  const raceCourseCounts = new Map<string, number>();
  for (const row of auditRows) raceCourseCounts.set(row.raceId, (raceCourseCounts.get(row.raceId) ?? 0) + 1);
  const courseSelectionMismatchRaces = races.filter((race) => {
    const count = raceCourseCounts.get(race.raceId) ?? 0;
    return count !== 0 && count !== COURSES.length;
  });

  const quotaGroups = new Map<string, Map<BudgetCourse, number>>();
  for (const row of auditRows) {
    const key = `${row.raceDate}:${row.venue}`;
    const group = quotaGroups.get(key) ?? new Map<BudgetCourse, number>();
    group.set(row.course, (group.get(row.course) ?? 0) + 1);
    quotaGroups.set(key, group);
  }
  const quotaViolations = [...quotaGroups.entries()].filter(([, group]) =>
    COURSES.some((course) => (group.get(course) ?? 0) !== 5)
  ).map(([venueDay, group]) => ({
    venueDay,
    courses: Object.fromEntries(COURSES.map((course) => [course, group.get(course) ?? 0]))
  }));

  const venueDays = n(venueResult?.count);
  const requiredSelections = venueDays * 5;
  const courses = COURSES.map((course) => ({
    requiredSelections,
    ...summarizeCourse(auditRows, course)
  }));
  const months = [...new Set(races.map((row) => row.raceDate.slice(0, 7)))].sort();
  const monthly = months.map((month) => ({
    month,
    courses: COURSES.map((course) => summarizeCourse(
      auditRows.filter((row) => row.raceDate.startsWith(month)),
      course
    ))
  }));

  const valid = missingModelRaces.length === 0
    && displayMismatches.length === 0
    && stakeViolations.length === 0
    && pendingRows.length === 0
    && courseSelectionMismatchRaces.length === 0
    && quotaViolations.length === 0
    && courses.every((row) => row.selectedRaces === requiredSelections);

  return {
    auditVersion: "three-month-stake-reconciliation-v2",
    generatedAt: nowIso(),
    scope: {
      startDate: THREE_MONTH_START_DATE,
      endDate: THREE_MONTH_END_DATE,
      totalRaces: races.length,
      venueDays,
      requiredSelections
    },
    valid,
    findings: {
      missingModelRaces: missingModelRaces.length,
      stakeViolationRaceCourses: stakeViolations.length,
      pendingRaceCourses: pendingRows.length,
      individualDetailMismatchRaces: displayMismatches.length,
      archiveMismatchRaces: displayMismatches.length,
      courseSelectionMismatchRaces: courseSelectionMismatchRaces.length,
      venueQuotaViolations: quotaViolations.length
    },
    courses,
    monthly,
    evaluationPeriod: periodSummary(auditRows, THREE_MONTH_START_DATE, "2026-07-26"),
    tuningPeriod: periodSummary(auditRows, "2026-08-01", THREE_MONTH_END_DATE),
    stakeViolations: includeAllRows ? stakeViolations : stakeViolations.slice(0, 50),
    displayMismatches: includeAllRows ? displayMismatches : displayMismatches.slice(0, 30),
    quotaViolations: includeAllRows ? quotaViolations : quotaViolations.slice(0, 30),
    courseSelectionMismatchRaces: includeAllRows ? courseSelectionMismatchRaces : courseSelectionMismatchRaces.slice(0, 30),
    allSelectedRaceCourses: includeAllRows ? auditRows : undefined
  };
}
