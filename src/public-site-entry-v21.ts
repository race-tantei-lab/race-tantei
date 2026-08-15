import publicSite from "./public-site-entry-v20.js";
import { runCompletedWorkerBackup, type CompletedBackupAudit } from "./v1/completed-worker-backup.js";
import type { CompletedWorkerEnv } from "./v1/completed-worker-lock.js";

const UI_VERSION = "ten-year-completed-public-v21-worker-live-lock-20260815";

async function writeFatalAudit(env: CompletedWorkerEnv, now: Date, error: unknown): Promise<void> {
  const targetDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
  const payload = {
    status: "fatal",
    modelVersion: "ten-year-completed-model",
    targetDate,
    checkedAt: now.toISOString(),
    error: error instanceof Error ? error.message : String(error),
  };
  try {
    await env.DB.prepare(`
      INSERT INTO rt_system_state(key,value) VALUES(?,?)
      ON CONFLICT(key) DO UPDATE SET value=excluded.value
    `).bind("worker_completed_backup:last_error", JSON.stringify(payload)).run();
  } catch (auditError) {
    console.error("worker completed backup fatal audit write failed", auditError);
  }
}

export default {
  async fetch(request: Request, env: CompletedWorkerEnv, ctx: ExecutionContext): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/_internal/")) return new Response("NOT_FOUND", { status: 404 });
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/internal/worker-live-lock-health") {
      return new Response("NOT_FOUND", { status: 404 });
    }
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-tantei-ui", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: CompletedWorkerEnv, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    const now = new Date(controller.scheduledTime || Date.now());
    try {
      const audit: CompletedBackupAudit = await runCompletedWorkerBackup(env, now);
      console.log("WORKER_COMPLETED_LIVE_LOCK", JSON.stringify(audit));
      if (audit.status === "deadline_missed") throw new Error(`WORKER_COMPLETED_DEADLINE_MISSED:${audit.deadlineMissedRaceIds.join(",")}`);
    } catch (error) {
      await writeFatalAudit(env, now, error);
      console.error("WORKER_COMPLETED_LIVE_LOCK_FAILED", error);
      throw error;
    }
  },
} satisfies ExportedHandler<CompletedWorkerEnv>;
