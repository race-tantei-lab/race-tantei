import publicSite from "./public-site-entry-v37-core.js";
import upstreamSite from "./public-site-entry-v34.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-race-day-recovery-20260905";

async function stabilizeEmergencyResponse(response: Response): Promise<Response> {
  if (response.headers.get("x-race-emergency-fallback") !== "d1-unavailable") return response;
  if (!response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  html = html
    .replace("setTimeout(()=>location.reload(),30000)", "setTimeout(()=>location.reload(),120000)")
    .replace("表示を自動復旧中です。30秒ごとに再試行します。", "表示を自動復旧中です。しばらくすると自動で再試行します。");
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return stabilizeEmergencyResponse(await publicSite.fetch(request, env, ctx));
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // The original v37 implementation added public-maintenance work but stopped
    // delegating to the v34 race-day scheduler chain. Restore the chain while
    // preserving the existing v37 fetch/UI implementation byte-for-byte in the
    // core module. Keep both recovery paths independent so one failure cannot
    // suppress the other.
    if (upstreamSite.scheduled) {
      try {
        await upstreamSite.scheduled(controller, env, ctx);
      } catch (error) {
        console.error("PUBLIC_UPSTREAM_SCHEDULED_FAILED", error);
      }
    }
    if (publicSite.scheduled) {
      try {
        await publicSite.scheduled(controller, env, ctx);
      } catch (error) {
        console.error("PUBLIC_V37_MAINTENANCE_FAILED", error);
      }
    }
  },
} satisfies ExportedHandler<Env>;
