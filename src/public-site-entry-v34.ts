import publicSite from "./public-site-entry-v33.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v34-independent-live-driver-20260822";
const SELECTION_PREFIX = "final_daily_selection:";
const HEARTBEAT_PREFIX = "worker_live_heartbeat:";

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

async function hasSelection(db: D1Database, date: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`).first<{ ok: number }>();
  return Number(row?.ok ?? 0) === 1;
}

async function saveHeartbeat(env: Env, now: Date, source: string): Promise<void> {
  const date = jstDate(now);
  await env.DB.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${HEARTBEAT_PREFIX}${date}`, JSON.stringify({ checkedAt: now.toISOString(), source, version: UI_VERSION })).run();
}

async function runDirectLiveTick(env: Env, now = new Date()) {
  const date = jstDate(now);
  if (!(await hasSelection(env.DB, date))) {
    return { status: "selection_missing", date, checkedAt: now.toISOString(), live: null, guardBefore: null, guardAfter: null };
  }

  // First pass is DB-only: if a valid official preview already exists, lock it
  // before any new JRA/model work can delay this invocation.
  const guardBefore = await runCompletedWorkerDeadlineGuard(env, now);

  let live: Awaited<ReturnType<typeof runCompletedWorkerLiveLock>> | null = null;
  let liveFailure: string | null = null;
  try {
    live = await runCompletedWorkerLiveLock(env, now);
  } catch (error) {
    liveFailure = errorText(error);
  }

  // A pre-deadline tick may generate a new official preview. Lock it in the
  // same invocation once the race enters the safety arm window.
  const guardAfter = await runCompletedWorkerDeadlineGuard(env, now);
  const lockedAfter = new Set([...guardBefore.lockedRaceIds, ...guardAfter.lockedRaceIds]);
  const due = new Set([...guardBefore.dueRaceIds, ...guardAfter.dueRaceIds]);
  const unresolvedDueRaceIds = [...due].filter((raceId) => !lockedAfter.has(raceId));

  if (guardBefore.errors.length || guardAfter.errors.length || unresolvedDueRaceIds.length) {
    throw new Error(`DIRECT_LIVE_TICK_DUE_UNRESOLVED:${unresolvedDueRaceIds.join(",")}:before=${JSON.stringify(guardBefore.errors)}:after=${JSON.stringify(guardAfter.errors)}`);
  }

  const liveErrors = live?.errors ?? [];
  const status = liveFailure || liveErrors.length
    ? "retrying"
    : live?.status === "deadline_breach"
      ? "deadline_breach"
      : "ok";

  return {
    status,
    date,
    checkedAt: now.toISOString(),
    liveFailure,
    live: live ? {
      status: live.status,
      completeBefore: live.completeBefore,
      completeAfter: live.completeAfter,
      refreshedPreviewRaceIds: live.refreshedPreviewRaceIds,
      previewAvailableRaceIds: live.previewAvailableRaceIds,
      lockedByWorker: live.lockedByWorker,
      incompleteRaceIds: live.incompleteRaceIds,
      deadlineBreachRaceIds: live.deadlineBreachRaceIds,
      errors: live.errors,
    } : null,
    guardBefore: {
      status: guardBefore.status,
      dueRaceIds: guardBefore.dueRaceIds,
      lockedRaceIds: guardBefore.lockedRaceIds,
      skippedAlreadyLockedRaceIds: guardBefore.skippedAlreadyLockedRaceIds,
      errors: guardBefore.errors,
    },
    guardAfter: {
      status: guardAfter.status,
      dueRaceIds: guardAfter.dueRaceIds,
      lockedRaceIds: guardAfter.lockedRaceIds,
      skippedAlreadyLockedRaceIds: guardAfter.skippedAlreadyLockedRaceIds,
      errors: guardAfter.errors,
    },
  };
}

function shouldOpportunisticallyDrive(url: URL, request: Request): boolean {
  if (request.method !== "GET" && request.method !== "HEAD") return false;
  return url.pathname === "/" || url.pathname.startsWith("/races/") || url.pathname.startsWith("/api/public/");
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/_ops/live-tick") {
      if (request.method !== "POST") return new Response("METHOD_NOT_ALLOWED", { status: 405 });
      try {
        await saveHeartbeat(env, new Date(), "ops_post");
        const result = await runDirectLiveTick(env, new Date());
        const ok = result.status === "ok" || result.status === "selection_missing";
        return Response.json(result, {
          status: ok ? 200 : 503,
          headers: { "cache-control": "no-store", "x-race-ui-version": UI_VERSION },
        });
      } catch (error) {
        const message = errorText(error);
        console.error("DIRECT_LIVE_TICK_FAILED", error);
        return Response.json({ status: "error", error: message }, {
          status: 503,
          headers: { "cache-control": "no-store", "x-race-ui-version": UI_VERSION },
        });
      }
    }

    if (shouldOpportunisticallyDrive(url, request)) {
      ctx.waitUntil(
        saveHeartbeat(env, new Date(), "public_request")
          .then(() => runDirectLiveTick(env, new Date()))
          .catch((error) => console.error("PUBLIC_REQUEST_LIVE_TICK_FAILED", error)),
      );
    }

    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const now = new Date(controller.scheduledTime || Date.now());

    // The heartbeat and DB-only deadline guard run synchronously and finish fast.
    // Heavy live/JRA work and inherited maintenance are detached from each other so
    // one blocked maintenance fetch cannot suppress the next minute's deadline path.
    try {
      await saveHeartbeat(env, now, "cloudflare_cron");
      await runCompletedWorkerDeadlineGuard(env, now);
    } catch (error) {
      console.error("DIRECT_DEADLINE_GUARD_CRON_FAILED", error);
    }

    ctx.waitUntil(
      runDirectLiveTick(env, now)
        .then((direct) => {
          if (direct.status !== "selection_missing") console.log("DIRECT_LIVE_TICK_CRON", JSON.stringify(direct));
        })
        .catch((error) => console.error("DIRECT_LIVE_TICK_CRON_FAILED", error)),
    );

    if (publicSite.scheduled) {
      ctx.waitUntil(
        Promise.resolve(publicSite.scheduled(controller, env, ctx))
          .catch((error) => console.error("INHERITED_SCHEDULED_FAILED", error)),
      );
    }
  },
} satisfies ExportedHandler<Env>;
