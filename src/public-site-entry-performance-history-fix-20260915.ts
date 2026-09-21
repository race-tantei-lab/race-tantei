import base from "./public-site-entry-quota-recovery-20260912.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
import type { Env } from "./v1/types.js";

type SnapshotRace = {
  raceId: string;
  refundsJson: string | null;
  status?: string | null;
};

type SnapshotBet = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  stakeYen?: number;
  returnYen: number | null;
  settlementStatus: string;
  refundsJson?: string | null;
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

type LiveBetRow = SnapshotBet & { refundsJson: string | null };

const DAYS = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;
const COURSES: readonly CourseName[] = ["ライト", "スタンダード", "プレミアム"];
const COURSE_STAKE_YEN: Readonly<Record<CourseName, number>> = {
  "ライト": 2_000,
  "スタンダード": 5_000,
  "プレミアム": 10_000,
};
const HISTORY_SOURCE = "snapshot-history-plus-date-bounded-live-v4";
const D1_READ_BACKOFF_MS = 60_000;
let d1ReadBackoffUntilMs = 0;

function d1ReadBackoffActive(nowMs = Date.now()): boolean {
  return nowMs < d1ReadBackoffUntilMs;
}

function tripD1ReadBackoff(nowMs = Date.now()): void {
  d1ReadBackoffUntilMs = Math.max(d1ReadBackoffUntilMs, nowMs + D1_READ_BACKOFF_MS);
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function validDate(value: string | null): value is string {
  return Boolean(value && /^20\d{2}-\d{2}-\d{2}$/.test(value));
}

function parseSelectionCountRaw(raw: string | null | undefined): number {
  if (!raw) return 0;
  try {
    const parsed = JSON.parse(raw) as { selected?: Array<{ raceId?: unknown }> };
    return new Set((parsed.selected ?? []).map((row) => String(row?.raceId ?? "")).filter(Boolean)).size;
  } catch {
    return 0;
  }
}

function parseSelectionCount(day: SnapshotDay): number {
  if (!day.selection) return 0;
  try {
    const parsed = JSON.parse(day.selection) as { selected?: Array<{ raceId?: unknown }> };
    const selected = new Set((parsed.selected ?? []).map((row) => String(row?.raceId ?? "")).filter(Boolean));
    const cancelled = new Set(["cancelled", "canceled", "postponed"]);
    return (day.races ?? []).filter((race) =>
      selected.has(String(race.raceId ?? ""))
      && !cancelled.has(String(race.status ?? "scheduled").toLowerCase())
    ).length;
  } catch {
    return 0;
  }
}

function horseNos(combination: string): number[] {
  return (String(combination).match(/\d{1,2}/g) ?? [])
    .map(Number)
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= 18);
}

function refundSet(raw: string | null | undefined): Set<number> {
  try {
    const parsed = JSON.parse(String(raw ?? "[]"));
    return new Set(Array.isArray(parsed) ? parsed.map(Number).filter((value) => Number.isInteger(value)) : []);
  } catch {
    return new Set();
  }
}

function summarizeDay(date: string, races: SnapshotRace[], bets: SnapshotBet[], targetRaces: number): DayPerformance {
  const refundsByRace = new Map(races.map((race) => [race.raceId, refundSet(race.refundsJson)]));
  for (const bet of bets) {
    if (bet.refundsJson != null && !refundsByRace.has(bet.raceId)) refundsByRace.set(bet.raceId, refundSet(bet.refundsJson));
  }

  const courses = COURSES.map((course): CoursePerformance => {
    const byRace = new Map<string, SnapshotBet[]>();
    for (const bet of bets) {
      if (bet.course !== course) continue;
      const rows = byRace.get(bet.raceId) ?? [];
      rows.push(bet);
      byRace.set(bet.raceId, rows);
    }

    let finalizedRaces = 0;
    let settledRaces = 0;
    let hitRaces = 0;
    let refundRaces = 0;
    let finalizedStakeYen = 0;
    let settledStakeYen = 0;
    let returnYen = 0;

    for (const [raceId, rows] of byRace) {
      if (rows.length !== 2) continue;
      finalizedRaces += 1;
      const explicitStake = rows.every((row) => Number.isFinite(Number(row.stakeYen)));
      const raceStake = explicitStake
        ? rows.reduce((sum, row) => sum + Number(row.stakeYen ?? 0), 0)
        : COURSE_STAKE_YEN[course];
      finalizedStakeYen += raceStake;

      if (!rows.every((row) => row.settlementStatus === "settled")) continue;
      settledRaces += 1;
      settledStakeYen += raceStake;

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

  const light = courses.find((row) => row.course === "ライト")!;
  return { ...light, date, courses, targetRaces };
}

function summarizeSnapshotDay(date: string, day: SnapshotDay): DayPerformance {
  return summarizeDay(date, day.races ?? [], day.bets ?? [], parseSelectionCount(day));
}

function snapshotHistory(overrides: DayPerformance[] = []): DayPerformance[] {
  const byDate = new Map<string, DayPerformance>();
  for (const [date, day] of Object.entries(DAYS)) {
    if (day?.races?.length) byDate.set(date, summarizeSnapshotDay(date, day));
  }
  for (const row of overrides) if (row?.date) byDate.set(row.date, row);
  return [...byDate.values()].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 30);
}

function emptyDay(date: string): DayPerformance {
  return summarizeDay(date, [], [], 0);
}

async function boundedLiveDay(db: D1Database, date: string): Promise<DayPerformance> {
  const [betResult, selectionRow] = await Promise.all([
    db.prepare(`
      SELECT b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
             b.stake_yen AS stakeYen,b.return_yen AS returnYen,b.settlement_status AS settlementStatus,
             r.refund_horse_nos_json AS refundsJson
      FROM rt_public_bets b
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE r.race_date=? AND b.source_prediction_id=-2
      ORDER BY b.race_id,b.course,b.id
    `).bind(date).all<LiveBetRow>(),
    db.prepare(`
      SELECT s.state_value AS value,
             (
               SELECT COUNT(*)
               FROM json_each(json_extract(s.state_value,'$.selected')) j
               JOIN rt_races r ON r.race_id=json_extract(j.value,'$.raceId')
               WHERE lower(COALESCE(r.status,'scheduled')) NOT IN ('cancelled','canceled','postponed')
             ) AS activeCount
      FROM rt_system_state s
      WHERE s.state_key=?
      LIMIT 1
    `).bind(`final_daily_selection:${date}`).first<{ value: string | null; activeCount: number | null }>(),
  ]);

  const rows = betResult.results ?? [];
  const races = new Map<string, SnapshotRace>();
  for (const row of rows) races.set(row.raceId, { raceId: row.raceId, refundsJson: row.refundsJson });
  return summarizeDay(date, [...races.values()], rows, Number(selectionRow?.activeCount ?? parseSelectionCountRaw(selectionRow?.value)));
}

function performanceResponse(today: string, summary: DayPerformance, history: DayPerformance[], mode: string): Response {
  return Response.json({
    ok: true,
    version: "daily-performance-v7-bounded-current-plus-snapshot-history",
    today,
    summary,
    history,
  }, {
    headers: {
      "cache-control": "public, max-age=20, stale-while-revalidate=40",
      "x-race-history-source": HISTORY_SOURCE,
      "x-race-performance-mode": mode,
    },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/public/daily-performance") {
      const today = jstDate();
      const requested = url.searchParams.get("date");
      const date = validDate(requested) ? requested : today;
      const snapshotDay = DAYS[date];

      // Historical dates are immutable in the embedded snapshot and must never
      // spend D1 rows_read on a web request.
      if (date !== today && snapshotDay?.races?.length) {
        const summary = summarizeSnapshotDay(date, snapshotDay);
        return performanceResponse(today, summary, snapshotHistory([summary]), "snapshot-historical");
      }

      // Current day is deliberately bounded to only that date's final public
      // bets plus one selection-state row. If D1 rejects one read (quota/outage),
      // this isolate backs off instead of retrying on every browser poll.
      if (d1ReadBackoffActive()) {
        const summary = snapshotDay?.races?.length ? summarizeSnapshotDay(date, snapshotDay) : emptyDay(date);
        return performanceResponse(today, summary, snapshotHistory([summary]), "quota-free-backoff-snapshot");
      }
      try {
        const summary = await boundedLiveDay(env.DB, date);
        return performanceResponse(today, summary, snapshotHistory([summary]), "bounded-current-day");
      } catch (error) {
        tripD1ReadBackoff();
        console.error("DAILY_PERFORMANCE_BOUNDED_D1_FALLBACK", date, error);
        const summary = snapshotDay?.races?.length ? summarizeSnapshotDay(date, snapshotDay) : emptyDay(date);
        return performanceResponse(today, summary, snapshotHistory([summary]), "quota-free-snapshot");
      }
    }

    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
    return base.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
