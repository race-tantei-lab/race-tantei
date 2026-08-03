import app from "./audit-repair-entry.js";
import { finishCronRun, tryStartCronRun } from "./cron-run-lock.js";
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

const CRON_ATTEMPT_KEY = "walk_forward_cron:last_attempt";
const CRON_HEARTBEAT_KEY = "walk_forward_cron:last_success";
const CRON_ERROR_KEY = "walk_forward_cron:last_error";
const CRON_DURATION_KEY = "walk_forward_cron:last_duration_ms";
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

function formatTime(label: string, value: string | null): string {
  if (!value) return `${label}なし`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `${label}${value}`;
  return `${label}${date.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}`;
}

async function withLearningPanel(response: Response, env: Env): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const [state, training, attempt, heartbeat, cronError, duration] = await Promise.all([
    getWorkerCalibrationState(env.DB),
    getWalkForwardTrainingProgress(env.DB),
    getState(env.DB, CRON_ATTEMPT_KEY),
    getState(env.DB, CRON_HEARTBEAT_KEY),
    getState(env.DB, CRON_ERROR_KEY),
    getState(env.DB, CRON_DURATION_KEY)
  ]);
  let html = await response.text();
  if (state.active) {
    html = html
      .replace("全期間の累計", "旧モデル参考")
      .replace("主要検証期間と本番公開分の合算", "旧モデルv1の参考成績");
  }
  const cronDetails = [
    formatTime("最終Cron発火：", attempt),
    formatTime("最終成功：", heartbeat),
    duration ? `処理時間：${duration}ms` : "",
    cronError ? `直近エラー：${cronError}` : ""
  ].filter(Boolean).join("<br>");
  const heartbeatHtml = `<p style="margin:10px 0 0;font-size:12px;opacity:.8;line-height:1.6">${cronDetails}</p>`;
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

async function safelyRecordCronFailure(db: D1Database, startedAt: number, error: unknown): Promise<void> {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  try {
    await Promise.all([
      setState(db, CRON_DURATION_KEY, String(Date.now() - startedAt)),
      setState(db, CRON_ERROR_KEY, message.slice(0, 500))
    ]);
  } catch (recordError) {
    console.error("WALK_FORWARD_CRON_ERROR_RECORD_FAILED", recordError);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    const isLearningPage = pathname === "/" || pathname === "/performance";

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
          lastAttempt: await getState(env.DB, CRON_ATTEMPT_KEY),
          lastSuccess: await getState(env.DB, CRON_HEARTBEAT_KEY),
          lastDurationMs: await getState(env.DB, CRON_DURATION_KEY),
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
    const startedAt = Date.now();
    if (!tryStartCronRun()) return;

    try {
      await ensureSchema(env.DB);
      await setState(env.DB, CRON_ATTEMPT_KEY, new Date(startedAt).toISOString());
      await advanceLearning(env.DB, 1, 1);
      await Promise.all([
        setState(env.DB, CRON_HEARTBEAT_KEY, new Date().toISOString()),
        setState(env.DB, CRON_DURATION_KEY, String(Date.now() - startedAt)),
        setState(env.DB, CRON_ERROR_KEY, "")
      ]);

      const progress = await getWalkForwardTrainingProgress(env.DB);
      if (progress.complete && app.scheduled) {
        await app.scheduled(controller, env, ctx);
      }
    } catch (error) {
      await safelyRecordCronFailure(env.DB, startedAt, error);
      console.error("WALK_FORWARD_CRON_STEP_FAILED", error);
    } finally {
      finishCronRun();
    }
  }
} satisfies ExportedHandler<Env>;
