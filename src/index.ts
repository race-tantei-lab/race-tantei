import { probeJraUrl } from "./core/probe.js";
import type { ProbeResult } from "./core/types.js";

interface Env {
  DB: D1Database;
  ENVIRONMENT: string;
  PROBE_ENABLED: string;
  PHASE0_MAX_CRON_SUCCESSES: string;
  PHASE0_MAX_CRON_ATTEMPTS: string;
  JRA_ROBOTS_PROBE_URL: string;
  JRA_RESULT_PROBE_URL: string;
  JRA_ENTRY_PROBE_URL: string;
  PHASE0_ADMIN_TOKEN?: string;
}

interface Phase0State {
  cronAttempts: number;
  cronSuccesses: number;
  completed: boolean;
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

function isAuthorized(request: Request, env: Env): boolean {
  if (!env.PHASE0_ADMIN_TOKEN) return false;
  const supplied = request.headers.get("authorization");
  return supplied === `Bearer ${env.PHASE0_ADMIN_TOKEN}`;
}

function positiveInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

async function ensureSchema(db: D1Database): Promise<void> {
  await db.prepare(`
    CREATE TABLE IF NOT EXISTS probe_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_url TEXT NOT NULL,
      fetched_at TEXT NOT NULL,
      trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual', 'cron')),
      ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
      http_status INTEGER NOT NULL,
      content_type TEXT,
      elapsed_ms INTEGER NOT NULL,
      body_bytes INTEGER NOT NULL,
      body_sha256 TEXT NOT NULL,
      page_kind TEXT NOT NULL,
      confidence REAL NOT NULL,
      markers_found_json TEXT NOT NULL,
      markers_missing_json TEXT NOT NULL,
      title TEXT,
      blocked_reason TEXT,
      error_code TEXT,
      error_message TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
  `).run();

  await db.prepare(`
    CREATE INDEX IF NOT EXISTS idx_probe_runs_fetched_at
    ON probe_runs(fetched_at DESC)
  `).run();

  await db.prepare(`
    CREATE INDEX IF NOT EXISTS idx_probe_runs_source_url
    ON probe_runs(source_url, fetched_at DESC)
  `).run();

  await db.prepare(`
    CREATE TABLE IF NOT EXISTS phase0_state (
      state_key TEXT PRIMARY KEY,
      state_value INTEGER NOT NULL,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
  `).run();
}

async function readStateValue(db: D1Database, key: string): Promise<number> {
  const row = await db.prepare(`
    SELECT state_value AS value
    FROM phase0_state
    WHERE state_key = ?
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

async function getPhase0State(env: Env): Promise<Phase0State> {
  await ensureSchema(env.DB);
  const [cronAttempts, cronSuccesses] = await Promise.all([
    readStateValue(env.DB, "cron_attempts"),
    readStateValue(env.DB, "cron_successes")
  ]);
  const maxSuccesses = positiveInt(env.PHASE0_MAX_CRON_SUCCESSES, 3);
  const maxAttempts = positiveInt(env.PHASE0_MAX_CRON_ATTEMPTS, 12);
  return {
    cronAttempts,
    cronSuccesses,
    completed: cronSuccesses >= maxSuccesses || cronAttempts >= maxAttempts
  };
}

async function saveProbe(db: D1Database, result: ProbeResult, triggerType: string): Promise<void> {
  await db.prepare(`
    INSERT INTO probe_runs (
      source_url, fetched_at, trigger_type, ok, http_status, content_type,
      elapsed_ms, body_bytes, body_sha256, page_kind, confidence,
      markers_found_json, markers_missing_json, title, blocked_reason,
      error_code, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    result.sourceUrl,
    result.fetchedAt,
    triggerType,
    result.ok ? 1 : 0,
    result.httpStatus,
    result.contentType,
    result.elapsedMs,
    result.bodyBytes,
    result.bodySha256,
    result.evidence.pageKind,
    result.evidence.confidence,
    JSON.stringify(result.evidence.markersFound),
    JSON.stringify(result.evidence.markersMissing),
    result.evidence.title,
    result.evidence.blockedReason,
    result.errorCode,
    result.errorMessage
  ).run();
}

async function runConfiguredProbes(env: Env, triggerType: "manual" | "cron"): Promise<ProbeResult[]> {
  if (env.PROBE_ENABLED !== "true") return [];

  await ensureSchema(env.DB);
  const urls = [env.JRA_ROBOTS_PROBE_URL, env.JRA_RESULT_PROBE_URL, env.JRA_ENTRY_PROBE_URL]
    .filter((url) => url.trim().length > 0);
  const results: ProbeResult[] = [];

  for (const url of urls) {
    const result = await probeJraUrl(url);
    results.push(result);
    await saveProbe(env.DB, result, triggerType);
  }

  return results;
}

async function getStatus(env: Env): Promise<unknown> {
  const state = await getPhase0State(env);
  const latest = await env.DB.prepare(`
    SELECT
      source_url AS sourceUrl,
      fetched_at AS fetchedAt,
      trigger_type AS triggerType,
      ok,
      http_status AS httpStatus,
      content_type AS contentType,
      elapsed_ms AS elapsedMs,
      body_bytes AS bodyBytes,
      body_sha256 AS bodySha256,
      page_kind AS pageKind,
      confidence,
      title,
      blocked_reason AS blockedReason,
      error_code AS errorCode,
      error_message AS errorMessage
    FROM probe_runs
    ORDER BY id DESC
    LIMIT 20
  `).all();

  return {
    ok: true,
    project: "race-tantei-phase0",
    environment: env.ENVIRONMENT,
    probeEnabled: env.PROBE_ENABLED === "true",
    limits: {
      maxCronSuccesses: positiveInt(env.PHASE0_MAX_CRON_SUCCESSES, 3),
      maxCronAttempts: positiveInt(env.PHASE0_MAX_CRON_ATTEMPTS, 12)
    },
    state,
    latest: latest.results,
    now: new Date().toISOString()
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        project: "race-tantei-phase0",
        environment: env.ENVIRONMENT,
        probeEnabled: env.PROBE_ENABLED === "true",
        endpoints: ["GET /health", "GET /phase0/status", "POST /phase0/run"],
        now: new Date().toISOString()
      });
    }

    if (url.pathname === "/phase0/status" && request.method === "GET") {
      return json(await getStatus(env));
    }

    if (url.pathname === "/phase0/run" && request.method === "POST") {
      if (!isAuthorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
      const results = await runConfiguredProbes(env, "manual");
      return json({ ok: results.length > 0 && results.every((result) => result.ok), results });
    }

    return json({
      ok: false,
      error: "NOT_FOUND",
      available: ["GET /health", "GET /phase0/status", "POST /phase0/run"]
    }, 404);
  },

  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil((async () => {
      const before = await getPhase0State(env);
      if (before.completed || env.PROBE_ENABLED !== "true") return;

      await incrementStateValue(env.DB, "cron_attempts");
      const results = await runConfiguredProbes(env, "cron");
      if (results.length > 0 && results.every((result) => result.ok)) {
        await incrementStateValue(env.DB, "cron_successes");
      }
    })());
  }
} satisfies ExportedHandler<Env>;
