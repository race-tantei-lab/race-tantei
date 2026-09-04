import publicSite from "./public-site-entry-v37.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v50-last-good-cache-20260905";
const CACHE_ORIGIN = "https://race-tantei-last-good.internal";
const CURRENT_DAY_TTL_SECONDS = 10 * 60;
const HOME_TTL_SECONDS = 5 * 60;

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function cacheRequest(kind: "day" | "home", date: string): Request {
  return new Request(`${CACHE_ORIGIN}/${kind}/${encodeURIComponent(date)}`, { method: "GET" });
}

async function storeLastGood(key: Request, response: Response, ttlSeconds: number, ctx: ExecutionContext): Promise<void> {
  if (!response.ok) return;
  const copy = response.clone();
  const body = await copy.arrayBuffer();
  const headers = new Headers(copy.headers);
  headers.set("cache-control", `public, max-age=${ttlSeconds}`);
  headers.set("x-race-last-good-stored-at", new Date().toISOString());
  headers.delete("set-cookie");
  ctx.waitUntil(caches.default.put(key, new Response(body, { status: copy.status, statusText: copy.statusText, headers })));
}

function serveLastGood(cached: Response, kind: "day" | "home"): Response {
  const headers = new Headers(cached.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-last-good-cache", kind);
  headers.set("warning", '110 - "Temporarily served from the last successful live snapshot"');
  return new Response(cached.body, { status: 200, statusText: "OK", headers });
}

async function cachedFallback(key: Request, kind: "day" | "home"): Promise<Response | null> {
  try {
    const cached = await caches.default.match(key);
    return cached ? serveLastGood(cached, kind) : null;
  } catch (error) {
    console.error("LAST_GOOD_CACHE_READ_FAILED", kind, error);
    return null;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const today = jstDate();
    const requestedDate = url.searchParams.get("date") || today;
    const currentDay = request.method === "GET" && url.pathname === "/api/public/day" && requestedDate === today;
    const home = request.method === "GET" && url.pathname === "/";
    const key = currentDay ? cacheRequest("day", today) : home ? cacheRequest("home", today) : null;
    const kind = currentDay ? "day" as const : home ? "home" as const : null;

    let response: Response;
    try {
      response = await publicSite.fetch(request, env, ctx);
    } catch (error) {
      console.error("PUBLIC_V50_UPSTREAM_THROW", url.pathname, error);
      if (key && kind) {
        const fallback = await cachedFallback(key, kind);
        if (fallback) return fallback;
      }
      return new Response("データ取得を一時的に再試行しています。", {
        status: 503,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store, max-age=0",
          "retry-after": "30",
          "x-race-ui-version": UI_VERSION,
          "x-race-emergency-fallback": "upstream-unavailable-no-last-good",
        },
      });
    }

    if (key && kind) {
      if (response.ok) {
        try {
          await storeLastGood(key, response, currentDay ? CURRENT_DAY_TTL_SECONDS : HOME_TTL_SECONDS, ctx);
        } catch (error) {
          console.error("LAST_GOOD_CACHE_WRITE_FAILED", kind, error);
        }
      } else if (response.status >= 500) {
        const fallback = await cachedFallback(key, kind);
        if (fallback) return fallback;
      }
    }

    const headers = new Headers(response.headers);
    headers.set("x-race-public-wrapper", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
