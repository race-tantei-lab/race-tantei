import app from "./audit-repair-entry.js";
import { ensureSchema } from "./v1/db.js";
import { renderWorkerCalibrationPanel } from "./v1/learned-calibration-ui.js";
import { getWalkForwardAnalysisData } from "./v1/walk-forward-analysis-data.js";
import {
  getWalkForwardTrainingProgress,
  runWalkForwardTrainingStep
} from "./v1/walk-forward-training.js";
import {
  getWorkerCalibrationState,
  runWorkerCalibrationStep
} from "./v1/worker-calibration-v2.js";
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

async function withLearningPanel(response: Response, env: Env): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const state = await getWorkerCalibrationState(env.DB);
  let html = await response.text();
  if (state.active) {
    html = html
      .replace("全期間の累計", "旧モデル参考")
      .replace("主要検証期間と本番公開分の合算", "旧モデルv1の参考成績");
  }
  const panel = renderWorkerCalibrationPanel(state);
  html = html.replace(/<main\b[^>]*>/, (match) => `${match}${panel}`);
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(html).length));
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

async function advanceLearning(db: D1Database): Promise<void> {
  for (let step = 0; step < 4; step += 1) {
    const progress = await getWalkForwardTrainingProgress(db);
    if (!progress.complete) {
      await runWalkForwardTrainingStep(db, 16);
      continue;
    }
    await runWorkerCalibrationStep(db);
    return;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (!pathname.startsWith("/api/training/walk-forward")) {
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      const response = await app.fetch(request, env, ctx);
      return pathname === "/" || pathname === "/performance"
        ? await withLearningPanel(response, env)
        : response;
    }

    await ensureSchema(env.DB);
    if (pathname === "/api/training/walk-forward/status" && request.method === "GET") {
      return json({
        training: await getWalkForwardTrainingProgress(env.DB),
        calibration: await getWorkerCalibrationState(env.DB)
      });
    }
    if (pathname === "/api/training/walk-forward/calibration-status" && request.method === "GET") {
      return json(await getWorkerCalibrationState(env.DB));
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
    if (pathname === "/api/training/walk-forward/calibration-step" && request.method === "POST") {
      if (request.headers.get("x-race-training") !== "walk-forward-12m-v1") {
        return json({ ok: false, error: "TRAINING_HEADER_REQUIRED" }, 403);
      }
      return json(await runWorkerCalibrationStep(env.DB));
    }
    return json({ ok: false, error: "NOT_FOUND" }, 404);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await ensureSchema(env.DB);
    const progress = await getWalkForwardTrainingProgress(env.DB);
    ctx.waitUntil(advanceLearning(env.DB).catch((error) => {
      console.error("WALK_FORWARD_PIPELINE_STEP_FAILED", error);
    }));

    // 過去データ取得・基礎予想生成中は通常メンテナンスと競合させない。
    // 学習データ完成後のみ、従来の定期処理も再開する。
    if (progress.complete && app.scheduled) {
      await app.scheduled(controller, env, ctx);
    }
  }
} satisfies ExportedHandler<Env>;
