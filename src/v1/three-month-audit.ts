import type { BudgetCourse } from "./types.js";
import { nowIso } from "./utils.js";

const START_DATE = "2026-05-02";
const END_DATE = "2026-08-02";
const THREE_MONTH_SUFFIX = "-roi-policy-v1-3m";
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const TARGET_STAKES: Record<BudgetCourse, number> = {
  ライト: 1600,
  スタンダード: 4200,
  プレミアム: 8800
};
const LEGACY_VALIDATION_MODELS: Record<string, string> = {
  "2026-08-01": "validation-2026-08-01-v3.0.0-value-engine-v1",
  "2026-08-02": "validation-2026-08-02-v3.0.0-value-engine-v1"
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
}

interface CourseValues {
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
}

interface RaceCourseAuditRow extends RaceRow, CourseValues {
  course: BudgetCourse;
  targetStakeYen: number;
  predictionId: number;
  modelVersion: string;
}

function n(value: unknown): number {
  return Number(value ?? 0);
}

function emptyValues(): CourseValues {
  return { tickets: 0, pendingTickets: 0, stakeYen: 0, returnYen: 0 };
}

function valuesFor(
  map: Map<string, BetAggregateRow>,
  predictionId: number | null | undefined,
  course: BudgetCourse
): CourseValues {
  if (!predictionId) return emptyValues();
  const row = map.get(`${predictionId}:${course}`);
  return row ? {
    tickets: row.tickets,
    pendingTickets: row.pendingTickets,
    stakeYen: row.stakeYen,
    returnYen: row.returnYen
  } : emptyValues();
}

function sameValues(left: CourseValues, right: CourseValues): boolean {
  return left.tickets === right.tickets
    && left.pendingTickets === right.pendingTickets
    && left.stakeYen === right.stakeYen
    && left.returnYen === right.returnYen;
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

function predictionForModel(rows: PredictionRow[], modelVersion: string): PredictionRow | null {
  return rows
    .filter((row) => row.modelVersion === modelVersion)
    .sort((a, b) => b.predictionId - a.predictionId)[0] ?? null;
}

function threeMonthModel(raceDate: string): string {
  return `validation-${raceDate}${THREE_MONTH_SUFFIX}`;
}

function selectLegacyDetailPrediction(rows: PredictionRow[], raceDate: string, liveModel: string): PredictionRow | null {
  const legacyValidation = LEGACY_VALIDATION_MODELS[raceDate];
  if (legacyValidation) {
    return rows
      .filter((row) => row.modelVersion === liveModel || row.modelVersion === legacyValidation)
      .sort((a, b) => {
        const aPriority = a.modelVersion === liveModel ? 1 : 2;
        const bPriority = b.modelVersion === liveModel ? 1 : 2;
        return aPriority - bPriority || b.predictionId - a.predictionId;
      })[0] ?? null;
  }
  return predictionForModel(rows, liveModel);
}

function selectArchivePrediction(rows: PredictionRow[], raceDate: string, liveModel: string): PredictionRow | null {
  const validationModel = threeMonthModel(raceDate);
  return [...rows].sort((a, b) => {
    const priority = (row: PredictionRow) => row.modelVersion === liveModel ? 1 : row.modelVersion === validationModel ? 2 : 9;
    return priority(a) - priority(b) || b.predictionId - a.predictionId;
  })[0] ?? null;
}

function comparison(
  race: RaceRow,
  source: PredictionRow | null,
  cumulative: PredictionRow | null,
  aggregates: Map<string, BetAggregateRow>
): null | Record<string, unknown> {
  const courseRows = COURSES.map((course) => {
    const displayed = valuesFor(aggregates, source?.predictionId, course);
    const counted = valuesFor(aggregates, cumulative?.predictionId, course);
    return { course, displayed, counted, matches: sameValues(displayed, counted) };
  });
  if (source?.predictionId === cumulative?.predictionId && courseRows.every((row) => row.matches)) return null;
  if (courseRows.every((row) => row.matches) && courseRows.every((row) => row.counted.tickets === 0)) return null;
  return {
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: race.raceNo,
    displayedPredictionId: source?.predictionId ?? null,
    displayedModelVersion: source?.modelVersion ?? null,
    cumulativePredictionId: cumulative?.predictionId ?? null,
    cumulativeModelVersion: cumulative?.modelVersion ?? null,
    courses: courseRows
  };
}

export async function getThreeMonthStakeAudit(
  db: D1Database,
  liveModel: string,
  includeAllRows = false
): Promise<Record<string, unknown>> {
  const [raceResult, predictionResult, betResult, venueResult] = await Promise.all([
    db.prepare(`
      SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo
      FROM rt_races
      WHERE race_date BETWEEN ? AND ? AND status='finished'
      ORDER BY race_date, venue, race_no
    `).bind(START_DATE, END_DATE).all<RaceRow>(),
    db.prepare(`
      SELECT p.id AS predictionId, p.race_id AS raceId, r.race_date AS raceDate,
        r.venue, r.race_no AS raceNo, p.model_version AS modelVersion
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date BETWEEN ? AND ? AND p.status='locked'
      ORDER BY r.race_date, r.venue, r.race_no, p.id
    `).bind(START_DATE, END_DATE).all<PredictionRow>(),
    db.prepare(`
      SELECT p.id AS predictionId,
        CASE
          WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
          WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
          WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
        END AS course,
        COUNT(*) AS tickets,
        SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END) AS pendingTickets,
        COALESCE(SUM(b.stake_yen),0) AS stakeYen,
        COALESCE(SUM(b.return_yen),0) AS returnYen
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date BETWEEN ? AND ?
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      GROUP BY p.id, course
    `).bind(START_DATE, END_DATE).all<BetAggregateRow>(),
    db.prepare(`
      SELECT COUNT(*) AS count FROM (
        SELECT race_date, venue FROM rt_races
        WHERE race_date BETWEEN ? AND ? AND status='finished'
        GROUP BY race_date, venue
      )
    `).bind(START_DATE, END_DATE).first<{ count: number }>()
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

  const cumulativeRows: RaceCourseAuditRow[] = [];
  const detailMismatches: Record<string, unknown>[] = [];
  const archiveMismatches: Record<string, unknown>[] = [];

  for (const race of races) {
    const racePredictions = predictionsByRace.get(race.raceId) ?? [];
    const cumulative = predictionForModel(racePredictions, threeMonthModel(race.raceDate));
    const legacyDetail = selectLegacyDetailPrediction(racePredictions, race.raceDate, liveModel);
    const archive = selectArchivePrediction(racePredictions, race.raceDate, liveModel);
    const detailMismatch = comparison(race, legacyDetail, cumulative, aggregates);
    const archiveMismatch = comparison(race, archive, cumulative, aggregates);
    if (detailMismatch) detailMismatches.push(detailMismatch);
    if (archiveMismatch) archiveMismatches.push(archiveMismatch);
    if (!cumulative) continue;
    for (const course of COURSES) {
      const values = valuesFor(aggregates, cumulative.predictionId, course);
      if (values.tickets === 0) continue;
      cumulativeRows.push({
        ...race,
        ...values,
        course,
        targetStakeYen: TARGET_STAKES[course],
        predictionId: cumulative.predictionId,
        modelVersion: cumulative.modelVersion
      });
    }
  }

  const stakeViolations = cumulativeRows.filter((row) => row.stakeYen !== row.targetStakeYen);
  const pendingRows = cumulativeRows.filter((row) => row.pendingTickets > 0);
  const venueDays = n(venueResult?.count);
  const requiredSelections = venueDays * 5;

  const courses = COURSES.map((course) => {
    const rows = cumulativeRows.filter((row) => row.course === course);
    const stakes = rows.map((row) => row.stakeYen);
    const hits = rows.filter((row) => row.returnYen > 0);
    const misses = rows.filter((row) => row.returnYen <= 0);
    const hitStakes = hits.map((row) => row.stakeYen);
    const missStakes = misses.map((row) => row.stakeYen);
    const totalStake = stakes.reduce((sum, value) => sum + value, 0);
    const totalReturn = rows.reduce((sum, row) => sum + row.returnYen, 0);
    return {
      course,
      targetStakeYen: TARGET_STAKES[course],
      requiredSelections,
      selectedRaces: rows.length,
      fixedStakeRaces: rows.filter((row) => row.stakeYen === TARGET_STAKES[course]).length,
      underStakeRaces: rows.filter((row) => row.stakeYen < TARGET_STAKES[course]).length,
      overStakeRaces: rows.filter((row) => row.stakeYen > TARGET_STAKES[course]).length,
      averageStakeYen: average(stakes),
      medianStakeYen: median(stakes),
      minimumStakeYen: stakes.length ? Math.min(...stakes) : null,
      maximumStakeYen: stakes.length ? Math.max(...stakes) : null,
      hitRaces: hits.length,
      missRaces: misses.length,
      averageHitStakeYen: average(hitStakes),
      averageMissStakeYen: average(missStakes),
      hitToMissAverageStakeRatio: average(hitStakes) !== null && average(missStakes)
        ? (average(hitStakes) ?? 0) / (average(missStakes) ?? 1)
        : null,
      stakeYen: totalStake,
      returnYen: totalReturn,
      roiPct: totalStake > 0 ? totalReturn / totalStake * 100 : null,
      pendingTickets: rows.reduce((sum, row) => sum + row.pendingTickets, 0)
    };
  });

  const months = [...new Set(cumulativeRows.map((row) => row.raceDate.slice(0, 7)))].sort();
  const monthly = months.map((month) => ({
    month,
    courses: COURSES.map((course) => {
      const rows = cumulativeRows.filter((row) => row.course === course && row.raceDate.startsWith(month));
      const stakeYen = rows.reduce((sum, row) => sum + row.stakeYen, 0);
      const returnYen = rows.reduce((sum, row) => sum + row.returnYen, 0);
      return {
        course,
        selectedRaces: rows.length,
        averageStakeYen: average(rows.map((row) => row.stakeYen)),
        fixedStakeRaces: rows.filter((row) => row.stakeYen === TARGET_STAKES[course]).length,
        stakeYen,
        returnYen,
        roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null
      };
    })
  }));

  const valid = stakeViolations.length === 0
    && pendingRows.length === 0
    && detailMismatches.length === 0
    && archiveMismatches.length === 0
    && courses.every((row) => row.selectedRaces === requiredSelections);

  return {
    auditVersion: "three-month-stake-reconciliation-v1",
    generatedAt: nowIso(),
    scope: { startDate: START_DATE, endDate: END_DATE, totalRaces: races.length, venueDays, requiredSelections },
    frozen: true,
    valid,
    findings: {
      stakeViolationRaceCourses: stakeViolations.length,
      pendingRaceCourses: pendingRows.length,
      individualDetailMismatchRaces: detailMismatches.length,
      archiveMismatchRaces: archiveMismatches.length
    },
    courses,
    monthly,
    stakeViolations: includeAllRows ? stakeViolations : stakeViolations.slice(0, 50),
    individualDetailMismatches: includeAllRows ? detailMismatches : detailMismatches.slice(0, 30),
    archiveMismatches: includeAllRows ? archiveMismatches : archiveMismatches.slice(0, 30),
    allSelectedRaceCourses: includeAllRows ? cumulativeRows : undefined
  };
}
