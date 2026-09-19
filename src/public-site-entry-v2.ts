import publicSite from "./public-site-entry.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return publicSite.fetch(request, env, ctx);
  },

  async scheduled(_controller: ScheduledController, _env: Env, _ctx: ExecutionContext): Promise<void> {
    // Legacy request-time calendar/discovery maintenance is disabled.
  },
} satisfies ExportedHandler<Env>;
