import publicSite from "./public-site-entry-v34.js";
import maintenanceSite from "./public-site-entry-v19.js";
import { runCompletedWin5Scheduled } from "./v1/completed-win5.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v35-exclusive-live-deadline-20260822";

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

async function runWin5DeadlineGuard(env: Env, label: string): Promise<void> {
  const now = new Date();
  try {
    const state = await runCompletedWin5Scheduled(env, now);
    console.log(label, JSON.stringify({
      status: state.status,
      date: state.date,
      lockedAt: state.snapshot?.lockedAt ?? null,
      generatedAt: state.snapshot?.generatedAt ?? null,
    }));
    if (state.targets.length === 5) {
      const firstStartMs = Math.min(...state.targets.map((row) => Date.parse(row.startTimeUtc)));
      const deadlineMs = firstStartMs - 15 * 60 * 1000;
      if (Number.isFinite(firstStartMs) && now.getTime() >= deadlineMs && now.getTime() < firstStartMs && state.status !== "final") {
        throw new Error(`${label}_FINAL_MISSING_AT_DEADLINE:${state.date}`);
      }
    }
  } catch (error) {
    console.error(`${label}_FAILED`, errorText(error));
    throw error;
  }
}

function scheduleEntryRepairs(env: Env, ctx: ExecutionContext, now: Date): void {
  ctx.waitUntil(Promise.all([
    runUpcomingEntryWorkerRepair(env, now).then((audit) => {
      if (audit.status !== "ready" && audit.status !== "idle") {
        console.log("UPCOMING_ENTRY_WORKER_REPAIR", JSON.stringify(audit));
      }
    }).catch((error) => console.error("UPCOMING_ENTRY_WORKER_REPAIR_FAILED", error)),
    runUpcomingEntryDerivedRepair(env, now).then((audit) => {
      if (audit.status !== "ready" && audit.status !== "idle") {
        console.log("UPCOMING_ENTRY_DERIVED_CRON_REPAIR", JSON.stringify(audit));
      }
    }).catch((error) => console.error("UPCOMING_ENTRY_DERIVED_CRON_REPAIR_FAILED", error)),
  ]).then(() => undefined));
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) {
      headers.set("x-race-ui-version", UI_VERSION);
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // IMPORTANT: never delegate scheduled() to the public UI wrapper chain.
    // v34 -> ... -> v20 still contains the retired normal-race selection/live-lock
    // implementation for historical source compatibility. Calling that inherited
    // scheduled() would create a second normal-race mutation owner.
    //
    // v19 and below are the audited maintenance-only chain: calendar/entry/result
    // synchronization, payout ingestion, settlement, and display-data repair.
    if (maintenanceSite.scheduled) await maintenanceSite.scheduled(controller, env, ctx);

    // WIN5 remains intentionally owned by the public Worker and is independent
    // from the normal-race live-deadline pipeline.
    await runWin5DeadlineGuard(env, "WIN5_DEADLINE_GUARD_PUBLIC_SITE");

    // Entry repairs are non-bet maintenance. Keep them background-only and make
    // every promise visible to the runtime through waitUntil().
    scheduleEntryRepairs(env, ctx, new Date(controller.scheduledTime || Date.now()));
  },
} satisfies ExportedHandler<Env>;
