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

const CRON_ATTEMPT_KEY = "walk_forward_cron:last_attempt";
const CRON_HEARTBEAT_KEY = "walk_forward_cron:last_success";
const CRON_ERROR_KEY = "walk_forward_cron:last_error";
const CRON_DURATION_KEY = "walk_forward_cron:last_duration_ms";
const CRON_STAGE_KEY = "walk_forward_cron:last_stage";
const CRON_DELTA_KEY = "walk_forward_cron:last_delta";
const CRON_MAX_STEPS = 9;
const CRON_TIME_BUDGET_MS = 45_000;

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
  const [state, training, attempt, heartbeat, cronError, duration, stage, delta] = await Promise.all([
    getWorkerCalibrationState(env.DB),
    getWalkForwardTrainingProgress(env.DB),
    getState(env.DB, CRON_ATTEMPT_KEY),
    getState(env.DB, CRON_HEARTBEAT_KEY),
    getState(env.DB, CRON_ERROR_KEY),
    getState(env.DB, CRON_DURATION_KEY),
    getState(env.DB, CRON_STAGE_KEY),
    getState(env.DB, CRON_DELTA_KEY)
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
    stage ? `最終工程：${stage}` : "",
    delta ? `直近進捗：${delta}` : "",
    duration ? `処理時間：${duration}ms` : "",
    cronError ? `直近エラー：${cronError}` : "",
    "更新処理：Cron専用（ページ閲覧では進みません）"
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

async function advanceCronWork(db: D1Database, startedAt: number): Promise<{ stage: string; delta: string }> {
  const initialTraining = await getWalkForwardTrainingProgress(db);
  const initialCalibration = await getWorkerCalibrationState(db);
  let latestTraining = initialTraining;
  let latestCalibration = initialCalibration;
  let steps = 0;

  while (steps < CRON_MAX_STEPS && Date.now() - startedAt < CRON_TIME_BUDGET_MS) {
    if (!latestTraining.complete) {
      await runWalkForwardTrainingStep(db, 4);
      latestTraining = await getWalkForwardTrainingProgress(db);
    } else {
      await runWorkerCalibrationStep(db);
      latestCalibration = await getWorkerCalibrationState(db);
      if (latestCalibration.phase === "complete" || latestCalibration.phase === "failed") break;
    }
    steps += 1;
  }

  if (!latestTraining.complete) {
    return {
      stage: latestTraining.phase,
      delta: `公式結果 +${Math.max(0, latestTraining.history.importedUrls - initialTraining.history.importedUrls)}件 / 基礎予想 +${Math.max(0, latestTraining.generatedRaces - initialTraining.generatedRaces)}R / ${steps}処理`
    };
  }

  return {
    stage: latestCalibration.phase,
    delta: `学習 +${Math.max(0, latestCalibration.scoredRaces - initialCalibration.scoredRaces)}R / 再予想 +${Math.max(0, latestCalibration.appliedRaces - initialCalibration.appliedRaces)}R / ${steps}処理`
  };
}

async function safelyRecordFailure(db: D1Database, startedAt: number, stage: string, error: unknown): Promise<void> {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  try {
    await Promise.all([
      setState(db, CRON_DURATION_KEY, String(Date.now() - startedAt)),
      setState(db, CRON_STAGE_KEY, stage),
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

    if (!pathname.startsWith("/api/training/walk-forward")) {
      if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
      const response = await app.fetch(request, env, ctx);
      return isLearningPage ? await withLearningPanel(response, env) : response;
    }

    await ensureSchema(env.DB);
    if (pathname === "/api/training/walk-forward/status" && request.method === "GET") {
      return json({
        training: await getWalkForwardTrainingProgress(env.DB),
        calibration: await getWorkerCalibrationState(env.DB),
        cron: {
          lastAttempt: await getState(env.DB, CRON_ATTEMPT_KEY),
          lastSuccess: await getState(env.DB, CRON_HEARTBEAT_KEY),
          lastDurationMs: await getState(env.DB, CRON_DURATION_KEY),
          lastStage: await getState(env.DB, CRON_STAGE_KEY),
          lastDelta: await getState(env.DB, CRON_DELTA_KEY),
          lastError: await getState(env.DB, CRON_ERROR_KEY)
        }
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
      return json(await runWalkForwardTrainingStep(env.DB, 4));
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
    let stage = "schema";
    try {
      await ensureSchema(env.DB);
      await setState(env.DB, CRON_ATTEMPT_KEY, new Date(startedAt).toISOString());
      stage = "learning";
      const result = await advanceCronWork(env.DB, startedAt);
      stage = result.stage;
      await Promise.all([
        setState(env.DB, CRON_HEARTBEAT_KEY, new Date().toISOString()),
        setState(env.DB, CRON_DURATION_KEY, String(Date.now() - startedAt)),
        setState(env.DB, CRON_STAGE_KEY, result.stage),
        setState(env.DB, CRON_DELTA_KEY, result.delta),
        setState(env.DB, CRON_ERROR_KEY, "")
      ]);

      const progress = await getWalkForwardTrainingProgress(env.DB);
      if (progress.complete && app.scheduled) {
        await app.scheduled(controller, env, ctx);
      }
    } catch (error) {
      await safelyRecordFailure(env.DB, startedAt, stage, error);
      console.error("WALK_FORWARD_CRON_STEP_FAILED", error);
    }
  }
} satisfies ExportedHandler<Env>;
