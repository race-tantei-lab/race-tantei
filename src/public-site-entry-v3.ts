import publicSite from "./public-site-entry-v2.js";
import { renderPublicConditions } from "./v1/public-conditions.js";
import { response } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (new URL(request.url).pathname === "/conditions") {
      return response(renderPublicConditions());
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return publicSite.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
