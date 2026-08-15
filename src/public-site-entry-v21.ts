import publicSite from "./public-site-entry-v20.js";
import { fastCurrentDayResponse } from "./v1/current-day-public-api.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v21-worker-live-lock-20260815";

type LiveLockAudit = {
  status?: string;
  sourceModel?: string;
  selectedRaceCount?: number;
  deadlineBreachRaceIds?: string[];
  bodyWeightBreachRaceIds?: string[];
};

type PredictionSampleRow = {
  raceId: string;
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
  const bodyWeightBreaches = Array.isArray(audit.bodyWeightBreachRaceIds) ? audit.bodyWeightBreachRaceIds.map(String).filter(Boolean) : [];
  if (bodyWeightBreaches.length) {
    // Bets have already been written from a pre-generated fallback. This must be
    // observable, but it must never turn a bodyweight acquisition miss into a
    // missing public prediction.
    console.error("WORKER_COMPLETED_BODYWEIGHT_SLA_BREACH", JSON.stringify({ raceIds: bodyWeightBreaches }));
  }
}

async function currentPredictionSample(db: D1Database): Promise<Response> {
  const date = jstDate();
  const row = await db.prepare(`
    SELECT b.race_id AS raceId
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date=? AND b.source_prediction_id=-2
    GROUP BY b.race_id,r.start_time_utc,r.race_no
    ORDER BY r.start_time_utc,r.race_no,b.race_id
    LIMIT 1
  `).bind(date).first<PredictionSampleRow>();
  return Response.json({
    date,
    hasPredictions: Boolean(row?.raceId),
    raceId: row?.raceId ? String(row.raceId) : null,
  }, { headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path.startsWith("/_internal/")) return new Response("NOT_FOUND", { status: 404 });
    if (path === "/api/public/today-prediction-sample") return currentPredictionSample(env.DB);
    if (path === "/api/public/day" && url.searchParams.get("date") === jstDate()) {
      // Current-day reads are latency-sensitive and must not inherit legacy
      // settlement/discovery wrappers or any JRA network wait. The authoritative
      // frozen selection and locked public bets already live in D1.
      return fastCurrentDayResponse(env.DB, jstDate());
    }
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
