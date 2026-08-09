import publicSite from "./public-site-entry-v2.js";
import { handleCanonicalHistorySeed } from "./v1/canonical-history-seed.js";
import { enhancePublicResponse } from "./v1/public-enhancements.js";
import { renderPublicConditions } from "./v1/public-conditions.js";
import { response } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const internal=await handleCanonicalHistorySeed(request,env.DB);
    if(internal)return internal;
    if (new URL(request.url).pathname === "/conditions") {
      return response(renderPublicConditions());
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const upstream=await publicSite.fetch(request, env, ctx);
    return enhancePublicResponse(request,env.DB,upstream);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
