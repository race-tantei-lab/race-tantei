import v37 from "./public-site-entry-v37.js";
import v34 from "./public-site-entry-v34.js";
import v33 from "./public-site-entry-v33.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v41-original-home-20260905";

async function pause(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function originalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  let lastResponse: Response | null = null;
  let lastError: unknown = null;

  // Keep the original v34 homepage as the primary path. Retry only the same
  // request on transient failures; never replace it with a custom retry page.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await v34.fetch(request, env, ctx);
      lastResponse = response;
      if (response.status < 500) {
        const headers = new Headers(response.headers);
        headers.set("cache-control", "no-store, max-age=0");
        headers.set("x-race-ui-version", UI_VERSION);
        headers.set("x-race-home-path", "v41-v34-original");
        return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
      }
    } catch (error) {
      lastError = error;
      console.error("V41_V34_HOME_FAILED", attempt + 1, error);
    }
    if (attempt < 2) await pause(150 * (attempt + 1));
  }

  // If a v34 enhancement is what failed, fall back to the immediately prior
  // normal UI renderer rather than showing a newly invented recovery screen.
  try {
    const response = await v33.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    headers.set("cache-control", "no-store, max-age=0");
    headers.set("x-race-ui-version", UI_VERSION);
    headers.set("x-race-home-path", "v41-v33-original-fallback");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  } catch (error) {
    lastError = error;
    console.error("V41_V33_HOME_FAILED", error);
  }

  if (lastResponse) return lastResponse;
  console.error("V41_HOME_UNAVAILABLE", lastError);
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
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return originalHome(request, env, ctx);
    }
    const response = await v37.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) {
      headers.set("x-race-ui-version", UI_VERSION);
    }
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (v37.scheduled) await v37.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
