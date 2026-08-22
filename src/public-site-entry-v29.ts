import publicSite from "./public-site-entry-v28.js";
import { runCompletedWin5Scheduled } from "./v1/completed-win5.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v29-live-deadline-detached-20260822";

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
    // Race-bet preview generation and T-15 finalization are intentionally absent
    // from the public-site Worker. They are owned only by the isolated live-deadline
    // primary/backup Workers. The public Worker keeps normal maintenance and WIN5.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    await runWin5DeadlineGuard(env, "WIN5_DEADLINE_GUARD_PUBLIC_SITE");
  },
} satisfies ExportedHandler<Env>;
