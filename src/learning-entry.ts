import app from "./audit-repair-entry.js";
import { ensureSchema } from "./v1/db.js";
import { getWalkForwardAnalysisData } from "./v1/walk-forward-analysis-data.js";
import {
  getWalkForwardTrainingProgress,
  runWalkForwardTrainingStep
} from "./v1/walk-forward-training.js";
import type { Env } from "./v1/types.js";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (!pathname.startsWith("/api/training/walk-forward")) {
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      return app.fetch(request, env, ctx);
    }

    await ensureSchema(env.DB);
    if (pathname === "/api/training/walk-forward/status" && request.method === "GET") {
      return json(await getWalkForwardTrainingProgress(env.DB));
    }
    if (pathname === "/api/training/walk-forward/data" && request.method === "GET") {
      return json(await getWalkForwardAnalysisData(env.DB));
    }
    if (pathname === "/api/training/walk-forward/step" && request.method === "POST") {
      if (request.headers.get("x-race-training") !== "walk-forward-12m-v1") {
        return json({ ok: false, error: "TRAINING_HEADER_REQUIRED" }, 403);
      }
      return json(await runWalkForwardTrainingStep(env.DB, 16));
    }
    return json({ ok: false, error: "NOT_FOUND" }, 404);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await ensureSchema(env.DB);
    ctx.waitUntil(runWalkForwardTrainingStep(env.DB, 12).catch((error) => {
      console.error("WALK_FORWARD_TRAINING_STEP_FAILED", error);
    }));
    if (app.scheduled) await app.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
