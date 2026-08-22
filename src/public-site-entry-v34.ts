import publicSite from "./public-site-entry-v33.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v34-live-deadline-detached-20260822";

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
    // Race-bet finalization has been removed from the public-site cron. Normal
    // site maintenance, WIN5, and entry repair remain in the inherited chain.
    // Race-bet preview/final ownership is exclusive to the isolated primary and
    // staggered backup live-deadline Workers.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
