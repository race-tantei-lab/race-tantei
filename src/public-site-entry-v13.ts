import publicSite from "./public-site-entry-v12.js";
import { runPublicDataSync } from "./public-data-sync.js";
import { jstDateKey, syncOfficialCalendarDay } from "./v1/jra-calendar.js";
import { isInvalidRaceName } from "./v1/race-display.js";
import type { Env } from "./v1/types.js";

type VenueRoi = {
  venue: string;
  settledRaces: number;
  light: number;
  standard: number;
  premium: number;
};

const VENUE_ROI: VenueRoi[] = [
  { venue: "札幌", settledRaces: 165, light: 86.7, standard: 84.4, premium: 86.8 },
  { venue: "函館", settledRaces: 170, light: 221.9, standard: 251.3, premium: 237.0 },
  { venue: "福島", settledRaces: 240, light: 336.0, standard: 321.2, premium: 321.3 },
  { venue: "新潟", settledRaces: 315, light: 164.4, standard: 157.9, premium: 159.8 },
  { venue: "東京", settledRaces: 505, light: 364.0, standard: 379.2, premium: 380.1 },
  { venue: "中山", settledRaces: 425, light: 449.2, standard: 443.6, premium: 444.0 },
  { venue: "中京", settledRaces: 330, light: 318.3, standard: 310.4, premium: 303.2 },
  { venue: "京都", settledRaces: 530, light: 318.3, standard: 327.9, premium: 328.1 },
  { venue: "阪神", settledRaces: 310, light: 188.9, standard: 186.9, premium: 192.1 },
  { venue: "小倉", settledRaces: 235, light: 279.2, standard: 264.2, premium: 262.7 }
];

function roiClass(value: number): string {
  return value >= 100 ? "venue-roi-plus" : "venue-roi-minus";
}

function venueRoiHtml(): string {
  const cards = VENUE_ROI.map((row) => `
    <article class="venue-roi-card">
      <div class="venue-roi-head"><b>${row.venue}</b><span>${row.settledRaces}R</span></div>
      <div class="venue-roi-row"><span>ライト</span><strong class="${roiClass(row.light)}">${row.light.toFixed(1)}%</strong></div>
      <div class="venue-roi-row"><span>スタンダード</span><strong class="${roiClass(row.standard)}">${row.standard.toFixed(1)}%</strong></div>
      <div class="venue-roi-row"><span>プレミアム</span><strong class="${roiClass(row.premium)}">${row.premium.toFixed(1)}%</strong></div>
    </article>`).join("");

  return `<div class="section-title venue-roi-title"><h2>会場別回収率</h2><span class="muted">全期間・3,225R</span></div><div class="venue-roi-rail">${cards}</div>`;
}

function injectVenueRoi(html: string): string {
  const css = `<style>
    .venue-roi-title{margin-top:20px!important}
    .venue-roi-rail{display:flex;gap:10px;overflow-x:auto;padding:2px 0 10px;scrollbar-width:thin}
    .venue-roi-card{flex:0 0 205px;border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:13px}
    .venue-roi-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
    .venue-roi-head b{font-size:18px}.venue-roi-head span{font-size:12px;color:var(--muted)}
    .venue-roi-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 0;border-top:1px solid rgba(43,61,82,.55);font-size:12px}
    .venue-roi-row span{color:var(--muted)}.venue-roi-row strong{font-size:15px}
    .venue-roi-plus{color:var(--green)}.venue-roi-minus{color:var(--red)}
    @media(max-width:760px){.venue-roi-card{flex-basis:190px}.venue-roi-head b{font-size:17px}}
  </style>`;
  const anchor = `<div class="section-title"><h2 id="selected-date">`;
  const withCss = html.replace("</head>", `${css}</head>`);
  return withCss.includes(anchor) ? withCss.replace(anchor, `${venueRoiHtml()}${anchor}`) : withCss;
}

function requestRaceDate(url: URL): string | null {
  if (url.pathname === "/api/public/day") {
    const date = url.searchParams.get("date") ?? "";
    return /^20\d{2}-\d{2}-\d{2}$/.test(date) ? date : null;
  }
  if (url.pathname.startsWith("/races/")) {
    const raceId = decodeURIComponent(url.pathname.slice("/races/".length));
    const date = raceId.slice(0, 10);
    return /^20\d{2}-\d{2}-\d{2}$/.test(date) ? date : null;
  }
  return null;
}

function hasStarted(startTimeUtc: unknown, nowMs = Date.now()): boolean {
  const startMs = Date.parse(String(startTimeUtc ?? ""));
  return Number.isFinite(startMs) && startMs <= nowMs;
}

async function normalizePostStartDay(response: Response): Promise<Response> {
  if (!response.ok) return response;
  try {
    const data = await response.clone().json() as { races?: Array<Record<string, any>>; [key: string]: any };
    if (!Array.isArray(data.races)) return response;
    const nowMs = Date.now();
    data.races = data.races.map((race) => {
      const publicState = { ...(race.publicState ?? {}) };
      if (publicState.code === "buy" && hasStarted(race.startTimeUtc, nowMs)) {
        publicState.code = "pending";
        publicState.label = "結果反映待ち";
        publicState.deadline = null;
      }
      return { ...race, publicState };
    });
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("content-type", "application/json; charset=utf-8");
    return new Response(JSON.stringify(data), { status: response.status, headers });
  } catch {
    return response;
  }
}

async function normalizePostStartDetail(request: Request, response: Response, db: D1Database): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  const path = new URL(request.url).pathname;
  if (!path.startsWith("/races/")) return response;
  try {
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const race = await db.prepare(`SELECT start_time_utc AS startTimeUtc FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<{ startTimeUtc: string | null }>();
    if (!race || !hasStarted(race.startTimeUtc)) return response;
    let html = await response.text();
    html = html.replace(/<span class="status buy">(?:買い目あり|固定済み)<\/span>/g, '<span class="status pending">結果反映待ち</span>');
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    return new Response(html, { status: response.status, headers });
  } catch {
    return response;
  }
}

async function needsRaceNameBackfill(db: D1Database, raceDate: string): Promise<boolean> {
  const rows = await db.prepare(`SELECT race_name AS raceName FROM rt_races WHERE race_date=?`).bind(raceDate).all<{ raceName: string | null }>();
  return rows.results.some((row) => isInvalidRaceName(row.raceName));
}

async function backfillRaceNamesForDate(db: D1Database, raceDate: string): Promise<boolean> {
  if (raceDate >= jstDateKey()) return false;
  try {
    if (!(await needsRaceNameBackfill(db, raceDate))) return false;
    await syncOfficialCalendarDay(db, raceDate);
    return true;
  } catch (error) {
    console.warn("HISTORICAL_RACE_NAME_BACKFILL_SKIPPED", raceDate, error instanceof Error ? error.message : String(error));
    return false;
  }
}

async function backfillHistoricalRaceNames(db: D1Database, limit = 3): Promise<void> {
  const safeLimit = Math.max(1, Math.min(6, Math.floor(limit)));
  const today = jstDateKey();
  const rows = await db.prepare(`
    SELECT DISTINCT race_date AS raceDate
    FROM rt_races
    WHERE race_date < ?
      AND (
        race_name IS NULL OR trim(race_name)=''
        OR race_name GLOB '[0-9]*R'
        OR race_name GLOB '[0-9]*レース'
        OR race_name LIKE '%検索ウィンドウ%'
        OR race_name LIKE '%検索メニュー%'
        OR race_name LIKE '%サイト内検索%'
        OR race_name LIKE '%メニューを開く%'
        OR race_name LIKE '%レース情報トップ%'
      )
    ORDER BY race_date DESC
    LIMIT ${safeLimit}
  `).bind(today).all<{ raceDate: string }>();

  for (const row of rows.results) {
    await backfillRaceNamesForDate(db, row.raceDate);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const url = new URL(request.url);
    const path = url.pathname;
    const raceDate = requestRaceDate(url);
    if (raceDate) await backfillRaceNamesForDate(env.DB, raceDate);
    if (raceDate === jstDateKey() && (path === "/api/public/day" || path.startsWith("/races/"))) {
      ctx.waitUntil(runPublicDataSync(env, "manual"));
    }

    let response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/public/day") response = await normalizePostStartDay(response);
    if (path.startsWith("/races/")) response = await normalizePostStartDetail(request, response, env.DB);
    if (path !== "/" || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      return new Response(injectVenueRoi(await response.text()), { status: response.status, headers });
    } catch {
      return response;
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await backfillHistoricalRaceNames(env.DB, 3);
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
