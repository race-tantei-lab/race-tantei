import legacy from "./entry.js";
import { getRaceDetail } from "./v1/db.js";
import { renderCourseRace } from "./v1/course-race-ui.js";
import type { Env } from "./v1/types.js";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname.startsWith("/races/")) {
      const raceId = decodeURIComponent(pathname.slice("/races/".length));
      const detail = await getRaceDetail(env.DB, raceId);
      if (detail) {
        return new Response(renderCourseRace(detail), {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff"
          }
        });
      }
    }
    if (!legacy.fetch) return new Response("NOT_FOUND", { status: 404 });
    return legacy.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (legacy.scheduled) await legacy.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
