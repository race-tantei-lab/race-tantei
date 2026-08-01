import { probeJraUrl } from "./core/probe.js";
import type { ProbeResult } from "./core/types.js";

interface Env {
  DB: D1Database;
  ENVIRONMENT: string;
  PROBE_ENABLED: string;
  JRA_ROBOTS_PROBE_URL: string;
  JRA_RESULT_PROBE_URL: string;
  JRA_ENTRY_PROBE_URL: string;
  PHASE0_ADMIN_TOKEN?: string;
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

async function runConfiguredProbes(env: Env, triggerType: string): Promise<ProbeResult[]> {
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({
        ok: true,
        project: "race-tantei-phase0",
        environment: env.ENVIRONMENT,
        probeEnabled: env.PROBE_ENABLED === "true",
        now: new Date().toISOString()
      });
    }

    if (url.pathname === "/phase0/run" && request.method === "POST") {
      if (!isAuthorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
      const results = await runConfiguredProbes(env, "manual");
      return json({ ok: results.every((result) => result.ok), results });
    }

    return json({ ok: false, error: "NOT_FOUND", available: ["GET /health", "POST /phase0/run"] }, 404);
  },

  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(runConfiguredProbes(env, "cron").then(() => undefined));
  }
} satisfies ExportedHandler<Env>;
