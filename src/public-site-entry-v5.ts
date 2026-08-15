import publicSite from "./public-site-entry-v4.js";
import type { Env } from "./v1/types.js";
import { safeRaceName } from "./v1/race-display.js";

type LiveSettlement = { hasBets: boolean; settled: boolean; hit: boolean };

function jstNowParts(now = new Date()): { date: string; minutes: number } {
  const shifted = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const year = shifted.getUTCFullYear();
  const month = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const day = String(shifted.getUTCDate()).padStart(2, "0");
  return { date: `${year}-${month}-${day}`, minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes() };
}

function timeMinutes(value: unknown): number | null {
  const match = String(value ?? "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function clock(total: number): string {
  const normalized = (total + 24 * 60) % (24 * 60);
  return `${String(Math.floor(normalized / 60)).padStart(2, "0")}:${String(normalized % 60).padStart(2, "0")}`;
}

async function frozenSelection(db: D1Database, raceDate: string): Promise<Set<string> | null> {
  try {
    const row = await db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1`)
      .bind(`final_daily_selection:${raceDate}`)
      .first<{ value: string | null }>();
    if (!row?.value) return null;
    const payload = JSON.parse(String(row.value)) as { selected?: Array<{ raceId?: unknown }> };
    if (!Array.isArray(payload.selected) || !payload.selected.length) return null;
    const ids = payload.selected.map((entry) => String(entry?.raceId ?? "")).filter(Boolean);
    return ids.length ? new Set(ids) : null;
  } catch {
    return null;
  }
}

async function liveSettlements(db: D1Database, raceIds: string[]): Promise<Map<string, LiveSettlement>> {
  const out = new Map<string, LiveSettlement>();
  if (!raceIds.length) return out;
  const placeholders = raceIds.map(() => "?").join(",");
  try {
    const rows = await db.prepare(`
      SELECT race_id AS raceId,
             COUNT(*) AS betRows,
             SUM(CASE WHEN settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
             MAX(CASE WHEN settlement_status='settled' AND COALESCE(return_yen,0)>0 THEN 1 ELSE 0 END) AS hit
      FROM rt_public_bets
      WHERE race_id IN (${placeholders})
      GROUP BY race_id
    `).bind(...raceIds).all<{ raceId: string; betRows: number; settledRows: number; hit: number }>();
    for (const row of rows.results) {
      const betRows = Number(row.betRows);
      const settledRows = Number(row.settledRows);
      out.set(row.raceId, {
        hasBets: betRows > 0,
        settled: betRows > 0 && settledRows === betRows,
        hit: Number(row.hit) > 0
      });
    }
  } catch { /* history may still be initializing */ }
  return out;
}

async function truthfulTodayApi(db: D1Database, response: Response): Promise<Response> {
  if (!response.ok) return response;
  try {
    const data = await response.clone().json() as { races?: Array<Record<string, any>>; [key: string]: any };
    const races = Array.isArray(data.races) ? data.races : [];
    const now = jstNowParts();
    const todays = races.filter((race) => String(race.raceDate ?? "") === now.date);
    const settlements = await liveSettlements(db, todays.map((race) => String(race.raceId ?? "")).filter(Boolean));
    const selected = await frozenSelection(db, now.date);

    data.races = races.map((race) => {
      if (String(race.raceDate ?? "") !== now.date) return race;
      const raceId = String(race.raceId ?? "");
      const saved = settlements.get(raceId);
      const publicState = { ...(race.publicState ?? {}) };

      if (saved?.hasBets) {
        if (saved.settled) {
          publicState.code = saved.hit ? "hit" : "miss";
          publicState.label = saved.hit ? "的中" : "不的中";
        } else {
          publicState.code = "buy";
          publicState.label = "買い目あり";
        }
        publicState.deadline = null;
        return { ...race, publicState };
      }

      const start = timeMinutes(race.startTimeJst);
      if (selected) {
        if (!selected.has(raceId)) {
          publicState.code = "skip";
          publicState.label = "見送り";
          publicState.deadline = null;
          return { ...race, publicState };
        }
        if (start === null) {
          publicState.code = "target";
          publicState.label = "買い目対象";
          publicState.deadline = "発走45〜15分前に買い目確定";
          return { ...race, publicState };
        }
        const deadline = start - 15;
        if (now.minutes < deadline) {
          publicState.code = "target";
          publicState.label = "買い目対象";
          publicState.deadline = `${clock(deadline)}までに買い目確定`;
        } else if (now.minutes < start) {
          publicState.code = "overdue";
          publicState.label = "買い目未確定";
          publicState.deadline = `${clock(deadline)}までに確定予定（未反映）`;
        } else {
          publicState.code = "missing";
          publicState.label = "買い目未生成";
          publicState.deadline = null;
        }
        return { ...race, publicState };
      }

      if (start === null) {
        publicState.code = "pending";
        publicState.label = "判定中";
        publicState.deadline = "対象レース判定後、発走45〜15分前に買い目確定";
        return { ...race, publicState };
      }

      const deadline = start - 15;
      if (now.minutes < deadline) {
        publicState.code = "pending";
        publicState.label = "判定中";
        publicState.deadline = "対象レースを判定中";
      } else if (now.minutes < start) {
        publicState.code = "overdue";
        publicState.label = "買い目未確定";
        publicState.deadline = `${clock(deadline)}までに確定予定（未反映）`;
      } else {
        publicState.code = "missing";
        publicState.label = "買い目未生成";
        publicState.deadline = null;
      }
      return { ...race, publicState };
    });

    const headers = new Headers(response.headers);
    headers.set("content-type", "application/json; charset=utf-8");
    headers.delete("content-length");
    return new Response(JSON.stringify(data), { status: response.status, headers });
  } catch {
    return response;
  }
}

function improveHome(html: string): string {
  const css = `<style>
    .status.target{background:#15483a!important;color:#baf4dd!important;border:1px solid #2d806c!important}
    .status.overdue{background:#4a3b1d!important;color:#f6dda0!important;border:1px solid #725b28!important}
    .status.missing{background:#4a2528!important;color:#ffc3c3!important;border:1px solid #784047!important}
    .monthly-drawer{margin-top:8px;border:1px solid var(--line);background:var(--panel);border-radius:14px;padding:12px;overflow:hidden}
    .monthly-drawer-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}
    .monthly-drawer-head b{font-size:15px}.monthly-drawer-head small{display:block;color:var(--muted);font-size:11px;margin-top:3px;line-height:1.4}
    .monthly-drawer-close{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:999px;padding:5px 9px;font:inherit;font-size:11px}
    @media(max-width:760px){
      body{overflow-x:hidden}.wrap{padding:8px 10px 34px!important}.top{padding-bottom:8px!important}.brand{font-size:22px!important}.nav{gap:5px!important}.nav a{padding:7px 9px!important;font-size:12px!important}
      .hero{padding:12px!important;margin-bottom:8px!important;border-radius:14px!important}.hero h1{font-size:20px!important;margin-bottom:3px!important}.hero p{font-size:12px!important;line-height:1.5!important;margin:2px 0!important}
      .section-title{margin:12px 0 6px!important}.section-title h2{font-size:18px!important}.section-title .muted{font-size:10px!important}
      .metrics{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}.metric{padding:9px 7px!important;border-radius:12px!important;min-width:0!important;overflow:hidden!important}.metric summary{min-width:0!important}.metric summary>b{font-size:11px!important;white-space:nowrap!important}.metric strong{font-size:21px!important;margin:3px 0 1px!important;white-space:nowrap!important}.metric small{display:block!important;font-size:9px!important;line-height:1.25!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}.metric summary:after{content:"月別"!important;font-size:9px!important;margin-top:3px!important}.metric .monthly{display:none!important}
      .monthly-drawer{padding:10px!important;border-radius:12px!important}.monthly-drawer .monthly{display:block!important;margin-top:0!important;padding-top:0!important;border-top:0!important;max-height:320px!important;overflow:auto!important}.monthly-drawer .monthly-row{grid-template-columns:58px minmax(0,1fr) 58px!important;gap:6px!important;font-size:10px!important;align-items:center!important}.monthly-drawer .monthly-row span{white-space:normal!important;line-height:1.35!important}.monthly-drawer .monthly-row strong{font-size:12px!important;text-align:right!important;white-space:nowrap!important}
      .navigator{padding:9px!important;border-radius:14px!important}.nav-step{display:block!important;margin:7px 0!important}.nav-label{margin:0 0 4px!important;font-size:10px!important;color:var(--muted)!important}.rail{width:100%!important;padding-bottom:3px!important;gap:5px!important}.chip{padding:6px 10px!important;font-size:11px!important}
      .race-rail{gap:7px!important;min-height:0!important;padding:2px 0 5px!important}.race-card{flex:0 0 190px!important;padding:11px!important;border-radius:13px!important;min-height:150px!important}.race-no{font-size:21px!important}.race-time{font-size:12px!important}.race-name{font-size:13px!important;line-height:1.35!important;min-height:36px!important;margin:6px 0 4px!important}.race-meta{font-size:10px!important}.status{font-size:10px!important;padding:4px 7px!important;margin-top:7px!important}.deadline{font-size:10px!important;margin-top:5px!important;color:var(--warn)!important;font-weight:700!important;line-height:1.35!important}
    }
  </style>`;
  const script = `<script>
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('.nav-label').forEach(el=>{el.textContent=(el.textContent||'').replace(/^\\d+\\.\\s*/, '')});
    const metrics=[...document.querySelectorAll('details.metric')];
    const grid=document.querySelector('.metrics');
    if(grid&&metrics.length){
      metrics.forEach(m=>m.removeAttribute('open'));
      const drawer=document.createElement('div');drawer.className='monthly-drawer';drawer.hidden=true;grid.insertAdjacentElement('afterend',drawer);
      let active=null;
      const close=()=>{drawer.hidden=true;drawer.innerHTML='';active=null};
      metrics.forEach(metric=>{
        const summary=metric.querySelector('summary');const monthly=metric.querySelector('.monthly');const name=summary?.querySelector('b')?.textContent||'';const small=summary?.querySelector('small');const fullSmall=small?.textContent||'';
        if(small){const m=fullSmall.match(/\\d+R/);small.textContent=m?m[0]:'';}
        summary?.addEventListener('click',e=>{e.preventDefault();metric.removeAttribute('open');if(active===metric){close();return;}active=metric;drawer.hidden=false;drawer.innerHTML='<div class="monthly-drawer-head"><div><b>'+name+' 月別回収率</b><small>'+fullSmall+'</small></div><button type="button" class="monthly-drawer-close">閉じる</button></div><div class="monthly">'+(monthly?.innerHTML||'')+'</div>';drawer.querySelector('.monthly-drawer-close')?.addEventListener('click',close);});
      });
    }
  });
  </script>`;
  return html.replace("</head>", `${css}</head>`).replace("</body>", `${script}</body>`);
}

async function fixRaceTitle(db: D1Database, path: string, response: Response): Promise<Response> {
  if (!path.startsWith("/races/") || !response.headers.get("content-type")?.includes("text/html")) return response;
  try {
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const row = await db.prepare(`SELECT race_no AS raceNo,race_name AS raceName,conditions FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<{ raceNo: number; raceName: string | null; conditions: string | null }>();
    if (!row) return response;
    const name = safeRaceName(row.raceName, Number(row.raceNo), row.conditions);
    let html = await response.text();
    html = html.replace(/(<div class="race-title">[\s\S]*?<h1>)[\s\S]*?(<\/h1>)/, `$1${name}$2`);
    const headers = new Headers(response.headers); headers.delete("content-length");
    return new Response(html, { status: response.status, headers });
  } catch { return response; }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    let response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/public/day") response = await truthfulTodayApi(env.DB, response);
    response = await fixRaceTitle(env.DB, path, response);
    if (path === "/" && response.headers.get("content-type")?.includes("text/html")) {
      try {
        const headers = new Headers(response.headers); headers.delete("content-length");
        return new Response(improveHome(await response.text()), { status: response.status, headers });
      } catch { return response; }
    }
    return response;
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
