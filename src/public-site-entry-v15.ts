import publicSite from "./public-site-entry-v14.js";
import type { Env } from "./v1/types.js";

const ARCHIVE_START = "2016-08-10";
const ARCHIVE_END = "2026-08-09";
const EXPECTED = { races: 34566, runners: 480441, payouts: 413247 } as const;

type CountRow = { count: number };
type YearRow = { year: string; races: number };
type MonthRow = { month: string; races: number };
type DayRow = { raceDate: string; races: number; venues: number };
type RaceRow = {
  raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string;
  surface: string | null; distanceM: number | null; weather: string | null; trackCondition: string | null;
  status: string;
};
type RunnerRow = {
  horseNo: number; frameNo: number | null; horseName: string; sexAge: string | null; jockey: string | null;
  trainer: string | null; horseWeight: number | null; weightChange: number | null; assignedWeight: number | null;
  finishPosition: number | null; resultStatus: string | null; timeText: string | null; marginText: string | null;
  final3f: number | null;
};
type PayoutRow = { betType: string; combination: string; payoutYen: number; popularity: number | null };

type ArchiveSummary = {
  races: number;
  runners: number;
  payouts: number;
  complete: boolean;
  start: string;
  end: string;
};

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function json(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { "cache-control": "no-store" } });
}

function validYear(value: string | null): string | null {
  return value && /^20\d{2}$/.test(value) ? value : null;
}
function validMonth(value: string | null): string | null {
  return value && /^(0[1-9]|1[0-2])$/.test(value) ? value : null;
}
function validDate(value: string | null): string | null {
  return value && /^20\d{2}-\d{2}-\d{2}$/.test(value) && value >= ARCHIVE_START && value <= ARCHIVE_END ? value : null;
}
function validRaceId(value: string): boolean {
  return /^20\d{2}-\d{2}-\d{2}-[a-z0-9-]+$/i.test(value);
}

function comma(value: number): string { return Math.round(value).toLocaleString("ja-JP"); }
function yen(value: number): string { return `¥${Math.round(value).toLocaleString("ja-JP")}`; }
function dateJp(value: string): string { return value.replace(/-/g, "/"); }

async function archiveSummary(db: D1Database): Promise<ArchiveSummary> {
  let state: any = null;
  try {
    const row = await db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key='ten_year_history_import:summary' LIMIT 1`).first<{ value: string }>();
    if (row?.value) state = JSON.parse(row.value);
  } catch {/* fall through */}

  if (state && Number.isFinite(Number(state.races))) {
    const races = Number(state.races ?? 0);
    const runners = Number(state.runners ?? 0);
    const payouts = Number(state.payouts ?? 0);
    return { races, runners, payouts, complete: races >= EXPECTED.races && runners >= EXPECTED.runners && payouts >= EXPECTED.payouts, start: ARCHIVE_START, end: ARCHIVE_END };
  }

  const race = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date BETWEEN ? AND ?`).bind(ARCHIVE_START, ARCHIVE_END).first<CountRow>();
  return { races: Number(race?.count ?? 0), runners: 0, payouts: 0, complete: false, start: ARCHIVE_START, end: ARCHIVE_END };
}

async function years(db: D1Database): Promise<YearRow[]> {
  const q = await db.prepare(`
    SELECT substr(race_date,1,4) AS year,COUNT(*) AS races
    FROM rt_races WHERE race_date BETWEEN ? AND ?
    GROUP BY substr(race_date,1,4) ORDER BY year DESC
  `).bind(ARCHIVE_START, ARCHIVE_END).all<YearRow>();
  return q.results.map((r) => ({ year: String(r.year), races: Number(r.races) }));
}

async function months(db: D1Database, year: string): Promise<MonthRow[]> {
  const q = await db.prepare(`
    SELECT substr(race_date,6,2) AS month,COUNT(*) AS races
    FROM rt_races WHERE race_date BETWEEN ? AND ? AND substr(race_date,1,4)=?
    GROUP BY substr(race_date,6,2) ORDER BY month DESC
  `).bind(ARCHIVE_START, ARCHIVE_END, year).all<MonthRow>();
  return q.results.map((r) => ({ month: String(r.month), races: Number(r.races) }));
}

async function days(db: D1Database, year: string, month: string): Promise<DayRow[]> {
  const prefix = `${year}-${month}-%`;
  const q = await db.prepare(`
    SELECT race_date AS raceDate,COUNT(*) AS races,COUNT(DISTINCT venue) AS venues
    FROM rt_races WHERE race_date BETWEEN ? AND ? AND race_date LIKE ?
    GROUP BY race_date ORDER BY race_date DESC
  `).bind(ARCHIVE_START, ARCHIVE_END, prefix).all<DayRow>();
  return q.results.map((r) => ({ raceDate: String(r.raceDate), races: Number(r.races), venues: Number(r.venues) }));
}

async function dayRaces(db: D1Database, raceDate: string): Promise<RaceRow[]> {
  const q = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
           surface,distance_m AS distanceM,weather,track_condition AS trackCondition,status
    FROM rt_races WHERE race_date=? ORDER BY venue,race_no
  `).bind(raceDate).all<RaceRow>();
  return q.results.map((r) => ({ ...r, raceNo: Number(r.raceNo), distanceM: r.distanceM == null ? null : Number(r.distanceM) }));
}

async function raceDetail(db: D1Database, raceId: string): Promise<{ race: RaceRow; runners: RunnerRow[]; payouts: PayoutRow[] } | null> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
           surface,distance_m AS distanceM,weather,track_condition AS trackCondition,status
    FROM rt_races WHERE race_id=? AND race_date BETWEEN ? AND ? LIMIT 1
  `).bind(raceId, ARCHIVE_START, ARCHIVE_END).first<RaceRow>();
  if (!race) return null;
  const runners = await db.prepare(`
    SELECT u.horse_no AS horseNo,u.frame_no AS frameNo,u.horse_name AS horseName,u.sex_age AS sexAge,u.jockey,u.trainer,
           u.horse_weight AS horseWeight,u.weight_change AS weightChange,u.assigned_weight AS assignedWeight,
           x.finish_position AS finishPosition,x.result_status AS resultStatus,x.time_text AS timeText,x.margin_text AS marginText,x.final3f
    FROM rt_runners u LEFT JOIN rt_results x ON x.race_id=u.race_id AND x.horse_no=u.horse_no
    WHERE u.race_id=? ORDER BY CASE WHEN x.finish_position IS NULL THEN 999 ELSE x.finish_position END,u.horse_no
  `).bind(raceId).all<RunnerRow>();
  const payouts = await db.prepare(`
    SELECT bet_type AS betType,combination,payout_yen AS payoutYen,popularity
    FROM rt_payouts WHERE race_id=? ORDER BY CASE bet_type WHEN '単勝' THEN 1 WHEN '複勝' THEN 2 WHEN '枠連' THEN 3 WHEN '馬連' THEN 4 WHEN 'ワイド' THEN 5 WHEN '馬単' THEN 6 WHEN '3連複' THEN 7 WHEN '3連単' THEN 8 ELSE 9 END,bet_type,combination
  `).bind(raceId).all<PayoutRow>();
  return {
    race: { ...race, raceNo: Number(race.raceNo), distanceM: race.distanceM == null ? null : Number(race.distanceM) },
    runners: runners.results.map((r) => ({ ...r, horseNo: Number(r.horseNo), frameNo: r.frameNo == null ? null : Number(r.frameNo), horseWeight: r.horseWeight == null ? null : Number(r.horseWeight), weightChange: r.weightChange == null ? null : Number(r.weightChange), assignedWeight: r.assignedWeight == null ? null : Number(r.assignedWeight), finishPosition: r.finishPosition == null ? null : Number(r.finishPosition), final3f: r.final3f == null ? null : Number(r.final3f) })),
    payouts: payouts.results.map((p) => ({ ...p, payoutYen: Number(p.payoutYen), popularity: p.popularity == null ? null : Number(p.popularity) }))
  };
}

function shell(title: string, body: string): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#08101b;--panel:#101b29;--panel2:#142234;--line:#26384d;--text:#f3f7fb;--muted:#91a2b7;--accent:#67d7c4;--green:#7be3a5}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;line-height:1.55}a{color:inherit;text-decoration:none}.wrap{width:min(1100px,calc(100% - 28px));margin:0 auto;padding:22px 0 50px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px}.brand{font-size:20px;font-weight:900}.back{font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:7px 11px}.hero{padding:18px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,var(--panel),#0d1723);margin-bottom:16px}.hero h1{font-size:24px;margin:0 0 6px}.hero p{margin:0;color:var(--muted);font-size:13px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:14px}.stat{padding:12px;border-radius:14px;background:var(--panel2);border:1px solid var(--line)}.stat b{display:block;font-size:19px}.stat span{font-size:11px;color:var(--muted)}.status{display:inline-flex;margin-top:10px;font-size:11px;border:1px solid var(--line);border-radius:999px;padding:5px 9px;color:var(--muted)}.status.ok{color:var(--green)}.section{margin-top:18px}.section h2{font-size:16px;margin:0 0 9px}.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{display:inline-flex;gap:6px;align-items:center;padding:8px 10px;border:1px solid var(--line);border-radius:11px;background:var(--panel);font-size:13px}.chip span{font-size:10px;color:var(--muted)}.chip.on{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}.venue{border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow:hidden;margin:10px 0}.venue-head{padding:11px 13px;font-weight:900;background:var(--panel2)}.races{display:grid;grid-template-columns:repeat(2,1fr)}.race{display:grid;grid-template-columns:46px 1fr auto;align-items:center;gap:10px;padding:11px 13px;border-top:1px solid var(--line)}.race:nth-child(odd){border-right:1px solid var(--line)}.race-no{font-weight:900;font-size:18px}.race-name{font-weight:700;font-size:13px}.race-meta{font-size:11px;color:var(--muted)}.arrow{color:var(--accent);font-size:18px}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--panel)}table{border-collapse:collapse;width:100%;min-width:760px}th,td{padding:9px 10px;border-top:1px solid var(--line);font-size:12px;text-align:left;white-space:nowrap}th{background:var(--panel2);color:var(--muted);font-weight:700;border-top:0}td.finish{font-size:16px;font-weight:900}.payouts{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.payout{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}.payout b{font-size:13px}.payout span{color:var(--muted);font-size:11px}.payout strong{font-size:14px}.empty{padding:20px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);font-size:13px}.crumb{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px;font-size:12px;color:var(--muted)}.crumb a{color:var(--accent)}
  @media(max-width:760px){.wrap{width:min(100% - 20px,1100px);padding-top:14px}.hero{padding:15px}.hero h1{font-size:21px}.stats{grid-template-columns:repeat(2,1fr)}.races{grid-template-columns:1fr}.race:nth-child(odd){border-right:0}.payouts{grid-template-columns:1fr}.top{margin-bottom:14px}}
  </style></head><body><main class="wrap"><div class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">予想トップへ</a></div>${body}</main></body></html>`;
}

function archiveHero(summary: ArchiveSummary): string {
  const runners = summary.runners || EXPECTED.runners;
  const payouts = summary.payouts || EXPECTED.payouts;
  return `<section class="hero"><h1>過去レースアーカイブ</h1><p>${dateJp(ARCHIVE_START)}〜${dateJp(ARCHIVE_END)}のJRA公式レースデータを、年 → 月 → 日 → 会場 → レースの順で確認できます。</p><div class="stats"><div class="stat"><b>${comma(summary.races)}</b><span>レース</span></div><div class="stat"><b>${comma(runners)}</b><span>出走馬</span></div><div class="stat"><b>${comma(payouts)}</b><span>払戻データ</span></div><div class="stat"><b>10年</b><span>保存期間</span></div></div><span class="status ${summary.complete ? "ok" : ""}">${summary.complete ? "10年分 反映完了" : `取込中 ${comma(summary.races)} / ${comma(EXPECTED.races)}R`}</span></section>`;
}

async function historyPage(db: D1Database, url: URL): Promise<Response> {
  const summary = await archiveSummary(db);
  const yearRows = await years(db);
  let year = validYear(url.searchParams.get("year"));
  if (year && !yearRows.some((x) => x.year === year)) year = null;
  const monthRows = year ? await months(db, year) : [];
  let month = validMonth(url.searchParams.get("month"));
  if (!year || (month && !monthRows.some((x) => x.month === month))) month = null;
  const dayRows = year && month ? await days(db, year, month) : [];
  let date = validDate(url.searchParams.get("date"));
  if (!year || !month || (date && !dayRows.some((x) => x.raceDate === date))) date = null;
  const races = date ? await dayRaces(db, date) : [];

  const y = `<section class="section"><h2>年</h2><div class="chips">${yearRows.map((r) => `<a class="chip ${r.year === year ? "on" : ""}" href="/history?year=${r.year}">${r.year}<span>${comma(r.races)}R</span></a>`).join("")}</div></section>`;
  const m = year ? `<section class="section"><h2>${year}年・月</h2><div class="chips">${monthRows.map((r) => `<a class="chip ${r.month === month ? "on" : ""}" href="/history?year=${year}&month=${r.month}">${Number(r.month)}月<span>${comma(r.races)}R</span></a>`).join("")}</div></section>` : "";
  const d = year && month ? `<section class="section"><h2>${year}年${Number(month)}月・開催日</h2><div class="chips">${dayRows.map((r) => `<a class="chip ${r.raceDate === date ? "on" : ""}" href="/history?year=${year}&month=${month}&date=${r.raceDate}">${Number(r.raceDate.slice(8))}日<span>${r.venues}場・${r.races}R</span></a>`).join("")}</div></section>` : "";

  const groups = new Map<string, RaceRow[]>();
  for (const r of races) groups.set(r.venue, [...(groups.get(r.venue) ?? []), r]);
  const rs = date ? `<section class="section"><h2>${dateJp(date)} のレース</h2>${[...groups.entries()].map(([venue, rows]) => `<div class="venue"><div class="venue-head">${esc(venue)} <span style="color:var(--muted);font-size:11px">${rows.length}R</span></div><div class="races">${rows.map((r) => `<a class="race" href="/history/races/${encodeURIComponent(r.raceId)}"><div class="race-no">${r.raceNo}R</div><div><div class="race-name">${esc(r.raceName || `${r.raceNo}R`)}</div><div class="race-meta">${esc(r.surface ?? "")} ${r.distanceM ? `${r.distanceM}m` : ""}${r.weather ? `・${esc(r.weather)}` : ""}${r.trackCondition ? `・${esc(r.trackCondition)}` : ""}</div></div><div class="arrow">›</div></a>`).join("")}</div></div>`).join("") || `<div class="empty">この日のレースデータはまだ取込中です。</div>`}</section>` : "";

  return new Response(shell("過去レース", `${archiveHero(summary)}${y}${m}${d}${rs}`), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

async function historyRacePage(db: D1Database, raceId: string): Promise<Response> {
  if (!validRaceId(raceId)) return new Response("NOT_FOUND", { status: 404 });
  const detail = await raceDetail(db, raceId);
  if (!detail) return new Response(shell("レースデータ", `<div class="empty">レースデータが見つかりません。</div>`), { status: 404, headers: { "content-type": "text/html; charset=utf-8" } });
  const r = detail.race;
  const [year, month] = r.raceDate.split("-");
  const crumb = `<div class="crumb"><a href="/history">過去レース</a><span>›</span><a href="/history?year=${year}">${year}</a><span>›</span><a href="/history?year=${year}&month=${month}">${Number(month)}月</a><span>›</span><a href="/history?year=${year}&month=${month}&date=${r.raceDate}">${dateJp(r.raceDate)}</a><span>›</span><span>${esc(r.venue)} ${r.raceNo}R</span></div>`;
  const head = `<section class="hero"><h1>${esc(r.venue)} ${r.raceNo}R　${esc(r.raceName || "")}</h1><p>${dateJp(r.raceDate)}・${esc(r.surface ?? "")} ${r.distanceM ? `${r.distanceM}m` : ""}${r.weather ? `・${esc(r.weather)}` : ""}${r.trackCondition ? `・${esc(r.trackCondition)}` : ""}</p></section>`;
  const runnerRows = detail.runners.map((x) => `<tr><td class="finish">${x.finishPosition ?? "—"}</td><td>${x.frameNo ?? "—"}</td><td>${x.horseNo}</td><td><b>${esc(x.horseName)}</b></td><td>${esc(x.sexAge ?? "—")}</td><td>${esc(x.jockey ?? "—")}</td><td>${x.assignedWeight ?? "—"}</td><td>${x.horseWeight ?? "—"}${x.weightChange == null ? "" : ` (${x.weightChange >= 0 ? "+" : ""}${x.weightChange})`}</td><td>${esc(x.timeText ?? "—")}</td><td>${x.final3f ?? "—"}</td></tr>`).join("");
  const runners = `<section class="section"><h2>着順・出走馬</h2><div class="table-wrap"><table><thead><tr><th>着</th><th>枠</th><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>斤量</th><th>馬体重</th><th>タイム</th><th>上がり3F</th></tr></thead><tbody>${runnerRows}</tbody></table></div></section>`;
  const payouts = `<section class="section"><h2>払戻</h2><div class="payouts">${detail.payouts.map((p) => `<div class="payout"><div><b>${esc(p.betType)}　${esc(p.combination)}</b><br><span>${p.popularity ? `${p.popularity}人気` : "JRA公式払戻"}</span></div><strong>${yen(p.payoutYen)}</strong></div>`).join("") || `<div class="empty">払戻データなし</div>`}</div></section>`;
  return new Response(shell(`${r.venue} ${r.raceNo}R`, `${crumb}${head}${runners}${payouts}`), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public,max-age=3600" } });
}

function enhanceHome(html: string): string {
  const css = `<style>.venue-roi-title,.venue-roi-rail{display:none!important}.teny-archive-card{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:18px 0;padding:15px 16px;border:1px solid var(--line);background:var(--panel);border-radius:16px}.teny-archive-card b{display:block;font-size:17px}.teny-archive-card span{display:block;color:var(--muted);font-size:11px;margin-top:2px}.teny-archive-card em{font-style:normal;font-weight:900;color:var(--green);font-size:18px}.teny-archive-card i{font-style:normal;color:var(--muted);font-size:18px}@media(max-width:760px){.teny-archive-card{padding:13px}.teny-archive-card em{font-size:15px}}</style>`;
  const card = `<a class="teny-archive-card" href="/history"><div><b>過去10年の全レース</b><span>2016/08/10〜2026/08/09・年 → 月 → 日 → 会場 → R</span></div><div><em>34,566R</em><i> ›</i></div></a>`;
  const anchor = `<div class="section-title"><h2 id="selected-date">`;
  let out = html.replace("</head>", `${css}</head>`);
  out = out.includes(anchor) ? out.replace(anchor, `${card}${anchor}`) : out.replace("</body>", `${card}</body>`);
  return out;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/history") return historyPage(env.DB, url);
    if (url.pathname.startsWith("/history/races/")) return historyRacePage(env.DB, decodeURIComponent(url.pathname.slice("/history/races/".length)));
    if (url.pathname === "/api/public/history/summary") return json(await archiveSummary(env.DB));
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (url.pathname !== "/" || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const headers = new Headers(response.headers); headers.delete("content-length");
      return new Response(enhanceHome(await response.text()), { status: response.status, headers });
    } catch { return response; }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
