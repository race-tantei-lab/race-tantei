import { runBoundedResultSettlement } from "./v1/bounded-result-settlement.js";
import { shouldRunOnJraRaceDay } from "./v1/race-day-gate.js";
import type { Env } from "./v1/types.js";

const VERSION = "result-settlement-v1-5m-priority-20260927";
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;
const ACTIVE_FROM_MINUTE = 9 * 60 + 30;
const ACTIVE_THROUGH_MINUTE = 18 * 60 + 30;

function jstMinuteOfDay(now: Date): number {
  const jst = new Date(now.getTime() + JST_OFFSET_MS);
  return jst.getUTCHours() * 60 + jst.getUTCMinutes();
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json(
        { ok: true, worker: "race-tantei-result-settlement", version: VERSION },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return new Response("NOT_FOUND", { status: 404 });
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const now = Number.isFinite(controller.scheduledTime) ? new Date(controller.scheduledTime) : new Date();
    const minute = jstMinuteOfDay(now);

    // Time gate and official race-day gate both happen before D1 settlement reads.
    // Public 15m maintenance remains the cross-day fallback for delayed prior-day results.
    if (minute < ACTIVE_FROM_MINUTE || minute > ACTIVE_THROUGH_MINUTE) {
      console.log("RESULT_SETTLEMENT_TIME_SKIP", JSON.stringify({ checkedAt: now.toISOString(), minute }));
      return;
    }
    const raceDay = await shouldRunOnJraRaceDay(now);
    if (!raceDay.shouldRun) {
      console.log("RESULT_SETTLEMENT_NON_RACE_DAY_SKIP", JSON.stringify({
        checkedAt: now.toISOString(),
        raceDate: raceDay.raceDate,
        reason: raceDay.reason,
      }));
      return;
    }

    const audit = await runBoundedResultSettlement(env, now, "public-bets-only");
    if (audit.candidates.length || audit.waitingRaceIds.length || audit.errors.length || audit.skippedReason) {
      console.log("RESULT_SETTLEMENT_TICK", JSON.stringify(audit));
    }
  },
} satisfies ExportedHandler<Env>;
