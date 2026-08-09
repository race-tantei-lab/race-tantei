import publicSite from "./public-site-entry.js";
import { ensureSchema, getState, setState } from "./v1/db.js";
import { jstDateKey, syncOfficialCalendarDay } from "./v1/jra-calendar.js";
import { expandRaceSourcesFromRecentPages } from "./v1/recent-discovery.js";
import type { Env } from "./v1/types.js";

const CALENDAR_REFRESH_MS = 30 * 60 * 1000;
const DISCOVERY_REFRESH_MS = 15 * 60 * 1000;
let inMemoryCalendarSync: Promise<void> | null = null;
let inMemoryDiscovery: Promise<void> | null = null;

async function shouldRefresh(db: D1Database, raceDate: string, now: Date): Promise<boolean> {
  const existing = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date=?`).bind(raceDate).first<{ count: number }>();
  const state = await getState(db, `public_calendar_${raceDate}`);
  if (!state || Number(existing?.count ?? 0) === 0) return true;
  try {
    const parsed = JSON.parse(state) as { fetchedAt?: string; expectedRaces?: number };
    if (Number(existing?.count ?? 0) < Number(parsed.expectedRaces ?? 0)) return true;
    const fetched = parsed.fetchedAt ? new Date(parsed.fetchedAt).getTime() : 0;
    return !Number.isFinite(fetched) || now.getTime() - fetched >= CALENDAR_REFRESH_MS;
  } catch {
    return true;
  }
}

async function syncCalendarWindow(env: Env): Promise<void> {
  if (inMemoryCalendarSync) return inMemoryCalendarSync;
  inMemoryCalendarSync = (async () => {
    await ensureSchema(env.DB);
    const now = new Date();
    for (const offset of [-1, 0]) {
      const raceDate = jstDateKey(now, offset);
      if (!(await shouldRefresh(env.DB, raceDate, now))) continue;
      try {
        const result = await syncOfficialCalendarDay(env.DB, raceDate);
        await setState(env.DB, `public_calendar_${raceDate}`, JSON.stringify({
          fetchedAt: now.toISOString(), expectedRaces: result.races, venues: result.venues
        }));
        console.log("PUBLIC_CALENDAR_SYNC", JSON.stringify(result));
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.log("PUBLIC_CALENDAR_SYNC_SKIPPED", JSON.stringify({ raceDate, message }));
      }
    }
  })().finally(() => { inMemoryCalendarSync = null; });
  return inMemoryCalendarSync;
}

async function expandRecentDiscovery(env: Env): Promise<void> {
  if (inMemoryDiscovery) return inMemoryDiscovery;
  inMemoryDiscovery = (async () => {
    await ensureSchema(env.DB);
    const now = new Date();
    const last = await getState(env.DB, "public_recent_discovery_at");
    const lastMs = last ? new Date(last).getTime() : 0;
    if (Number.isFinite(lastMs) && now.getTime() - lastMs < DISCOVERY_REFRESH_MS) return;
    try {
      const result = await expandRaceSourcesFromRecentPages(env);
      await setState(env.DB, "public_recent_discovery_at", now.toISOString());
      console.log("PUBLIC_RECENT_DISCOVERY", JSON.stringify(result));
    } catch (error) {
      console.error("PUBLIC_RECENT_DISCOVERY_FAILED", error);
    }
  })().finally(() => { inMemoryDiscovery = null; });
  return inMemoryDiscovery;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/" || pathname === "/api/public/calendar" || pathname === "/api/public/day" || pathname.startsWith("/races/")) {
      await syncCalendarWindow(env);
      ctx.waitUntil(expandRecentDiscovery(env));
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return publicSite.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await syncCalendarWindow(env);
    await expandRecentDiscovery(env);
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
