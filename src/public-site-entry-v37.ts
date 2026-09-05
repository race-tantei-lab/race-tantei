import core from "./public-site-entry-v37-core.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-free-tier-safe-20260905";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
] as const;

// Public scheduled work is maintenance-only. Live bet generation stays isolated
// in the dedicated primary/backup live-deadline Workers.
// runPublicMaintenance
// runUpcomingCalendarRepair
// runUpcomingEntryWorkerRepair
// runUpcomingEntryDerivedRepair

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
  // One browser request gets exactly one canonical render attempt. Previous
  // versions retried the same D1-backed render through v37/v34/v33 up to six
  // times when D1 was unhealthy, which amplified rows_read precisely when the
  // free-tier budget was under pressure.
  try {
    const response = await core.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    const html = contentType.includes("text/html") ? await response.text() : "";
    if (html && !isRecoveryScreen(response, html)) {
      return normalHomeResponse(response, html, "v37-normal");
    }
    console.error("V37_NORMAL_HOME_UNAVAILABLE", response.status);
  } catch (error) {
    console.error("V37_NORMAL_HOME_FAILED", error);
  }

  // Never fan out to older renderers here: they use the same D1 database and
  // would turn one failed page view into several more database reads.
  return new Response("一時的にページを表示できません。", {
    status: 503,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "30",
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
