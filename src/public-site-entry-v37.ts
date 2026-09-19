import core from "./public-site-entry-v37-core.js";
import { NORMAL_HOME_SNAPSHOT } from "./normal-home-snapshot.js";
import { RECENT_HOME_CALENDAR_SNAPSHOT } from "./recent-home-calendar-snapshot.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
import { projectCurrentPublicState } from "./v1/current-day-public-api.js";
import { quotaFreeOfficialResultResponse } from "./v1/quota-free-jra-result-20260919.js";
import { shell } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-free-tier-safe-snapshot-20260905";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を一時的に再試行しています",
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
  "一時的にページを表示できません。",
] as const;

type CalendarRow = { raceDate: string; venue: string; raceCount: number };
type SnapshotRace = {
  raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string | null;
  startTimeJst: string | null; startTimeUtc: string | null; surface: string | null;
  distanceM: number | null; status: string; refundsJson: string | null;
};
type SnapshotBet = {
  raceId: string; course: string; betType: string; combination: string;
  returnYen: number | null; settlementStatus: string;
};
type SnapshotDay = { selection: string | null; races: SnapshotRace[]; bets: SnapshotBet[] };
const DAY_SNAPSHOT = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;

// Public scheduled work remains maintenance-only. Race-bet generation is
// owned exclusively by the isolated primary/backup live-deadline Workers.

function hasForbidden(text: string): boolean {
  return FORBIDDEN_RECOVERY_TEXT.some((value) => text.includes(value))
    || /データ.{0,16}(?:再試行|再接続)/.test(text)
    || /(?:再試行|再接続).{0,16}(?:しています|中です)/.test(text);
}

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch] ?? ch));
}

function staticRecentCalendar(): CalendarRow[] {
  const byKey = new Map<string, CalendarRow>();
  for (const row of RECENT_HOME_CALENDAR_SNAPSHOT) {
    const normalized = {
      raceDate: String(row.raceDate),
      venue: String(row.venue),
      raceCount: Number(row.raceCount),
    };
    byKey.set(`${normalized.raceDate}\u0000${normalized.venue}`, normalized);
  }

  // The current/recent day snapshot is the quota-free source of truth when D1
  // reads are blocked. Let it update stale calendar counts and add missing
  // venues (for example the second venue on the current race day).
  for (const [raceDate, day] of Object.entries(DAY_SNAPSHOT)) {
    const counts = new Map<string, number>();
    for (const race of day?.races ?? []) {
      const venue = String(race.venue ?? "");
      if (!venue) continue;
      counts.set(venue, (counts.get(venue) ?? 0) + 1);
    }
    for (const [venue, raceCount] of counts) {
      byKey.set(`${raceDate}\u0000${venue}`, { raceDate, venue, raceCount });
    }
  }

  return [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
}

async function loadRecentCalendar(env: Env): Promise<CalendarRow[]> {
  try {
    const result = await env.DB.prepare(`
      SELECT race_date AS raceDate, venue, COUNT(*) AS raceCount
      FROM rt_races
      WHERE race_date >= date('now','-45 days')
      GROUP BY race_date, venue
      ORDER BY race_date, venue
    `).all<CalendarRow>();
    const rows = (result.results ?? []).filter((row) => row.raceDate && row.venue && Number(row.raceCount) > 0);
    if (rows.length) return rows.map((row) => ({ ...row, raceCount: Number(row.raceCount) }));
  } catch (error) {
    console.error("V37_RECENT_CALENDAR_DB_FAILED", error);
  }
  return staticRecentCalendar();
}

function mergeRecentCalendar(html: string, rows: CalendarRow[]): string {
  const marker = "const calendar=";
  const start = html.indexOf(marker);
  const end = html.indexOf(";const today=", start);
  if (start < 0 || end < 0 || !rows.length) return html;

  try {
    const raw = html.slice(start + marker.length, end);
    const existing = JSON.parse(raw) as CalendarRow[];
    const byKey = new Map<string, CalendarRow>();
    for (const row of existing) {
      const normalized = {
        raceDate: String(row.raceDate),
        venue: String(row.venue),
        raceCount: Number(row.raceCount),
      };
      byKey.set(`${normalized.raceDate}\u0000${normalized.venue}`, normalized);
    }
    for (const row of rows) {
      byKey.set(`${row.raceDate}\u0000${row.venue}`, row);
    }
    const merged = [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
    return `${html.slice(0, start + marker.length)}${JSON.stringify(merged)}${html.slice(end)}`;
  } catch (error) {
    console.error("V37_CALENDAR_MERGE_FAILED", error);
    return html;
  }
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

function rewriteEmbeddedToday(html: string): string {
  const today = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const [, month, day] = today.split("-").map(Number);
  return html
    .replace(/const today="20\d{2}-\d{2}-\d{2}";/g, `const today="${today}";`)
    .replace(/const TODAY="20\d{2}-\d{2}-\d{2}";/g, `const TODAY="${today}";`)
    .replace(/本日の集計（\d{1,2}\/\d{1,2}）/g, `本日の集計（${month}/${day}）`);
}

function embeddedNormalHome(): Response {
  const html = rewriteEmbeddedToday(mergeRecentCalendar(NORMAL_HOME_SNAPSHOT, staticRecentCalendar()));
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

function parseSelection(raw: string | null): Set<string> | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { selected?: Array<{ raceId?: unknown }> };
    const ids = Array.isArray(parsed.selected) ? parsed.selected.map((row) => String(row?.raceId ?? "")).filter(Boolean) : [];
    return ids.length ? new Set(ids) : null;
  } catch { return null; }
}

function snapshotBetsForRace(day: SnapshotDay, race: SnapshotRace): Array<SnapshotBet & { refundsJson: string | null }> {
  return day.bets
    .filter((bet) => String(bet.raceId) === String(race.raceId))
    .map((bet) => ({ ...bet, refundsJson: race.refundsJson }));
}

function staticPublicDay(date: string): Response | null {
  const day = DAY_SNAPSHOT[date];
  if (!day?.races?.length) return null;
  const frozen = parseSelection(day.selection);
  const refundByRace = new Map(day.races.map((race) => [race.raceId, race.refundsJson]));
  const byRace = new Map<string, Array<SnapshotBet & { refundsJson: string | null }>>();
  for (const bet of day.bets) {
    const list = byRace.get(bet.raceId) ?? [];
    list.push({ ...bet, refundsJson: refundByRace.get(bet.raceId) ?? null });
    byRace.set(bet.raceId, list);
  }
  const nowMs = Date.now();
  const races = day.races.map((race) => ({
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: Number(race.raceNo),
    raceName: race.raceName,
    startTimeJst: race.startTimeJst,
    startTimeUtc: race.startTimeUtc,
    surface: race.surface,
    distanceM: race.distanceM === null ? null : Number(race.distanceM),
    status: race.status,
    publicState: projectCurrentPublicState(race, frozen, byRace.get(race.raceId) ?? [], nowMs),
  }));
  return Response.json({ ok: true, date, races, betStateAvailable: true, fallbackSource: "recent-public-day-snapshot-v1" }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-current-day-path": "recent-public-day-snapshot-v1",
    },
  });
}

function stateCssClass(code: string): string {
  if (code === "buy" || code === "hit") return "buy";
  if (code === "skip") return "skip";
  if (code === "pending" || code === "target" || code === "refund") return "pending";
  return "none";
}

function staticRaceDetail(raceId: string): Response | null {
  const date = raceId.slice(0, 10);
  const day = DAY_SNAPSHOT[date];
  if (!day?.races?.length) return null;
  const race = day.races.find((row) => String(row.raceId) === raceId);
  if (!race) return null;

  const frozen = parseSelection(day.selection);
  const bets = snapshotBetsForRace(day, race);
  const state = projectCurrentPublicState(race, frozen, bets, Date.now());
  const stateCode = String(state.code ?? "pending");
  const stateLabel = String(state.label ?? "判定中");
  const meta = [
    race.raceDate.replaceAll("-", "/"),
    race.venue,
    `${Number(race.raceNo)}R`,
    race.startTimeJst ? `${race.startTimeJst}発走` : null,
    race.surface,
    race.distanceM == null ? null : `${Number(race.distanceM)}m`,
  ].filter(Boolean).join("　");

  let betHtml = "";
  if (bets.length) {
    const courseOrder = ["ライト", "スタンダード", "プレミアム"];
    const groups = courseOrder.map((course) => ({ course, rows: bets.filter((bet) => bet.course === course) })).filter((group) => group.rows.length);
    betHtml = groups.map((group) => `<section class="card panel"><h2>${esc(group.course)}の買い目</h2><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>状態</th></tr></thead><tbody>${group.rows.map((bet) => `<tr><td>${esc(bet.betType)}</td><td><b>${esc(bet.combination)}</b></td><td>${bet.settlementStatus === "settled" ? "精算済み" : "確定済み"}</td></tr>`).join("")}</tbody></table></div></section>`).join("");
  } else {
    betHtml = `<section class="card panel"><h2>予想買い目</h2><p class="muted">${esc(stateLabel)}</p></section>`;
  }

  const body = `<a class="back" href="/races/">← レース一覧へ</a><section class="hero"><div class="race-title"><span class="race-no">${Number(race.raceNo)}R</span><h1>${esc(race.raceName ?? `${race.venue} ${race.raceNo}R`)}</h1><span class="status ${stateCssClass(stateCode)}">${esc(stateLabel)}</span></div><p>${esc(meta)}</p></section>${betHtml}`;
  return new Response(shell(`${race.venue}${race.raceNo}R`, body), {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-detail-path": "recent-public-day-snapshot-v1",
    },
  });
}

async function fetchPublicDay(request: Request, env: Env, ctx: ExecutionContext, date: string): Promise<Response> {
  let live: Response | null = null;
  try {
    live = await core.fetch(request, env, ctx);
    const text = await live.text();
    let payload: { races?: unknown } | null = null;
    try { payload = JSON.parse(text) as { races?: unknown }; } catch { /* handled below */ }
    if (live.ok && Array.isArray(payload?.races) && payload.races.length > 0) {
      return new Response(text, { status: live.status, statusText: live.statusText, headers: live.headers });
    }
    const fallback = staticPublicDay(date);
    if (fallback) return fallback;
    return new Response(text, { status: live.status, statusText: live.statusText, headers: live.headers });
  } catch (error) {
    console.error("V37_PUBLIC_DAY_USING_SNAPSHOT", date, error);
    return staticPublicDay(date) ?? new Response("NOT_FOUND", { status: 404 });
  }
}

async function fetchNormalHome(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  // Never spend production D1 rows_read just to render the home/calendar.
  // Recent/current calendar rows are already available from embedded snapshots.
  const recentCalendar = staticRecentCalendar();
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

async function fetchRaceList(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const homeUrl = new URL(request.url);
  homeUrl.pathname = "/";
  const homeRequest = new Request(homeUrl.toString(), request);
  return fetchNormalHome(homeRequest, env, ctx);
}

async function fetchRaceDetail(request: Request, env: Env, ctx: ExecutionContext, raceId: string): Promise<Response> {
  // Results must stay visible even when the D1 daily rows_read quota is exhausted.
  // For races covered by the quota-free JRA map, prefer the official result page
  // once it exists; before result publication this returns null and normal detail
  // rendering continues.
  try {
    const official = await quotaFreeOfficialResultResponse(raceId);
    if (official) return official;
  } catch (error) {
    console.error("V37_RACE_DETAIL_DIRECT_JRA_FIRST_FAILED", raceId, error);
  }

  try {
    const response = await core.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("text/html")) {
      const html = await response.text();
      const recoveryHeader = Boolean(response.headers.get("x-race-resilient-home") || response.headers.get("x-race-emergency-fallback"));
      if (response.status < 500 && html && !recoveryHeader && !hasForbidden(html) && !html.includes("レースが見つかりません")) {
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store, max-age=0");
        headers.set("x-race-ui-version", UI_VERSION);
        headers.set("x-race-detail-path", "v37-normal");
        return new Response(html, { status: response.status, statusText: response.statusText, headers });
      }
    } else if (response.ok && !hasForbidden(await response.clone().text())) {
      return response;
    }
    console.error("V37_RACE_DETAIL_USING_SNAPSHOT", raceId, response.status);
  } catch (error) {
    console.error("V37_RACE_DETAIL_USING_SNAPSHOT_AFTER_ERROR", raceId, error);
  }
  try {
    const official = await quotaFreeOfficialResultResponse(raceId);
    if (official) return official;
  } catch (error) {
    console.error("V37_RACE_DETAIL_DIRECT_JRA_FAILED", raceId, error);
  }
  return staticRaceDetail(raceId) ?? new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const pathname = url.pathname;
    if (pathname === "/_ops/live-tick") return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    if (request.method === "GET" && pathname === "/api/public/day") return fetchPublicDay(request, env, ctx, url.searchParams.get("date") ?? "");
    if (request.method === "GET" && (pathname === "/" || pathname === "/index.html")) return fetchNormalHome(request, env, ctx);
    if (request.method === "GET" && (pathname === "/races" || pathname === "/races/")) return fetchRaceList(request, env, ctx);
    if (request.method === "GET" && /^\/races\/20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2}\/?$/i.test(pathname)) {
      return fetchRaceDetail(request, env, ctx, decodeURIComponent(pathname.replace(/^\/races\//, "").replace(/\/$/, "")));
    }
    return core.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
