import publicSite from "./public-site-entry-v37.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v38-lightweight-home-20260904";
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
  status: string;
};

type BetRow = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  stakeYen: number;
  assumedOdds: number | null;
  returnYen: number | null;
  settlementStatus: string;
};

type PublicState = { code: string; label: string; detail: string | null };

type FastDay = {
  date: string;
  races: RaceRow[];
  selectedIds: Set<string> | null;
  betsByRace: Map<string, BetRow[]>;
};

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function validDate(value: string | null): value is string {
  return Boolean(value && /^20\d{2}-\d{2}-\d{2}$/.test(value));
}

function raceStartMs(race: RaceRow): number | null {
  const utc = Date.parse(String(race.startTimeUtc ?? ""));
  if (Number.isFinite(utc)) return utc;
  const match = String(race.startTimeJst ?? "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const parsed = Date.parse(`${race.raceDate}T${match[1].padStart(2, "0")}:${match[2]}:00+09:00`);
  return Number.isFinite(parsed) ? parsed : null;
}

function timeLabel(value: string | null): string {
  const match = String(value ?? "").match(/(\d{1,2}:\d{2})/);
  return match?.[1] ?? "--:--";
}

function selectionIds(raw: string | null | undefined): Set<string> | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { selected?: Array<{ raceId?: unknown }> };
    const ids = (parsed.selected ?? []).map((row) => String(row?.raceId ?? "")).filter(Boolean);
    return ids.length ? new Set(ids) : null;
  } catch {
    return null;
  }
}

async function loadRacesForDate(db: D1Database, date: string): Promise<RaceRow[]> {
  const rows = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
           start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,surface,distance_m AS distanceM,status
    FROM rt_races
    WHERE race_date=?
    ORDER BY venue,race_no
  `).bind(date).all<RaceRow>();
  return (rows.results ?? []).map((row) => ({ ...row, raceNo: Number(row.raceNo), distanceM: row.distanceM == null ? null : Number(row.distanceM) }));
}

async function loadUpcomingRaces(db: D1Database, today: string): Promise<RaceRow[]> {
  const rows = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
           start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,surface,distance_m AS distanceM,status
    FROM rt_races
    WHERE race_date>=? AND race_date<=date(?,'+8 days')
    ORDER BY race_date,venue,race_no
    LIMIT 108
  `).bind(today, today).all<RaceRow>();
  return (rows.results ?? []).map((row) => ({ ...row, raceNo: Number(row.raceNo), distanceM: row.distanceM == null ? null : Number(row.distanceM) }));
}

async function loadSelection(db: D1Database, date: string): Promise<Set<string> | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`final_daily_selection:${date}`).first<{ value: string | null }>();
  return selectionIds(row?.value);
}

async function loadBetsForRaceIds(db: D1Database, raceIds: string[]): Promise<Map<string, BetRow[]>> {
  const out = new Map<string, BetRow[]>();
  if (!raceIds.length) return out;
  const ids = [...new Set(raceIds)].slice(0, 40);
  const placeholders = ids.map(() => "?").join(",");
  const rows = await db.prepare(`
    SELECT race_id AS raceId,course,bet_type AS betType,combination,stake_yen AS stakeYen,
           assumed_odds AS assumedOdds,return_yen AS returnYen,settlement_status AS settlementStatus
    FROM rt_public_bets
    WHERE race_id IN (${placeholders})
    ORDER BY race_id,course,id
  `).bind(...ids).all<BetRow>();
  for (const raw of rows.results ?? []) {
    const row: BetRow = {
      ...raw,
      stakeYen: Number(raw.stakeYen),
      assumedOdds: raw.assumedOdds == null ? null : Number(raw.assumedOdds),
      returnYen: raw.returnYen == null ? null : Number(raw.returnYen),
    };
    const list = out.get(row.raceId) ?? [];
    list.push(row);
    out.set(row.raceId, list);
  }
  return out;
}

async function loadFastDay(db: D1Database, date: string): Promise<FastDay> {
  // Read the small race/state tables first. Critically, do not touch the large
  // public-bet table when there are no races for the requested date.
  const [races, selectedIds] = await Promise.all([loadRacesForDate(db, date), loadSelection(db, date)]);
  const betsByRace = races.length ? await loadBetsForRaceIds(db, races.map((race) => race.raceId)) : new Map<string, BetRow[]>();
  return { date, races, selectedIds, betsByRace };
}

function completeFinal(rows: BetRow[]): boolean {
  if (rows.length !== 6) return false;
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.course, (counts.get(row.course) ?? 0) + 1);
  return COURSES.every((course) => counts.get(course) === 2) && counts.size === COURSES.length;
}

function publicState(race: RaceRow, day: FastDay, nowMs = Date.now()): PublicState {
  const bets = day.betsByRace.get(race.raceId) ?? [];
  if (completeFinal(bets)) {
    if (bets.every((row) => row.settlementStatus === "settled")) {
      return bets.some((row) => Number(row.returnYen ?? 0) > 0)
        ? { code: "hit", label: "的中", detail: null }
        : { code: "miss", label: "不的中", detail: null };
    }
    const start = raceStartMs(race);
    return start != null && start <= nowMs
      ? { code: "pending", label: "結果反映待ち", detail: null }
      : { code: "buy", label: "買い目確定", detail: "発走まで表示します" };
  }
  if (race.raceDate !== day.date) return { code: "pending", label: "準備中", detail: null };
  const start = raceStartMs(race);
  if (day.selectedIds) {
    if (!day.selectedIds.has(race.raceId)) return { code: "skip", label: "見送り", detail: null };
    if (start != null && start <= nowMs) return { code: "missing", label: "買い目未生成", detail: null };
    if (start != null && start - nowMs <= 15 * 60_000) return { code: "pending", label: "最終計算中", detail: "発走10分前までに確定" };
    return { code: "target", label: "買い目対象", detail: "JRA公式オッズで作成" };
  }
  return { code: "pending", label: "判定中", detail: null };
}

function ticketRows(rows: BetRow[]): string {
  const base = rows.filter((row) => row.course === "ライト");
  const source = base.length ? base : rows;
  const unique = new Map<string, BetRow>();
  for (const row of source) unique.set(`${row.betType}:${row.combination}`, row);
  if (!unique.size) return `<div class="next-wait">JRA公式オッズ取得後に買い目を表示します。</div>`;
  return `<div class="tickets">${[...unique.values()].map((row) => `<div class="ticket"><b>${esc(row.betType)}</b><strong>${esc(row.combination)}</strong><span>${row.assumedOdds == null ? "JRA公式オッズ取得済み" : `JRA公式 ${row.assumedOdds.toFixed(1)}倍`}</span></div>`).join("")}</div>`;
}

function nextBetHtml(day: FastDay, nowMs = Date.now()): string {
  if (!day.selectedIds) return `<section class="next"><div class="eyebrow">次の買い目</div><h2>対象レースを判定中</h2><p>開催情報の確定後、対象レースをここに表示します。</p></section>`;
  const candidates = day.races
    .filter((race) => day.selectedIds?.has(race.raceId))
    .map((race) => ({ race, start: raceStartMs(race) }))
    .filter((item): item is { race: RaceRow; start: number } => item.start != null && item.start > nowMs)
    .sort((a, b) => a.start - b.start || a.race.raceNo - b.race.raceNo);
  const next = candidates[0]?.race;
  if (!next) return `<section class="next"><div class="eyebrow">次の買い目</div><h2>本日の対象レースは終了しました</h2><p>確定済みの結果は各レースから確認できます。</p></section>`;
  const bets = day.betsByRace.get(next.raceId) ?? [];
  const locked = completeFinal(bets);
  return `<section class="next" data-next-race="${esc(next.raceId)}"><div class="next-head"><div><div class="eyebrow">次の買い目</div><h2>${esc(next.venue)} ${next.raceNo}R　${esc(next.raceName ?? `${next.raceNo}R`)}</h2><p>${timeLabel(next.startTimeJst)}発走</p></div><span class="next-state ${locked ? "buy" : "target"}">${locked ? "買い目確定済み" : "作成待ち"}</span></div>${ticketRows(bets)}<a class="detail" href="/races/${encodeURIComponent(next.raceId)}">レース詳細を見る →</a></section>`;
}

function raceCard(race: RaceRow, day: FastDay): string {
  const state = publicState(race, day);
  const meta = [race.surface, race.distanceM ? `${race.distanceM}m` : null].filter(Boolean).join(" / ");
  return `<a class="race-card" href="/races/${encodeURIComponent(race.raceId)}"><div class="race-top"><b>${race.raceNo}R</b><span>${timeLabel(race.startTimeJst)}</span></div><h3>${esc(race.raceName ?? `${race.raceNo}R`)}</h3><small>${esc(meta)}</small><em class="state ${esc(state.code)}">${esc(state.label)}</em>${state.detail ? `<p>${esc(state.detail)}</p>` : ""}</a>`;
}

function dateLabel(date: string): string {
  const [, month = "", day = ""] = date.split("-");
  return `${Number(month)}月${Number(day)}日`;
}

function renderHome(upcoming: RaceRow[], todayDay: FastDay): Response {
  const byDate = new Map<string, RaceRow[]>();
  for (const race of upcoming) {
    const list = byDate.get(race.raceDate) ?? [];
    list.push(race);
    byDate.set(race.raceDate, list);
  }
  const sections = [...byDate.entries()].map(([date, races]) => {
    const venues = [...new Set(races.map((race) => race.venue))];
    const groups = venues.map((venue) => `<section class="venue"><div class="venue-title"><b>${esc(venue)}</b><span>${races.filter((race) => race.venue === venue).length}R</span></div><div class="race-rail">${races.filter((race) => race.venue === venue).map((race) => raceCard(race, date === todayDay.date ? todayDay : { date, races, selectedIds: null, betsByRace: new Map() })).join("")}</div></section>`).join("");
    return `<section class="day"><h2>${dateLabel(date)}</h2>${groups}</section>`;
  }).join("");
  const body = sections || `<section class="empty"><h2>次回開催データを準備中です</h2><p>開催情報が入り次第、この画面へ自動反映します。</p></section>`;
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111f"><title>レース探偵</title><style>
  :root{color-scheme:dark;--bg:#07111f;--panel:#0d1d2d;--line:#28445f;--text:#eaf3ff;--muted:#9fb2c6;--green:#6fe0bd;--red:#ff9797;--warn:#f2cd7d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic",sans-serif}.wrap{max-width:980px;margin:auto;padding:18px 14px 60px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}.brand{font-size:28px;font-weight:900}.nav{display:flex;gap:7px;overflow:auto}.nav a{white-space:nowrap;padding:8px 10px;border:1px solid var(--line);border-radius:999px;background:#0b1927;font-size:12px}.next{padding:16px;border:1px solid #356179;border-radius:18px;background:linear-gradient(145deg,#10263a,#0b1b2b);margin-bottom:22px}.next-head{display:flex;justify-content:space-between;gap:12px}.eyebrow{color:var(--green);font-size:11px;font-weight:900;letter-spacing:.08em}.next h2{margin:4px 0 3px;font-size:20px}.next p{margin:0;color:var(--muted);font-size:12px}.next-state{align-self:flex-start;padding:6px 9px;border-radius:999px;font-size:11px;font-weight:800;background:#17334a}.next-state.buy{background:#153a30;color:#a9f1d8}.tickets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:13px}.ticket{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0a1724}.ticket b{font-size:11px;color:var(--muted)}.ticket strong{font-size:15px}.ticket span{font-size:10px;color:var(--green);text-align:right}.next-wait{margin-top:12px;padding:10px;border:1px dashed var(--line);border-radius:11px;color:var(--muted);font-size:12px}.detail{display:inline-block;margin-top:11px;color:#b9dcff;font-size:12px}.day{margin-top:22px}.day>h2{margin:0 0 10px;font-size:19px}.venue{margin-bottom:16px}.venue-title,.race-top{display:flex;justify-content:space-between;align-items:center}.venue-title{margin:0 2px 7px}.venue-title span{font-size:11px;color:var(--muted)}.race-rail{display:flex;gap:8px;overflow-x:auto;padding-bottom:5px;scrollbar-width:none}.race-card{flex:0 0 205px;min-height:150px;padding:12px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.race-top b{font-size:19px}.race-top span{font-size:12px;color:var(--muted)}.race-card h3{margin:8px 0 4px;font-size:13px;min-height:36px}.race-card small{display:block;color:var(--muted);font-size:10px}.state{display:inline-block;margin-top:9px;padding:4px 7px;border-radius:999px;background:#182b3e;color:#bed6ec;font-size:10px;font-style:normal;font-weight:800}.state.buy,.state.hit{background:#153a30;color:#a9f1d8}.state.miss,.state.missing{background:#47282b;color:#ffc0c0}.state.target{background:#173b34;color:#a9f1d8}.state.skip{background:#252b33;color:#b4bec8}.race-card p{margin:5px 0 0;font-size:9px;color:var(--muted)}.empty{padding:22px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}.empty h2{margin-top:0}@media(max-width:700px){.wrap{padding:14px 10px 50px}.top{align-items:flex-start}.brand{font-size:25px;white-space:nowrap}.nav{justify-content:flex-end}.next{padding:13px}.next-head{display:block}.next-state{display:inline-block;margin-top:8px}.tickets{grid-template-columns:1fr}.ticket{grid-template-columns:auto 1fr}.ticket span{grid-column:1/-1;text-align:left}.race-card{flex-basis:180px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav class="nav"><a href="/win5">WIN5</a><a href="/performance">成績</a><a href="/conditions">予想ロジック</a></nav></header>${nextBetHtml(todayDay)}${body}</main><script>(function(){let busy=false;async function refresh(){if(busy||document.hidden)return;busy=true;try{const r=await fetch('/?live=1',{cache:'no-store'});if(!r.ok)return;const text=await r.text();const doc=new DOMParser().parseFromString(text,'text/html');const incoming=doc.querySelector('main.wrap');const current=document.querySelector('main.wrap');if(incoming&&current&&incoming.innerHTML!==current.innerHTML)current.innerHTML=incoming.innerHTML;}catch{}finally{busy=false}}setInterval(refresh,30000);})();</script></body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION, "x-race-home-path": "lightweight-direct-d1" } });
}

async function fastHome(env: Env): Promise<Response> {
  const today = jstDate();
  const upcoming = await loadUpcomingRaces(env.DB, today);
  const todays = upcoming.filter((race) => race.raceDate === today);
  const selectedIds = await loadSelection(env.DB, today);
  const betsByRace = todays.length ? await loadBetsForRaceIds(env.DB, todays.map((race) => race.raceId)) : new Map<string, BetRow[]>();
  return renderHome(upcoming, { date: today, races: todays, selectedIds, betsByRace });
}

async function fastDayResponse(env: Env, date: string): Promise<Response> {
  try {
    const day = await loadFastDay(env.DB, date);
    return Response.json({
      ok: true,
      date,
      races: day.races.map((race) => ({ ...race, publicState: publicState(race, day) })),
    }, { headers: { "cache-control": "no-store, max-age=0", "x-race-current-day-path": "v38-race-id-bounded" } });
  } catch (error) {
    console.error("V38_FAST_DAY_FAILED", date, error);
    return Response.json({ ok: false, date, races: [], error: "CURRENT_DAY_UNAVAILABLE" }, { status: 503, headers: { "cache-control": "no-store", "retry-after": "15" } });
  }
}

function staticEmergencyHome(): Response {
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>レース探偵</title><style>body{margin:0;background:#07111f;color:#eaf3ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:720px;margin:auto;padding:32px 20px}.card{margin-top:22px;padding:22px;border:1px solid #28445f;border-radius:18px;background:#0d1d2d}p{color:#c7d6e6;line-height:1.8}</style><script>setTimeout(()=>location.reload(),15000)</script></head><body><main class="wrap"><h1>レース探偵</h1><section class="card"><h2>データ更新中</h2><p>表示データの取得を再試行しています。Worker自体は稼働しています。</p></section></main></body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-race-ui-version": UI_VERSION, "x-race-emergency-fallback": "direct-d1-failed" } });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // The production home screen must not traverse the historical compatibility
    // wrapper chain. That chain performs legacy repairs/aggregations which are
    // irrelevant to live display and can overload D1 under normal page traffic.
    if (request.method === "GET" && path === "/") {
      try { return await fastHome(env); }
      catch (error) { console.error("V38_FAST_HOME_FAILED", error); return staticEmergencyHome(); }
    }

    if (request.method === "GET" && path === "/api/public/day") {
      const requested = url.searchParams.get("date");
      const today = jstDate();
      if (validDate(requested) && requested >= today) return fastDayResponse(env, requested);
    }

    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return publicSite.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
