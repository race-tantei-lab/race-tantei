import publicSite from "./public-site-entry-v33.js";
import maintenanceSite from "./public-site-entry-v25.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v34-live-deadline-detached-20260822";

function scheduleEntryRepairs(env: Env, ctx: ExecutionContext, now: Date): void {
  ctx.waitUntil(runUpcomingEntryWorkerRepair(env, now).then((audit) => {
    if (audit.status !== "ready" && audit.status !== "idle") console.log("UPCOMING_ENTRY_WORKER_REPAIR", JSON.stringify(audit));
  }).catch((error) => console.error("UPCOMING_ENTRY_WORKER_REPAIR_FAILED", error)));
  ctx.waitUntil(runUpcomingEntryDerivedRepair(env, now).then((audit) => {
    if (audit.status !== "ready" && audit.status !== "idle") console.log("UPCOMING_ENTRY_DERIVED_CRON_REPAIR", JSON.stringify(audit));
  }).catch((error) => console.error("UPCOMING_ENTRY_DERIVED_CRON_REPAIR_FAILED", error)));
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Public requests are display-only. No route, including /_ops/live-tick,
    // can create previews or final race bets from this Worker anymore.
    if (new URL(request.url).pathname === "/_ops/live-tick") {
      return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) {
      headers.set("x-race-ui-version", UI_VERSION);
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // WIN5 is deliberately excluded from the public-site cron. The inherited
    // v26/v29 chain contains historical WIN5 scheduler calls, so delegating to
    // publicSite.scheduled here would couple WIN5 to unrelated maintenance again.
    // Run only the pre-WIN5 maintenance chain and the two current entry repairs;
    // isolated primary/backup WIN5 Workers own all WIN5 generation/finalization.
    if (maintenanceSite.scheduled) await maintenanceSite.scheduled(controller, env, ctx);
    scheduleEntryRepairs(env, ctx, new Date(controller.scheduledTime || Date.now()));
  },
} satisfies ExportedHandler<Env>;
