import v39 from "./public-site-entry-v39.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v40-no-race-day-stable-20260904";

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

async function pause(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function hasTodayRace(db: D1Database, date: string): Promise<boolean | null> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const row = await db.prepare("SELECT race_id AS raceId FROM rt_races WHERE race_date=? LIMIT 1")
        .bind(date).first<{ raceId: string }>();
      return Boolean(row?.raceId);
    } catch {
      if (attempt < 3) await pause(150 * (attempt + 1));
    }
  }
  return null;
}

function noRaceHome(date: string, uncertain = false): Response {
  const notice = uncertain
    ? `<div class="notice">開催データの確認を再試行中です。画面は自動更新されます。</div>`
    : "";
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111f"><title>レース探偵</title><style>
  :root{color-scheme:dark;--bg:#07111f;--panel:#0d1d2d;--line:#28445f;--text:#eaf3ff;--muted:#9fb2c6;--green:#71e2be}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic",sans-serif}.wrap{max-width:980px;margin:auto;padding:18px 14px 60px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:18px}.brand{font-size:28px;font-weight:900}.nav{display:flex;gap:7px;overflow:auto}.nav a{padding:8px 10px;border:1px solid var(--line);border-radius:999px;background:#0b1927;white-space:nowrap;font-size:12px}.next,.panel{padding:16px;border:1px solid #356179;border-radius:18px;background:linear-gradient(145deg,#10263a,#0b1b2b);margin-bottom:14px}.eyebrow{font-size:11px;font-weight:900;color:var(--green)}h2{margin:5px 0 7px;font-size:20px}p{margin:0;color:var(--muted);font-size:13px;line-height:1.7}.links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}.links a{padding:12px;border:1px solid var(--line);border-radius:12px;background:#0a1724;text-align:center;font-size:12px;font-weight:800}.notice{margin-bottom:14px;padding:9px 11px;border:1px solid #6d5c33;border-radius:11px;background:#2a2417;color:#f0d98d;font-size:11px}@media(max-width:700px){.wrap{padding:14px 10px 50px}.top{align-items:flex-start}.brand{font-size:25px}.links{grid-template-columns:1fr}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav class="nav"><a href="/win5">WIN5</a><a href="/performance">成績</a><a href="/conditions">予想ロジック</a></nav></header>${notice}<section class="next"><div class="eyebrow">次の買い目</div><h2>${uncertain ? "開催データを確認中" : "本日のJRA開催はありません"}</h2><p>${uncertain ? "接続が戻り次第、対象レースと買い目をこの画面に自動表示します。" : `${date} は開催対象レースがありません。レース開催日は対象レースと買い目をここに表示します。`}</p></section><section class="panel"><div class="eyebrow">レース探偵</div><h2>予想・成績を確認</h2><p>開催のない日も、過去成績や予想ロジック、WIN5ページは通常どおり確認できます。</p><div class="links"><a href="/performance">成績を見る</a><a href="/conditions">予想ロジック</a><a href="/win5">WIN5</a></div></section></main><script>(function(){let busy=false;async function refresh(){if(busy||document.hidden)return;busy=true;try{const r=await fetch('/?live='+Date.now(),{cache:'no-store'});if(!r.ok)return;const t=await r.text();const d=new DOMParser().parseFromString(t,'text/html');const incoming=d.querySelector('main.wrap');const current=document.querySelector('main.wrap');if(incoming&&current&&incoming.innerHTML!==current.innerHTML)current.innerHTML=incoming.innerHTML;}catch{}finally{busy=false}}setInterval(refresh,15000)})();</script></body></html>`;
  return new Response(html, { status: 200, headers: {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "no-store, max-age=0",
    "x-race-ui-version": UI_VERSION,
    "x-race-home-path": uncertain ? "v40-preflight-retrying" : "v40-no-race-day",
    ...(uncertain ? { "x-race-home-degraded": "1" } : {}),
  }});
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      const today = jstDate();
      const hasRace = await hasTodayRace(env.DB, today);
      if (hasRace === false) return noRaceHome(today, false);
      if (hasRace === null) return noRaceHome(today, true);
      const response = await v39.fetch(request, env, ctx);
      const headers = new Headers(response.headers);
      headers.set("x-race-ui-version", UI_VERSION);
      headers.set("x-race-home-path", "v40-race-day-v39");
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
    }
    const response = await v39.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (v39.scheduled) await v39.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
