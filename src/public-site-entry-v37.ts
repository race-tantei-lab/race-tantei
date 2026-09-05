import core from "./public-site-entry-v37-core.js";
import { NORMAL_HOME_SNAPSHOT } from "./normal-home-snapshot.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-free-tier-safe-snapshot-20260905";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
  "一時的にページを表示できません。",
] as const;

// Public scheduled work remains maintenance-only. Race-bet generation is
// owned exclusively by the isolated primary/backup live-deadline Workers.
// runPublicMaintenance
// runUpcomingCalendarRepair
// runUpcomingEntryWorkerRepair
// runUpcomingEntryDerivedRepair

function hasForbidden(text: string): boolean {
  return FORBIDDEN_RECOVERY_TEXT.some((value) => text.includes(value));
}

function normalResponse(response: Response, html: string, path: string): Response {
  const headers = new Headers(response.headers);
  headers.delete("x-race-resilient-home");
  headers.delete("x-race-emergency-fallback");
  headers.delete("content-length");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-home-path", path);
  return new Response(html, { status: 200, headers });
}

function embeddedNormalHome(): Response {
  return new Response(NORMAL_HOME_SNAPSHOT, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-home-path": "v37-normal-snapshot",
    },
  });
}

async function fetchNormalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  try {
    const response = await core.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    const html = contentType.includes("text/html") ? await response.text() : "";
    const recoveryHeader = Boolean(response.headers.get("x-race-resilient-home") || response.headers.get("x-race-emergency-fallback"));
    if (response.status < 500 && html && !recoveryHeader && !hasForbidden(html)) {
      return normalResponse(response, html, "v37-normal");
    }
    console.error("V37_NORMAL_HOME_USING_SNAPSHOT", response.status);
  } catch (error) {
    console.error("V37_NORMAL_HOME_USING_SNAPSHOT_AFTER_ERROR", error);
  }
  return embeddedNormalHome();
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/_ops/live-tick") return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    if (request.method === "GET" && pathname === "/") return fetchNormalHome(request, env, ctx);
    return core.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
