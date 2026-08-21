import publicSite from "./public-site-entry-v32.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v33-derived-entry-repair-20260821";

function raceDetail(path: string): boolean {
  return /^\/races\/20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2}\/?$/i.test(path);
}

function scheduleDerivedRepair(env: Env, ctx: ExecutionContext, now: Date, label: string): void {
  ctx.waitUntil(runUpcomingEntryDerivedRepair(env, now).then((audit) => {
    if (audit.status !== "ready" && audit.status !== "idle") {
      console.log(label, JSON.stringify(audit));
    }
  }).catch((error) => console.error(`${label}_FAILED`, error)));
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    if (raceDetail(path)) scheduleDerivedRepair(env, ctx, new Date(), "UPCOMING_ENTRY_DERIVED_FETCH_REPAIR");
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // v32 preserves the T-15 / learning / official-odds critical path and then
    // schedules its bounded probe repair. Run the deterministic repair only as
    // another background task after that inherited path has returned.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    scheduleDerivedRepair(env, ctx, new Date(controller.scheduledTime || Date.now()), "UPCOMING_ENTRY_DERIVED_CRON_REPAIR");
  },
} satisfies ExportedHandler<Env>;
