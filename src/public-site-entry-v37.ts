import publicSite from "./public-site-entry-v34.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-next-bet-until-post-20260830";

type RaceRow = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeUtc: string | null;
  startTimeJst: string | null;
};

type NextBetState = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeJst: string | null;
  deadlineJst: string | null;
  locked: boolean;
};

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstClock(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return /^\d{1,2}:\d{2}$/.test(value) ? value.padStart(5, "0") : null;
  return new Date(time + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function deadlineClock(startTimeUtc: string | null): string | null {
  if (!startTimeUtc) return null;
  const time = Date.parse(startTimeUtc);
  if (!Number.isFinite(time)) return null;
  return new Date(time - 30 * 60 * 1000 + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch] ?? ch));
}

async function loadNextBetUntilPost(
  env: Env,
  now = new Date(),
): Promise<{ ok: boolean; selectionExists: boolean; nextBet: NextBetState | null }> {
  const date = jstDate(now);
  try {
    const [selection, races, locked] = await Promise.all([
      env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
        .bind(`final_daily_selection:${date}`)
        .first<{ value: string | null }>(),
      env.DB.prepare(`
        SELECT race_id AS raceId,venue,race_no AS raceNo,start_time_utc AS startTimeUtc,start_time_jst AS startTimeJst
        FROM rt_races
        WHERE race_date=?
        ORDER BY start_time_utc,race_no,race_id
      `).bind(date).all<RaceRow>(),
      env.DB.prepare(`
        SELECT DISTINCT b.race_id AS raceId
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date=? AND b.source_prediction_id=-2
      `).bind(date).all<{ raceId: string }>(),
    ]);

    if (!selection?.value) return { ok: true, selectionExists: false, nextBet: null };

    const selectedIds = new Set<string>();
    try {
      const parsed = JSON.parse(selection.value) as {
        selected?: Array<{ raceId?: unknown }>;
        selectedRaceIds?: unknown[];
      };
      for (const row of parsed.selected ?? []) {
        const raceId = String(row?.raceId ?? "");
        if (raceId) selectedIds.add(raceId);
      }
      for (const value of parsed.selectedRaceIds ?? []) {
        const raceId = String(value ?? "");
        if (raceId) selectedIds.add(raceId);
      }
    } catch {
      return { ok: false, selectionExists: true, nextBet: null };
    }

    const lockedIds = new Set(locked.results.map((row) => String(row.raceId)));
    const nowMs = now.getTime();
    const next = races.results
      .filter((row) => selectedIds.has(String(row.raceId)))
      .map((row) => ({ row, startMs: Date.parse(String(row.startTimeUtc ?? "")) }))
      .filter((item) => Number.isFinite(item.startMs) && item.startMs > nowMs)
      .sort((a, b) => a.startMs - b.startMs)[0];

    if (!next) return { ok: true, selectionExists: true, nextBet: null };

    return {
      ok: true,
      selectionExists: true,
      nextBet: {
        raceId: String(next.row.raceId),
        venue: String(next.row.venue),
        raceNo: Number(next.row.raceNo),
        startTimeJst: jstClock(next.row.startTimeUtc) ?? next.row.startTimeJst,
        deadlineJst: deadlineClock(next.row.startTimeUtc),
        locked: lockedIds.has(String(next.row.raceId)),
      },
    };
  } catch (error) {
    console.error("HOME_NEXT_BET_UNTIL_POST_LOAD_FAILED", error);
    return { ok: false, selectionExists: false, nextBet: null };
  }
}

function nextBetHtml(state: { selectionExists: boolean; nextBet: NextBetState | null }): string {
  if (state.nextBet) {
    const next = state.nextBet;
    return `<section class="home-next-release${next.locked ? " home-next-release-locked" : ""}" aria-label="次の買い目">
      <span>次の買い目</span>
      <a href="/races/${encodeURIComponent(next.raceId)}"><b>${esc(next.venue)} ${next.raceNo}R</b><strong>${next.locked ? "公開済み" : `${esc(next.deadlineJst ?? "--:--")}までに公開`}</strong></a>
      <small>${esc(next.startTimeJst ?? "--:--")}発走</small>
    </section>`;
  }
  if (state.selectionExists) {
    return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
      <span>次の買い目</span>
      <div class="home-next-release-copy"><b>本日の対象買い目は終了</b></div>
      <small>次回は次の開催日の対象決定後に表示</small>
    </section>`;
  }
  return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
    <span>次の買い目</span>
    <div class="home-next-release-copy"><b>対象レース決定後に表示</b></div>
    <small>当日の対象決定後に表示</small>
  </section>`;
}

async function rewriteHome(response: Response, env: Env): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;

  const state = await loadNextBetUntilPost(env);
  if (!state.ok) return response;

  let html = await response.text();
  const slot = nextBetHtml(state);
  const existing = /<section class="home-next-release[\s\S]*?<\/section>/;

  if (existing.test(html)) {
    html = html.replace(existing, slot);
  } else if (html.includes('<section class="home-live-learning"')) {
    html = html.replace('<section class="home-live-learning"', `${slot}<section class="home-live-learning"`);
  } else if (html.includes('<details class="home-publish-flow home-publish-details">')) {
    html = html.replace('<details class="home-publish-flow home-publish-details">', `${slot}<details class="home-publish-flow home-publish-details">`);
  } else {
    html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${slot}$1`);
  }

  html = html.replace(
    "</head>",
    `<style>.home-next-release-locked strong{color:var(--green)!important}</style></head>`,
  );

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return new URL(request.url).pathname === "/" ? rewriteHome(response, env) : response;
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
