import base from "./public-site-entry-quota-recovery-20260912.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

type SnapshotRace = {
  raceId: string;
  refundsJson: string | null;
};

type SnapshotBet = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  returnYen: number | null;
  settlementStatus: string;
};

type SnapshotDay = {
  selection: string | null;
  races: SnapshotRace[];
  bets: SnapshotBet[];
};

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

type DayPerformance = CoursePerformance & {
  date: string;
  courses: CoursePerformance[];
  targetRaces?: number;
};

type PerformancePayload = {
  history?: DayPerformance[];
  [key: string]: unknown;
};

const DAYS = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;
const COURSES: readonly CourseName[] = ["ライト", "スタンダード", "プレミアム"];
const COURSE_STAKE_YEN: Readonly<Record<CourseName, number>> = {
  "ライト": 2_000,
  "スタンダード": 5_000,
  "プレミアム": 10_000,
};
const HISTORY_SOURCE = "recent-public-day-snapshot-v3-all-dates";

function parseSelectionCount(day: SnapshotDay): number {
  if (!day.selection) return 0;
  try {
    const parsed = JSON.parse(day.selection) as { selected?: Array<{ raceId?: unknown }> };
    return new Set(
      (parsed.selected ?? [])
        .map((row) => String(row?.raceId ?? ""))
        .filter(Boolean),
    ).size;
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
    return new Set(
      Array.isArray(parsed)
        ? parsed.map(Number).filter((value) => Number.isInteger(value))
        : [],
    );
  } catch {
    return new Set();
  }
}

function summarizeSnapshotDay(date: string, day: SnapshotDay): DayPerformance {
  const refundsByRace = new Map(
    day.races.map((race) => [race.raceId, refundSet(race.refundsJson)]),
  );

  const courses = COURSES.map((course): CoursePerformance => {
    const byRace = new Map<string, SnapshotBet[]>();
    for (const bet of day.bets ?? []) {
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

  const baseCourse = courses.find((row) => row.course === "ライト")!;
  return {
    ...baseCourse,
    date,
    courses,
    targetRaces: parseSelectionCount(day),
  };
}

function mergeSnapshotDates(history: DayPerformance[] | undefined): DayPerformance[] {
  const byDate = new Map<string, DayPerformance>();
  for (const row of history ?? []) {
    if (row?.date) byDate.set(String(row.date), row);
  }

  for (const [date, day] of Object.entries(DAYS)) {
    if (!day?.races?.length || byDate.has(date)) continue;
    byDate.set(date, summarizeSnapshotDay(date, day));
  }

  return [...byDate.values()]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 30);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });

    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);
    if (
      request.method !== "GET" ||
      url.pathname !== "/api/public/daily-performance" ||
      !response.ok
    ) {
      return response;
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) return response;

    try {
      const payload = await response.clone().json() as PerformancePayload;
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-history-source", HISTORY_SOURCE);
      return Response.json({
        ...payload,
        history: mergeSnapshotDates(payload.history),
      }, {
        status: response.status,
        headers,
      });
    } catch (error) {
      console.error("DAILY_PERFORMANCE_HISTORY_MERGE_FAILED", error);
      return response;
    }
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const raceDay = await shouldRunOnJraRaceDay(new Date());
    if (!raceDay.shouldRun) {
      return;
    }
    // runBoundedPublicMaintenance remains owned by the delegated public scheduler.
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
