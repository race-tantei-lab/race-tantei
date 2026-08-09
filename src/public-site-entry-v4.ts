import publicSite from "./public-site-entry-v3.js";
import type { Env } from "./v1/types.js";
import { safeRaceName } from "./v1/race-display.js";
import { frozenRaceOutcome } from "./v1/frozen-race-results.js";

const BAD_NAME_SQL = `
  UPDATE rt_races
  SET race_name = CAST(race_no AS TEXT) || 'レース', updated_at=CURRENT_TIMESTAMP
  WHERE race_name IS NULL OR trim(race_name)=''
     OR race_name LIKE '%検索ウィンドウ%'
     OR race_name LIKE '%検索メニュー%'
     OR race_name LIKE '%サイト内検索%'
     OR race_name LIKE '%メニューを開く%'
`;

async function repairBadRaceNames(db: D1Database): Promise<void> {
  try { await db.prepare(BAD_NAME_SQL).run(); } catch { /* display guard still applies */ }
}

async function settlementMap(db: D1Database, raceIds: string[]): Promise<Map<string, { settled: boolean; hit: boolean }>> {
  const out = new Map<string, { settled: boolean; hit: boolean }>();
  if (!raceIds.length) return out;
  const placeholders = raceIds.map(() => '?').join(',');
  try {
    const rows = await db.prepare(`
      SELECT race_id AS raceId,
             MAX(CASE WHEN settlement_status='settled' THEN 1 ELSE 0 END) AS settled,
             MAX(CASE WHEN settlement_status='settled' AND COALESCE(return_yen,0)>0 THEN 1 ELSE 0 END) AS hit
      FROM rt_public_bets
      WHERE race_id IN (${placeholders})
      GROUP BY race_id
    `).bind(...raceIds).all<{ raceId: string; settled: number; hit: number }>();
    for (const row of rows.results) out.set(row.raceId, { settled: Number(row.settled) > 0, hit: Number(row.hit) > 0 });
  } catch { /* history table may not be ready */ }
  return out;
}

const RESULT_CSS = `<style>
  .status.hit{background:#124b37;color:#bdf5dc;border:1px solid #287d5b}
  .status.miss{background:#4a2528;color:#ffc3c3;border:1px solid #784047}
</style>`;

function compactHomePage(html: string): string {
  const css = `<style>
    .status.hit{background:#124b37;color:#bdf5dc;border:1px solid #287d5b}.status.miss{background:#4a2528;color:#ffc3c3;border:1px solid #784047}
    @media(max-width:760px){
      .wrap{padding-top:8px!important}.top{padding-bottom:9px!important}.brand{font-size:22px!important}.nav a{padding:7px 9px!important;font-size:12px!important}
      .hero{padding:13px!important;margin-bottom:9px!important;border-radius:14px!important}.hero h1{font-size:21px!important;margin-bottom:4px!important}.hero p{font-size:12px!important;line-height:1.55!important;margin:3px 0!important}
      .section-title{margin:13px 0 7px!important}.section-title h2{font-size:18px!important}.section-title .muted{font-size:11px!important}
      .metrics{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}.metric{padding:9px 7px!important;border-radius:12px!important;min-width:0!important}
      .metric summary>b{font-size:12px!important}.metric strong{font-size:22px!important;margin:2px 0!important}.metric small{display:block!important;font-size:9px!important;line-height:1.35!important;overflow:hidden!important}.metric summary:after{font-size:9px!important;margin-top:3px!important}
      .monthly{font-size:9px!important;max-height:220px!important}.monthly-row{grid-template-columns:48px 1fr auto!important;font-size:9px!important;gap:4px!important}
      .navigator{padding:8px!important;border-radius:14px!important}.nav-step{display:grid!important;grid-template-columns:42px minmax(0,1fr)!important;gap:5px!important;align-items:center!important;margin:4px 0!important}.nav-label{margin:0!important;font-size:10px!important}.rail{padding-bottom:3px!important;gap:5px!important}.chip{padding:6px 9px!important;font-size:11px!important}
      .race-rail{gap:7px!important;min-height:150px!important;padding-bottom:4px!important}.race-card{flex-basis:185px!important;padding:10px!important;border-radius:13px!important}.race-no{font-size:20px!important}.race-time{font-size:12px!important}.race-name{font-size:13px!important;min-height:34px!important;margin:6px 0 3px!important}.race-meta{font-size:10px!important}.status{font-size:10px!important;padding:4px 7px!important;margin-top:7px!important}.deadline{font-size:9px!important;margin-top:4px!important}
    }
  </style>`;
  return html.replace('</head>', `${css}</head>`);
}

function compactRacePage(html: string): string {
  let out = html.replace(
    /<section class="panel" style="margin-top:12px"><h3>買い目について<\/h3><ul>([\s\S]*?)<\/ul><\/section>/g,
    '<details class="bet-note"><summary>買い目について</summary><ul>$1</ul></details>'
  );
  const css = `<style>
    .bet-note{margin-top:10px;border:1px solid var(--line);border-radius:12px;background:var(--panel2);font-size:12px}
    .bet-note summary{cursor:pointer;padding:10px 12px;color:var(--muted);font-weight:700;list-style:none}
    .bet-note summary::-webkit-details-marker{display:none}.bet-note ul{margin:0;padding:0 16px 11px 30px;color:var(--muted)}
    .status.hit{background:#124b37;color:#bdf5dc}.status.miss{background:#4a2528;color:#ffc3c3}
  </style>`;
  out = out.replace('</head>', `${css}</head>`);
  return out;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    if (!publicSite.fetch) return new Response('NOT_FOUND', { status: 404 });

    const response = await publicSite.fetch(request, env, ctx);
    if (path === '/' || path === '/api/public/calendar' || path === '/api/public/day' || path.startsWith('/races/')) {
      ctx.waitUntil(repairBadRaceNames(env.DB));
    }

    if (path === '/api/public/day' && response.ok) {
      try {
        const data = await response.clone().json() as { races?: Array<any>; [key: string]: any };
        const races = Array.isArray(data.races) ? data.races : [];
        const settlements = await settlementMap(env.DB, races.map((race) => String(race.raceId ?? '')).filter(Boolean));
        data.races = races.map((race) => {
          const raceNo = Number(race.raceNo ?? 0);
          const fixedName = safeRaceName(race.raceName, raceNo, race.conditions ?? null);
          const settled = settlements.get(String(race.raceId ?? ''));
          const frozenOutcome = frozenRaceOutcome(String(race.raceDate ?? ''), String(race.venue ?? ''), raceNo);
          const publicState = { ...(race.publicState ?? {}) };
          if (publicState.code === 'buy' && frozenOutcome) {
            publicState.code = frozenOutcome;
            publicState.label = frozenOutcome === 'hit' ? '的中' : '不的中';
            publicState.deadline = null;
          } else if (publicState.code === 'buy' && settled?.settled) {
            publicState.code = settled.hit ? 'hit' : 'miss';
            publicState.label = settled.hit ? '的中' : '不的中';
            publicState.deadline = null;
          }
          return { ...race, raceName: fixedName, publicState };
        });
        return new Response(JSON.stringify(data), { status: response.status, headers: response.headers });
      } catch { return response; }
    }

    if (path === '/' && response.headers.get('content-type')?.includes('text/html')) {
      try { return new Response(compactHomePage(await response.text()), { status: response.status, headers: response.headers }); }
      catch { return response; }
    }

    if (path.startsWith('/races/') && response.headers.get('content-type')?.includes('text/html')) {
      try {
        const raceId = decodeURIComponent(path.slice('/races/'.length));
        const row = await env.DB.prepare(`SELECT race_no AS raceNo,race_name AS raceName,conditions FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<{ raceNo: number; raceName: string | null; conditions: string | null }>();
        let html = await response.text();
        if (row) {
          const fixed = safeRaceName(row.raceName, Number(row.raceNo), row.conditions);
          html = html.replace(/<h1>検索ウィンドウ<\/h1>/g, `<h1>${fixed}</h1>`)
                     .replace(/<h1>検索メニュー<\/h1>/g, `<h1>${fixed}</h1>`)
                     .replace(/<h1>サイト内検索<\/h1>/g, `<h1>${fixed}</h1>`);
        }
        return new Response(compactRacePage(html), { status: response.status, headers: response.headers });
      } catch { return response; }
    }

    if (response.headers.get('content-type')?.includes('text/html')) {
      try { return new Response((await response.text()).replace('</head>', `${RESULT_CSS}</head>`), { status: response.status, headers: response.headers }); }
      catch { return response; }
    }
    return response;
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await repairBadRaceNames(env.DB);
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
