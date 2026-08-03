import app from "./audit-repair-entry.js";
import { ensureSchema, getState, setState } from "./v1/db.js";
import { renderWorkerCalibrationPanel } from "./v1/learned-calibration-ui.js";
import { getWalkForwardAnalysisData } from "./v1/walk-forward-analysis-data.js";
import { getWalkForwardTrainingProgress, runWalkForwardTrainingStep } from "./v1/walk-forward-training.js";
import { getWorkerCalibrationState, runWorkerCalibrationStep } from "./v1/worker-calibration-v2.js";
import type { Env } from "./v1/types.js";

const CRON_ATTEMPT_KEY = "walk_forward_cron:last_attempt";
const CRON_HEARTBEAT_KEY = "walk_forward_cron:last_success";
const CRON_ERROR_KEY = "walk_forward_cron:last_error";
const CRON_DURATION_KEY = "walk_forward_cron:last_duration_ms";
const CRON_STAGE_KEY = "walk_forward_cron:last_stage";
const CRON_DELTA_KEY = "walk_forward_cron:last_delta";

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

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

async function withLearningPanel(response: Response, env: Env): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const [state, training, attempt, heartbeat, cronError, duration, stage, delta] = await Promise.all([
    getWorkerCalibrationState(env.DB), getWalkForwardTrainingProgress(env.DB),
    getState(env.DB, CRON_ATTEMPT_KEY), getState(env.DB, CRON_HEARTBEAT_KEY),
    getState(env.DB, CRON_ERROR_KEY), getState(env.DB, CRON_DURATION_KEY),
    getState(env.DB, CRON_STAGE_KEY), getState(env.DB, CRON_DELTA_KEY)
  ]);
  let html = await response.text();
  if (state.active) {
    html = html.replace("全期間の累計", "旧モデル参考").replace("主要検証期間と本番公開分の合算", "旧モデルv1の参考成績");
  }
  const cronDetails = [
    formatTime("最終Cron発火：", attempt), formatTime("最終成功：", heartbeat),
    stage ? `最終工程：${stage}` : "", delta ? `直近進捗：${delta}` : "",
    duration ? `処理時間：${duration}ms` : "", cronError ? `直近エラー：${cronError}` : "",
    "更新処理：Cron専用（ページ閲覧では進みません）"
  ].filter(Boolean).join("<br>");
  const heartbeatHtml = `<p style="margin:10px 0 0;font-size:12px;opacity:.8;line-height:1.6">${cronDetails}</p>`;
  const panel = renderWorkerCalibrationPanel({ ...state, trainingProgress: training } as typeof state)
    .replace("</section>", `${heartbeatHtml}</section>`);
  html = html.replace(/<main\b[^>]*>/, (match) => `${match}${panel}`);
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(html).length));
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

interface CronWorkResult {
  stage: string;
  delta: string;
  trainingComplete: boolean;
}

async function advanceCronWork(db: D1Database): Promise<CronWorkResult> {
  // runWalkForwardTrainingStep already performs the one status read it needs and returns
  // the resulting progress. Do not surround it with duplicate progress queries: on the
  // Workers Free plan those reads count toward the same 50-query invocation budget.
  const trainingResult = objectValue(await runWalkForwardTrainingStep(db, 4));
  const trainingStage = stringValue(trainingResult.stage, "learning");
  const progress = objectValue(trainingResult.progress);
  const trainingComplete = progress.complete === true;

  if (!trainingComplete) {
    const action = objectValue(trainingResult.action);
    const history = objectValue(action.history);
    const historyAction = objectValue(history.action);
    const imported = numberValue(historyAction.imported);
    const skipped = numberValue(historyAction.skipped);
    const errors = numberValue(historyAction.errors);
    const processed = numberValue(objectValue(action.features).processed);
    return {
      stage: trainingStage,
      delta: `公式結果 +${imported}件（既存${skipped}・失敗${errors}）/ 基礎予想 +${processed}R / 1処理`,
      trainingComplete: false
    };
  }

  const calibrationBefore = await getWorkerCalibrationState(db);
  if (calibrationBefore.phase === "complete" || calibrationBefore.phase === "failed") {
    return {
      stage: calibrationBefore.phase,
      delta: `学習 ${calibrationBefore.scoredRaces}R / 再予想 ${calibrationBefore.appliedRaces}R`,
      trainingComplete: true
    };
  }

  const calibrationResult = objectValue(await runWorkerCalibrationStep(db));
  const calibrationProgress = objectValue(calibrationResult.progress);
  return {
    stage: stringValue(calibrationProgress.phase, "calibration"),
    delta: `勝率学習・再予想を1処理実行`,
    trainingComplete: true
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
          lastAttempt: await getState(env.DB, CRON_ATTEMPT_KEY), lastSuccess: await getState(env.DB, CRON_HEARTBEAT_KEY),
          lastDurationMs: await getState(env.DB, CRON_DURATION_KEY), lastStage: await getState(env.DB, CRON_STAGE_KEY),
          lastDelta: await getState(env.DB, CRON_DELTA_KEY), lastError: await getState(env.DB, CRON_ERROR_KEY)
        }
      });
    }
    if (pathname === "/api/training/walk-forward/calibration-status" && request.method === "GET") return json(await getWorkerCalibrationState(env.DB));
    if (pathname === "/api/training/walk-forward/data" && request.method === "GET") return json(await getWalkForwardAnalysisData(env.DB));
    if (pathname === "/api/training/walk-forward/step" && request.method === "POST") {
      if (request.headers.get("x-race-training") !== "walk-forward-12m-v1") return json({ ok: false, error: "TRAINING_HEADER_REQUIRED" }, 403);
      return json(await runWalkForwardTrainingStep(env.DB, 4));
    }
    if (pathname === "/api/training/walk-forward/calibration-step" && request.method === "POST") {
      if (request.headers.get("x-race-training") !== "walk-forward-12m-v1") return json({ ok: false, error: "TRAINING_HEADER_REQUIRED" }, 403);
      return json(await runWorkerCalibrationStep(env.DB));
    }
    return json({ ok: false, error: "NOT_FOUND" }, 404);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const startedAt = Date.now();
    let stage = "learning";
    try {
      await setState(env.DB, CRON_ATTEMPT_KEY, new Date(startedAt).toISOString());
      const result = await advanceCronWork(env.DB);
      stage = result.stage;
      await Promise.all([
        setState(env.DB, CRON_HEARTBEAT_KEY, new Date().toISOString()),
        setState(env.DB, CRON_DURATION_KEY, String(Date.now() - startedAt)),
        setState(env.DB, CRON_STAGE_KEY, result.stage),
        setState(env.DB, CRON_DELTA_KEY, result.delta),
        setState(env.DB, CRON_ERROR_KEY, "")
      ]);
      if (result.trainingComplete && app.scheduled) await app.scheduled(controller, env, ctx);
    } catch (error) {
      await safelyRecordFailure(env.DB, startedAt, stage, error);
      console.error("WALK_FORWARD_CRON_STEP_FAILED", error);
    }
  }
} satisfies ExportedHandler<Env>;
