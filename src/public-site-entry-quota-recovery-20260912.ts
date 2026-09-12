import recovery from "./public-site-entry-recovery-20260906.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
import { postAug9PerformanceResponse } from "./v1/post-aug9-public-fallback.js";
import { projectCurrentPublicState } from "./v1/current-day-public-api.js";
import type { Env } from "./v1/types.js";

type SnapshotRace = {
  raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string | null;
  startTimeJst: string | null; startTimeUtc: string | null; surface: string | null;
  distanceM: number | null; status: string; refundsJson: string | null;
};
type SnapshotBet = {
  raceId: string; course: string; betType: string; combination: string;
  returnYen: number | null; settlementStatus: string;
};
type SnapshotDay = { selection: string | null; races: SnapshotRace[]; bets: SnapshotBet[] };
type CourseName = "ライト" | "スタンダード" | "プレミアム";
type CoursePerformance = {
  course: CourseName;
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
type DayPerformance = CoursePerformance & { date: string; courses: CoursePerformance[]; targetRaces?: number };

const DAYS = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;
const COURSES: readonly CourseName[] = ["ライト", "スタンダード", "プレミアム"];
const COURSE_STAKE_YEN: Readonly<Record<CourseName, number>> = {
  "ライト": 2_000,
  "スタンダード": 5_000,
  "プレミアム": 10_000,
};
const PERFORMANCE_VERSION = "daily-performance-v6-target-race-count-20260830";
const QUOTA_FALLBACK_SOURCE = "recent-public-day-snapshot-v2-quota-lockout-performance";

function jstToday(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function parseSelectionCount(day: SnapshotDay | undefined): number {
  if (!day?.selection) return 0;
  try {
    const parsed = JSON.parse(day.selection) as { selected?: Array<{ raceId?: unknown }> };
    return new Set((parsed.selected ?? []).map((row) => String(row?.raceId ?? "")).filter(Boolean)).size;
  } catch {
    return 0;
  }
}

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

function summarizeSnapshotDay(date: string, day: SnapshotDay): DayPerformance {
  const refundsByRace = new Map(day.races.map((race) => [race.raceId, refundSet(race.refundsJson)]));
  const courses = COURSES.map((course): CoursePerformance => {
    const byRace = new Map<string, SnapshotBet[]>();
    for (const bet of day.bets) {
      if (bet.course !== course) continue;
      const rows = byRace.get(bet.raceId) ?? [];
      rows.push(bet);
      byRace.set(bet.raceId, rows);
    }

    let finalizedRaces = 0;
    let settledRaces = 0;
    let hitRaces = 0;
    let refundRaces = 0;
    let returnYen = 0;
    for (const [raceId, rows] of byRace) {
      if (rows.length !== 2) continue;
      finalizedRaces += 1;
      if (!rows.every((row) => row.settlementStatus === "settled")) continue;
      settledRaces += 1;
      let genuineHit = false;
      let hasRefund = false;
      const refunds = refundsByRace.get(raceId) ?? new Set<number>();
      for (const row of rows) {
        const refunded = horseNos(row.combination).some((horseNo) => refunds.has(horseNo));
        if (refunded) hasRefund = true;
        if (!refunded && Number(row.returnYen ?? 0) > 0) genuineHit = true;
        returnYen += Number(row.returnYen ?? 0);
      }
      if (genuineHit) hitRaces += 1;
      if (hasRefund) refundRaces += 1;
    }

    const finalizedStakeYen = finalizedRaces * COURSE_STAKE_YEN[course];
    const settledStakeYen = settledRaces * COURSE_STAKE_YEN[course];
    return {
      course,
      finalizedRaces,
      settledRaces,
      hitRaces,
      refundRaces,
      finalizedStakeYen,
      settledStakeYen,
      returnYen,
      pendingStakeYen: Math.max(0, finalizedStakeYen - settledStakeYen),
      profitYen: returnYen - settledStakeYen,
      roiPct: settledStakeYen > 0 ? returnYen / settledStakeYen * 100 : null,
    };
  });

  const base = courses.find((row) => row.course === "ライト")!;
  return { ...base, date, courses, targetRaces: parseSelectionCount(day) };
}

async function snapshotPerformanceResponse(date: string, today: string): Promise<Response | null> {
  const day = DAYS[date];
  if (!day?.races?.length) return null;
  const summary = summarizeSnapshotDay(date, day);

  const legacy = await postAug9PerformanceResponse(date, today).json() as {
    history?: DayPerformance[];
    recent30?: unknown;
  };
  const historyByDate = new Map<string, DayPerformance>();
  for (const row of legacy.history ?? []) historyByDate.set(String(row.date), row);
  for (const [snapshotDate, snapshotDay] of Object.entries(DAYS)) {
    if (!snapshotDay?.bets?.length || historyByDate.has(snapshotDate)) continue;
    historyByDate.set(snapshotDate, summarizeSnapshotDay(snapshotDate, snapshotDay));
  }
  historyByDate.set(date, summary);
  const history = [...historyByDate.values()]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 30);

  return Response.json({
    ok: true,
    version: PERFORMANCE_VERSION,
    today,
    roiBasis: "ライト・2点とも精算完了したレースのみ",
    summary,
    history,
    recent30: legacy.recent30 ?? null,
    fallbackSource: QUOTA_FALLBACK_SOURCE,
  }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-performance-api": PERFORMANCE_VERSION,
      "x-race-history-source": QUOTA_FALLBACK_SOURCE,
    },
  });
}

function snapshotTodaySummary(date: string): Response | null {
  const day = DAYS[date];
  if (!day?.races?.length) return null;
  const perf = summarizeSnapshotDay(date, day);
  const courses = perf.courses.map((row) => ({
    course: row.course,
    totalRaces: row.finalizedRaces,
    settledRaces: row.settledRaces,
    hitRaces: row.hitRaces,
    refundRaces: row.refundRaces,
    stakeYen: row.settledStakeYen,
    returnYen: row.returnYen,
    roiPct: row.roiPct,
    complete: row.finalizedRaces > 0 && row.finalizedRaces === row.settledRaces,
  }));
  return Response.json({
    ok: true,
    date,
    hasPredictions: courses.some((row) => row.totalRaces > 0),
    targetRaces: perf.targetRaces ?? 0,
    courses,
    fallbackSource: QUOTA_FALLBACK_SOURCE,
  }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-today-summary-source": QUOTA_FALLBACK_SOURCE,
    },
  });
}

function snapshotResponse(date: string): Response | null {
  const day = DAYS[date];
  if (!day?.races?.length) return null;
  let selected: Set<string> | null = null;
  try {
    const parsed = JSON.parse(String(day.selection ?? "")) as { selected?: Array<{ raceId?: unknown }> };
    const ids = (parsed.selected ?? []).map((row) => String(row?.raceId ?? "")).filter(Boolean);
    selected = ids.length ? new Set(ids) : null;
  } catch { /* no frozen selection */ }

  const refunds = new Map(day.races.map((race) => [race.raceId, race.refundsJson]));
  const byRace = new Map<string, Array<SnapshotBet & { refundsJson: string | null }>>();
  for (const bet of day.bets) {
    const rows = byRace.get(bet.raceId) ?? [];
    rows.push({ ...bet, refundsJson: refunds.get(bet.raceId) ?? null });
    byRace.set(bet.raceId, rows);
  }
  const nowMs = Date.now();
  const races = day.races.map((race) => ({
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: Number(race.raceNo),
    raceName: race.raceName,
    startTimeJst: race.startTimeJst,
    startTimeUtc: race.startTimeUtc,
    surface: race.surface,
    distanceM: race.distanceM === null ? null : Number(race.distanceM),
    status: race.status,
    publicState: projectCurrentPublicState(race, selected, byRace.get(race.raceId) ?? [], nowMs),
  }));

  return Response.json({
    ok: true,
    date,
    races,
    betStateAvailable: true,
    fallbackSource: "recent-public-day-snapshot-v1-quota-lockout",
  }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-current-day-path": "recent-public-day-snapshot-v1-quota-lockout",
    },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const today = jstToday();
    if (request.method === "GET" && url.pathname === "/api/public/day") {
      const date = url.searchParams.get("date") ?? "";
      if (date === today) {
        const snapshot = snapshotResponse(date);
        if (snapshot) return snapshot;
      }
    }
    if (request.method === "GET" && url.pathname === "/api/public/daily-performance") {
      const date = url.searchParams.get("date") || today;
      if (date === today) {
        const snapshot = await snapshotPerformanceResponse(date, today);
        if (snapshot) return snapshot;
      }
    }
    if (request.method === "GET" && url.pathname === "/api/public/today-summary") {
      const snapshot = snapshotTodaySummary(today);
      if (snapshot) return snapshot;
    }
    if (!recovery.fetch) return new Response("NOT_FOUND", { status: 404 });
    return recovery.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // 2026-09-12 production D1 rows_read is hard-blocked until the UTC daily reset.
    // Do not hammer D1 from the public maintenance cron during that lockout.
    const date = jstToday(Number.isFinite(controller.scheduledTime) ? new Date(controller.scheduledTime) : new Date());
    if (date === "2026-09-12") {
      console.warn("PUBLIC_D1_READ_LOCKOUT_SKIP", date);
      return;
    }
    if (recovery.scheduled) await recovery.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
