import publicSite from "./public-site-entry-v31.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v32-worker-entry-repair-20260821";

function shouldNudgeRepair(path: string): boolean {
  return /^\/races\/20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2}\/?$/i.test(path);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    // Opening a race detail can nudge the same background repair, but the page
    // response never waits on JRA network access.
    if (shouldNudgeRepair(path)) {
      ctx.waitUntil(runUpcomingEntryWorkerRepair(env, new Date()).then((audit) => {
        if (audit.status !== "ready" && audit.status !== "idle") console.log("UPCOMING_ENTRY_FETCH_REPAIR", JSON.stringify(audit));
      }).catch((error) => console.error("UPCOMING_ENTRY_FETCH_REPAIR_FAILED", error)));
    }
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // Keep the existing T-15 / odds / learning chain first. Upcoming-entry repair
    // is deliberately background-only so it can never delay the live critical path.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    ctx.waitUntil(runUpcomingEntryWorkerRepair(env, new Date(controller.scheduledTime || Date.now())).then((audit) => {
      console.log("UPCOMING_ENTRY_WORKER_REPAIR", JSON.stringify(audit));
    }).catch((error) => console.error("UPCOMING_ENTRY_WORKER_REPAIR_FAILED", error)));
  },
} satisfies ExportedHandler<Env>;
