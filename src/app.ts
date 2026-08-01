import phase0Handler from "./index.js";
import { getPhase1Status, renderDashboard, runPhase1Pilot } from "./phase1.js";

interface Env {
  DB: D1Database;
  ENVIRONMENT: string;
  PROBE_ENABLED: string;
  PHASE0_MAX_CRON_SUCCESSES: string;
  PHASE0_MAX_CRON_ATTEMPTS: string;
  PHASE1_MAX_PILOT_ATTEMPTS: string;
  JRA_ROBOTS_PROBE_URL: string;
  JRA_RESULT_PROBE_URL: string;
  JRA_ENTRY_PROBE_URL: string;
  PHASE0_ADMIN_TOKEN?: string;
}

interface Phase0Status {
  state?: {
    cronAttempts?: number;
    cronSuccesses?: number;
    completed?: boolean;
  };
  limits?: {
    maxCronSuccesses?: number;
  };
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}

function html(body: string): Response {
  return new Response(body, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer"
    }
  });
}

function isAuthorized(request: Request, env: Env): boolean {
  if (!env.PHASE0_ADMIN_TOKEN) return false;
  return request.headers.get("authorization") === `Bearer ${env.PHASE0_ADMIN_TOKEN}`;
}

function positiveInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

async function phase0Status(env: Env): Promise<Phase0Status> {
  if (!phase0Handler.fetch) return {};
  const response = await phase0Handler.fetch(
    new Request("https://race-tantei.internal/phase0/status"),
    env,
    { waitUntil: () => undefined, passThroughOnException: () => undefined }
  );
  return await response.json() as Phase0Status;
}

function isPhase0Verified(status: Phase0Status): boolean {
  const successes = status.state?.cronSuccesses ?? 0;
  const required = status.limits?.maxCronSuccesses ?? positiveInt("3", 3);
  return successes >= required;
}

async function readStateValue(db: D1Database, key: string): Promise<number> {
  const row = await db.prepare(`
    SELECT state_value AS value FROM phase0_state WHERE state_key = ?
  `).bind(key).first<{ value: number }>();
  return row?.value ?? 0;
}

async function incrementStateValue(db: D1Database, key: string): Promise<void> {
  await db.prepare(`
    INSERT INTO phase0_state (state_key, state_value, updated_at)
    VALUES (?, 1, CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET
      state_value = state_value + 1,
      updated_at = CURRENT_TIMESTAMP
  `).bind(key).run();
}

async function maybeRunPhase1Pilot(env: Env): Promise<void> {
  const status = await phase0Status(env);
  if (!isPhase0Verified(status)) return;

  const [attempts, successes] = await Promise.all([
    readStateValue(env.DB, "phase1_pilot_attempts"),
    readStateValue(env.DB, "phase1_pilot_successes")
  ]);
  if (successes >= 1 || attempts >= positiveInt(env.PHASE1_MAX_PILOT_ATTEMPTS, 3)) return;

  await incrementStateValue(env.DB, "phase1_pilot_attempts");
  const result = await runPhase1Pilot(env);
  if (result.ok) await incrementStateValue(env.DB, "phase1_pilot_successes");
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/") {
      const status = await phase0Status(env);
      return html(await renderDashboard(env.DB, status));
    }

    if (url.pathname === "/health") {
      const status = await phase0Status(env);
      const phase1 = await getPhase1Status(env.DB);
      return json({
        ok: true,
        project: "race-tantei",
        phase0Verified: isPhase0Verified(status),
        phase1,
        now: new Date().toISOString()
      });
    }

    if (url.pathname === "/phase1/status" && request.method === "GET") {
      return json(await getPhase1Status(env.DB));
    }

    if (url.pathname === "/phase1/run" && request.method === "POST") {
      if (!isAuthorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
      const status = await phase0Status(env);
      if (!isPhase0Verified(status)) return json({ ok: false, error: "PHASE0_NOT_VERIFIED" }, 409);
      return json(await runPhase1Pilot(env));
    }

    if (!phase0Handler.fetch) return json({ ok: false, error: "NOT_FOUND" }, 404);
    return phase0Handler.fetch(request, env, ctx);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (phase0Handler.scheduled) await phase0Handler.scheduled(controller, env, ctx);
    ctx.waitUntil(maybeRunPhase1Pilot(env));
  }
} satisfies ExportedHandler<Env>;
