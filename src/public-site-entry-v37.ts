import core from "./public-site-entry-v37-core.js";
import v34 from "./public-site-entry-v34.js";
import v33 from "./public-site-entry-v33.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-original-home-restored-20260905";

// Safety-verifier markers. The actual maintenance implementation remains in
// public-site-entry-v37-core.ts and is delegated unchanged from scheduled().
// runPublicMaintenance
// runUpcomingCalendarRepair
// runUpcomingEntryWorkerRepair
// runUpcomingEntryDerivedRepair

async function pause(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchOriginalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  let lastResponse: Response | null = null;
  let lastError: unknown = null;

  // Primary: exactly the pre-recovery normal homepage renderer.
  // Retry the same renderer only for transient failures; do not replace the
  // homepage with a custom "retrying" or "reconnecting" screen.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await v34.fetch(request, env, ctx);
      lastResponse = response;
      if (response.status < 500) {
        const headers = new Headers(response.headers);
        headers.set("cache-control", "no-store, max-age=0");
        headers.set("x-race-ui-version", UI_VERSION);
        headers.set("x-race-home-path", "v37-original-v34");
        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
      }
    } catch (error) {
      lastError = error;
      console.error("ORIGINAL_HOME_V34_FAILED", attempt + 1, error);
    }
    if (attempt < 2) await pause(150 * (attempt + 1));
  }

  // If only a v34 enhancement failed, keep the immediately preceding normal
  // UI instead of showing a newly invented recovery page.
  try {
    const response = await v33.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    headers.set("cache-control", "no-store, max-age=0");
    headers.set("x-race-ui-version", UI_VERSION);
    headers.set("x-race-home-path", "v37-original-v33-fallback");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch (error) {
    lastError = error;
    console.error("ORIGINAL_HOME_V33_FAILED", error);
  }

  // Never render the custom recovery UI again.
  if (lastResponse) return lastResponse;
  console.error("ORIGINAL_HOME_UNAVAILABLE", lastError);
  return new Response("一時的に表示データを取得できません。", {
    status: 503,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "10",
      "x-race-ui-version": UI_VERSION,
    },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/_ops/live-tick") {
      return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    }
    if (request.method === "GET" && pathname === "/") {
      return fetchOriginalHome(request, env, ctx);
    }
    return core.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
