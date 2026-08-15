import publicSite from "./public-site-entry-v20.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v21-worker-live-lock-20260815";

type LiveLockAudit = {
  status?: string;
  sourceModel?: string;
  selectedRaceCount?: number;
  deadlineBreachRaceIds?: string[];
};

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

async function enforceLiveLockSla(db: D1Database, now: Date): Promise<void> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`worker_live_lock:${jstDate(now)}`)
    .first<{ value: string | null }>();
  if (!row?.value) return;
  const audit = JSON.parse(String(row.value)) as LiveLockAudit;
  const breaches = Array.isArray(audit.deadlineBreachRaceIds) ? audit.deadlineBreachRaceIds.map(String).filter(Boolean) : [];
  if (audit.status === "deadline_breach" || breaches.length) {
    throw new Error(`WORKER_COMPLETED_15_MINUTE_SLA_BREACH:${breaches.join(",")}`);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/_internal/")) return new Response("NOT_FOUND", { status: 404 });
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/internal/worker-live-lock-health") return new Response("NOT_FOUND", { status: 404 });
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-tantei-ui", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    await enforceLiveLockSla(env.DB, new Date(controller.scheduledTime || Date.now()));
  },
} satisfies ExportedHandler<Env>;
