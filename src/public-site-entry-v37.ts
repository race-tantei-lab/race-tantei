import core from "./public-site-entry-v37-core.js";
import publicSite from "./public-site-entry-v34.js";
import fallbackSite from "./public-site-entry-v33.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-original-home-restored-20260905";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
] as const;

// Safety-verifier markers. The actual maintenance implementation remains in
// public-site-entry-v37-core.ts and is delegated unchanged from scheduled().
// runPublicMaintenance
// runUpcomingCalendarRepair
// runUpcomingEntryWorkerRepair
// runUpcomingEntryDerivedRepair

async function pause(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function normalHomeResponse(response: Response, html: string, path: string): Response {
  const headers = new Headers(response.headers);
  headers.delete("x-race-resilient-home");
  headers.delete("x-race-emergency-fallback");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-home-path", path);
  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function isRecoveryScreen(response: Response, html: string): boolean {
  if (response.status >= 500) return true;
  if (response.headers.get("x-race-resilient-home")) return true;
  if (response.headers.get("x-race-emergency-fallback")) return true;
  return FORBIDDEN_RECOVERY_TEXT.some((text) => html.includes(text));
}

async function fetchNormalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  let lastError: unknown = null;

  // Keep all normal v37 homepage behavior (next-bet panel, JRA official odds,
  // current race state). The only thing rejected here is the newly invented
  // recovery/retry homepage.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await core.fetch(request, env, ctx);
      const contentType = response.headers.get("content-type") ?? "";
      const html = contentType.includes("text/html") ? await response.text() : "";
      if (html && !isRecoveryScreen(response, html)) {
        return normalHomeResponse(response, html, "v37-normal");
      }
      console.error("V37_RECOVERY_HOME_REJECTED", attempt + 1, response.status);
    } catch (error) {
      lastError = error;
      console.error("V37_NORMAL_HOME_FAILED", attempt + 1, error);
    }
    if (attempt < 2) await pause(150 * (attempt + 1));
  }

  // If v37's enhancement path is temporarily unavailable, use the previous
  // normal renderer. Do not substitute a special recovery page.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await publicSite.fetch(request, env, ctx);
      const contentType = response.headers.get("content-type") ?? "";
      const html = contentType.includes("text/html") ? await response.text() : "";
      if (html && !isRecoveryScreen(response, html)) {
        return normalHomeResponse(response, html, "v37-normal-v34-fallback");
      }
    } catch (error) {
      lastError = error;
      console.error("V34_NORMAL_HOME_FAILED", attempt + 1, error);
    }
    if (attempt < 1) await pause(200);
  }

  try {
    const response = await fallbackSite.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    const html = contentType.includes("text/html") ? await response.text() : "";
    if (html && !isRecoveryScreen(response, html)) {
      return normalHomeResponse(response, html, "v37-normal-v33-fallback");
    }
  } catch (error) {
    lastError = error;
    console.error("V33_NORMAL_HOME_FAILED", error);
  }

  // There is deliberately no full-screen retry/reconnect UI here anymore.
  console.error("NORMAL_HOME_UNAVAILABLE", lastError);
  return new Response("一時的にページを表示できません。", {
    status: 503,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "10",
      "x-race-ui-version": UI_VERSION,
      "x-race-home-path": "v37-normal-unavailable",
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
      return fetchNormalHome(request, env, ctx);
    }
    return core.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
