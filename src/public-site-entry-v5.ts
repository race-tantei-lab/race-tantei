import publicSite from "./public-site-entry-v4.js";
import type { Env } from "./v1/types.js";
import { safeRaceName } from "./v1/race-display.js";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/races/") || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const raceId = decodeURIComponent(path.slice("/races/".length));
      const row = await env.DB.prepare(`SELECT race_no AS raceNo,race_name AS raceName,conditions FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<{raceNo:number;raceName:string|null;conditions:string|null}>();
      if (!row) return response;
      const name = safeRaceName(row.raceName, Number(row.raceNo), row.conditions);
      let html = await response.text();
      html = html.replace(/(<div class="race-title">[\s\S]*?<h1>)[\s\S]*?(<\/h1>)/, `$1${name}$2`);
      const headers = new Headers(response.headers); headers.delete("content-length");
      return new Response(html, { status: response.status, headers });
    } catch { return response; }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
