import publicSite from "./public-site-entry-v34.js";
import { fastCurrentDayResponse } from "./v1/current-day-public-api.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v36-fast-upcoming-sunday-entry-20260829";

function jstDate(now = new Date(), offsetDays = 0): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

function fastUpcomingDate(value: string | null, now = new Date()): value is string {
  if (!value || !/^20\d{2}-\d{2}-\d{2}$/.test(value)) return false;
  return value >= jstDate(now) && value <= jstDate(now, 2);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const now = new Date();
    const requestedDate = url.searchParams.get("date");

    if (path === "/api/public/day" && fastUpcomingDate(requestedDate, now)) {
      // Today and the next two calendar days are display-only reads here.
      // Never inherit the legacy discovery/settlement/JRA-network chain: the
      // authoritative schedule, frozen selection and public bets already live in D1.
      const response = await fastCurrentDayResponse(env.DB, requestedDate, now);
      const headers = new Headers(response.headers);
      headers.set("x-race-ui-version", UI_VERSION);
      headers.set("x-race-upcoming-day-path", "direct-d1-fast-upcoming-v1");
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    }

    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
