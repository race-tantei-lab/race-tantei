import win5V2 from "./win5-entry-v2.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

const DRIVER_VERSION = "win5-entry-v3-race-day-gate-20260908";

export default {
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === "/health") {
      return Response.json(
        { service: "race-tantei-win5", version: DRIVER_VERSION, status: "up" },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return win5V2.fetch(request);
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledAt = Number.isFinite(controller.scheduledTime)
      ? new Date(controller.scheduledTime)
      : new Date();
    const raceDay = await shouldRunOnJraRaceDay(scheduledAt);
    if (!raceDay.shouldRun) {
      console.log("WIN5_NON_RACE_DAY_SKIP", JSON.stringify({ raceDate: raceDay.raceDate, reason: raceDay.reason }));
      return;
    }
    await win5V2.scheduled(controller, env);
  },
} satisfies ExportedHandler<Env>;
