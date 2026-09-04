import { POST_AUG9_PUBLIC_SNAPSHOT } from "./post-aug9-public-snapshot.js";
import { projectCurrentPublicState } from "./current-day-public-api.js";
import { summarizeTodayPerformance, type TodayPerformanceBetRow } from "./today-performance.js";

const SNAPSHOT_VERSION = "post-aug9-public-snapshot-v1";
const PERFORMANCE_VERSION = "daily-performance-v6-target-race-count-20260830";
const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;
const BASE_COURSE = "ライト";
const SAFE_DATES = new Set(["2026-08-15", "2026-08-16", "2026-08-22", "2026-08-23", "2026-08-29", "2026-08-30"]);

type SnapshotRace = {
  race_id: string;
  race_date: string;
  venue: string;
  race_no: number;
  race_name: string | null;
  start_time_jst: string | null;
  start_time_utc: string | null;
  surface: string | null;
  distance_m: number | null;
  status: string;
  refund_horse_nos_json: string | null;
};

type SnapshotBet = {
  race_id: string;
  course: string;
  bet_type: string;
  combination: string;
  stake_yen: number;
  return_yen: number | null;
  settlement_status: string;
  source_prediction_id: number | null;
  locked_at: string | null;
};

type SnapshotDay = { races: readonly SnapshotRace[]; bets: readonly SnapshotBet[]; selection: string | null };
type SnapshotRoot = { version: string; dates: Record<string, SnapshotDay> };
type CanonicalBetRow = TodayPerformanceBetRow & { raceDate: string };
type CourseView = {
  course: string;
  finalizedRaces: number;
  settledRaces: number;
  hitRaces: number;
  refundRaces: number;
  finalizedStakeYen: number;
  settledStakeYen: number;
  returnYen: number;
  pendingStakeYen: number;
  profitYen: number;
  roiPct: number | null;
};
type DayView = CourseView & { date: string; courses: CourseView[] };

const SNAPSHOT = POST_AUG9_PUBLIC_SNAPSHOT as unknown as SnapshotRoot;

function parseSelection(raw: string | null): Set<string> | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { selected?: Array<{ raceId?: unknown }> };
    if (!Array.isArray(parsed.selected)) return null;
    const ids = parsed.selected.map((row) => String(row?.raceId ?? "")).filter(Boolean);
    return ids.length ? new Set(ids) : null;
  } catch {
    return null;
  }
}

function canonicalRows(day: SnapshotDay): CanonicalBetRow[] {
  const refunds = new Map(day.races.map((race) => [String(race.race_id), race.refund_horse_nos_json]));
  return day.bets.map((bet) => ({
    raceDate: String(bet.race_id).slice(0, 10),
    raceId: String(bet.race_id),
    course: String(bet.course),
    betType: String(bet.bet_type),
    combination: String(bet.combination),
    stakeYen: Number(bet.stake_yen ?? 0),
    returnYen: bet.return_yen === null ? null : Number(bet.return_yen),
    settlementStatus: String(bet.settlement_status),
    refundsJson: refunds.get(String(bet.race_id)) ?? null,
  }));
}

function canonicalDay(date: string, rows: CanonicalBetRow[]): DayView {
  const stats = summarizeTodayPerformance(rows, COURSES);
  const courses: CourseView[] = stats.map((stat) => {
    const allRows = rows.filter((row) => String(row.course) === stat.course);
    const finalizedRaces = new Set(allRows.map((row) => String(row.raceId)).filter(Boolean)).size;
    const finalizedStakeYen = allRows.reduce((sum, row) => sum + Number(row.stakeYen ?? 0), 0);
    const settledStakeYen = Number(stat.stakeYen ?? 0);
    const returnYen = Number(stat.returnYen ?? 0);
    return {
      course: stat.course,
      finalizedRaces,
      settledRaces: Number(stat.settledRaces ?? 0),
      hitRaces: Number(stat.hitRaces ?? 0),
      refundRaces: Number(stat.refundRaces ?? 0),
      finalizedStakeYen,
      settledStakeYen,
      returnYen,
      pendingStakeYen: Math.max(0, finalizedStakeYen - settledStakeYen),
      profitYen: returnYen - settledStakeYen,
      roiPct: stat.roiPct == null ? null : Number(stat.roiPct),
    };
  });
  const base = courses.find((row) => row.course === BASE_COURSE) ?? courses[0] ?? {
    course: BASE_COURSE,
    finalizedRaces: 0,
    settledRaces: 0,
    hitRaces: 0,
    refundRaces: 0,
    finalizedStakeYen: 0,
    settledStakeYen: 0,
    returnYen: 0,
    pendingStakeYen: 0,
    profitYen: 0,
    roiPct: null,
  };
  return { ...base, date, courses };
}

function targetCount(day: SnapshotDay | undefined): number {
  if (!day) return 0;
  const selected = parseSelection(day.selection);
  return selected?.size ?? new Set(day.bets.map((row) => String(row.race_id))).size;
}

export function hasPostAug9SnapshotDate(date: string): boolean {
  return SAFE_DATES.has(date) && Boolean(SNAPSHOT.dates[date]);
}

export function postAug9DayResponse(date: string, now = new Date()): Response | null {
  if (!hasPostAug9SnapshotDate(date)) return null;
  const day = SNAPSHOT.dates[date];
  if (!day) return null;
  const frozen = parseSelection(day.selection);
  const refunds = new Map(day.races.map((race) => [String(race.race_id), race.refund_horse_nos_json]));
  const byRace = new Map<string, Array<{
    raceId: string; course: string; betType: string; combination: string; returnYen: number | null; settlementStatus: string; refundsJson: string | null;
  }>>();
  for (const bet of day.bets) {
    const raceId = String(bet.race_id);
    const list = byRace.get(raceId) ?? [];
    list.push({
      raceId,
      course: String(bet.course),
      betType: String(bet.bet_type),
      combination: String(bet.combination),
      returnYen: bet.return_yen === null ? null : Number(bet.return_yen),
      settlementStatus: String(bet.settlement_status),
      refundsJson: refunds.get(raceId) ?? null,
    });
    byRace.set(raceId, list);
  }
  const races = day.races.map((race) => {
    const projectedRace = {
      raceId: String(race.race_id),
      raceDate: String(race.race_date),
      startTimeJst: race.start_time_jst,
      startTimeUtc: race.start_time_utc,
    };
    return {
      raceId: String(race.race_id),
      raceDate: String(race.race_date),
      venue: String(race.venue),
      raceNo: Number(race.race_no),
      raceName: race.race_name,
      startTimeJst: race.start_time_jst,
      startTimeUtc: race.start_time_utc,
      surface: race.surface,
      distanceM: race.distance_m === null ? null : Number(race.distance_m),
      status: String(race.status),
      publicState: projectCurrentPublicState(projectedRace, frozen, byRace.get(String(race.race_id)) ?? [], now.getTime()),
    };
  });
  return Response.json({ ok: true, date, races }, {
    headers: {
      "cache-control": "public, max-age=3600, immutable",
      "x-race-history-source": SNAPSHOT_VERSION,
    },
  });
}

export function postAug9PerformanceResponse(requestedDate: string, today: string): Response {
  const dates = [...SAFE_DATES].filter((date) => Boolean(SNAPSHOT.dates[date])).sort((a, b) => b.localeCompare(a));
  const date = /^20\d{2}-\d{2}-\d{2}$/.test(requestedDate) ? requestedDate : today;
  const history = dates.map((d) => {
    const day = SNAPSHOT.dates[d];
    const rows = day ? canonicalRows(day) : [];
    return { ...canonicalDay(d, rows), targetRaces: targetCount(day) };
  });
  const selectedDay = SNAPSHOT.dates[date];
  const selectedRows = selectedDay && SAFE_DATES.has(date) ? canonicalRows(selectedDay) : [];
  return Response.json({
    ok: true,
    version: PERFORMANCE_VERSION,
    today,
    roiBasis: "ライト・2点とも精算完了したレースのみ",
    summary: { ...canonicalDay(date, selectedRows), targetRaces: targetCount(selectedDay) },
    history,
    recent30: null,
    fallbackSource: SNAPSHOT_VERSION,
  }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-performance-api": PERFORMANCE_VERSION,
      "x-race-history-source": SNAPSHOT_VERSION,
    },
  });
}
