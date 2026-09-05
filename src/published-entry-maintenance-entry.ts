import { runPublishedEntryMaintenance } from "./v1/published-entry-maintenance.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, worker: "race-tantei-entry-maintenance", version: "published-entry-v1" }, {
        headers: { "cache-control": "no-store" },
      });
    }
    return new Response("NOT_FOUND", { status: 404 });
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const now = new Date(controller.scheduledTime || Date.now());
    const audit = await runPublishedEntryMaintenance(env, now);
    console.log("PUBLISHED_ENTRY_MAINTENANCE", JSON.stringify(audit));
  },
} satisfies ExportedHandler<Env>;
