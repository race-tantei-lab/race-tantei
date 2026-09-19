import { runPublishedEntryMaintenance } from "./v1/published-entry-maintenance.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, worker: "race-tantei-entry-maintenance", version: "published-entry-v2-gated-5m" }, {
        headers: { "cache-control": "no-store" },
      });
    }
    return new Response("NOT_FOUND", { status: 404 });
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const now = new Date(controller.scheduledTime || Date.now());
    const jstDay = new Date(now.getTime() + 9 * 3600_000).getUTCDay();
    const preparationDay = jstDay === 4 || jstDay === 5;
    const raceDay = await shouldRunOnJraRaceDay(now);
    if (!preparationDay && !raceDay.shouldRun) {
      console.log("PUBLISHED_ENTRY_NON_RACE_DAY_SKIP", JSON.stringify({ raceDate: raceDay.raceDate, reason: raceDay.reason }));
      return;
    }
    const audit = await runPublishedEntryMaintenance(env, now);
    console.log("PUBLISHED_ENTRY_MAINTENANCE", JSON.stringify(audit));
  },
} satisfies ExportedHandler<Env>;
