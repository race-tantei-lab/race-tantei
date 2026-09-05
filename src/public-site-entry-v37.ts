import core from "./public-site-entry-v37-core.js";
import { NORMAL_HOME_SNAPSHOT } from "./normal-home-snapshot.js";
import { RECENT_HOME_CALENDAR_SNAPSHOT } from "./recent-home-calendar-snapshot.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-free-tier-safe-snapshot-20260905";
const RECENT_CALENDAR_START = "2026-08-09";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
  "一時的にページを表示できません。",
] as const;

type CalendarRow = { raceDate: string; venue: string; raceCount: number };

// Public scheduled work remains maintenance-only. Race-bet generation is
// owned exclusively by the isolated primary/backup live-deadline Workers.
// runPublicMaintenance
// runUpcomingCalendarRepair
// runUpcomingEntryWorkerRepair
// runUpcomingEntryDerivedRepair

function hasForbidden(text: string): boolean {
  return FORBIDDEN_RECOVERY_TEXT.some((value) => text.includes(value));
}

function staticRecentCalendar(): CalendarRow[] {
  return RECENT_HOME_CALENDAR_SNAPSHOT.map((row) => ({
    raceDate: String(row.raceDate),
    venue: String(row.venue),
    raceCount: Number(row.raceCount),
  }));
}

async function loadRecentCalendar(env: Env): Promise<CalendarRow[]> {
  try {
    const result = await env.DB.prepare(`
      SELECT race_date AS raceDate, venue, COUNT(*) AS raceCount
      FROM rt_races
      WHERE race_date > ?
      GROUP BY race_date, venue
      ORDER BY race_date, venue
    `).bind(RECENT_CALENDAR_START).all<CalendarRow>();
    const rows = (result.results ?? []).filter((row) => row.raceDate && row.venue && Number(row.raceCount) > 0);
    if (rows.length) return rows.map((row) => ({ ...row, raceCount: Number(row.raceCount) }));
  } catch (error) {
    console.error("V37_RECENT_CALENDAR_DB_FAILED", error);
  }
  return staticRecentCalendar();
}

function mergeRecentCalendar(html: string, rows: CalendarRow[]): string {
  const start = html.indexOf("const calendar=[");
  const end = html.indexOf("];const today=", start);
  if (start < 0 || end < 0 || !rows.length) return html;
  const existing = html.slice(start, end);
  const extra = rows.filter((row) => {
    const token = `\"raceDate\":\"${row.raceDate}\",\"venue\":\"${row.venue}\"`;
    return !existing.includes(token);
  });
  if (!extra.length) return html;
  return `${html.slice(0, end)},${extra.map((row) => JSON.stringify(row)).join(",")}${html.slice(end)}`;
}

function normalResponse(response: Response, html: string, path: string): Response {
  const headers = new Headers(response.headers);
  headers.delete("x-race-resilient-home");
  headers.delete("x-race-emergency-fallback");
  headers.delete("content-length");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-home-path", path);
  return new Response(html, { status: 200, headers });
}

function embeddedNormalHome(): Response {
  const html = mergeRecentCalendar(NORMAL_HOME_SNAPSHOT, staticRecentCalendar());
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-home-path": "v37-normal-snapshot",
    },
  });
}

async function fetchNormalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const recentCalendar = await loadRecentCalendar(env);
  try {
    const response = await core.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    const html = contentType.includes("text/html") ? await response.text() : "";
    const recoveryHeader = Boolean(response.headers.get("x-race-resilient-home") || response.headers.get("x-race-emergency-fallback"));
    if (response.status < 500 && html && !recoveryHeader && !hasForbidden(html)) {
      return normalResponse(response, mergeRecentCalendar(html, recentCalendar), "v37-normal");
    }
    console.error("V37_NORMAL_HOME_USING_SNAPSHOT", response.status);
  } catch (error) {
    console.error("V37_NORMAL_HOME_USING_SNAPSHOT_AFTER_ERROR", error);
  }
  return embeddedNormalHome();
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/_ops/live-tick") return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    if (request.method === "GET" && (pathname === "/" || pathname === "/index.html")) return fetchNormalHome(request, env, ctx);
    return core.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
