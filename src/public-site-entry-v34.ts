import publicSite from "./public-site-entry-v33.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v34-live-tick-backup-20260822";
const SELECTION_PREFIX = "final_daily_selection:";

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

async function hasSelection(db: D1Database, date: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`).first<{ ok: number }>();
  return Number(row?.ok ?? 0) === 1;
}

async function runDirectLiveTick(env: Env, now = new Date()) {
  const date = jstDate(now);
  if (!(await hasSelection(env.DB, date))) {
    return { status: "selection_missing", date, checkedAt: now.toISOString(), live: null, guard: null };
  }

  const live = await runCompletedWorkerLiveLock(env, now);
  const guard = await runCompletedWorkerDeadlineGuard(env, now);
  const locked = new Set(guard.lockedRaceIds);
  const unresolvedDueRaceIds = guard.dueRaceIds.filter((raceId) => !locked.has(raceId));

  if (guard.errors.length || unresolvedDueRaceIds.length) {
    throw new Error(`DIRECT_LIVE_TICK_DUE_UNRESOLVED:${unresolvedDueRaceIds.join(",")}:errors=${JSON.stringify(guard.errors)}`);
  }

  return {
    status: live.status === "deadline_breach" ? "deadline_breach" : "ok",
    date,
    checkedAt: now.toISOString(),
    live: {
      status: live.status,
      completeBefore: live.completeBefore,
      completeAfter: live.completeAfter,
      refreshedPreviewRaceIds: live.refreshedPreviewRaceIds,
      previewAvailableRaceIds: live.previewAvailableRaceIds,
      lockedByWorker: live.lockedByWorker,
      incompleteRaceIds: live.incompleteRaceIds,
      deadlineBreachRaceIds: live.deadlineBreachRaceIds,
      errors: live.errors,
    },
    guard: {
      status: guard.status,
      dueRaceIds: guard.dueRaceIds,
      lockedRaceIds: guard.lockedRaceIds,
      skippedAlreadyLockedRaceIds: guard.skippedAlreadyLockedRaceIds,
      errors: guard.errors,
    },
  };
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/_ops/live-tick") {
      if (request.method !== "POST") return new Response("METHOD_NOT_ALLOWED", { status: 405 });
      try {
        const result = await runDirectLiveTick(env, new Date());
        return Response.json(result, {
          status: result.status === "deadline_breach" ? 503 : 200,
          headers: { "cache-control": "no-store", "x-race-ui-version": UI_VERSION },
        });
      } catch (error) {
        const message = error instanceof Error ? `${error.name}:${error.message}` : String(error);
        console.error("DIRECT_LIVE_TICK_FAILED", error);
        return Response.json({ status: "error", error: message }, {
          status: 503,
          headers: { "cache-control": "no-store", "x-race-ui-version": UI_VERSION },
        });
      }
    }

    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const now = new Date(controller.scheduledTime || Date.now());
    try {
      const direct = await runDirectLiveTick(env, now);
      if (direct.status !== "selection_missing") console.log("DIRECT_LIVE_TICK_CRON", JSON.stringify(direct));
    } catch (error) {
      console.error("DIRECT_LIVE_TICK_CRON_FAILED", error);
    }

    // Preserve every existing scheduled task (results, settlement, WIN5, entry repair, etc.).
    // The direct live tick above deliberately runs first so a failure deeper in the
    // inherited chain cannot prevent preview generation / T-15 finalization.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
