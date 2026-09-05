import publicSite from "./public-site-entry-v37.js";
import { runConfiguredEntrySeedWriteOnly } from "./v1/configured-entry-seed-write-only.js";
import type { Env } from "./v1/types.js";

const RECOVERY_PATH = "/_ops/entry-seed-sync-20260906-7f4c9d2a";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === RECOVERY_PATH) {
      const audit = await runConfiguredEntrySeedWriteOnly(env, "2026-09-06");
      return Response.json(audit, {
        status: audit.status === "failed" ? 503 : 200,
        headers: { "cache-control": "no-store, max-age=0" },
      });
    }
    if (url.pathname === RECOVERY_PATH) return new Response("NOT_FOUND", { status: 404 });
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return publicSite.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
