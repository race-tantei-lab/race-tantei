import publicSite from "./public-site-entry-v20.js";
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
  },
} satisfies ExportedHandler<Env>;
