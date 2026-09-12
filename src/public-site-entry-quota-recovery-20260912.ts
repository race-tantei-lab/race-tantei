import recovery from "./public-site-entry-recovery-20260906.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
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
const DAYS = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;

function jstToday(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
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
    if (request.method === "GET" && url.pathname === "/api/public/day") {
      const date = url.searchParams.get("date") ?? "";
      if (date === jstToday()) {
        const snapshot = snapshotResponse(date);
        if (snapshot) return snapshot;
      }
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
