import base from "./entry.js";
import { runThreeMonthFixedStakeRepair } from "./v1/three-month-repair.js";
import type { Env } from "./v1/types.js";

let repairRunning: Promise<void> | null = null;

function runRepair(env: Env): Promise<void> {
  if (repairRunning) return repairRunning;
  repairRunning = runThreeMonthFixedStakeRepair(env.DB, env.MODEL_VERSION, 8)
    .then((result) => {
      console.log("AUDITED_THREE_MONTH_REPAIR", JSON.stringify({
        complete: result.complete,
        repairedVenues: result.repairedVenues,
        addedRaces: result.addedRaces,
        replacedRaces: result.replacedRaces,
        removedRaces: result.removedRaces
      }));
    })
    .catch((error) => {
      console.error("AUDITED_THREE_MONTH_REPAIR_FAILED", error);
    })
    .finally(() => {
      repairRunning = null;
    });
  return repairRunning;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    ctx.waitUntil(runRepair(env));
    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
    return base.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(runRepair(env));
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
