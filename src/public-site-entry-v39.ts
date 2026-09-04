import publicSite from "./public-site-entry-v38.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v39-exact-date-home-20260904";
const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;

type RaceRow = {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string | null;
  startTimeJst: string | null;
  startTimeUtc: string | null;
  surface: string | null;
  distanceM: number | null;
};

type BetRow = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  stakeYen: number;
  assumedOdds: number | null;
  settlementStatus: string;
};

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function addDays(date: string, days: number): string {
  const base = new Date(`${date}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() + days);
  return base.toISOString().slice(0, 10);
}

function startMs(race: RaceRow): number | null {
  const utc = Date.parse(String(race.startTimeUtc ?? ""));
  if (Number.isFinite(utc)) return utc;
  const m = String(race.startTimeJst ?? "").match(/(\d{1,2}):(\d{2})/);
  if (!m) return null;
  const value = Date.parse(`${race.raceDate}T${m[1].padStart(2, "0")}:${m[2]}:00+09:00`);
  return Number.isFinite(value) ? value : null;
}

function timeLabel(value: string | null): string {
  return String(value ?? "").match(/(\d{1,2}:\d{2})/)?.[1] ?? "--:--";
}

async function pause(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function retry<T>(fn: () => Promise<T>, attempts = 3): Promise<T> {
  let last: unknown;
  for (let i = 0; i < attempts; i += 1) {
    try { return await fn(); }
    catch (error) {
      last = error;
      if (i + 1 < attempts) await pause(120 * (i + 1));
    }
  }
  throw last;
}

async function racesForDate(db: D1Database, date: string): Promise<RaceRow[]> {
  return retry(async () => {
    const rows = await db.prepare(`
      SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
             start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,surface,distance_m AS distanceM
      FROM rt_races
      WHERE race_date=?
      ORDER BY venue,race_no
    `).bind(date).all<RaceRow>();
    return (rows.results ?? []).map((row) => ({
      ...row,
      raceNo: Number(row.raceNo),
      distanceM: row.distanceM == null ? null : Number(row.distanceM),
    }));
  });
}

async function selectedIds(db: D1Database, date: string): Promise<Set<string> | null> {
  return retry(async () => {
    const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
      .bind(`final_daily_selection:${date}`).first<{ value: string | null }>();
    if (!row?.value) return null;
    try {
      const parsed = JSON.parse(row.value) as { selected?: Array<{ raceId?: unknown }> };
      const ids = (parsed.selected ?? []).map((item) => String(item.raceId ?? "")).filter(Boolean);
      return ids.length ? new Set(ids) : null;
    } catch { return null; }
  });
}

async function betsForRaces(db: D1Database, raceIds: string[]): Promise<Map<string, BetRow[]>> {
  const out = new Map<string, BetRow[]>();
  if (!raceIds.length) return out;
  return retry(async () => {
    const ids = [...new Set(raceIds)].slice(0, 40);
    const placeholders = ids.map(() => "?").join(",");
    const rows = await db.prepare(`
      SELECT race_id AS raceId,course,bet_type AS betType,combination,stake_yen AS stakeYen,
             assumed_odds AS assumedOdds,settlement_status AS settlementStatus
      FROM rt_public_bets
      WHERE race_id IN (${placeholders})
      ORDER BY race_id,course,id
    `).bind(...ids).all<BetRow>();
    for (const raw of rows.results ?? []) {
      const row: BetRow = {
        ...raw,
        stakeYen: Number(raw.stakeYen),
        assumedOdds: raw.assumedOdds == null ? null : Number(raw.assumedOdds),
      };
      const list = out.get(row.raceId) ?? [];
      list.push(row);
      out.set(row.raceId, list);
    }
    return out;
  });
}

function isFinal(rows: BetRow[]): boolean {
  if (rows.length !== 6) return false;
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.course, (counts.get(row.course) ?? 0) + 1);
  return COURSES.every((course) => counts.get(course) === 2) && counts.size === COURSES.length;
}

function dateLabel(date: string): string {
  const [, m = "", d = ""] = date.split("-");
  return `${Number(m)}月${Number(d)}日`;
}

function raceCard(race: RaceRow, selected: Set<string> | null, bets: Map<string, BetRow[]>): string {
  const rows = bets.get(race.raceId) ?? [];
  const final = isFinal(rows);
  const selectedRace = Boolean(selected?.has(race.raceId));
  const state = final ? "買い目確定" : selectedRace ? "買い目対象" : selected ? "見送り" : "開催予定";
  const cls = final ? "buy" : selectedRace ? "target" : "scheduled";
  const meta = [race.surface, race.distanceM ? `${race.distanceM}m` : null].filter(Boolean).join(" / ");
  return `<a class="race" href="/races/${encodeURIComponent(race.raceId)}"><div class="race-top"><b>${race.raceNo}R</b><span>${timeLabel(race.startTimeJst)}</span></div><h3>${esc(race.raceName ?? `${race.raceNo}R`)}</h3><small>${esc(meta)}</small><em class="state ${cls}">${state}</em></a>`;
}

function nextBet(todayRaces: RaceRow[], selected: Set<string> | null, bets: Map<string, BetRow[]>): string {
  const now = Date.now();
  if (!todayRaces.length) return `<section class="next"><div class="eyebrow">次の買い目</div><h2>本日のJRA開催はありません</h2><p>次回開催データを下に表示します。</p></section>`;
  if (!selected) return `<section class="next"><div class="eyebrow">次の買い目</div><h2>対象レースを判定中</h2><p>対象レース確定後に自動表示します。</p></section>`;
  const next = todayRaces
    .filter((race) => selected.has(race.raceId))
    .map((race) => ({ race, start: startMs(race) }))
    .filter((item): item is { race: RaceRow; start: number } => item.start != null && item.start > now)
    .sort((a, b) => a.start - b.start || a.race.raceNo - b.race.raceNo)[0]?.race;
  if (!next) return `<section class="next"><div class="eyebrow">次の買い目</div><h2>本日の対象レースは終了しました</h2><p>結果は各レース詳細から確認できます。</p></section>`;
  const rows = bets.get(next.raceId) ?? [];
  const final = isFinal(rows);
  const light = rows.filter((row) => row.course === "ライト");
  const tickets = (light.length ? light : rows).map((row) => `<div class="ticket"><b>${esc(row.betType)}</b><strong>${esc(row.combination)}</strong><span>${row.assumedOdds == null ? "JRA公式オッズ" : `${row.assumedOdds.toFixed(1)}倍`}</span></div>`).join("");
  return `<section class="next" data-next-race="${esc(next.raceId)}"><div class="next-head"><div><div class="eyebrow">次の買い目</div><h2>${esc(next.venue)} ${next.raceNo}R　${esc(next.raceName ?? `${next.raceNo}R`)}</h2><p>${timeLabel(next.startTimeJst)}発走</p></div><span class="pill">${final ? "買い目確定済み" : "作成待ち"}</span></div>${tickets ? `<div class="tickets">${tickets}</div>` : `<div class="wait">JRA公式オッズ取得後に買い目を表示します。</div>`}<a class="detail" href="/races/${encodeURIComponent(next.raceId)}">レース詳細を見る →</a></section>`;
}

function page(today: string, todayRaces: RaceRow[], nextDate: string | null, nextRaces: RaceRow[], selected: Set<string> | null, bets: Map<string, BetRow[]>, degraded: boolean): Response {
  const shownDate = todayRaces.length ? today : nextDate;
  const shownRaces = todayRaces.length ? todayRaces : nextRaces;
  const groups = [...new Set(shownRaces.map((race) => race.venue))].map((venue) => `<section class="venue"><div class="venue-title"><b>${esc(venue)}</b><span>${shownRaces.filter((race) => race.venue === venue).length}R</span></div><div class="rail">${shownRaces.filter((race) => race.venue === venue).map((race) => raceCard(race, todayRaces.length ? selected : null, todayRaces.length ? bets : new Map())).join("")}</div></section>`).join("");
  const schedule = shownDate && shownRaces.length ? `<section class="day"><h2>${dateLabel(shownDate)}</h2>${groups}</section>` : `<section class="empty"><h2>開催データを取得しています</h2><p>通常画面のまま自動で再取得します。</p></section>`;
  const note = degraded ? `<div class="notice">一部データの取得を再試行中です。画面は自動更新されます。</div>` : "";
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111f"><title>レース探偵</title><style>
  :root{color-scheme:dark;--bg:#07111f;--panel:#0d1d2d;--line:#28445f;--text:#eaf3ff;--muted:#9fb2c6;--green:#71e2be}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic",sans-serif}.wrap{max-width:980px;margin:auto;padding:18px 14px 60px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:18px}.brand{font-size:28px;font-weight:900}.nav{display:flex;gap:7px;overflow:auto}.nav a{padding:8px 10px;border:1px solid var(--line);border-radius:999px;background:#0b1927;white-space:nowrap;font-size:12px}.next{padding:16px;border:1px solid #356179;border-radius:18px;background:linear-gradient(145deg,#10263a,#0b1b2b);margin-bottom:18px}.next-head{display:flex;justify-content:space-between;gap:12px}.eyebrow{font-size:11px;font-weight:900;color:var(--green)}.next h2{margin:4px 0;font-size:20px}.next p{margin:0;color:var(--muted);font-size:12px}.pill{align-self:flex-start;padding:6px 9px;border-radius:999px;background:#153a30;color:#a9f1d8;font-size:11px;font-weight:800}.tickets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}.ticket{display:grid;grid-template-columns:auto 1fr auto;gap:8px;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0a1724}.ticket b,.ticket span{font-size:10px;color:var(--muted)}.ticket strong{font-size:14px}.wait{margin-top:12px;padding:10px;border:1px dashed var(--line);border-radius:11px;color:var(--muted);font-size:12px}.detail{display:inline-block;margin-top:10px;color:#b9dcff;font-size:12px}.notice{margin-bottom:14px;padding:9px 11px;border:1px solid #6d5c33;border-radius:11px;background:#2a2417;color:#f0d98d;font-size:11px}.day>h2{font-size:19px}.venue{margin-bottom:16px}.venue-title,.race-top{display:flex;justify-content:space-between;align-items:center}.venue-title{margin:0 2px 7px}.venue-title span{font-size:11px;color:var(--muted)}.rail{display:flex;gap:8px;overflow-x:auto;padding-bottom:5px}.race{flex:0 0 190px;min-height:145px;padding:12px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.race-top b{font-size:19px}.race-top span{font-size:12px;color:var(--muted)}.race h3{margin:8px 0 4px;min-height:36px;font-size:13px}.race small{display:block;color:var(--muted);font-size:10px}.state{display:inline-block;margin-top:9px;padding:4px 7px;border-radius:999px;background:#1b2a38;color:#bed6ec;font-size:10px;font-style:normal;font-weight:800}.state.buy,.state.target{background:#153a30;color:#a9f1d8}.empty{padding:22px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}.empty h2{margin-top:0}@media(max-width:700px){.wrap{padding:14px 10px 50px}.top{align-items:flex-start}.brand{font-size:25px}.tickets{grid-template-columns:1fr}.next-head{display:block}.pill{display:inline-block;margin-top:8px}.race{flex-basis:180px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav class="nav"><a href="/win5">WIN5</a><a href="/performance">成績</a><a href="/conditions">予想ロジック</a></nav></header>${note}${nextBet(todayRaces, selected, bets)}${schedule}</main><script>(function(){let busy=false;async function refresh(){if(busy||document.hidden)return;busy=true;try{const r=await fetch('/?live=1',{cache:'no-store'});if(!r.ok)return;const t=await r.text();const d=new DOMParser().parseFromString(t,'text/html');const incoming=d.querySelector('main.wrap');const current=document.querySelector('main.wrap');if(incoming&&current&&incoming.innerHTML!==current.innerHTML)current.innerHTML=incoming.innerHTML;}catch{}finally{busy=false}}setInterval(refresh,15000)})();</script></body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION, "x-race-home-path": "v39-exact-date", ...(degraded ? { "x-race-home-degraded": "1" } : {}) } });
}

async function home(env: Env): Promise<Response> {
  const today = jstDate();
  let degraded = false;
  let todayRaces: RaceRow[] = [];
  try { todayRaces = await racesForDate(env.DB, today); }
  catch { degraded = true; }

  let selected: Set<string> | null = null;
  let bets = new Map<string, BetRow[]>();
  if (todayRaces.length) {
    try { selected = await selectedIds(env.DB, today); } catch { degraded = true; }
    try { bets = await betsForRaces(env.DB, todayRaces.map((race) => race.raceId)); } catch { degraded = true; }
  }

  let nextDate: string | null = null;
  let nextRaces: RaceRow[] = [];
  if (!todayRaces.length) {
    for (let offset = 1; offset <= 8; offset += 1) {
      const date = addDays(today, offset);
      try {
        const rows = await racesForDate(env.DB, date);
        if (rows.length) { nextDate = date; nextRaces = rows; break; }
      } catch { degraded = true; }
    }
  }

  return page(today, todayRaces, nextDate, nextRaces, selected, bets, degraded);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return home(env);
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const headers = new Headers(response.headers);
    headers.set("x-race-ui-version", UI_VERSION);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
