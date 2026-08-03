import app from "./audit-repair-entry.js";
import { ensureSchema, getState, setState } from "./v1/db.js";
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

const CRON_HEARTBEAT_KEY = "walk_forward_cron:last_success";
const CRON_ERROR_KEY = "walk_forward_cron:last_error";
let learningRunning: Promise<void> | null = null;

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

function formatHeartbeat(value: string | null): string {
  if (!value) return "定期処理の成功記録なし";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `最終定期処理：${date.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}`;
}

async function withLearningPanel(response: Response, env: Env): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const [state, training, heartbeat, cronError] = await Promise.all([
    getWorkerCalibrationState(env.DB),
    getWalkForwardTrainingProgress(env.DB),
    getState(env.DB, CRON_HEARTBEAT_KEY),
    getState(env.DB, CRON_ERROR_KEY)
  ]);
  let html = await response.text();
  if (state.active) {
    html = html
      .replace("全期間の累計", "旧モデル参考")
      .replace("主要検証期間と本番公開分の合算", "旧モデルv1の参考成績");
  }
  const heartbeatHtml = `<p style="margin:10px 0 0;font-size:12px;opacity:.8">${formatHeartbeat(heartbeat)}${cronError ? `／直近エラー：${cronError}` : ""}</p>`;
  const panel = renderWorkerCalibrationPanel({
    ...state,
    trainingProgress: training
  } as typeof state).replace("</section>", `${heartbeatHtml}</section>`);
  html = html.replace(/<main\b[^>]*>/, (match) => `${match}${panel}`);
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(html).length));
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

async function advanceLearning(db: D1Database, steps: number, predictionBatchSize: number): Promise<void> {
  for (let step = 0; step < steps; step += 1) {
    const progress = await getWalkForwardTrainingProgress(db);
    if (!progress.complete) {
      await runWalkForwardTrainingStep(db, predictionBatchSize);
      continue;
    }
    await runWorkerCalibrationStep(db);
    return;
  }
}

function startLearning(env: Env): Promise<void> {
  if (learningRunning) return learningRunning;
  learningRunning = (async () => {
    await ensureSchema(env.DB);
    await advanceLearning(env.DB, 4, 16);
  })().catch((error) => {
    console.error("WALK_FORWARD_SELF_START_FAILED", error);
  }).finally(() => {
    learningRunning = null;
  });
  return learningRunning;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    const isLearningPage = pathname === "/" || pathname === "/performance";

    // 閲覧時は応答を待たせず複数ステップ進める。
    if (isLearningPage) ctx.waitUntil(startLearning(env));

    if (!pathname.startsWith("/api/training/walk-forward")) {
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      const response = await app.fetch(request, env, ctx);
      return isLearningPage ? await withLearningPanel(response, env) : response;
    }

    await ensureSchema(env.DB);
    if (pathname === "/api/training/walk-forward/status" && request.method === "GET") {
      ctx.waitUntil(startLearning(env));
      return json({
        training: await getWalkForwardTrainingProgress(env.DB),
        calibration: await getWorkerCalibrationState(env.DB),
        cron: {
          lastSuccess: await getState(env.DB, CRON_HEARTBEAT_KEY),
          lastError: await getState(env.DB, CRON_ERROR_KEY)
        }
      });
    }
    if (pathname === "/api/training/walk-forward/calibration-status" && request.method === "GET") {
      ctx.waitUntil(startLearning(env));
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
    try {
      // Cronは小さい1ステップを直接待ち、DB保存まで完了してから終了する。
      // waitUntilへ投げた重い処理が途中終了する問題を避ける。
      await advanceLearning(env.DB, 1, 4);
      await Promise.all([
        setState(env.DB, CRON_HEARTBEAT_KEY, new Date().toISOString()),
        setState(env.DB, CRON_ERROR_KEY, "")
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await setState(env.DB, CRON_ERROR_KEY, message.slice(0, 300));
      console.error("WALK_FORWARD_CRON_STEP_FAILED", error);
      return;
    }

    const progress = await getWalkForwardTrainingProgress(env.DB);
    if (progress.complete && app.scheduled) {
      await app.scheduled(controller, env, ctx);
    }
  }
} satisfies ExportedHandler<Env>;
