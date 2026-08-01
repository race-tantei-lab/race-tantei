import app from "./complete.js";
import { ensureSchema } from "./v1/db.js";
import type { Env } from "./v1/types.js";

let startupReady: Promise<void> | null = null;

function prepare(db: D1Database): Promise<void> {
  startupReady ??= ensureSchema(db).catch((error) => {
    startupReady = null;
    throw error;
  });
  return startupReady;
}

function failureResponse(request: Request, error: unknown): Response {
  console.error("WORKER_STARTUP_FAILED", error);
  const pathname = new URL(request.url).pathname;
  const detail = error instanceof Error ? error.message : String(error);
  if (pathname === "/health" || pathname.startsWith("/api/")) {
    return new Response(JSON.stringify({ ok: false, error: "WORKER_STARTUP_FAILED", detail }), {
      status: 500,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow"
      }
    });
  }
  return new Response(
    `レース探偵の起動処理に失敗しました。\nエラーコード: WORKER_STARTUP_FAILED\n詳細: ${detail}`,
    {
      status: 500,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow"
      }
    }
  );
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    try {
      await prepare(env.DB);
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      return await app.fetch(request, env, ctx);
    } catch (error) {
      return failureResponse(request, error);
    }
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    try {
      await prepare(env.DB);
      if (app.scheduled) await app.scheduled(controller, env, ctx);
    } catch (error) {
      console.error("SCHEDULED_STARTUP_FAILED", error);
    }
  }
} satisfies ExportedHandler<Env>;
