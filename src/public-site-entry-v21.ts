import publicSite from "./public-site-entry-v20.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v21-worker-live-lock-20260815";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/_internal/")) return new Response("NOT_FOUND", { status: 404 });
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/internal/worker-live-lock-health") return new Response("NOT_FOUND", { status: 404 });
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-tantei-ui", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    const now = new Date(controller.scheduledTime || Date.now());
    const selection = await freezeCompletedWorkerSelectionIfNeeded(env, now);
    console.log("COMPLETED_WORKER_SELECTION", JSON.stringify(selection));
    if (selection.status === "frozen") {
      const audit = await runCompletedWorkerLiveLock(env, now);
      console.log("COMPLETED_WORKER_LIVE_LOCK_AFTER_SELECTION", JSON.stringify(audit));
      if (audit.deadlineBreachRaceIds.length) {
        throw new Error(`WORKER_COMPLETED_DEADLINE_BREACH:${audit.deadlineBreachRaceIds.join(",")}`);
      }
    }
  },
} satisfies ExportedHandler<Env>;
